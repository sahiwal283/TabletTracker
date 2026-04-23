"""Bag-level running totals and timing for verification UI (matches get_submission_details semantics)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.submission_details_service import BLISTER_BLISTERS_PER_CUT


def _bag_match_params(conn, bag_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        '''
        SELECT b.id, b.bag_label_count, b.pill_count, tt.inventory_item_id, sb.box_number, r.po_id, b.bag_number
        FROM bags b
        JOIN small_boxes sb ON b.small_box_id = sb.id
        JOIN receiving r ON sb.receiving_id = r.id
        JOIN tablet_types tt ON b.tablet_type_id = tt.id
        WHERE b.id = ?
        ''',
        (bag_id,),
    ).fetchone()
    return dict(row) if row else None


def compute_bag_check_running_totals(conn, bag_id: int) -> Dict[str, Any]:
    """
    Chronological running totals for all warehouse_submissions tied to this bag
    (same WHERE shape as get_bag_submissions_payload), aligned with
    app.blueprints.api.get_submission_details bag-keyed accumulation.
    """
    bag = _bag_match_params(conn, bag_id)
    if not bag:
        return {}

    bag_params = (
        bag_id,
        bag['inventory_item_id'],
        bag['bag_number'],
        bag['po_id'],
        bag['box_number'],
    )
    rows = conn.execute(
        '''
        SELECT ws.*, pd.packages_per_display, pd.tablets_per_package,
               COALESCE(pd.tablets_per_package, (
                   SELECT pd2.tablets_per_package
                   FROM product_details pd2
                   JOIN tablet_types tt2 ON pd2.tablet_type_id = tt2.id
                   WHERE tt2.inventory_item_id = ws.inventory_item_id
                   LIMIT 1
               )) AS tablets_per_package_final,
               COALESCE(m.machine_role, 'sealing') AS machine_role
        FROM warehouse_submissions ws
        LEFT JOIN product_details pd ON ws.product_name = pd.product_name
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
            OR (
                COALESCE(ws.submission_type, 'packaged') = 'packaged'
                AND ws.receipt_number IN (
                    SELECT DISTINCT ws2.receipt_number
                    FROM warehouse_submissions ws2
                    WHERE TRIM(COALESCE(ws2.receipt_number, '')) != ''
                    AND (
                        ws2.bag_id = ?
                        OR (
                            ws2.bag_id IS NULL
                            AND ws2.inventory_item_id = ?
                            AND ws2.bag_number = ?
                            AND ws2.assigned_po_id = ?
                            AND (ws2.box_number = ? OR ws2.box_number IS NULL)
                        )
                    )
                )
            )
        )
        ORDER BY ws.created_at ASC, ws.id ASC
        ''',
        bag_params + bag_params,
    ).fetchall()

    bag_running_total = 0
    machine_blister_running_total = 0
    machine_sealing_running_total = 0
    packaged_running_total = 0

    first_bag_start: Optional[str] = None
    last_bag_end: Optional[str] = None

    for bag_sub in rows:
        bag_sub_dict = dict(bag_sub)
        bs = bag_sub_dict.get('bag_start_time')
        be = bag_sub_dict.get('bag_end_time')
        if bs and str(bs).strip():
            if first_bag_start is None:
                first_bag_start = str(bs).strip()
        if be and str(be).strip():
            last_bag_end = str(be).strip()

        bag_sub_type = bag_sub_dict.get('submission_type') or 'packaged'
        if bag_sub_type == 'machine':
            bag_tablets_per_package = (
                bag_sub_dict.get('tablets_per_package_final')
                or bag_sub_dict.get('tablets_per_package')
                or 0
            )
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
                machine_blister_running_total += individual_total
            else:
                packs_remaining = bag_sub_dict.get('packs_remaining', 0) or 0
                stored_tablets = bag_sub_dict.get('tablets_pressed_into_cards') or 0
                tablets_from_cards = (packs_remaining * bag_tablets_per_package) or 0
                loose_tablets = bag_sub_dict.get('loose_tablets') or 0
                individual_total = max(stored_tablets, tablets_from_cards, loose_tablets, 0)
                machine_sealing_running_total += individual_total
        elif bag_sub_type == 'bag':
            individual_total = bag_sub_dict.get('loose_tablets', 0) or 0
            bag_running_total += individual_total
        elif bag_sub_type == 'repack':
            pass
        else:
            packages_per_display = bag_sub_dict.get('packages_per_display', 0) or 0
            tablets_per_package = bag_sub_dict.get('tablets_per_package', 0) or 0
            displays_made = bag_sub_dict.get('displays_made', 0) or 0
            packs_remaining = bag_sub_dict.get('packs_remaining', 0) or 0
            loose_tablets = bag_sub_dict.get('loose_tablets', 0) or 0
            individual_total = (
                (displays_made * packages_per_display * tablets_per_package)
                + (packs_remaining * tablets_per_package)
                + loose_tablets
            )
            packaged_running_total += individual_total

    bag_label_count = bag.get('bag_label_count', 0) or 0
    if not bag_label_count:
        bag_label_count = bag.get('pill_count', 0) or 0

    if abs(packaged_running_total - bag_label_count) <= 5:
        count_status = 'match'
        tablet_difference = abs(packaged_running_total - bag_label_count)
    elif packaged_running_total < bag_label_count:
        count_status = 'under'
        tablet_difference = bag_label_count - packaged_running_total
    else:
        count_status = 'over'
        tablet_difference = packaged_running_total - bag_label_count

    return {
        'bag_running_total': bag_running_total,
        'machine_blister_running_total': machine_blister_running_total,
        'machine_sealing_running_total': machine_sealing_running_total,
        'packaged_running_total': packaged_running_total,
        'running_total': packaged_running_total,
        'count_status': count_status,
        'tablet_difference': tablet_difference,
        'aggregated_bag_start_time': first_bag_start,
        'aggregated_bag_end_time': last_bag_end,
    }
