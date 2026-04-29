"""
API routes - all /api/* endpoints
"""
import sqlite3
from datetime import datetime

from flask import current_app, jsonify, request, session

from app.services.repack_allocation_service import (
    allocate_repack_tablets,
    allocation_payload_to_json,
)
from app.services.packaged_submission_display import normalize_packaged_case_fields_for_ui
from app.services.submission_calculator import calculate_repack_output_good
from app.utils.auth_utils import (
    WAREHOUSE_SUBMISSION_EDIT_UNLOCK_TTL_SECONDS,
    admin_required,
    employee_required,
    role_required,
    set_warehouse_submission_edit_unlock,
    verify_password,
    warehouse_submission_edit_unlock_seconds_remaining,
    warehouse_submission_edit_unlock_valid,
)
from app.utils.db_utils import db_read_only, db_transaction
from app.utils.eastern_datetime import parse_optional_eastern
from app.utils.route_helpers import (
    ensure_app_settings_table,
    get_setting,
)

from . import BLISTER_BLISTERS_PER_CUT, bp


@bp.route('/api/submission/<int:submission_id>/details', methods=['GET'])
@role_required('submissions')
def get_submission_details(submission_id):
    """Get full details of a submission (viewable by all authenticated users)"""
    try:
        with db_read_only() as conn:
            ws_columns = {row['name'] for row in conn.execute("PRAGMA table_info(warehouse_submissions)").fetchall()}
            case_count_select = "ws.case_count," if "case_count" in ws_columns else "NULL AS case_count,"
            loose_display_select = (
                "ws.loose_display_count," if "loose_display_count" in ws_columns else "NULL AS loose_display_count,"
            )
            submission = conn.execute(f'''
            SELECT ws.*, po.po_number, po.closed as po_closed, po.zoho_po_id, po.vendor_name,
                   COALESCE(ws.po_assignment_verified, 0) as po_verified,
                   pd.packages_per_display, pd.tablets_per_package,
                   pd.displays_per_case,
                   {case_count_select}
                   {loose_display_select}
                   COALESCE(pd.tablets_per_package, (
                               SELECT pd2.tablets_per_package
                               FROM product_details pd2
                               JOIN tablet_types tt2 ON pd2.tablet_type_id = tt2.id
                               WHERE tt2.inventory_item_id = ws.inventory_item_id
                               LIMIT 1
                           )) as tablets_per_package_final,
                   COALESCE(b.bag_label_count, ws.bag_label_count, 0) as bag_label_count,
                   b.batch_number as bag_batch_number,
                   b.batch_source as bag_batch_source,
                   b.estimated_tablets_from_weight as estimated_count_by_weight,
                   r.id as receive_id, r.received_date, r.receive_name as receive_name_from_receive,
                   m.machine_name, m.cards_per_turn as machine_cards_per_turn,
                   m.machine_role AS machine_role,
                   tt_submission.tablet_type_name AS submission_tablet_type_name,
                   tt_bag.tablet_type_name AS bag_tablet_type_name,
                   (
                       SELECT COUNT(*) + 1
                       FROM receiving r2
                       WHERE r2.po_id = r.po_id
                       AND (r2.received_date < r.received_date
                            OR (r2.received_date = r.received_date AND r2.id < r.id))
                   ) as shipment_number
            FROM warehouse_submissions ws
            LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name            LEFT JOIN bags b ON ws.bag_id = b.id
            LEFT JOIN small_boxes sb ON b.small_box_id = sb.id
            LEFT JOIN receiving r ON sb.receiving_id = r.id
            LEFT JOIN machines m ON ws.machine_id = m.id
            LEFT JOIN tablet_types tt_submission ON tt_submission.inventory_item_id = ws.inventory_item_id
            LEFT JOIN tablet_types tt_bag ON tt_bag.id = b.tablet_type_id
                WHERE ws.id = ?
            ''', (submission_id,)).fetchone()

            if not submission:
                return jsonify({'success': False, 'error': 'Submission not found'}), 404

            submission_dict = dict(submission)
            db_submission_type = submission_dict.get('submission_type')
            submission_type = db_submission_type or 'packaged'

            # If submission_type is already 'bottle' in the database, use it
            if db_submission_type == 'bottle':
                submission_type = 'bottle'
            if db_submission_type == 'repack':
                submission_type = 'repack'

            # Also check product config to determine if this is a bottle/variety pack submission
            # This handles legacy submissions where submission_type might not be set correctly
            product_name = submission_dict.get('product_name')
            if product_name and submission_type != 'repack':
                product_config = conn.execute('''
                    SELECT is_variety_pack, is_bottle_product, variety_pack_contents, tablets_per_bottle, bottles_per_display
                    FROM product_details WHERE product_name = ?
                ''', (product_name,)).fetchone()

                if product_config:
                    product_config_dict = dict(product_config)
                    is_variety = product_config_dict.get('is_variety_pack')
                    is_bottle = product_config_dict.get('is_bottle_product')
                    has_variety_contents = product_config_dict.get('variety_pack_contents')
                    has_bottle_config = product_config_dict.get('tablets_per_bottle')

                    if is_variety or is_bottle or has_variety_contents or has_bottle_config:
                        submission_type = 'bottle'
                        submission_dict['submission_type'] = 'bottle'

            # If bag_label_count is 0 or missing but bag_id exists, try to get it directly from bags table
            if submission_dict.get('bag_id') and (
                (not submission_dict.get('bag_label_count') or submission_dict.get('bag_label_count') == 0)
                or submission_dict.get('estimated_count_by_weight') is None
            ):
                bag_row = conn.execute(
                    'SELECT bag_label_count, estimated_tablets_from_weight, batch_number, batch_source FROM bags WHERE id = ?',
                    (submission_dict.get('bag_id'),)
                ).fetchone()
                if bag_row:
                    bag_dict = dict(bag_row)
                    if bag_dict.get('bag_label_count'):
                        submission_dict['bag_label_count'] = bag_dict.get('bag_label_count')
                    if bag_dict.get('estimated_tablets_from_weight') is not None:
                        submission_dict['estimated_count_by_weight'] = bag_dict.get('estimated_tablets_from_weight')
                    if bag_dict.get('batch_number') is not None and submission_dict.get('bag_batch_number') in (None, ''):
                        submission_dict['bag_batch_number'] = bag_dict.get('batch_number')
                    if bag_dict.get('batch_source') is not None and submission_dict.get('bag_batch_source') in (None, ''):
                        submission_dict['bag_batch_source'] = bag_dict.get('batch_source')

            # Get machine information for machine submissions
            # First try to get from the JOIN we already did
            machine_name = submission_dict.get('machine_name')
            cards_per_turn = submission_dict.get('machine_cards_per_turn')

            if submission_type == 'machine' and submission_dict.get('machine_id'):
                machine_row = conn.execute(
                    '''
                    SELECT machine_name, cards_per_turn,
                           COALESCE(machine_role, 'sealing') AS machine_role
                    FROM machines
                    WHERE id = ?
                    ''',
                    (submission_dict.get('machine_id'),),
                ).fetchone()
                if machine_row:
                    machine = dict(machine_row)
                    if not machine_name:
                        machine_name = machine.get('machine_name')
                    if not cards_per_turn:
                        cards_per_turn = machine.get('cards_per_turn')
                    if not submission_dict.get('machine_role'):
                        submission_dict['machine_role'] = machine.get('machine_role')

            # If still not found, try to find from machine_counts table by matching submission details
            if not cards_per_turn:
                tablet_type_row = conn.execute('''
                    SELECT id FROM tablet_types WHERE inventory_item_id = ?
                ''', (submission_dict.get('inventory_item_id'),)).fetchone()

                if tablet_type_row:
                    tablet_type = dict(tablet_type_row)
                    tablet_type_id = tablet_type.get('id')

                    # Try to find machine_count record that matches this submission
                    submission_date = submission_dict.get('submission_date') or submission_dict.get('created_at')
                    machine_count_record_row = conn.execute('''
                        SELECT mc.machine_id, m.machine_name, m.cards_per_turn,
                               COALESCE(m.machine_role, 'sealing') AS machine_role
                        FROM machine_counts mc
                        LEFT JOIN machines m ON mc.machine_id = m.id
                        WHERE mc.tablet_type_id = ?
                        AND mc.machine_count = ?
                        AND mc.employee_name = ?
                        AND DATE(mc.count_date) = DATE(?)
                        ORDER BY mc.created_at DESC
                        LIMIT 1
                    ''', (tablet_type_id,
                          submission_dict.get('displays_made'),
                          submission_dict.get('employee_name'),
                          submission_date)).fetchone()

                    if machine_count_record_row:
                        machine_count_record = dict(machine_count_record_row)
                        if not machine_name:
                            machine_name = machine_count_record.get('machine_name')
                        if not cards_per_turn:
                            cards_per_turn = machine_count_record.get('cards_per_turn')
                        if not submission_dict.get('machine_role'):
                            submission_dict['machine_role'] = machine_count_record.get('machine_role')

            # Fallback to app_settings if machine not found
            if not cards_per_turn:
                cards_per_turn_setting_row = conn.execute(
                    'SELECT setting_value FROM app_settings WHERE setting_key = ?',
                    ('cards_per_turn',)
                ).fetchone()
                if cards_per_turn_setting_row:
                    cards_per_turn_setting = dict(cards_per_turn_setting_row)
                    cards_per_turn = int(cards_per_turn_setting.get('setting_value', 1))
                else:
                    cards_per_turn = 1

            machine_role_norm = 'sealing'
            if submission_type == 'machine':
                mr = submission_dict.get('machine_role')
                machine_role_norm = (mr or 'sealing').strip().lower()
                if machine_role_norm not in ('sealing', 'blister'):
                    machine_role_norm = 'sealing'
                submission_dict['machine_role'] = machine_role_norm

            # Prefer tablet type display name for UX; fallback to product label.
            submission_dict['tablet_used_name'] = (
                submission_dict.get('bag_tablet_type_name')
                or submission_dict.get('submission_tablet_type_name')
                or submission_dict.get('product_name')
                or 'N/A'
            )

            # Station timing is row-local (direct QR submission timing).
            submission_dict['station_start_time'] = submission_dict.get('bag_start_time')
            submission_dict['station_end_time'] = submission_dict.get('bag_end_time')

            # Bag timing is receipt-scoped: earliest start and latest end across receipt rows.
            receipt_number = (submission_dict.get('receipt_number') or '').strip()
            if receipt_number:
                receipt_times = conn.execute(
                    '''
                    SELECT MIN(NULLIF(TRIM(bag_start_time), '')) AS bag_start_time,
                           MAX(NULLIF(TRIM(bag_end_time), '')) AS bag_end_time
                    FROM warehouse_submissions
                    WHERE receipt_number = ?
                    ''',
                    (receipt_number,),
                ).fetchone()
                if receipt_times:
                    rt = dict(receipt_times)
                    submission_dict['bag_start_time'] = (
                        rt.get('bag_start_time') or submission_dict.get('bag_start_time')
                    )
                    submission_dict['bag_end_time'] = (
                        rt.get('bag_end_time') or submission_dict.get('bag_end_time')
                    )

            # Recalculate cards_made using correct machine-specific cards_per_turn (sealing only)
            if submission_type == 'machine' and machine_role_norm == 'sealing':
                machine_count = submission_dict.get('displays_made', 0) or 0
                cards_made = machine_count * cards_per_turn
                submission_dict['cards_made'] = cards_made
            elif submission_type == 'machine' and machine_role_norm == 'blister':
                submission_dict['cards_made'] = None

            # For bottle submissions, preserve explicit leftover single bottles.
            # We store this in packs_remaining for bottle records (no schema migration needed).
            if submission_type == 'bottle':
                bottles_per_display = 0
                if product_name:
                    bottle_config = conn.execute('''
                        SELECT bottles_per_display
                        FROM product_details
                        WHERE product_name = ?
                    ''', (product_name,)).fetchone()
                    if bottle_config:
                        bottles_per_display = dict(bottle_config).get('bottles_per_display') or 0

                explicit_remaining = submission_dict.get('packs_remaining')
                if explicit_remaining is not None and explicit_remaining >= 0:
                    submission_dict['bottles_remaining'] = explicit_remaining
                else:
                    submission_dict['bottles_remaining'] = max(
                        0,
                        (submission_dict.get('bottles_made') or 0) -
                        ((submission_dict.get('displays_made') or 0) * bottles_per_display)
                    )

            # Calculate total tablets based on submission type
            # Use tablets_per_package_final (with fallback) if available, otherwise try tablets_per_package
            tablets_per_package = (submission_dict.get('tablets_per_package_final') or
                                 submission_dict.get('tablets_per_package') or 0)

            # If tablets_per_package is still 0 or None, try to get it directly from database using inventory_item_id
            if not tablets_per_package or tablets_per_package == 0:
                inventory_item_id = submission_dict.get('inventory_item_id')
                if inventory_item_id:
                    # Try to get tablets_per_package via inventory_item_id -> tablet_types -> product_details
                    tpp_row = conn.execute('''
                        SELECT pd.tablets_per_package
                        FROM tablet_types tt
                        JOIN product_details pd ON tt.id = pd.tablet_type_id
                        WHERE tt.inventory_item_id = ?
                        LIMIT 1
                    ''', (inventory_item_id,)).fetchone()
                    if tpp_row:
                        tpp_dict = dict(tpp_row)
                        tablets_per_package = tpp_dict.get('tablets_per_package', 0) or 0

            # Calculate based on submission type
            if submission_type == 'machine':
                # Blister: one operator count (displays_made); never turns × cards × tablets.
                if machine_role_norm == 'blister':
                    bc = submission_dict.get('displays_made', 0) or 0
                    tpp = int(tablets_per_package or 0)
                    blisters_made = bc * BLISTER_BLISTERS_PER_CUT
                    tablet_total = blisters_made * tpp if tpp else (
                        submission_dict.get('tablets_pressed_into_cards') or 0
                    )
                    submission_dict['individual_calc'] = tablet_total
                    submission_dict['total_tablets'] = tablet_total
                    submission_dict['blister_machine_count'] = bc
                    submission_dict['blisters_per_cut'] = BLISTER_BLISTERS_PER_CUT
                    submission_dict['blisters_made'] = blisters_made
                    submission_dict['tablets_per_blister'] = tpp
                    submission_dict['cards_per_turn'] = None
                    submission_dict['machine_name'] = machine_name
                else:
                    # Sealing: normalize legacy rows where tablets_pressed_into_cards was stored as cards.
                    packs_remaining = submission_dict.get('packs_remaining', 0) or 0
                    stored_tablets = submission_dict.get('tablets_pressed_into_cards') or 0
                    tablets_from_cards = (packs_remaining * tablets_per_package) or 0
                    loose_tablets = submission_dict.get('loose_tablets') or 0
                    submission_dict['individual_calc'] = max(stored_tablets, tablets_from_cards, loose_tablets, 0)
                    submission_dict['total_tablets'] = submission_dict['individual_calc']
                    submission_dict['cards_per_turn'] = cards_per_turn
                    submission_dict['machine_name'] = machine_name
                    cm = submission_dict.get('cards_made')
                    if cm is not None:
                        submission_dict['packs_remaining'] = cm
            elif submission_type == 'repack':
                packages_per_display = submission_dict.get('packages_per_display', 0) or 0
                out = calculate_repack_output_good(
                    submission_dict, packages_per_display, tablets_per_package
                )
                submission_dict['individual_calc'] = out
                submission_dict['total_tablets'] = out
            else:
                # For packaged/bag submissions: calculate from displays and packs
                packages_per_display = submission_dict.get('packages_per_display', 0) or 0
                displays_made = submission_dict.get('displays_made', 0) or 0
                packs_remaining = submission_dict.get('packs_remaining', 0) or 0
                loose_tablets = submission_dict.get('loose_tablets', 0) or 0

                calculated_total = (
                    (displays_made * packages_per_display * tablets_per_package) +
                    (packs_remaining * tablets_per_package) +
                    loose_tablets
                )
                submission_dict['individual_calc'] = calculated_total
                submission_dict['total_tablets'] = calculated_total
                normalize_packaged_case_fields_for_ui(
                    submission_dict,
                    warehouse_submission_type=(
                        db_submission_type if db_submission_type is not None else 'packaged'
                    ),
                )
                if submission_dict.get('packaged_legacy_displays_only'):
                    pass
                elif 'case_count' in ws_columns and 'loose_display_count' in ws_columns:
                    submission_dict['case_count'] = int(submission_dict.get('case_count') or 0)
                    elc = submission_dict.get('loose_display_count')
                    if elc is not None:
                        submission_dict['loose_display_count'] = int(elc or 0)
                    else:
                        submission_dict['loose_display_count'] = int(displays_made or 0)
                    submission_dict['cases_made_total'] = int(submission_dict['case_count'])
                else:
                    submission_dict['case_count'] = None
                    submission_dict['loose_display_count'] = int(displays_made or 0)
                    submission_dict['cases_made_total'] = None

            # Repack rows store allocated bag_id but INSERT leaves box_number/bag_number NULL on the row.
            # Hydrate from bags/small_boxes so receive_name and bag running totals match the physical bag.
            if submission_type == 'repack' and submission_dict.get('bag_id'):
                bag_loc_row = conn.execute(
                    """
                    SELECT b.bag_number, b.bag_label_count, sb.box_number
                    FROM bags b
                    JOIN small_boxes sb ON b.small_box_id = sb.id
                    WHERE b.id = ?
                    """,
                    (submission_dict['bag_id'],),
                ).fetchone()
                if bag_loc_row:
                    bag_loc = dict(bag_loc_row)
                    submission_dict['box_number'] = bag_loc.get('box_number')
                    submission_dict['bag_number'] = bag_loc.get('bag_number')
                    if bag_loc.get('bag_label_count') is not None:
                        submission_dict['bag_label_count'] = bag_loc.get('bag_label_count')

            # Prefer receiving.receive_name; else shipment-level PO-{n}-{shipment}
            receive_name = submission_dict.get('receive_name_from_receive')
            if not receive_name and submission_dict.get('po_number') and submission_dict.get('shipment_number'):
                receive_name = f"{submission_dict.get('po_number')}-{submission_dict.get('shipment_number')}"
            submission_dict['receive_name'] = receive_name
            submission_dict.pop('receive_name_from_receive', None)

            # Cumulative bag check totals for this submission (chronological through this row)
            # Get all submissions to the same bag up to and including this submission (chronological order)
            if submission_dict.get('assigned_po_id') and submission_dict.get('product_name') and submission_dict.get('box_number') is not None and submission_dict.get('bag_number') is not None:
                # Same physical bag: match bag_id (repack + rows that store bag_id) OR legacy box_number+bag_number on row
                bid = submission_dict.get('bag_id')
                bx = submission_dict.get('box_number')
                bn = submission_dict.get('bag_number')

                # Get all submissions to this bag up to and including this one, in chronological order
                bag_submissions = conn.execute('''
                    SELECT ws.*, pd.packages_per_display, pd.tablets_per_package,
                           COALESCE(pd.tablets_per_package, (
                               SELECT pd2.tablets_per_package
                               FROM product_details pd2
                               JOIN tablet_types tt2 ON pd2.tablet_type_id = tt2.id
                               WHERE tt2.inventory_item_id = ws.inventory_item_id
                               LIMIT 1
                           )) as tablets_per_package_final,
                           COALESCE(m.machine_role, 'sealing') AS machine_role
                    FROM warehouse_submissions ws
                    LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                    LEFT JOIN machines m ON ws.machine_id = m.id
                    WHERE ws.assigned_po_id = ?
                    AND ws.product_name = ?
                    AND ws.created_at <= ?
                    AND (
                        (? IS NOT NULL AND ws.bag_id = ?)
                        OR (ws.box_number IS NOT NULL AND ws.bag_number IS NOT NULL
                            AND ws.box_number = ? AND ws.bag_number = ?)
                    )
                    ORDER BY ws.created_at ASC
                ''', (submission_dict.get('assigned_po_id'),
                      submission_dict.get('product_name'),
                      submission_dict.get('created_at'),
                      bid, bid, bx, bn)).fetchall()

                # Cumulative per-stage tablet totals for this physical bag
                bag_submission_tablets_total = 0
                machine_tablets_total = 0
                machine_blister_tablets_total = 0
                machine_sealing_tablets_total = 0
                packaged_tablets_total = 0

                for bag_sub in bag_submissions:
                    bag_sub_dict = dict(bag_sub)
                    bag_sub_type = bag_sub_dict.get('submission_type', 'packaged')

                    # Calculate individual total for this submission
                    if bag_sub_type == 'machine':
                        bag_tablets_per_package = (bag_sub_dict.get('tablets_per_package_final') or
                                                   bag_sub_dict.get('tablets_per_package') or 0)
                        machine_role = (bag_sub_dict.get('machine_role') or 'sealing').strip().lower()
                        if machine_role == 'blister':
                            cuts = bag_sub_dict.get('displays_made', 0) or 0
                            tpp = int(bag_tablets_per_package or 0)
                            blisters_made = cuts * BLISTER_BLISTERS_PER_CUT
                            individual_total = (
                                blisters_made * tpp
                                if tpp
                                else (bag_sub_dict.get('tablets_pressed_into_cards') or 0)
                            )
                            machine_blister_tablets_total += individual_total
                        else:
                            packs_remaining = bag_sub_dict.get('packs_remaining', 0) or 0
                            stored_tablets = bag_sub_dict.get('tablets_pressed_into_cards') or 0
                            tablets_from_cards = (packs_remaining * bag_tablets_per_package) or 0
                            loose_tablets = bag_sub_dict.get('loose_tablets') or 0
                            individual_total = max(stored_tablets, tablets_from_cards, loose_tablets, 0)
                            machine_sealing_tablets_total += individual_total
                        machine_tablets_total += individual_total
                        # Machine counts are NOT added to total - they're consumed in production
                    elif bag_sub_type == 'bag':
                        # For bag count submissions, use loose_tablets (the actual count from form)
                        individual_total = bag_sub_dict.get('loose_tablets', 0) or 0
                        bag_submission_tablets_total += individual_total
                        # Bag counts are NOT added to total - they're just inventory counts
                    elif bag_sub_type == 'repack':
                        # Repack credits PO good; physical bag totals stay packaged-only (no double-count)
                        individual_total = 0
                    else:  # 'packaged'
                        packages_per_display = bag_sub_dict.get('packages_per_display', 0) or 0
                        tablets_per_package = bag_sub_dict.get('tablets_per_package', 0) or 0
                        displays_made = bag_sub_dict.get('displays_made', 0) or 0
                        packs_remaining = bag_sub_dict.get('packs_remaining', 0) or 0
                        loose_tablets = bag_sub_dict.get('loose_tablets', 0) or 0
                        individual_total = (
                            (displays_made * packages_per_display * tablets_per_package) +
                            (packs_remaining * tablets_per_package) +
                            loose_tablets
                        )
                        packaged_tablets_total += individual_total

                submission_dict['bag_submission_tablets_total'] = bag_submission_tablets_total
                submission_dict['machine_tablets_total'] = machine_tablets_total
                submission_dict['machine_blister_tablets_total'] = machine_blister_tablets_total
                submission_dict['machine_sealing_tablets_total'] = machine_sealing_tablets_total
                submission_dict['packaged_tablets_total'] = packaged_tablets_total

                # Compare packaged tablet flow to bag label; machine/bag-inventory rows excluded from match
                bag_label_count = submission_dict.get('bag_label_count', 0) or 0
                if not submission_dict.get('bag_id'):
                    submission_dict['count_status'] = 'no_bag'
                    submission_dict['tablet_difference'] = None
                elif abs(packaged_tablets_total - bag_label_count) <= 5:  # Allow 5 tablet tolerance
                    submission_dict['count_status'] = 'match'
                    submission_dict['tablet_difference'] = abs(packaged_tablets_total - bag_label_count)
                elif packaged_tablets_total < bag_label_count:
                    submission_dict['count_status'] = 'under'
                    submission_dict['tablet_difference'] = bag_label_count - packaged_tablets_total
                else:
                    submission_dict['count_status'] = 'over'
                    submission_dict['tablet_difference'] = packaged_tablets_total - bag_label_count
            else:
                submission_dict['bag_submission_tablets_total'] = 0
                submission_dict['machine_tablets_total'] = 0
                submission_dict['machine_blister_tablets_total'] = 0
                submission_dict['machine_sealing_tablets_total'] = 0
                submission_dict['packaged_tablets_total'] = 0
                submission_dict['count_status'] = 'no_bag'
                submission_dict['tablet_difference'] = None

            # For bottle submissions, get bag deductions from junction table
            bag_deductions = []
            if submission_type == 'bottle':
                deductions = conn.execute('''
                    SELECT sbd.id, sbd.bag_id, sbd.tablets_deducted, sbd.created_at,
                           b.bag_number, b.bag_label_count,
                           sb.box_number,
                           tt.tablet_type_name,
                           r.receive_name, po.po_number
                    FROM submission_bag_deductions sbd
                    JOIN bags b ON sbd.bag_id = b.id
                    LEFT JOIN small_boxes sb ON b.small_box_id = sb.id
                    LEFT JOIN receiving r ON sb.receiving_id = r.id
                    LEFT JOIN purchase_orders po ON r.po_id = po.id
                    LEFT JOIN tablet_types tt ON b.tablet_type_id = tt.id
                    WHERE sbd.submission_id = ?
                    ORDER BY tt.tablet_type_name, sbd.created_at
                ''', (submission_id,)).fetchall()

                bag_deductions = [dict(d) for d in deductions]

                # Calculate total tablets from bag deductions (for variety packs)
                total_from_deductions = sum(d.get('tablets_deducted', 0) for d in bag_deductions)
                if total_from_deductions > 0:
                    submission_dict['individual_calc'] = total_from_deductions
                    submission_dict['total_tablets'] = total_from_deductions
                elif submission_dict.get('bottles_made'):
                    # For bottle-only products without junction table entries
                    bottles_made = submission_dict.get('bottles_made', 0) or 0
                    # Get tablets_per_bottle from product_details
                    product_row = conn.execute('''
                        SELECT tablets_per_bottle FROM product_details WHERE product_name = ?
                    ''', (submission_dict.get('product_name'),)).fetchone()
                    if product_row:
                        tablets_per_bottle = dict(product_row).get('tablets_per_bottle', 0) or 0
                        submission_dict['individual_calc'] = bottles_made * tablets_per_bottle
                        submission_dict['total_tablets'] = bottles_made * tablets_per_bottle

            return jsonify({
                'success': True,
                'submission': submission_dict,
                'bag_deductions': bag_deductions
            })
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        current_app.logger.error(f"GET SUBMISSION ERROR: {str(e)}")
        current_app.logger.error(error_trace)
        return jsonify({'error': str(e)}), 500



@bp.route('/api/submission/warehouse-edit-unlock-status', methods=['GET'])
@role_required('submissions')
@employee_required
def warehouse_submission_edit_unlock_status():
    """Unlock status for timed warehouse-staff edit window."""
    role = session.get('employee_role')
    if session.get('admin_authenticated') or role in ('admin', 'manager'):
        return jsonify({
            'success': True,
            'needs_unlock': False,
            'unlocked': True,
            'seconds_remaining': None,
        })
    if role in ('warehouse_staff', 'warehouse_lead'):
        unlocked = warehouse_submission_edit_unlock_valid()
        sec = warehouse_submission_edit_unlock_seconds_remaining() if unlocked else 0
        return jsonify({
            'success': True,
            'needs_unlock': True,
            'unlocked': unlocked,
            'seconds_remaining': sec,
            'ttl_seconds': WAREHOUSE_SUBMISSION_EDIT_UNLOCK_TTL_SECONDS,
        })
    return jsonify({
        'success': True,
        'needs_unlock': False,
        'unlocked': False,
        'seconds_remaining': 0,
    }), 200


@bp.route('/api/submission/warehouse-edit-unlock', methods=['POST'])
@role_required('submissions')
@employee_required
def warehouse_submission_edit_unlock():
    """
    Warehouse staff: verify admin-configured password and start timed edit-unlock session.
    CSRF via JSON API (same pattern as other staff POSTs).
    """
    role = session.get('employee_role')
    if role not in ('warehouse_staff', 'warehouse_lead'):
        return jsonify({'success': False, 'error': 'Unlock is only for warehouse staff/lead accounts.'}), 400
    data = request.get_json(silent=True) or {}
    password = (data.get('password') or '').strip()
    if not password:
        return jsonify({'success': False, 'error': 'Password is required.'}), 400

    ensure_app_settings_table()
    stored_hash = get_setting('warehouse_submission_edit_password_hash', '')
    if not stored_hash:
        return jsonify({'success': False, 'error': 'Submission edit password is not configured. Ask an admin to set it in Admin Panel.'}), 503

    if not verify_password(password, stored_hash):
        return jsonify({'success': False, 'error': 'Invalid password.'}), 403

    set_warehouse_submission_edit_unlock()
    return jsonify({
        'success': True,
        'seconds_remaining': warehouse_submission_edit_unlock_seconds_remaining(),
        'ttl_seconds': WAREHOUSE_SUBMISSION_EDIT_UNLOCK_TTL_SECONDS,
    })


@bp.route('/api/submission/<int:submission_id>/edit', methods=['POST'])
@employee_required
def edit_submission(submission_id):
    """Edit a submission — managers/admin always; warehouse staff only during timed unlock."""
    # Must not use @admin_required here — managers use employee login, not admin panel.
    role = session.get('employee_role')
    if session.get('admin_authenticated') or (session.get('employee_authenticated') and role in ('admin', 'manager')):
        pass
    elif role in ('warehouse_staff', 'warehouse_lead'):
        if not warehouse_submission_edit_unlock_valid():
            return jsonify({
                'success': False,
                'error': 'Admin unlock password required. Ask an admin to enter the password, then try again.',
                'code': 'WAREHOUSE_EDIT_LOCKED',
            }), 403
    else:
        return jsonify({'success': False, 'error': 'Access denied. Only administrators and managers can edit submissions.'}), 403
    try:
        data = request.get_json()
        with db_transaction() as conn:
            # Get the submission's current PO assignment
            submission = conn.execute('''
                SELECT assigned_po_id, product_name, displays_made, packs_remaining,
                       loose_tablets, cards_reopened, tablets_pressed_into_cards, inventory_item_id,
                       bottles_made, machine_id,
                       COALESCE(submission_type, 'packaged') as submission_type,
                       repack_vendor_return_notes, repack_machine_count,
                       bag_start_time, bag_end_time, bottle_sealing_machine_count,
                       receipt_number, employee_name, submission_date
                FROM warehouse_submissions
                WHERE id = ?
            ''', (submission_id,)).fetchone()

            if not submission:
                return jsonify({'success': False, 'error': 'Submission not found'}), 404

            # Convert Row to dict for safe access
            submission = dict(submission)
            ws_columns = {row['name'] for row in conn.execute("PRAGMA table_info(warehouse_submissions)").fetchall()}

            old_po_id = submission['assigned_po_id']
            inventory_item_id = submission['inventory_item_id']

            # Check if product_name is being changed
            new_product_name = data.get('product_name')
            product_name_to_use = new_product_name if new_product_name else submission['product_name']

            # If product is being changed, update inventory_item_id
            if new_product_name and new_product_name != submission['product_name']:
                # Get the new inventory_item_id for the new product
                # Try product_name first (from product_details)
                new_product_info = conn.execute('''
                    SELECT tt.inventory_item_id, pd.product_name
                    FROM tablet_types tt
                    JOIN product_details pd ON tt.id = pd.tablet_type_id
                    WHERE pd.product_name = ?
                    LIMIT 1
                ''', (new_product_name,)).fetchone()

                # If not found by product_name, try tablet_type_name
                if not new_product_info:
                    new_product_info = conn.execute('''
                        SELECT tt.inventory_item_id, pd.product_name
                        FROM tablet_types tt
                        LEFT JOIN product_details pd ON tt.id = pd.tablet_type_id
                        WHERE tt.tablet_type_name = ?
                        LIMIT 1
                    ''', (new_product_name,)).fetchone()

                if new_product_info:
                    # Convert Row to dict for safe access
                    new_product_info = dict(new_product_info)
                    inventory_item_id = new_product_info['inventory_item_id']
                    # Use the actual product_name from product_details if available
                    if new_product_info.get('product_name'):
                        new_product_name = new_product_info['product_name']

            # Get product details for calculations
            # Make this more resilient - try multiple approaches
            product = conn.execute('''
                SELECT pd.packages_per_display, pd.tablets_per_package, pd.tablets_per_bottle, pd.bottles_per_display,
                       pd.displays_per_case
                FROM product_details pd
                JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                WHERE pd.product_name = ?
            ''', (product_name_to_use,)).fetchone()

            if not product:
                # Fallback: try to get product details without the JOIN
                product = conn.execute('''
                    SELECT packages_per_display, tablets_per_package, tablets_per_bottle, bottles_per_display,
                           displays_per_case
                    FROM product_details
                    WHERE product_name = ?
                ''', (product_name_to_use,)).fetchone()

            if not product:
                # Last resort: get from existing submission or use defaults
                existing_config = conn.execute('''
                    SELECT pd.packages_per_display, pd.tablets_per_package, pd.tablets_per_bottle, pd.bottles_per_display,
                           pd.displays_per_case
                    FROM warehouse_submissions ws
                    LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                    WHERE ws.id = ?
                ''', (submission_id,)).fetchone()

                if existing_config:
                    existing_config = dict(existing_config)

                if existing_config and (existing_config.get('packages_per_display') or existing_config.get('tablets_per_package')):
                    product = existing_config
                else:
                    # Use defaults to allow edit (admin can fix product config later)
                    current_app.logger.warning(f"Product configuration not found for {product_name_to_use}, using defaults")
                    product = {
                        'packages_per_display': 1,
                        'tablets_per_package': 1,
                        'tablets_per_bottle': 0,
                        'bottles_per_display': 0
                    }

            # Convert Row to dict for safe access
            if not isinstance(product, dict):
                product = dict(product)

            # Validate and normalize product configuration values
            packages_per_display = product.get('packages_per_display')
            tablets_per_package = product.get('tablets_per_package')
            tablets_per_bottle = product.get('tablets_per_bottle') or 0
            bottles_per_display = product.get('bottles_per_display') or 0

            submission_type = submission.get('submission_type', 'packaged')
            if submission_type in ['packaged', 'bag', 'repack'] and (
                packages_per_display is None or tablets_per_package is None or
                packages_per_display == 0 or tablets_per_package == 0
            ):
                return jsonify({'success': False, 'error': 'Product configuration incomplete: packages_per_display and tablets_per_package are required and must be greater than 0'}), 400
            if submission_type == 'bottle' and (bottles_per_display is None or bottles_per_display == 0):
                return jsonify({'success': False, 'error': 'Bottle product configuration incomplete: bottles_per_display must be greater than 0'}), 400

            # Convert to int after validation
            try:
                packages_per_display = int(packages_per_display)
                tablets_per_package = int(tablets_per_package)
                tablets_per_bottle = int(tablets_per_bottle or 0)
                bottles_per_display = int(bottles_per_display or 0)
            except (ValueError, TypeError):
                return jsonify({'success': False, 'error': 'Invalid numeric values for product configuration'}), 400
            displays_per_case = int(product.get('displays_per_case') or 0)

            # Calculate old totals to subtract based on submission type
            if submission_type == 'machine':
                old_good = submission.get('tablets_pressed_into_cards', 0) or 0
            elif submission_type == 'bottle':
                old_deductions = conn.execute(
                    'SELECT COALESCE(SUM(tablets_deducted), 0) as total FROM submission_bag_deductions WHERE submission_id = ?',
                    (submission_id,)
                ).fetchone()
                if old_deductions and old_deductions['total']:
                    old_good = old_deductions['total']
                else:
                    old_bottles = submission.get('bottles_made')
                    if old_bottles is None:
                        old_bottles = ((submission.get('displays_made') or 0) * bottles_per_display) + (submission.get('packs_remaining') or 0)
                    old_good = (old_bottles or 0) * tablets_per_bottle
            elif submission_type == 'repack':
                old_good = calculate_repack_output_good(
                    submission, packages_per_display, tablets_per_package
                )
            else:
                old_good = (submission['displays_made'] * packages_per_display * tablets_per_package +
                           submission['packs_remaining'] * tablets_per_package +
                           submission['loose_tablets'])
            # Cards re-opened (cards_reopened) does not affect PO damaged_count
            old_damaged = 0

            # Validate and convert input data
            try:
                displays_made = int(data.get('displays_made', 0) or 0)
                packs_remaining = int(data.get('packs_remaining', 0) or 0)
                loose_tablets = int(data.get('loose_tablets', 0) or 0) if submission_type not in ['machine', 'bottle', 'repack'] else 0
                cards_reopened = int(data.get('cards_reopened', 0) or 0) if submission_type not in ('bottle', 'repack') else 0
                tablets_pressed_into_cards = int(data.get('tablets_pressed_into_cards', 0) or 0) if submission_type == 'machine' else 0
            except (ValueError, TypeError):
                return jsonify({'success': False, 'error': 'Invalid numeric values for counts'}), 400

            bottle_sealing_machine_count = None
            if submission_type == 'bottle':
                try:
                    if 'bottle_sealing_machine_count' in data:
                        bsm_raw = data.get('bottle_sealing_machine_count')
                        if bsm_raw is None or (isinstance(bsm_raw, str) and not str(bsm_raw).strip()):
                            bottle_sealing_machine_count = 0
                        else:
                            bottle_sealing_machine_count = int(bsm_raw)
                    else:
                        prev = submission.get('bottle_sealing_machine_count')
                        bottle_sealing_machine_count = int(prev) if prev is not None else 0
                except (ValueError, TypeError):
                    return jsonify({'success': False, 'error': 'Invalid bottle sealing machine count'}), 400
                if bottle_sealing_machine_count < 0:
                    return jsonify({'success': False, 'error': 'Bottle sealing machine count must be >= 0'}), 400

            new_machine_id = None
            if submission_type == 'machine':
                mid_raw = data.get('machine_id')
                if mid_raw is None or str(mid_raw).strip() == '':
                    return jsonify({'success': False, 'error': 'Machine is required for machine submissions'}), 400
                try:
                    new_machine_id = int(mid_raw)
                except (ValueError, TypeError):
                    return jsonify({'success': False, 'error': 'Invalid machine_id'}), 400
                machine_row = conn.execute(
                    '''
                    SELECT id, COALESCE(cards_per_turn, 0) AS cards_per_turn,
                           COALESCE(machine_role, 'sealing') AS machine_role
                    FROM machines
                    WHERE id = ? AND COALESCE(is_active, 1) = 1
                    ''',
                    (new_machine_id,),
                ).fetchone()
                if not machine_row:
                    return jsonify({'success': False, 'error': 'Invalid or inactive machine selected'}), 400
                machine_role_edit = (machine_row['machine_role'] or 'sealing').strip().lower()
                if machine_role_edit not in ('sealing', 'blister'):
                    machine_role_edit = 'sealing'
                if machine_role_edit == 'blister':
                    tablets_pressed_into_cards = displays_made * BLISTER_BLISTERS_PER_CUT * tablets_per_package
                    packs_remaining = 0
                else:
                    cpt = int(machine_row['cards_per_turn'] or 0)
                    if cpt <= 0:
                        return jsonify({'success': False, 'error': 'Selected machine has no valid cards-per-turn configured'}), 400
                    tablets_pressed_into_cards = displays_made * cpt
                    packs_remaining = tablets_pressed_into_cards

            # Calculate new totals based on submission type
            if submission_type == 'machine':
                new_good = tablets_pressed_into_cards
            elif submission_type == 'bottle':
                new_bottles_made = (displays_made * bottles_per_display) + packs_remaining
                deduction_totals = conn.execute(
                    'SELECT COALESCE(SUM(tablets_deducted), 0) as total FROM submission_bag_deductions WHERE submission_id = ?',
                    (submission_id,)
                ).fetchone()
                if deduction_totals and deduction_totals['total']:
                    new_good = deduction_totals['total']
                else:
                    new_good = new_bottles_made * tablets_per_bottle
            elif submission_type == 'repack':
                new_good = calculate_repack_output_good(
                    {
                        'displays_made': displays_made,
                        'packs_remaining': packs_remaining,
                    },
                    packages_per_display,
                    tablets_per_package,
                )
            else:
                new_good = (displays_made * packages_per_display * tablets_per_package +
                           packs_remaining * tablets_per_package +
                           loose_tablets)
            new_damaged = 0

            # Get receipt_number from form data
            receipt_number = (data.get('receipt_number') or '').strip() or None

            bag_start_parsed = None
            bag_end_parsed = None
            if submission_type == 'machine' and 'bag_start_time' in data:
                try:
                    bag_start_parsed = parse_optional_eastern(data.get('bag_start_time'))
                except ValueError as ve:
                    return jsonify({'success': False, 'error': f'Invalid bag start time: {ve}'}), 400
            elif submission_type == 'packaged' and 'bag_end_time' in data:
                try:
                    bag_end_parsed = parse_optional_eastern(data.get('bag_end_time'))
                except ValueError as ve:
                    return jsonify({'success': False, 'error': f'Invalid bag end time: {ve}'}), 400

            # Find the correct bag_id if box_number and bag_number are provided
            new_box_number = data.get('box_number')
            new_bag_number = data.get('bag_number')
            new_bag_id = None

            if new_box_number is not None and new_bag_number is not None and old_po_id:
                # Try to find the bag that matches the new box_number and bag_number for this PO
                bag_row = conn.execute('''
                    SELECT b.id
                    FROM bags b
                    JOIN small_boxes sb ON b.small_box_id = sb.id
                    JOIN receiving r ON sb.receiving_id = r.id
                    WHERE r.po_id = ?
                    AND sb.box_number = ?
                    AND b.bag_number = ?
                    LIMIT 1
                ''', (old_po_id, new_box_number, new_bag_number)).fetchone()

                if bag_row:
                    new_bag_id = dict(bag_row).get('id')
                # If no bag found, set bag_id to NULL (submission will be unassigned)

            # Update the submission
            submission_date = data.get('submission_date', datetime.now().date().isoformat())
            if submission_type == 'machine':
                if 'bag_start_time' in data:
                    conn.execute('''
                        UPDATE warehouse_submissions
                        SET displays_made = ?, packs_remaining = ?, tablets_pressed_into_cards = ?,
                            cards_reopened = ?, box_number = ?, bag_number = ?, bag_id = ?, bag_label_count = ?,
                            submission_date = ?, admin_notes = ?, receipt_number = ?, product_name = ?, inventory_item_id = ?,
                            machine_id = ?, bag_start_time = ?
                        WHERE id = ?
                    ''', (displays_made, packs_remaining, tablets_pressed_into_cards,
                          cards_reopened, new_box_number, new_bag_number, new_bag_id,
                          data.get('bag_label_count'), submission_date, data.get('admin_notes'), receipt_number,
                          product_name_to_use, inventory_item_id, new_machine_id, bag_start_parsed, submission_id))
                else:
                    conn.execute('''
                        UPDATE warehouse_submissions
                        SET displays_made = ?, packs_remaining = ?, tablets_pressed_into_cards = ?,
                            cards_reopened = ?, box_number = ?, bag_number = ?, bag_id = ?, bag_label_count = ?,
                            submission_date = ?, admin_notes = ?, receipt_number = ?, product_name = ?, inventory_item_id = ?,
                            machine_id = ?
                        WHERE id = ?
                    ''', (displays_made, packs_remaining, tablets_pressed_into_cards,
                          cards_reopened, new_box_number, new_bag_number, new_bag_id,
                          data.get('bag_label_count'), submission_date, data.get('admin_notes'), receipt_number,
                          product_name_to_use, inventory_item_id, new_machine_id, submission_id))
            elif submission_type == 'bottle':
                bottles_made = (displays_made * bottles_per_display) + packs_remaining
                conn.execute('''
                    UPDATE warehouse_submissions
                    SET displays_made = ?, packs_remaining = ?, bottles_made = ?, loose_tablets = 0,
                        cards_reopened = 0, box_number = ?, bag_number = ?, bag_id = ?, bag_label_count = ?,
                        submission_date = ?, admin_notes = ?, receipt_number = ?, product_name = ?, inventory_item_id = ?,
                        bottle_sealing_machine_count = ?
                    WHERE id = ?
                ''', (displays_made, packs_remaining, bottles_made,
                      new_box_number, new_bag_number, new_bag_id,
                      data.get('bag_label_count'), submission_date, data.get('admin_notes'), receipt_number,
                      product_name_to_use, inventory_item_id, bottle_sealing_machine_count, submission_id))
            elif submission_type == 'repack':
                tt_row = conn.execute(
                    'SELECT tablet_type_id FROM product_details WHERE product_name = ?',
                    (product_name_to_use,),
                ).fetchone()
                tablet_type_id = tt_row['tablet_type_id'] if tt_row else None
                alloc_json = None
                nr_flag = False
                first_bag_id = None
                if old_po_id and tablet_type_id is not None:
                    ap, nr_flag = allocate_repack_tablets(conn, old_po_id, tablet_type_id, max(0, new_good))
                    alloc_json = allocation_payload_to_json(ap)
                    for a in ap.get('allocations') or []:
                        if a.get('bag_id') is not None and not a.get('overflow'):
                            first_bag_id = a['bag_id']
                            break
                vn = data.get('repack_vendor_return_notes')
                if vn is None:
                    vn = submission.get('repack_vendor_return_notes')
                elif isinstance(vn, str):
                    vn = vn.strip() or None
                else:
                    vn = None
                try:
                    rmc = data.get('repack_machine_count', submission.get('repack_machine_count', 0))
                    repack_machine_count = int(rmc) if rmc is not None else 0
                except (TypeError, ValueError):
                    repack_machine_count = 0
                if repack_machine_count < 0:
                    repack_machine_count = 0
                conn.execute(
                    '''
                    UPDATE warehouse_submissions
                    SET displays_made = ?, packs_remaining = ?, loose_tablets = 0, cards_reopened = 0,
                        bag_id = ?, needs_review = ?,
                        submission_date = ?, admin_notes = ?, receipt_number = ?, product_name = ?, inventory_item_id = ?,
                        repack_bag_allocations = ?, repack_vendor_return_notes = ?,
                        repack_machine_count = ?
                    WHERE id = ?
                    ''',
                    (
                        displays_made,
                        packs_remaining,
                        first_bag_id,
                        nr_flag,
                        submission_date,
                        data.get('admin_notes'),
                        receipt_number,
                        product_name_to_use,
                        inventory_item_id,
                        alloc_json,
                        vn,
                        repack_machine_count,
                        submission_id,
                    ),
                )
            else:
                case_count_for_update = 0
                loose_display_count_for_update = 0
                if displays_per_case > 0:
                    case_count_for_update = displays_made // displays_per_case
                    loose_display_count_for_update = displays_made % displays_per_case
                if submission_type == 'packaged' and 'bag_end_time' in data:
                    if 'case_count' in ws_columns and 'loose_display_count' in ws_columns:
                        conn.execute('''
                            UPDATE warehouse_submissions
                            SET displays_made = ?, packs_remaining = ?, loose_tablets = ?,
                                    cards_reopened = ?, box_number = ?, bag_number = ?, bag_id = ?, bag_label_count = ?,
                                    submission_date = ?, admin_notes = ?, receipt_number = ?, product_name = ?, inventory_item_id = ?,
                                    bag_end_time = ?, case_count = ?, loose_display_count = ?
                            WHERE id = ?
                        ''', (displays_made, packs_remaining, loose_tablets,
                                  cards_reopened, new_box_number, new_bag_number, new_bag_id,
                                  data.get('bag_label_count'), submission_date, data.get('admin_notes'), receipt_number,
                                  product_name_to_use, inventory_item_id, bag_end_parsed,
                                  case_count_for_update, loose_display_count_for_update, submission_id))
                    else:
                        conn.execute('''
                            UPDATE warehouse_submissions
                            SET displays_made = ?, packs_remaining = ?, loose_tablets = ?,
                                    cards_reopened = ?, box_number = ?, bag_number = ?, bag_id = ?, bag_label_count = ?,
                                    submission_date = ?, admin_notes = ?, receipt_number = ?, product_name = ?, inventory_item_id = ?,
                                    bag_end_time = ?
                            WHERE id = ?
                        ''', (displays_made, packs_remaining, loose_tablets,
                                  cards_reopened, new_box_number, new_bag_number, new_bag_id,
                                  data.get('bag_label_count'), submission_date, data.get('admin_notes'), receipt_number,
                                  product_name_to_use, inventory_item_id, bag_end_parsed, submission_id))
                else:
                    if 'case_count' in ws_columns and 'loose_display_count' in ws_columns:
                        conn.execute('''
                            UPDATE warehouse_submissions
                            SET displays_made = ?, packs_remaining = ?, loose_tablets = ?,
                                    cards_reopened = ?, box_number = ?, bag_number = ?, bag_id = ?, bag_label_count = ?,
                                    submission_date = ?, admin_notes = ?, receipt_number = ?, product_name = ?, inventory_item_id = ?,
                                    case_count = ?, loose_display_count = ?
                            WHERE id = ?
                        ''', (displays_made, packs_remaining, loose_tablets,
                                  cards_reopened, new_box_number, new_bag_number, new_bag_id,
                                  data.get('bag_label_count'), submission_date, data.get('admin_notes'), receipt_number,
                                  product_name_to_use, inventory_item_id,
                                  case_count_for_update, loose_display_count_for_update, submission_id))
                    else:
                        conn.execute('''
                            UPDATE warehouse_submissions
                            SET displays_made = ?, packs_remaining = ?, loose_tablets = ?,
                                    cards_reopened = ?, box_number = ?, bag_number = ?, bag_id = ?, bag_label_count = ?,
                                    submission_date = ?, admin_notes = ?, receipt_number = ?, product_name = ?, inventory_item_id = ?
                            WHERE id = ?
                        ''', (displays_made, packs_remaining, loose_tablets,
                                  cards_reopened, new_box_number, new_bag_number, new_bag_id,
                                  data.get('bag_label_count'), submission_date, data.get('admin_notes'), receipt_number,
                                  product_name_to_use, inventory_item_id, submission_id))

            propagated_edits = 0
            apply_receipt_group = data.get('apply_receipt_group', True)
            source_receipt = (submission.get('receipt_number') or '').strip() if submission.get('receipt_number') else ''
            source_employee = submission.get('employee_name')
            source_submission_date = submission.get('submission_date')
            should_propagate = (
                bool(apply_receipt_group)
                and source_receipt
                and source_employee
                and source_submission_date
                and submission_type != 'repack'
            )
            if should_propagate:
                siblings = conn.execute(
                    '''
                    SELECT id
                    FROM warehouse_submissions
                    WHERE id != ?
                      AND receipt_number = ?
                      AND employee_name = ?
                      AND submission_date = ?
                      AND COALESCE(submission_type, 'packaged') != 'repack'
                    ''',
                    (submission_id, source_receipt, source_employee, source_submission_date),
                ).fetchall()
                sibling_ids = [int(r['id']) for r in siblings]
                if sibling_ids:
                    placeholders = ','.join(['?'] * len(sibling_ids))
                    conn.execute(
                        f'''
                        UPDATE warehouse_submissions
                        SET box_number = ?, bag_number = ?, bag_id = ?, bag_label_count = ?,
                            submission_date = ?, receipt_number = ?
                        WHERE id IN ({placeholders})
                        ''',
                        (
                            new_box_number,
                            new_bag_number,
                            new_bag_id,
                            data.get('bag_label_count'),
                            submission_date,
                            receipt_number,
                            *sibling_ids,
                        ),
                    )
                    propagated_edits = len(sibling_ids)

            # Update PO line counts if assigned to a PO
            if old_po_id and inventory_item_id:
                # Find the PO line
                po_line = conn.execute('''
                    SELECT id FROM po_lines
                    WHERE po_id = ? AND inventory_item_id = ?
                    LIMIT 1
                ''', (old_po_id, inventory_item_id)).fetchone()

                if po_line:
                    # Convert Row to dict for safe access
                    po_line = dict(po_line)

                    # Calculate the difference and update
                    good_diff = new_good - old_good
                    damaged_diff = new_damaged - old_damaged

                    conn.execute('''
                        UPDATE po_lines
                        SET good_count = good_count + ?, damaged_count = damaged_count + ?
                        WHERE id = ?
                    ''', (good_diff, damaged_diff, po_line['id']))

                    # Update PO header totals
                    totals = conn.execute('''
                        SELECT
                            COALESCE(SUM(quantity_ordered), 0) as total_ordered,
                            COALESCE(SUM(good_count), 0) as total_good,
                            COALESCE(SUM(damaged_count), 0) as total_damaged
                        FROM po_lines
                        WHERE po_id = ?
                    ''', (old_po_id,)).fetchone()

                    # Convert Row to dict for safe access
                    totals = dict(totals)

                    remaining = totals['total_ordered'] - totals['total_good'] - totals['total_damaged']
                    conn.execute('''
                        UPDATE purchase_orders
                        SET ordered_quantity = ?, current_good_count = ?,
                            current_damaged_count = ?, remaining_quantity = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    ''', (totals['total_ordered'], totals['total_good'],
                          totals['total_damaged'], remaining, old_po_id))

            return jsonify({
                'success': True,
                'message': (
                    'Submission updated successfully'
                    if propagated_edits <= 0
                    else f'Submission updated successfully (applied to {propagated_edits + 1} submissions on this receipt)'
                ),
                'propagated_count': propagated_edits
            })
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        current_app.logger.error(f"EDIT SUBMISSION ERROR: {str(e)}")
        current_app.logger.error(error_trace)
        return jsonify({'error': str(e)}), 500



@bp.route('/api/submission/<int:submission_id>/delete', methods=['POST'])
@admin_required
def delete_submission(submission_id):
    """Delete a submission and remove its counts from PO (Admin only)"""
    try:
        with db_transaction() as conn:
            # Get the submission details
            submission = conn.execute('''
                SELECT assigned_po_id, product_name, displays_made, packs_remaining,
                       loose_tablets, cards_reopened, tablets_pressed_into_cards, inventory_item_id,
                       bottles_made,
                       COALESCE(submission_type, 'packaged') as submission_type
                FROM warehouse_submissions
                WHERE id = ?
            ''', (submission_id,)).fetchone()

            if not submission:
                return jsonify({'success': False, 'error': 'Submission not found'}), 404

            # Convert Row to dict for safe access
            submission = dict(submission)

            old_po_id = submission['assigned_po_id']
            inventory_item_id = submission['inventory_item_id']

            # Get product details for calculations
            product = conn.execute('''
                SELECT pd.packages_per_display, pd.tablets_per_package,
                       pd.tablets_per_bottle, pd.bottles_per_display,
                       pd.is_bottle_product, pd.is_variety_pack
                FROM product_details pd
                LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                WHERE pd.product_name = ?
            ''', (submission['product_name'],)).fetchone()

            # Calculate counts to remove based on submission type
            submission_type = submission.get('submission_type', 'packaged')

            if submission_type == 'bottle':
                # For bottle submissions, delete junction table entries first
                conn.execute('''
                    DELETE FROM submission_bag_deductions WHERE submission_id = ?
                ''', (submission_id,))

                # Calculate tablets for bottle submissions
                if product:
                    product = dict(product)
                    tablets_per_bottle = product.get('tablets_per_bottle') or 0
                    bottles_made = submission.get('bottles_made', 0) or 0
                    good_tablets = bottles_made * tablets_per_bottle
                else:
                    # If no product config, just use 0 (can't calculate)
                    good_tablets = 0
            elif submission_type == 'machine':
                good_tablets = submission.get('tablets_pressed_into_cards', 0) or 0
            elif submission_type == 'repack':
                if not product:
                    return jsonify({'success': False, 'error': 'Product configuration not found'}), 400
                product = dict(product)
                good_tablets = calculate_repack_output_good(
                    submission,
                    product.get('packages_per_display'),
                    product.get('tablets_per_package'),
                )
            else:
                # Packaged submissions require product config
                if not product:
                    return jsonify({'success': False, 'error': 'Product configuration not found'}), 400
                product = dict(product)
                good_tablets = (submission['displays_made'] * (product.get('packages_per_display') or 0) * (product.get('tablets_per_package') or 0) +
                               submission['packs_remaining'] * (product.get('tablets_per_package') or 0) +
                               submission['loose_tablets'])

            # Packaging cards re-opened do not affect PO line damaged_count
            receiving_damaged_subtract = 0

            # Remove counts from PO line if assigned
            if old_po_id and inventory_item_id:
                # Find the PO line
                po_line = conn.execute('''
                    SELECT id FROM po_lines
                    WHERE po_id = ? AND inventory_item_id = ?
                    LIMIT 1
                ''', (old_po_id, inventory_item_id)).fetchone()

                if po_line:
                    # Get current counts first to calculate new values
                    current_line = conn.execute('''
                        SELECT good_count, damaged_count FROM po_lines WHERE id = ?
                    ''', (po_line['id'],)).fetchone()

                    new_good = max(0, (current_line['good_count'] or 0) - good_tablets)
                    new_damaged = max(0, (current_line['damaged_count'] or 0) - receiving_damaged_subtract)

                    # Remove counts from PO line
                    conn.execute('''
                        UPDATE po_lines
                        SET good_count = ?,
                            damaged_count = ?
                        WHERE id = ?
                    ''', (new_good, new_damaged, po_line['id']))

                    # Update PO header totals
                    totals = conn.execute('''
                        SELECT
                            COALESCE(SUM(quantity_ordered), 0) as total_ordered,
                            COALESCE(SUM(good_count), 0) as total_good,
                            COALESCE(SUM(damaged_count), 0) as total_damaged
                        FROM po_lines
                        WHERE po_id = ?
                    ''', (old_po_id,)).fetchone()

                    remaining = totals['total_ordered'] - totals['total_good'] - totals['total_damaged']
                    conn.execute('''
                        UPDATE purchase_orders
                        SET ordered_quantity = ?, current_good_count = ?,
                            current_damaged_count = ?, remaining_quantity = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    ''', (totals['total_ordered'], totals['total_good'],
                          totals['total_damaged'], remaining, old_po_id))

            # Delete the submission
            conn.execute('DELETE FROM warehouse_submissions WHERE id = ?', (submission_id,))

            return jsonify({
                'success': True,
                'message': 'Submission deleted successfully'
            })
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        current_app.logger.error(f"DELETE SUBMISSION ERROR: {str(e)}")
        current_app.logger.error(error_trace)
        return jsonify({'success': False, 'error': str(e)}), 500



@bp.route('/api/po/<int:po_id>/delete', methods=['POST'])
@admin_required
def delete_po(po_id):
    """Delete a PO and all its related data (Admin only)"""
    try:
        with db_transaction() as conn:
            # Get PO details first
            po = conn.execute('SELECT po_number FROM purchase_orders WHERE id = ?', (po_id,)).fetchone()

            if not po:
                return jsonify({'success': False, 'error': 'PO not found'}), 404

            # Delete related data
            # 1. Unassign all submissions (don't delete submissions, just unassign them)
            conn.execute('UPDATE warehouse_submissions SET assigned_po_id = NULL WHERE assigned_po_id = ?', (po_id,))

            # 2. Delete shipments
            conn.execute('DELETE FROM shipments WHERE po_id = ?', (po_id,))

            # 3. Delete PO lines
            conn.execute('DELETE FROM po_lines WHERE po_id = ?', (po_id,))

            # 4. Delete the PO itself
            conn.execute('DELETE FROM purchase_orders WHERE id = ?', (po_id,))

            return jsonify({
                'success': True,
                'message': f'Successfully deleted {po["po_number"]} and all related data'
            })
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        current_app.logger.error(f"DELETE PO ERROR: {str(e)}")
        current_app.logger.error(error_trace)
        return jsonify({'error': str(e)}), 500



@bp.route('/api/resync_unassigned_submissions', methods=['POST'])
@admin_required
def resync_unassigned_submissions():
    """Resync unassigned submissions to try matching them with POs based on updated item IDs"""
    try:
        with db_transaction() as conn:
            # Get all unassigned submissions - convert to dicts immediately
            # Note: Use 'id' instead of 'rowid' for better compatibility
            unassigned_rows = conn.execute('''
                SELECT ws.id, ws.product_name, ws.displays_made,
                       ws.packs_remaining, ws.loose_tablets, ws.cards_reopened, ws.tablets_pressed_into_cards,
                       COALESCE(ws.submission_type, 'packaged') as submission_type
                FROM warehouse_submissions ws
                WHERE ws.assigned_po_id IS NULL
                ORDER BY ws.created_at DESC
            ''').fetchall()

            # Convert Row objects to dicts to avoid key access issues
            unassigned = [dict(row) for row in unassigned_rows]

            if not unassigned:
                return jsonify({'success': True, 'message': 'No unassigned submissions found'})

            matched_count = 0
            updated_pos = set()

            for submission in unassigned:
                try:
                    # Get the product's details including inventory_item_id
                    # submission['product_name'] matches product_details.product_name
                    # then join to tablet_types to get inventory_item_id
                    product_row = conn.execute('''
                        SELECT tt.inventory_item_id, pd.packages_per_display, pd.tablets_per_package
                        FROM product_details pd
                        JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                        WHERE pd.product_name = ?
                    ''', (submission['product_name'],)).fetchone()

                    if not product_row:
                        # Try direct tablet_type match if no product_details entry
                        product_row = conn.execute('''
                            SELECT inventory_item_id, 0 as packages_per_display, 0 as tablets_per_package
                            FROM tablet_types
                            WHERE tablet_type_name = ?
                        ''', (submission['product_name'],)).fetchone()

                    if not product_row:
                        current_app.logger.warning(f"⚠️  No product config found for: {submission['product_name']}")
                        continue

                    # Convert to dict for safe access
                    product = dict(product_row)
                    inventory_item_id = product.get('inventory_item_id')

                    if not inventory_item_id:
                        current_app.logger.warning(f"⚠️  No inventory_item_id for: {submission['product_name']}")
                        continue
                except Exception as e:
                    current_app.logger.error(f"❌ Error processing submission {submission.get('id', 'unknown')}: {e}")
                    continue

                # Find open PO lines for this inventory item
                # Order by PO number (oldest PO numbers first) since they represent issue order
                # Exclude Draft POs - only assign to Issued/Active POs
                # Note: We do NOT filter by available quantity - POs can receive more than ordered
                po_lines_rows = conn.execute('''
                    SELECT pl.*, po.closed
                    FROM po_lines pl
                    JOIN purchase_orders po ON pl.po_id = po.id
                    WHERE pl.inventory_item_id = ? AND po.closed = FALSE
                    AND COALESCE(po.internal_status, '') != 'Draft'
                    ORDER BY po.po_number ASC
                ''', (inventory_item_id,)).fetchall()

                # Convert to dicts
                po_lines = [dict(row) for row in po_lines_rows]

                if not po_lines:
                    continue

                # Good tablets and PO-line damaged delta (packaging cards_reopened never here)
                submission_type = submission.get('submission_type', 'packaged')
                if submission_type == 'machine':
                    good_tablets = submission.get('tablets_pressed_into_cards', 0) or 0
                    line_damaged_delta = 0
                elif submission_type == 'repack':
                    packages_per_display = product.get('packages_per_display') or 0
                    tablets_per_package = product.get('tablets_per_package') or 0
                    good_tablets = calculate_repack_output_good(
                        submission, packages_per_display, tablets_per_package
                    )
                    line_damaged_delta = 0
                else:
                    packages_per_display = product.get('packages_per_display') or 0
                    tablets_per_package = product.get('tablets_per_package') or 0
                    good_tablets = (submission.get('displays_made', 0) * packages_per_display * tablets_per_package +
                                  submission.get('packs_remaining', 0) * tablets_per_package +
                                  submission.get('loose_tablets', 0))
                    line_damaged_delta = 0

                # Assign to first available PO
                assigned_po_id = po_lines[0]['po_id']
                conn.execute('''
                    UPDATE warehouse_submissions
                    SET assigned_po_id = ?
                    WHERE id = ?
                ''', (assigned_po_id, submission['id']))

                # Allocate counts to PO lines
                # Note: We do NOT cap at ordered quantity - actual production may exceed the PO
                line = po_lines[0]

                # Apply all counts to the first line
                conn.execute('''
                    UPDATE po_lines
                    SET good_count = good_count + ?, damaged_count = damaged_count + ?
                    WHERE id = ?
                ''', (good_tablets, line_damaged_delta, line['id']))

                updated_pos.add(line['po_id'])

                matched_count += 1

            # Update PO header totals for all affected POs
            for po_id in updated_pos:
                totals_row = conn.execute('''
                    SELECT
                        COALESCE(SUM(quantity_ordered), 0) as total_ordered,
                        COALESCE(SUM(good_count), 0) as total_good,
                        COALESCE(SUM(damaged_count), 0) as total_damaged
                    FROM po_lines
                    WHERE po_id = ?
                ''', (po_id,)).fetchone()

                # Convert to dict
                totals = dict(totals_row)
                remaining = totals.get('total_ordered', 0) - totals.get('total_good', 0) - totals.get('total_damaged', 0)

                conn.execute('''
                    UPDATE purchase_orders
                    SET ordered_quantity = ?, current_good_count = ?,
                        current_damaged_count = ?, remaining_quantity = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (totals.get('total_ordered', 0), totals.get('total_good', 0),
                      totals.get('total_damaged', 0), remaining, po_id))

            return jsonify({
                'success': True,
                'message': f'Successfully matched {matched_count} of {len(unassigned)} unassigned submissions to POs',
                'matched': matched_count,
                'total_unassigned': len(unassigned)
            })
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        current_app.logger.error(f"RESYNC ERROR: {str(e)}")
        current_app.logger.error(error_trace)
        return jsonify({'error': str(e), 'trace': error_trace}), 500



@bp.route('/api/po/<int:po_id>/submissions', methods=['GET'])
@role_required('submissions')
def get_po_submissions(po_id):
    """Get all submissions assigned to a specific PO"""
    try:
        with db_read_only() as conn:
            # Get PO details including machine counts
            po_row = conn.execute('''
                SELECT po_number, tablet_type, ordered_quantity,
                       current_good_count, current_damaged_count, remaining_quantity,
                       machine_good_count, machine_damaged_count,
                       parent_po_number
                FROM purchase_orders
                WHERE id = ?
            ''', (po_id,)).fetchone()

            if not po_row:
                return jsonify({'error': 'PO not found'}), 404

            po = dict(po_row)

            # Check if submission_date and submission_type columns exist
            has_submission_date = False
            has_submission_type = False
            try:
                conn.execute('SELECT submission_date FROM warehouse_submissions LIMIT 1')
                has_submission_date = True
            except sqlite3.Error:
                has_submission_date = False
            try:
                conn.execute('SELECT submission_type FROM warehouse_submissions LIMIT 1')
                has_submission_type = True
            except sqlite3.Error:
                has_submission_type = False

            # For PO-specific views, show ALL submissions for auditing purposes

            # Determine which PO IDs to query:
            # 1. If this is a parent PO, also include submissions from related OVERS POs
            # 2. If this is an OVERS PO, also include submissions from the parent PO
            po_ids_to_query = [po_id]
            po_number = po.get('po_number')

            # Check if this is a parent PO - find related OVERS POs
            overs_pos = conn.execute('''
                SELECT id FROM purchase_orders
                WHERE parent_po_number = ?
            ''', (po_number,)).fetchall()
            for overs_po_row in overs_pos:
                overs_po = dict(overs_po_row)
                po_ids_to_query.append(overs_po.get('id'))

            # Check if this is an OVERS PO - find parent PO
            if po.get('parent_po_number'):
                parent_po_row = conn.execute('''
                    SELECT id FROM purchase_orders
                    WHERE po_number = ?
                ''', (po.get('parent_po_number'),)).fetchone()
                if parent_po_row:
                    parent_po = dict(parent_po_row)
                    parent_po_id = parent_po.get('id')
                    if parent_po_id and parent_po_id not in po_ids_to_query:
                        po_ids_to_query.append(parent_po_id)

            # Build WHERE clause for multiple PO IDs
            po_ids_placeholders = ','.join(['?'] * len(po_ids_to_query))

            # Get all submissions for this PO (and related OVERS/parent POs) with product details
            # Include inventory_item_id for matching with PO line items
            # PO is source of truth - only include submissions where assigned_po_id matches
            submission_type_select = ', ws.submission_type' if has_submission_type else ", 'packaged' as submission_type"
            po_verified_select = ', COALESCE(ws.po_assignment_verified, 0) as po_verified' if has_submission_type else ", 0 as po_verified"
            if has_submission_date:
                submissions_query = f'''
                    SELECT DISTINCT
                        ws.id,
                        ws.product_name,
                        ws.employee_name,
                        ws.displays_made,
                        ws.packs_remaining,
                        ws.loose_tablets,
                        ws.cards_reopened,
                        ws.tablets_pressed_into_cards,
                        ws.created_at,
                        ws.submission_date,
                        ws.box_number,
                        ws.bag_number,
                        ws.bag_id,
                        COALESCE(b.bag_label_count, ws.bag_label_count, 0) as bag_label_count,
                        ws.admin_notes,
                        pd.packages_per_display,
                        COALESCE(pd.tablets_per_package, (
                               SELECT pd2.tablets_per_package
                               FROM product_details pd2
                               JOIN tablet_types tt2 ON pd2.tablet_type_id = tt2.id
                               WHERE tt2.inventory_item_id = ws.inventory_item_id
                               LIMIT 1
                           )) as tablets_per_package,
                        tt.inventory_item_id,
                        ws.assigned_po_id,
                        po.po_number,
                        po.closed as po_closed,
                        ws.machine_id,
                        m.machine_name,
                        COALESCE(m.machine_role, 'sealing') AS machine_role
                        {submission_type_select}
                        {po_verified_select}
                    FROM warehouse_submissions ws
                    LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                    LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id                    LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
                    LEFT JOIN bags b ON ws.bag_id = b.id
                    LEFT JOIN machines m ON ws.machine_id = m.id
                    WHERE ws.assigned_po_id IN ({po_ids_placeholders})
                    ORDER BY ws.created_at ASC
                '''
            else:
                submissions_query = f'''
                    SELECT DISTINCT
                        ws.id,
                        ws.product_name,
                        ws.employee_name,
                        ws.displays_made,
                        ws.packs_remaining,
                        ws.loose_tablets,
                        ws.cards_reopened,
                        ws.tablets_pressed_into_cards,
                        ws.created_at,
                        ws.created_at as submission_date,
                        ws.box_number,
                        ws.bag_number,
                        ws.bag_id,
                        COALESCE(b.bag_label_count, ws.bag_label_count, 0) as bag_label_count,
                        ws.admin_notes,
                        pd.packages_per_display,
                        COALESCE(pd.tablets_per_package, (
                               SELECT pd2.tablets_per_package
                               FROM product_details pd2
                               JOIN tablet_types tt2 ON pd2.tablet_type_id = tt2.id
                               WHERE tt2.inventory_item_id = ws.inventory_item_id
                               LIMIT 1
                           )) as tablets_per_package,
                        tt.inventory_item_id,
                        ws.assigned_po_id,
                        po.po_number,
                        po.closed as po_closed,
                        ws.machine_id,
                        m.machine_name,
                        COALESCE(m.machine_role, 'sealing') AS machine_role
                        {submission_type_select}
                        {po_verified_select}
                    FROM warehouse_submissions ws
                    LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                    LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id                    LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
                    LEFT JOIN bags b ON ws.bag_id = b.id
                    LEFT JOIN machines m ON ws.machine_id = m.id
                    WHERE ws.assigned_po_id IN ({po_ids_placeholders})
                    ORDER BY ws.created_at ASC
                '''

            # Execute query with PO IDs
            submissions_raw = conn.execute(submissions_query, tuple(po_ids_to_query)).fetchall()
            current_app.logger.debug(f"🔍 get_po_submissions: Found {len(submissions_raw)} submissions for PO {po_id} ({po_number}) including related POs: {po_ids_to_query}")

            # Total tablets and cumulative packaged total per bag key (for check vs label)
            # Also track separate totals for machine vs packaged+bag counts
            bag_cumulative_packaged = {}
            submissions = []
            machine_total = 0
            packaged_total = 0
            bag_total = 0
            repack_total = 0

            for sub in submissions_raw:
                sub_dict = dict(sub)
                submission_type = sub_dict.get('submission_type', 'packaged')

                # Calculate total tablets for this submission
                if submission_type == 'machine':
                    role = (sub_dict.get('machine_role') or 'sealing').strip().lower()
                    if role == 'blister':
                        cuts = sub_dict.get('displays_made', 0) or 0
                        sub_dict['blisters_made'] = cuts * BLISTER_BLISTERS_PER_CUT
                        sub_dict['blisters_per_cut'] = BLISTER_BLISTERS_PER_CUT
                        tpp = int(sub_dict.get('tablets_per_package') or 0)
                        computed = sub_dict['blisters_made'] * tpp if tpp else 0
                        total_tablets = computed or (
                            sub_dict.get('tablets_pressed_into_cards')
                            or sub_dict.get('loose_tablets')
                            or 0
                        )
                    else:
                        # Sealing: tablets_pressed_into_cards (fallback packs × tablets_per_package)
                        total_tablets = (sub_dict.get('tablets_pressed_into_cards') or
                                       sub_dict.get('loose_tablets') or
                                       ((sub_dict.get('packs_remaining', 0) or 0) * (sub_dict.get('tablets_per_package', 0) or 0)) or
                                       0)
                elif submission_type == 'repack':
                    total_tablets = calculate_repack_output_good(
                        sub_dict,
                        sub_dict.get('packages_per_display'),
                        sub_dict.get('tablets_per_package'),
                    )
                else:
                    # Packaged: tablets from displays, packs, loose only (cards re-opened excluded)
                    displays_tablets = (sub_dict.get('displays_made', 0) or 0) * (sub_dict.get('packages_per_display', 0) or 0) * (sub_dict.get('tablets_per_package', 0) or 0)
                    package_tablets = (sub_dict.get('packs_remaining', 0) or 0) * (sub_dict.get('tablets_per_package', 0) or 0)
                    loose_tablets = sub_dict.get('loose_tablets', 0) or 0
                    total_tablets = displays_tablets + package_tablets + loose_tablets

                sub_dict['total_tablets'] = total_tablets

                # Track totals separately by submission type
                if submission_type == 'machine':
                    machine_total += total_tablets
                elif submission_type == 'packaged':
                    packaged_total += total_tablets
                elif submission_type == 'bag':
                    bag_total += total_tablets
                elif submission_type == 'repack':
                    repack_total += total_tablets
                # Bag counts are separate from packaged counts - they're just inventory counts, not production

                # Cumulative packaged tablets by bag key PER PO (packaged only; not bag inv. or repack for this bar)
                if submission_type == 'packaged':
                    bag_identifier = f"{sub_dict.get('box_number', '')}/{sub_dict.get('bag_number', '')}"
                    bag_key = (po_id, sub_dict.get('product_name', ''), bag_identifier)
                    if bag_key not in bag_cumulative_packaged:
                        bag_cumulative_packaged[bag_key] = 0
                    bag_cumulative_packaged[bag_key] += total_tablets
                    sub_dict['cumulative_bag_tablets'] = bag_cumulative_packaged[bag_key]

                    if not sub_dict.get('bag_id'):
                        sub_dict['count_status'] = 'no_bag'
                    else:
                        bag_count = sub_dict.get('bag_label_count', 0) or 0
                        if abs(bag_cumulative_packaged[bag_key] - bag_count) <= 5:
                            sub_dict['count_status'] = 'match'
                        elif bag_cumulative_packaged[bag_key] < bag_count:
                            sub_dict['count_status'] = 'under'
                        else:
                            sub_dict['count_status'] = 'over'
                elif submission_type == 'bag':
                    sub_dict['cumulative_bag_tablets'] = total_tablets
                    sub_dict['count_status'] = None
                elif submission_type == 'repack':
                    sub_dict['cumulative_bag_tablets'] = total_tablets
                    sub_dict['count_status'] = 'repack_po'
                else:
                    sub_dict['cumulative_bag_tablets'] = total_tablets
                    sub_dict['count_status'] = None

                submissions.append(sub_dict)

            # Reverse to show newest first in modal
            submissions.reverse()

            return jsonify({
                'success': True,
                'po': dict(po),
                'submissions': submissions,
                'count': len(submissions),
                'totals': {
                    'machine': machine_total,
                    'packaged': packaged_total,
                    'bag': bag_total,
                    'repack': repack_total,
                    'total': machine_total + packaged_total + bag_total + repack_total
                }
            })
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        current_app.logger.error(f"Error fetching PO submissions: {str(e)}")
        current_app.logger.error(error_trace)
        return jsonify({'error': str(e)}), 500

@bp.route('/api/submission/<int:submission_id>', methods=['DELETE'])
@role_required('dashboard')
def delete_submission_alt(submission_id):
    """Delete a submission (for removing duplicates) - DELETE method"""
    try:
        with db_transaction() as conn:
            # Check if submission exists
            submission = conn.execute('''
                SELECT id FROM warehouse_submissions WHERE id = ?
            ''', (submission_id,)).fetchone()

            if not submission:
                return jsonify({'success': False, 'error': 'Submission not found'}), 404

            # Delete the submission
            conn.execute('DELETE FROM warehouse_submissions WHERE id = ?', (submission_id,))

            return jsonify({
                'success': True,
                'message': 'Submission deleted successfully'
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

