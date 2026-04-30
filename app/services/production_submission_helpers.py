"""
Shared execution logic for machine, packaged, and combined production submissions.
"""

import sqlite3
from datetime import datetime

from flask import current_app

from app.services.product_tablet_allowlist import (
    allowed_tablet_type_ids_for_product,
    inventory_item_id_for_bag_tablet,
)
from app.services.submission_context_service import normalize_optional_text
from app.utils.eastern_datetime import parse_optional_eastern, utc_now_naive_string
from app.utils.receive_tracking import (
    find_bag_for_submission_allowlist,
    find_bag_for_submission_for_product,
)
from app.utils.route_helpers import get_setting


class ProductionSubmissionError(Exception):
    """Business-rule failure inside a transaction; rollback and return JSON body + HTTP status."""

    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self.body = body
        super().__init__(str(body))


def refresh_purchase_order_header_aggregates(conn, po_id: int) -> None:
    """Recompute ``purchase_orders`` header columns from ``po_lines`` (machine/packaged paths)."""
    totals = conn.execute(
        """
        SELECT
            COALESCE(SUM(quantity_ordered), 0) as total_ordered,
            COALESCE(SUM(good_count), 0) as total_good,
            COALESCE(SUM(damaged_count), 0) as total_damaged,
            COALESCE(SUM(machine_good_count), 0) as total_machine_good,
            COALESCE(SUM(machine_damaged_count), 0) as total_machine_damaged
        FROM po_lines
        WHERE po_id = ?
        """,
        (po_id,),
    ).fetchone()
    remaining = totals['total_ordered'] - totals['total_good'] - totals['total_damaged']
    conn.execute(
        """
        UPDATE purchase_orders
        SET ordered_quantity = ?, current_good_count = ?,
            current_damaged_count = ?, remaining_quantity = ?,
            machine_good_count = ?, machine_damaged_count = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            totals['total_ordered'],
            totals['total_good'],
            totals['total_damaged'],
            remaining,
            totals['total_machine_good'],
            totals['total_machine_damaged'],
            po_id,
        ),
    )


def _insert_machine_counts_row(
    conn,
    tablet_type_id: int,
    machine_id,
    machine_count_int: int,
    employee_name: str,
    count_date,
    box_number,
    bag_number,
) -> None:
    """Insert ``machine_counts``; include box/bag when columns exist (for workflow sync reversal)."""
    if machine_id:
        try:
            conn.execute(
                """
                INSERT INTO machine_counts (
                    tablet_type_id, machine_id, machine_count, employee_name, count_date,
                    box_number, bag_number
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tablet_type_id,
                    machine_id,
                    machine_count_int,
                    employee_name,
                    count_date,
                    box_number,
                    bag_number,
                ),
            )
            return
        except sqlite3.OperationalError:
            conn.execute(
                """
                INSERT INTO machine_counts (tablet_type_id, machine_id, machine_count, employee_name, count_date)
                VALUES (?, ?, ?, ?, ?)
                """,
                (tablet_type_id, machine_id, machine_count_int, employee_name, count_date),
            )
            return
    try:
        conn.execute(
            """
            INSERT INTO machine_counts (
                tablet_type_id, machine_count, employee_name, count_date, box_number, bag_number
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (tablet_type_id, machine_count_int, employee_name, count_date, box_number, bag_number),
        )
    except sqlite3.OperationalError:
        conn.execute(
            """
            INSERT INTO machine_counts (tablet_type_id, machine_count, employee_name, count_date)
            VALUES (?, ?, ?, ?)
            """,
            (tablet_type_id, machine_count_int, employee_name, count_date),
        )


def parse_machine_submission_entries(data):
    """
    Normalize request body to a list of dicts: machine_id (int or None), machine_count (int).

    Supports batch submissions via machine_entries: [{machine_id, machine_count}, ...]
    or legacy single machine_id + machine_count fields.
    """
    raw = data.get('machine_entries')
    if isinstance(raw, list) and len(raw) > 0:
        out = []
        for row in raw:
            if not isinstance(row, dict):
                return None, 'Invalid machine_entries format.'
            try:
                mc = int(row.get('machine_count'))
            except (TypeError, ValueError):
                return None, 'Each machine row needs a valid machine count.'
            if mc < 0:
                return None, 'Machine count cannot be negative.'
            mid = row.get('machine_id')
            if mid is None or mid == '':
                mid_parsed = None
            else:
                try:
                    mid_parsed = int(mid)
                except (TypeError, ValueError):
                    return None, 'Invalid machine selection in machine_entries.'
            out.append({'machine_id': mid_parsed, 'machine_count': mc})
        if not out:
            return None, 'Add at least one machine count.'
        non_null = [e['machine_id'] for e in out if e['machine_id'] is not None]
        if len(non_null) != len(set(non_null)):
            return None, 'Each machine may only appear once in this submission.'
        if len(out) > 1 and any(e['machine_id'] is None for e in out):
            return None, 'When submitting multiple machine counts, select a machine for each row.'
        return out, None

    try:
        mc = int(data.get('machine_count'))
    except (TypeError, ValueError):
        return None, 'Valid machine count is required'
    if mc < 0:
        return None, 'Valid machine count is required'
    mid = data.get('machine_id')
    if mid is None or mid == '':
        mid_parsed = None
    else:
        try:
            mid_parsed = int(mid)
        except (TypeError, ValueError):
            mid_parsed = None
    return [{'machine_id': mid_parsed, 'machine_count': mc}], None


def _machine_admin_notes(data):
    return normalize_optional_text(data.get('machine_admin_notes') or data.get('admin_notes') or '')


def _ensure_default_count_date(data: dict) -> None:
    """Set count_date (production date for machine rows) to today when missing or blank."""
    raw = data.get('count_date')
    if raw is None or (isinstance(raw, str) and not str(raw).strip()):
        data['count_date'] = datetime.now().date().isoformat()


# Keep in sync with app.blueprints.api.BLISTER_BLISTERS_PER_CUT
BLISTER_BLISTERS_PER_CUT = 2


def _machine_role_for_id(conn, machine_id) -> str:
    if not machine_id:
        return 'sealing'
    row = conn.execute(
        "SELECT COALESCE(machine_role, 'sealing') AS machine_role FROM machines WHERE id = ?",
        (machine_id,),
    ).fetchone()
    if not row:
        return 'sealing'
    r = (dict(row).get('machine_role') or 'sealing').strip().lower()
    return r if r in ('sealing', 'blister') else 'sealing'


def execute_machine_submission(conn, data, employee_name: str, entries: list) -> dict:
    """
    Execute machine submission inside an existing connection/transaction.
    Raises ProductionSubmissionError on validation failures.
    """
    product_id = data.get('product_id')
    if not product_id:
        raise ProductionSubmissionError(400, {'error': 'Product is required'})
    _ensure_default_count_date(data)
    count_date = data['count_date']

    product = conn.execute(
        """
        SELECT pd.id, pd.product_name, pd.tablet_type_id, pd.tablets_per_package,
               tt.tablet_type_name, tt.inventory_item_id
        FROM product_details pd
        JOIN tablet_types tt ON pd.tablet_type_id = tt.id
        WHERE pd.id = ?
        """,
        (product_id,),
    ).fetchone()

    if not product:
        raise ProductionSubmissionError(400, {'error': 'Product not found'})

    product = dict(product)

    tablet_type_id = product.get('tablet_type_id')
    if not tablet_type_id:
        raise ProductionSubmissionError(400, {'error': 'Product has no tablet type configured'})

    tablets_per_package = product.get('tablets_per_package', 0)
    if tablets_per_package == 0:
        raise ProductionSubmissionError(
            400,
            {'error': 'Product configuration incomplete: tablets_per_package must be greater than 0'},
        )

    inventory_item_id = product.get('inventory_item_id')
    if not inventory_item_id:
        raise ProductionSubmissionError(
            400,
            {
                'error': f'Product "{product.get("product_name")}" is missing inventory_item_id. Please configure this in admin.'
            },
        )

    box_number_raw = data.get('box_number')
    box_number = box_number_raw if (box_number_raw and str(box_number_raw).strip()) else None
    bag_number = data.get('bag_number')

    admin_notes = _machine_admin_notes(data)

    bag = None
    needs_review = False
    error_message = None
    assigned_po_id = None
    bag_id = None
    confirm_reserved_override = str(data.get('confirm_reserved_override', '')).strip().lower() in (
        '1',
        'true',
        'yes',
        'on',
    )
    confirm_unassigned_submit = str(data.get('confirm_unassigned_submit', '')).strip().lower() in (
        '1',
        'true',
        'yes',
        'on',
    )

    if bag_number:
        bag, needs_review, error_message = find_bag_for_submission_for_product(
            conn, int(product_id), int(bag_number), box_number, submission_type="machine"
        )

    bag_counts_tablet_type_id = int(tablet_type_id)
    if bag:
        bag_id = bag['id']
        assigned_po_id = bag['po_id']
        box_number = bag.get('box_number') or box_number
        if bag.get("tablet_type_id") is not None:
            bag_counts_tablet_type_id = int(bag["tablet_type_id"])
            inv_row = conn.execute(
                "SELECT inventory_item_id FROM tablet_types WHERE id = ?",
                (bag_counts_tablet_type_id,),
            ).fetchone()
            if inv_row and inv_row["inventory_item_id"]:
                inventory_item_id = inv_row["inventory_item_id"]
        box_ref = f", box={box_number}" if box_number else ""
        current_app.logger.info(
            f"✅ Matched to receive: bag_id={bag_id}, po_id={assigned_po_id}, bag={bag_number}{box_ref}"
        )
    elif needs_review:
        box_ref = f" Box {box_number}," if box_number else ""
        current_app.logger.warning(f"⚠️ Multiple receives found for{box_ref} Bag {bag_number} - needs review")
    elif error_message:
        current_app.logger.error(f"❌ {error_message}")

    if bag_number and not bag and error_message and not confirm_unassigned_submit:
        raise ProductionSubmissionError(
            409,
            {
                'error': (
                    f'Bag not found for Box #{box_number}, Bag #{bag_number}. '
                    'Please double check bag information. Submit anyway?'
                ),
                'requires_unassigned_confirmation': True,
                'box_number': box_number,
                'bag_number': bag_number,
            },
        )

    if bag and int(bag.get('reserved_for_bottles') or 0) == 1 and not confirm_reserved_override:
        raise ProductionSubmissionError(
            409,
            {
                'error': (
                    f'Bag #{bag_number} (Box #{box_number}) is currently reserved for variety pack/bottle use. '
                    'Do you want to continue with this machine submission on the reserved bag?'
                ),
                'requires_reserved_override': True,
                'bag_id': bag_id,
                'box_number': box_number,
                'bag_number': bag_number,
            },
        )

    receipt_number = (data.get('receipt_number') or '').strip() or None

    if receipt_number:
        from app.services.receipt_product_chain import assert_receipt_product_chain

        assert_receipt_product_chain(conn, receipt_number=receipt_number, product_name=product["product_name"])

    if receipt_number:
        for entry in entries:
            machine_id_chk = entry['machine_id']
            if machine_id_chk is not None:
                existing_same_machine = conn.execute(
                    """
                    SELECT id, product_name, created_at
                    FROM warehouse_submissions
                    WHERE receipt_number = ? AND submission_type = 'machine' AND machine_id = ?
                    LIMIT 1
                    """,
                    (receipt_number, machine_id_chk),
                ).fetchone()
                if existing_same_machine:
                    raise ProductionSubmissionError(
                        400,
                        {
                            'error': (
                                f'Receipt number {receipt_number} already has a machine count for this machine '
                                f'(Product: {existing_same_machine["product_name"]}, Created: {existing_same_machine["created_at"]}). '
                                'Use a different receipt or verify the submission was not already entered.'
                            ),
                        },
                    )
            else:
                existing_null_machine = conn.execute(
                    """
                    SELECT id, product_name, created_at
                    FROM warehouse_submissions
                    WHERE receipt_number = ? AND submission_type = 'machine' AND machine_id IS NULL
                    LIMIT 1
                    """,
                    (receipt_number,),
                ).fetchone()
                if existing_null_machine:
                    raise ProductionSubmissionError(
                        400,
                        {
                            'error': (
                                f'Receipt number {receipt_number} already used for a machine count without a machine selected '
                                f'(Created: {existing_null_machine["created_at"]}). Please use a unique receipt or select a machine.'
                            ),
                        },
                    )

    bag_start_time = None
    try:
        bag_start_time = parse_optional_eastern(data.get('bag_start_time'))
    except ValueError as ve:
        raise ProductionSubmissionError(400, {'error': f'Invalid bag start time: {ve}'}) from ve

    def cards_per_turn_for(mid):
        cp = None
        if mid:
            machine_row = conn.execute('SELECT cards_per_turn FROM machines WHERE id = ?', (mid,)).fetchone()
            if machine_row:
                cp = dict(machine_row).get('cards_per_turn')
        if not cp:
            tc = get_setting('cards_per_turn', '1')
            try:
                cp = int(tc)
            except (ValueError, TypeError):
                cp = 1
        return int(cp)

    assigned_po_lines = []
    if assigned_po_id:
        po_lines = conn.execute(
            """
            SELECT pl.*, po.closed
            FROM po_lines pl
            JOIN purchase_orders po ON pl.po_id = po.id
            WHERE pl.inventory_item_id = ? AND po.id = ?
            """,
            (inventory_item_id, assigned_po_id),
        ).fetchall()
        assigned_po_lines = [line for line in po_lines if line['po_id'] == assigned_po_id]

    line_for_po = assigned_po_lines[0] if assigned_po_lines else None

    for entry in entries:
        machine_id = entry['machine_id']
        machine_count_int = entry['machine_count']
        cards_per_turn = cards_per_turn_for(machine_id)
        machine_role = _machine_role_for_id(conn, machine_id)
        if machine_role == 'blister':
            # Blister: presses × blisters/press × tablets per blister (product tablets_per_package).
            blisters_made = machine_count_int * BLISTER_BLISTERS_PER_CUT
            tablets_pressed_into_cards = blisters_made * tablets_per_package
            cards_made = 0
        else:
            tablets_pressed_into_cards = machine_count_int * cards_per_turn * tablets_per_package
            cards_made = machine_count_int * cards_per_turn

        _insert_machine_counts_row(
            conn,
            bag_counts_tablet_type_id,
            machine_id,
            machine_count_int,
            employee_name,
            count_date,
            box_number,
            bag_number,
        )

        conn.execute(
            """
            INSERT INTO warehouse_submissions
            (employee_name, product_name, inventory_item_id, box_number, bag_number,
             displays_made, packs_remaining, tablets_pressed_into_cards,
             submission_date, submission_type, bag_id, assigned_po_id, needs_review, machine_id, admin_notes, receipt_number, bag_start_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'machine', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                employee_name,
                product['product_name'],
                inventory_item_id,
                box_number,
                bag_number,
                machine_count_int,
                cards_made,
                tablets_pressed_into_cards,
                count_date,
                bag_id,
                assigned_po_id,
                needs_review,
                machine_id,
                admin_notes,
                receipt_number,
                bag_start_time,
            ),
        )

        if line_for_po:
            conn.execute(
                """
                UPDATE po_lines
                SET machine_good_count = machine_good_count + ?
                WHERE id = ?
                """,
                (tablets_pressed_into_cards, line_for_po['id']),
            )
            current_app.logger.info(
                f"Machine count - Updated PO line {line_for_po['id']}: +{tablets_pressed_into_cards} tablets pressed into cards"
            )

    if assigned_po_id and assigned_po_lines:
        updated_pos = set()
        for line in assigned_po_lines:
            if line['po_id'] not in updated_pos:
                refresh_purchase_order_header_aggregates(conn, line['po_id'])
                updated_pos.add(line['po_id'])

    if not assigned_po_id:
        if error_message:
            return {
                'success': True,
                'warning': error_message,
                'submission_saved': True,
                'needs_review': needs_review,
                'message': 'Machine count submitted successfully.',
            }
        return {
            'success': True,
            'warning': 'No receive found for this box/bag combination. Submission saved but not assigned to PO.',
            'submission_saved': True,
            'message': 'Machine count submitted successfully.',
        }

    return {'success': True, 'message': 'Machine count submitted successfully.'}


def _packaged_admin_notes(data):
    return normalize_optional_text(data.get('packaged_admin_notes') or data.get('admin_notes') or '')


def _ensure_packaging_case_columns(conn) -> dict[str, bool]:
    """Ensure optional packaging case columns exist on warehouse_submissions."""
    try:
        columns = {row[1] for row in conn.execute('PRAGMA table_info(warehouse_submissions)').fetchall()}
    except Exception:
        columns = set()
    has_case_count = 'case_count' in columns
    has_loose_display_count = 'loose_display_count' in columns
    if not has_case_count:
        try:
            conn.execute('ALTER TABLE warehouse_submissions ADD COLUMN case_count INTEGER DEFAULT 0')
            has_case_count = True
        except sqlite3.OperationalError:
            pass
    if not has_loose_display_count:
        try:
            conn.execute('ALTER TABLE warehouse_submissions ADD COLUMN loose_display_count INTEGER DEFAULT 0')
            has_loose_display_count = True
        except sqlite3.OperationalError:
            pass
    return {
        'case_count': has_case_count,
        'loose_display_count': has_loose_display_count,
    }


def execute_packaged_submission(conn, data, employee_name: str) -> dict:
    """
    Execute packaged (warehouse) submission inside an existing connection/transaction.
    Raises ProductionSubmissionError on validation failures.
    """
    data = dict(data)
    product_name = (data.get('product_name') or '').strip()
    if not product_name and data.get('product_id'):
        try:
            pid = int(data['product_id'])
        except (TypeError, ValueError):
            raise ProductionSubmissionError(400, {'error': 'Invalid product_id'}) from None
        prow = conn.execute('SELECT product_name FROM product_details WHERE id = ?', (pid,)).fetchone()
        if not prow:
            raise ProductionSubmissionError(400, {'error': 'Product not found'})
        product_name = prow['product_name'].strip()
        data['product_name'] = product_name

    if not product_name:
        raise ProductionSubmissionError(400, {'error': 'product_name is required'})

    current_app.logger.info(f"Looking up product: '{product_name}'")

    product = conn.execute(
        """
        SELECT pd.*, tt.inventory_item_id, tt.tablet_type_name, tt.id as tablet_type_id
        FROM product_details pd
        JOIN tablet_types tt ON pd.tablet_type_id = tt.id
        WHERE pd.product_name = ?
        """,
        (product_name,),
    ).fetchone()

    if not product:
        similar = conn.execute(
            """
            SELECT pd.product_name, tt.tablet_type_name
            FROM product_details pd
            JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            WHERE pd.product_name LIKE ? OR tt.tablet_type_name LIKE ?
            LIMIT 5
            """,
            (f'%{product_name}%', f'%{product_name}%'),
        ).fetchall()

        error_msg = f"Product '{product_name}' not found in product_details table."
        if similar:
            error_msg += f" Did you mean: {', '.join([s['product_name'] for s in similar])}?"
        else:
            all_products = conn.execute(
                'SELECT pd.product_name FROM product_details pd ORDER BY pd.product_name LIMIT 10'
            ).fetchall()
            if all_products:
                error_msg += f" Available products: {', '.join([p['product_name'] for p in all_products])}"

        current_app.logger.error(error_msg)
        raise ProductionSubmissionError(400, {'error': error_msg})

    product = dict(product)
    case_columns = _ensure_packaging_case_columns(conn)

    packages_per_display = product.get('packages_per_display')
    tablets_per_package = product.get('tablets_per_package')
    displays_per_case = product.get('displays_per_case')

    if (
        packages_per_display is None
        or tablets_per_package is None
        or packages_per_display == 0
        or tablets_per_package == 0
    ):
        raise ProductionSubmissionError(
            400,
            {
                'error': 'Product configuration incomplete: packages_per_display and tablets_per_package are required and must be greater than 0'
            },
        )

    try:
        packages_per_display = int(packages_per_display)
        tablets_per_package = int(tablets_per_package)
        displays_per_case = int(displays_per_case or 0)
    except (ValueError, TypeError):
        raise ProductionSubmissionError(400, {'error': 'Invalid numeric values for product configuration'}) from None

    try:
        displays_made = int(data.get('displays_made', 0) or 0)
        packs_remaining = int(data.get('packs_remaining', 0) or 0)
        loose_tablets = int(data.get('loose_tablets', 0) or 0)
        cards_reopened = int(data.get('cards_reopened', 0) or 0)
    except (ValueError, TypeError):
        raise ProductionSubmissionError(400, {'error': 'Invalid numeric values for counts'}) from None

    case_count_raw = data.get('case_count')
    has_case_input = case_count_raw is not None
    try:
        case_count = int(case_count_raw or 0)
        loose_display_count = int(displays_made or 0)
    except (ValueError, TypeError):
        raise ProductionSubmissionError(400, {'error': 'Invalid case_count or displays_made'}) from None
    if case_count < 0 or loose_display_count < 0:
        raise ProductionSubmissionError(400, {'error': 'case_count and displays_made must be >= 0'})
    if has_case_input:
        if displays_per_case <= 0 and case_count > 0:
            raise ProductionSubmissionError(
                400,
                {
                    'error': (
                        f"Product '{product_name}' needs displays_per_case > 0 "
                        "to convert cases into displays."
                    )
                },
            )
        displays_made = (case_count * displays_per_case) + loose_display_count

    submission_date = data.get('submission_date', datetime.now().date().isoformat())

    admin_notes = _packaged_admin_notes(data)

    inventory_item_id = product.get('inventory_item_id')
    if not inventory_item_id:
        current_app.logger.error(
            f"Product '{data.get('product_name')}' missing inventory_item_id. Product data: {dict(product)}"
        )
        raise ProductionSubmissionError(
            400,
            {
                'error': f"Product '{data.get('product_name')}' is missing inventory_item_id configuration. Please contact admin to configure this product."
            },
        )

    tablet_type_id = product.get('tablet_type_id')
    if not tablet_type_id:
        raise ProductionSubmissionError(400, {'error': 'Product tablet_type_id not found'})

    receipt_number = (data.get('receipt_number') or '').strip() or None
    if not receipt_number:
        raise ProductionSubmissionError(400, {'error': 'Receipt number is required'})

    from app.services.receipt_product_chain import assert_receipt_product_chain

    assert_receipt_product_chain(conn, receipt_number=receipt_number, product_name=product_name)

    existing_packaged = conn.execute(
        """
        SELECT ws.id, ws.product_name, ws.created_at, ws.bag_id, ws.assigned_po_id,
               po.po_number, po.closed AS po_closed
        FROM warehouse_submissions ws
        LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
        WHERE ws.receipt_number = ? AND ws.submission_type = 'packaged'
        LIMIT 1
        """,
        (receipt_number,),
    ).fetchone()

    if existing_packaged:
        ep = dict(existing_packaged)
        po_hint = ""
        if ep.get("po_closed"):
            po_hint = (
                " That submission is on a **closed** PO and may be hidden until you enable **Show Archived** "
                "on Submissions History."
            )
        elif ep.get("assigned_po_id") and not ep.get("bag_id"):
            po_hint = (
                f" It has no bag link yet; use Submissions History with receipt search to open submission #{ep['id']}."
            )
        raise ProductionSubmissionError(
            400,
            {
                'error': (
                    f'Receipt number {receipt_number} already used for a packaged submission '
                    f'(Submission id **{ep["id"]}**, Product: {ep["product_name"]}, '
                    f'Created: {ep["created_at"]}, PO: {ep.get("po_number") or "—"}). '
                    f'{po_hint} '
                    'Please use a unique receipt number, edit that submission, or delete it if it was entered by mistake.'
                )
            },
        )

    box_number_raw = data.get('box_number')
    box_number = box_number_raw if (box_number_raw and str(box_number_raw).strip()) else None
    bag_number = data.get('bag_number')
    confirm_reserved_override = str(data.get('confirm_reserved_override', '')).strip().lower() in (
        '1',
        'true',
        'yes',
        'on',
    )
    confirm_unassigned_submit = str(data.get('confirm_unassigned_submit', '')).strip().lower() in (
        '1',
        'true',
        'yes',
        'on',
    )
    bag_id = None
    assigned_po_id = None
    bag_label_count = None
    needs_review = False
    error_message = None
    matched_bag = None

    if not (box_number and bag_number):
        machine_rows = conn.execute(
            """
            SELECT inventory_item_id, product_name, bag_id, assigned_po_id, box_number, bag_number
            FROM warehouse_submissions
            WHERE receipt_number = ? AND submission_type = 'machine'
            ORDER BY created_at ASC
            """,
            (receipt_number,),
        ).fetchall()

        if machine_rows:
            inv_ids = {dict(r)['inventory_item_id'] for r in machine_rows}
            bag_ids = {dict(r)['bag_id'] for r in machine_rows}
            if len(inv_ids) > 1:
                raise ProductionSubmissionError(
                    400,
                    {
                        'error': (
                            f'Machine counts on receipt #{receipt_number} disagree on product/inventory '
                            '(multiple inventory_item_id values). Enter box/bag manually or fix submissions.'
                        ),
                    },
                )
            if len(bag_ids) > 1:
                raise ProductionSubmissionError(
                    400,
                    {
                        'error': (
                            f'Machine counts on receipt #{receipt_number} disagree on bag assignment '
                            '(multiple bag_id values). Enter box/bag manually or fix submissions.'
                        ),
                    },
                )
            expect_pn = (data.get('product_name') or product_name or "").strip()
            for mr in machine_rows:
                mpn = (dict(mr).get('product_name') or '').strip()
                if mpn and expect_pn and mpn != expect_pn:
                    raise ProductionSubmissionError(
                        400,
                        {
                            'error': (
                                f'Receipt #{receipt_number} was used for **{mpn}**, but this submission is for '
                                f'**{expect_pn}**. Blister, sealing, and packaging must use the same finished product.'
                            ),
                        },
                    )
            machine_count = dict(machine_rows[0])
            bag_id = machine_count['bag_id']
            assigned_po_id = machine_count['assigned_po_id']
            box_number = machine_count['box_number']
            bag_number = machine_count['bag_number']
            if bag_id:
                bag_row = conn.execute(
                    'SELECT id, bag_label_count, reserved_for_bottles FROM bags WHERE id = ?', (bag_id,)
                ).fetchone()
                if bag_row:
                    matched_bag = dict(bag_row)
                    bag_label_count = bag_row['bag_label_count']
                current_app.logger.info(
                    f"📝 Inherited bag_id from receipt {receipt_number}: bag_id={bag_id}, po_id={assigned_po_id}, box={box_number}, bag={bag_number}"
                )
            else:
                needs_review = True
                current_app.logger.warning(
                    f"⚠️ Machine count for receipt {receipt_number} was flagged for review - packaging also needs review"
                )
        else:
            raise ProductionSubmissionError(
                400,
                {
                    'error': f'No machine count found for receipt #{receipt_number}. Please check the receipt number or enter box and bag numbers manually.'
                },
            )
    else:
        allow_ids = allowed_tablet_type_ids_for_product(conn, int(product['id']))
        bag, needs_review, error_message = find_bag_for_submission_allowlist(
            conn, allow_ids, int(bag_number), box_number, submission_type='packaged'
        )

        if bag:
            matched_bag = bag
            bag_id = bag['id']
            assigned_po_id = bag['po_id']
            bag_label_count = bag.get('bag_label_count', 0)
            box_number = bag.get('box_number') or box_number
            box_ref = f", box={box_number}" if box_number else ""
            current_app.logger.info(
                f"✅ Matched to receive: bag_id={bag_id}, po_id={assigned_po_id}, bag={bag_number}{box_ref}"
            )
        elif needs_review:
            box_ref = f" Box {box_number}," if box_number else ""
            current_app.logger.warning(f"⚠️ Multiple receives found for{box_ref} Bag {bag_number} - needs review")
        elif error_message and not confirm_unassigned_submit:
            raise ProductionSubmissionError(
                409,
                {
                    'error': (
                        f'Bag not found for Box #{box_number}, Bag #{bag_number}. '
                        'Please double check bag information. Submit anyway?'
                    ),
                    'requires_unassigned_confirmation': True,
                    'box_number': box_number,
                    'bag_number': bag_number,
                },
            )

    if matched_bag and int(matched_bag.get('reserved_for_bottles') or 0) == 1 and not confirm_reserved_override:
        raise ProductionSubmissionError(
            409,
            {
                'error': (
                    f'Bag #{bag_number} (Box #{box_number}) is currently reserved for variety pack/bottle use. '
                    'Do you want to continue with a regular packaged submission on this bag?'
                ),
                'requires_reserved_override': True,
                'bag_id': bag_id,
                'box_number': box_number,
                'bag_number': bag_number,
            },
        )

    try:
        columns = [row[1] for row in conn.execute('PRAGMA table_info(warehouse_submissions)').fetchall()]
        if 'inventory_item_id' not in columns:
            current_app.logger.error('inventory_item_id column missing from warehouse_submissions table')
            try:
                conn.execute('ALTER TABLE warehouse_submissions ADD COLUMN inventory_item_id TEXT')
                current_app.logger.info('Added inventory_item_id column to warehouse_submissions')
            except Exception as alter_error:
                current_app.logger.error(f'Failed to add inventory_item_id column: {alter_error}')
                raise ProductionSubmissionError(
                    500,
                    {'error': 'Database schema error: inventory_item_id column missing. Please run migration script.'},
                ) from alter_error
    except Exception as pragma_error:
        current_app.logger.error(f'Error checking table schema: {pragma_error}')

    bag_start_for_order = None
    try:
        bag_start_for_order = parse_optional_eastern(data.get('bag_start_time'))
    except ValueError as ve:
        raise ProductionSubmissionError(400, {'error': f'Invalid bag start time: {ve}'}) from ve

    bag_end_time = None
    try:
        if data.get('bag_end_time'):
            bag_end_time = parse_optional_eastern(data.get('bag_end_time'))
        else:
            bag_end_time = utc_now_naive_string()
    except ValueError as ve:
        raise ProductionSubmissionError(400, {'error': f'Invalid bag end time: {ve}'}) from ve

    if bag_start_for_order is not None and bag_end_time < bag_start_for_order:
        raise ProductionSubmissionError(
            400,
            {'error': 'Bag end time cannot be before bag start time. Please correct the times.'},
        )

    if bag_id:
        b_inv = inventory_item_id_for_bag_tablet(conn, int(bag_id))
        if b_inv:
            inventory_item_id = b_inv

    try:
        if case_columns.get('case_count') and case_columns.get('loose_display_count'):
            conn.execute(
                """
                INSERT INTO warehouse_submissions
                (employee_name, product_name, inventory_item_id, box_number, bag_number, bag_label_count,
                 displays_made, packs_remaining, loose_tablets, cards_reopened, submission_date, admin_notes,
                 submission_type, bag_id, assigned_po_id, needs_review, receipt_number, bag_end_time,
                 case_count, loose_display_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'packaged', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    employee_name,
                    data.get('product_name'),
                    inventory_item_id,
                    box_number,
                    bag_number,
                    bag_label_count or data.get('bag_label_count') or 0,
                    displays_made,
                    packs_remaining,
                    loose_tablets,
                    cards_reopened,
                    submission_date,
                    admin_notes,
                    bag_id,
                    assigned_po_id,
                    needs_review,
                    receipt_number,
                    bag_end_time,
                    case_count,
                    loose_display_count,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO warehouse_submissions
                (employee_name, product_name, inventory_item_id, box_number, bag_number, bag_label_count,
                 displays_made, packs_remaining, loose_tablets, cards_reopened, submission_date, admin_notes,
                 submission_type, bag_id, assigned_po_id, needs_review, receipt_number, bag_end_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'packaged', ?, ?, ?, ?, ?)
                """,
                (
                    employee_name,
                    data.get('product_name'),
                    inventory_item_id,
                    box_number,
                    bag_number,
                    bag_label_count or data.get('bag_label_count') or 0,
                    displays_made,
                    packs_remaining,
                    loose_tablets,
                    cards_reopened,
                    submission_date,
                    admin_notes,
                    bag_id,
                    assigned_po_id,
                    needs_review,
                    receipt_number,
                    bag_end_time,
                ),
            )
    except Exception as e:
        current_app.logger.error(f'SQL Error inserting submission: {e}')
        current_app.logger.error(
            f'Values: product_name={data.get("product_name")}, inventory_item_id={inventory_item_id}, box={box_number}, bag={bag_number}'
        )
        if 'inventory_item_id' in str(e).lower() or 'syntax error' in str(e).lower():
            raise ProductionSubmissionError(
                500,
                {
                    'error': f'Database schema error: {str(e)}. Please ensure inventory_item_id column exists in warehouse_submissions table.'
                },
            ) from e
        raise

    if error_message:
        return {
            'success': True,
            'warning': error_message,
            'submission_saved': True,
            'needs_review': needs_review,
            'bag_id': bag_id,
            'po_id': assigned_po_id,
        }
    if needs_review:
        return {
            'success': True,
            'message': 'Submission flagged for manager review - multiple matching receives found.',
            'bag_id': bag_id,
            'po_id': assigned_po_id,
            'needs_review': needs_review,
        }
    return {
        'success': True,
        'message': 'Packaged count submitted successfully',
        'bag_id': bag_id,
        'po_id': assigned_po_id,
        'needs_review': needs_review,
    }
