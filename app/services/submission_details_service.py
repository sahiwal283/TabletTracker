"""Submission detail read workflows used by API routes."""
from typing import Dict, Any, Optional


def _get_submission_config(conn, product_name: Optional[str], inventory_item_id: Optional[str]):
    config = None
    if product_name:
        config = conn.execute(
            '''
            SELECT packages_per_display, tablets_per_package, tablets_per_bottle, bottles_per_display
            FROM product_details
            WHERE product_name = ?
            ''',
            (product_name,),
        ).fetchone()
        if not config:
            config = conn.execute(
                '''
                SELECT packages_per_display, tablets_per_package, tablets_per_bottle, bottles_per_display
                FROM product_details
                WHERE TRIM(LOWER(product_name)) = TRIM(LOWER(?))
                ''',
                (product_name,),
            ).fetchone()

    if not config and inventory_item_id:
        config = conn.execute(
            '''
            SELECT pd.packages_per_display, pd.tablets_per_package, pd.tablets_per_bottle, pd.bottles_per_display
            FROM tablet_types tt
            LEFT JOIN product_details pd ON tt.id = pd.tablet_type_id
            WHERE tt.inventory_item_id = ?
            AND pd.id IS NOT NULL
            ORDER BY
                CASE WHEN pd.is_bottle_product = 1 THEN 1 ELSE 0 END,
                pd.packages_per_display DESC NULLS LAST
            LIMIT 1
            ''',
            (inventory_item_id,),
        ).fetchone()
    return dict(config) if config else None


def get_bag_submissions_payload(conn, bag_id: int) -> Dict[str, Any]:
    bag = conn.execute(
        '''
        SELECT b.*, tt.inventory_item_id, sb.box_number, r.po_id
        FROM bags b
        JOIN small_boxes sb ON b.small_box_id = sb.id
        JOIN receiving r ON sb.receiving_id = r.id
        JOIN tablet_types tt ON b.tablet_type_id = tt.id
        WHERE b.id = ?
        ''',
        (bag_id,),
    ).fetchone()
    if not bag:
        return {'success': False, 'status_code': 404, 'error': 'Bag not found'}

    submissions = conn.execute(
        '''
        SELECT ws.*, m.machine_name AS machine_name
        FROM warehouse_submissions ws
        LEFT JOIN machines m ON ws.machine_id = m.id
        WHERE (
            ws.bag_id = ?
            OR (
                ws.bag_id IS NULL
                AND ws.inventory_item_id = ?
                AND ws.bag_number = ?
                AND ws.assigned_po_id = ?
                AND (ws.box_number = ? OR ws.box_number IS NULL)
            )
        )
        ORDER BY ws.created_at DESC
        ''',
        (bag_id, bag['inventory_item_id'], bag['bag_number'], bag['po_id'], bag['box_number']),
    ).fetchall()

    submissions_with_totals = []
    for row in submissions:
        sub = dict(row)
        submission_type = sub.get('submission_type') or 'packaged'
        config = _get_submission_config(conn, sub.get('product_name'), sub.get('inventory_item_id'))

        ppd = (config or {}).get('packages_per_display') or 0
        tpp = (config or {}).get('tablets_per_package') or 0
        tpb = (config or {}).get('tablets_per_bottle') or 0
        bpd = (config or {}).get('bottles_per_display') or 0

        if submission_type == 'packaged':
            total = ((sub.get('displays_made') or 0) * ppd * tpp) + ((sub.get('packs_remaining') or 0) * tpp)
        elif submission_type == 'bag':
            total = sub.get('loose_tablets') or 0
        elif submission_type == 'machine':
            role = None
            mid = sub.get('machine_id')
            if mid:
                role_row = conn.execute(
                    "SELECT COALESCE(machine_role, 'sealing') AS machine_role FROM machines WHERE id = ?",
                    (mid,),
                ).fetchone()
                if role_row:
                    role = (dict(role_row).get('machine_role') or 'sealing').strip().lower()
            if role == 'blister':
                total = sub.get('displays_made') or 0
            else:
                tablets_pressed = sub.get('tablets_pressed_into_cards') or 0
                total = tablets_pressed or ((sub.get('packs_remaining') or 0) * tpp)
        elif submission_type == 'bottle':
            deductions = conn.execute(
                'SELECT SUM(tablets_deducted) as total FROM submission_bag_deductions WHERE submission_id = ?',
                (sub['id'],),
            ).fetchone()
            if deductions and deductions['total']:
                total = deductions['total']
            else:
                total = (sub.get('bottles_made') or 0) * tpb
            explicit_remaining = sub.get('packs_remaining')
            if explicit_remaining is not None and explicit_remaining >= 0:
                sub['bottles_remaining'] = explicit_remaining
            else:
                sub['bottles_remaining'] = max(
                    0,
                    (sub.get('bottles_made') or 0) - ((sub.get('displays_made') or 0) * bpd),
                )
        else:
            total = 0

        sub['total_tablets'] = total
        submissions_with_totals.append(sub)

    variety_pack_deductions = conn.execute(
        '''
        SELECT sbd.id, sbd.submission_id, sbd.bag_id, sbd.tablets_deducted, sbd.created_at,
               ws.employee_name, ws.product_name, ws.bottles_made, ws.displays_made,
               ws.submission_date, ws.submission_type
        FROM submission_bag_deductions sbd
        JOIN warehouse_submissions ws ON sbd.submission_id = ws.id
        WHERE sbd.bag_id = ?
        ORDER BY sbd.created_at DESC
        ''',
        (bag_id,),
    ).fetchall()

    return {
        'success': True,
        'bag': dict(bag),
        'submissions': submissions_with_totals,
        'variety_pack_deductions': [dict(row) for row in variety_pack_deductions],
    }
