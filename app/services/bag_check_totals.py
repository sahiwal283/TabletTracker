"""Bag-level cumulative tablet totals and timing for verification UI (matches get_submission_details)."""

from __future__ import annotations

from typing import Any

from app.services.submission_calculator import calculate_repack_output_good
from app.services.submission_details_service import BLISTER_BLISTERS_PER_CUT


def _bag_match_params(conn, bag_id: int) -> dict[str, Any] | None:
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


def _safe_rate(numer: int, denom: int) -> float | None:
    if denom <= 0 or numer < 0:
        return None
    return round(numer / denom, 6)


def compute_bag_check_totals(conn, bag_id: int) -> dict[str, Any]:
    """
    Cumulative per-stage tablet totals for all warehouse_submissions for this bag
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

    bag_submission_tablets_total = 0
    machine_blister_tablets_total = 0
    machine_sealing_tablets_total = 0
    packaged_tablets_total = 0

    # Physical/counter unit accumulators (card flow: 1 machine blister = 1 sealed card in normal flow)
    blisters_from_blister_counter = 0
    # Sealing: sum packs_remaining on sealing rows (same field the floor uses for cards from presses)
    cards_from_sealing_counter = 0
    # Packaged: full displays + partial packs as cards; repack uses same (no loose in repack "good" cards)
    cards_in_packaged_output = 0
    packaged_loose_tablets = 0

    primary_blister_machine_id: int | None = None
    primary_sealing_machine_id: int | None = None

    first_bag_start: str | None = None
    last_bag_end: str | None = None

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
                bag_sub_dict.get('tablets_per_package_final') or bag_sub_dict.get('tablets_per_package') or 0
            )
            machine_role = (bag_sub_dict.get('machine_role') or 'sealing').strip().lower()
            if machine_role == 'blister':
                if primary_blister_machine_id is None and bag_sub_dict.get('machine_id'):
                    primary_blister_machine_id = int(bag_sub_dict['machine_id'])
                presses = bag_sub_dict.get('displays_made', 0) or 0
                tpp = int(bag_tablets_per_package or 0)
                blisters_made = presses * BLISTER_BLISTERS_PER_CUT
                blisters_from_blister_counter += blisters_made
                individual_total = blisters_made * tpp if tpp else (bag_sub_dict.get('tablets_pressed_into_cards') or 0)
                machine_blister_tablets_total += individual_total
            else:
                if primary_sealing_machine_id is None and bag_sub_dict.get('machine_id'):
                    primary_sealing_machine_id = int(bag_sub_dict['machine_id'])
                packs_remaining = bag_sub_dict.get('packs_remaining', 0) or 0
                cards_from_sealing_counter += int(packs_remaining)
                stored_tablets = bag_sub_dict.get('tablets_pressed_into_cards') or 0
                tablets_from_cards = (packs_remaining * bag_tablets_per_package) or 0
                loose_tablets = bag_sub_dict.get('loose_tablets') or 0
                individual_total = max(stored_tablets, tablets_from_cards, loose_tablets, 0)
                machine_sealing_tablets_total += individual_total
        elif bag_sub_type == 'bag':
            individual_total = bag_sub_dict.get('loose_tablets', 0) or 0
            bag_submission_tablets_total += individual_total
        elif bag_sub_type == 'repack':
            ppd = bag_sub_dict.get('packages_per_display', 0) or 0
            tpp = int(bag_sub_dict.get('tablets_per_package') or bag_sub_dict.get('tablets_per_package_final') or 0)
            r_tablets = calculate_repack_output_good(bag_sub_dict, ppd, tpp)
            packaged_tablets_total += r_tablets
            dm = bag_sub_dict.get('displays_made', 0) or 0
            pr = bag_sub_dict.get('packs_remaining', 0) or 0
            cards_in_packaged_output += int(dm * ppd + pr)
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
            packaged_tablets_total += individual_total
            cards_in_packaged_output += int(displays_made * packages_per_display + packs_remaining)
            packaged_loose_tablets += int(loose_tablets)

    B = machine_blister_tablets_total
    S = machine_sealing_tablets_total
    P = packaged_tablets_total

    # Non-negative delta = "error" between counters / counter vs packed (not always physical loss)
    err_b_s_tablets = max(0, B - S)
    err_s_p_tablets = max(0, S - P)
    err_b_p_tablets = max(0, B - P)

    err_b_s_cards = max(0, blisters_from_blister_counter - cards_from_sealing_counter)
    err_s_p_cards = max(0, cards_from_sealing_counter - cards_in_packaged_output)
    err_b_p_cards = max(0, blisters_from_blister_counter - cards_in_packaged_output)

    neg_b_s = (B > 0 and S > 0 and S > B) or (
        blisters_from_blister_counter > 0
        and cards_from_sealing_counter > 0
        and cards_from_sealing_counter > blisters_from_blister_counter
    )
    neg_s_p = S > 0 and P > 0 and P > S
    neg_b_p = B > 0 and P > 0 and P > B

    pipeline_stages_present = {
        'blisters': B > 0 or blisters_from_blister_counter > 0,
        'sealing': S > 0 or cards_from_sealing_counter > 0,
        'packaged': P > 0,
    }
    incomplete_pipeline = not all(pipeline_stages_present.values())

    stage_transition_errors_tablets = {
        'blister_to_sealing': err_b_s_tablets if (B > 0 and S > 0) else None,
        'sealing_to_packaged': err_s_p_tablets if (S > 0 and P > 0) else None,
        'blister_to_packaged': err_b_p_tablets if (B > 0 and P > 0) else None,
    }
    stage_transition_error_rates: dict[str, float | None] = {
        'blister_to_sealing': _safe_rate(err_b_s_tablets, B) if B > 0 and S > 0 else None,
        'sealing_to_packaged': _safe_rate(err_s_p_tablets, S) if S > 0 and P > 0 else None,
        'blister_to_packaged': _safe_rate(err_b_p_tablets, B) if B > 0 and P > 0 else None,
    }
    stage_transition_errors_cards: dict[str, int | None] = {
        'blister_to_sealing': (
            err_b_s_cards if blisters_from_blister_counter > 0 and cards_from_sealing_counter > 0 else None
        ),
        'sealing_to_packaged': (
            err_s_p_cards
            if S > 0 and P > 0 and (cards_from_sealing_counter > 0 or cards_in_packaged_output > 0)
            else None
        ),
        'blister_to_packaged': (err_b_p_cards if blisters_from_blister_counter > 0 and P > 0 else None),
    }

    stage_transition_error_rates_cards: dict[str, float | None] = {
        'blister_to_sealing': _safe_rate(err_b_s_cards, blisters_from_blister_counter)
        if blisters_from_blister_counter > 0 and cards_from_sealing_counter > 0
        else None,
        'sealing_to_packaged': _safe_rate(err_s_p_cards, cards_from_sealing_counter)
        if S > 0 and P > 0 and cards_from_sealing_counter > 0
        else None,
        'blister_to_packaged': _safe_rate(err_b_p_cards, blisters_from_blister_counter)
        if blisters_from_blister_counter > 0 and P > 0
        else None,
    }

    bag_label_count = bag.get('bag_label_count', 0) or 0
    if not bag_label_count:
        bag_label_count = bag.get('pill_count', 0) or 0

    if abs(packaged_tablets_total - bag_label_count) <= 5:
        count_status = 'match'
        tablet_difference = abs(packaged_tablets_total - bag_label_count)
    elif packaged_tablets_total < bag_label_count:
        count_status = 'under'
        tablet_difference = bag_label_count - packaged_tablets_total
    else:
        count_status = 'over'
        tablet_difference = packaged_tablets_total - bag_label_count

    return {
        'bag_submission_tablets_total': bag_submission_tablets_total,
        'machine_blister_tablets_total': machine_blister_tablets_total,
        'machine_sealing_tablets_total': machine_sealing_tablets_total,
        'packaged_tablets_total': packaged_tablets_total,
        'count_status': count_status,
        'tablet_difference': tablet_difference,
        'aggregated_bag_start_time': first_bag_start,
        'aggregated_bag_end_time': last_bag_end,
        # Counter / machine error vs next step or vs packed output
        'blisters_from_blister_counter': blisters_from_blister_counter,
        'cards_from_sealing_counter': cards_from_sealing_counter,
        'cards_in_packaged_output': cards_in_packaged_output,
        'packaged_loose_tablets': packaged_loose_tablets,
        'primary_blister_machine_id': primary_blister_machine_id,
        'primary_sealing_machine_id': primary_sealing_machine_id,
        'pipeline_stages_present': pipeline_stages_present,
        'incomplete_pipeline': incomplete_pipeline,
        'stage_transition_errors_tablets': stage_transition_errors_tablets,
        'stage_transition_error_rates': stage_transition_error_rates,
        'stage_transition_errors_cards': stage_transition_errors_cards,
        'stage_transition_error_rates_cards': stage_transition_error_rates_cards,
        'stage_error_quality': {
            'negative_blister_to_sealing': bool(neg_b_s),
            'negative_sealing_to_packaged': bool(neg_s_p),
            'negative_blister_to_packaged': bool(neg_b_p),
        },
    }
