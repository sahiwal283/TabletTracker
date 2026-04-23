"""Receiving and Shipping API routes (subsection)."""

import json
import traceback
from datetime import datetime

from flask import current_app, jsonify, request, session

from app.services.chart_service import generate_bag_chart_image
from app.services.purchase_order_service import create_or_update_overs_po_for_push
from app.services.receiving_service import (
    build_zoho_receive_notes,
    extract_shipment_number,
    get_bag_with_packaged_count,
)
from app.services.zoho_service import zoho_api
from app.utils.auth_utils import role_required
from app.utils.db_utils import db_read_only, db_transaction

from . import bp
from .helpers import (
    _extract_zoho_receive_id_from_result,
    _resolve_zoho_line_item_id_for_po_item,
    _update_bag_zoho_push,
    get_zoho_po_line_receive_stats,
)


@bp.route('/api/bag/<int:bag_id>/reserve-bottles', methods=['POST'])
@role_required('dashboard')
def reserve_bag_for_bottles(bag_id):
    """Toggle bag reservation for bottle production (variety packs)

    Reserved bags are set aside for variety pack or bottle production.
    A bag can be reserved even after machine/packaged submissions -
    only the remaining tablets (original - packaged) are available.
    """
    try:
        user_role = session.get('employee_role')
        is_admin = session.get('admin_authenticated')
        if user_role not in ['manager', 'admin'] and not is_admin:
            return jsonify({'success': False, 'error': 'Only managers and admins can reserve bags'}), 403

        with db_transaction() as conn:
            # Get bag with details and calculate remaining tablets
            bag_row = conn.execute('''
                SELECT b.id, b.bag_number, b.bag_label_count, b.pill_count,
                       COALESCE(b.reserved_for_bottles, 0) as reserved_for_bottles,
                       COALESCE(b.status, 'Available') as status,
                       sb.box_number, tt.tablet_type_name, tt.id as tablet_type_id,
                       r.po_id
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN receiving r ON sb.receiving_id = r.id
                LEFT JOIN tablet_types tt ON b.tablet_type_id = tt.id
                WHERE b.id = ?
            ''', (bag_id,)).fetchone()

            if not bag_row:
                return jsonify({'success': False, 'error': 'Bag not found'}), 404

            bag = dict(bag_row)

            # Check if bag is closed
            if bag.get('status') == 'Closed':
                return jsonify({'success': False, 'error': 'Cannot reserve a closed bag'}), 400

            # Calculate remaining tablets (original - packaged - bottle)
            # Machine count is intermediary, packaged and bottle are what's actually consumed
            original_count = bag.get('bag_label_count') or bag.get('pill_count') or 0

            # Packaged submissions (card products)
            packaged_total = conn.execute('''
                SELECT COALESCE(SUM(sub.tablet_count), 0) as total
                FROM (
                    SELECT
                        ws.id,
                        (COALESCE(ws.displays_made, 0) * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0)) +
                        (COALESCE(ws.packs_remaining, 0) * COALESCE(pd.tablets_per_package, 0)) as tablet_count
                    FROM warehouse_submissions ws
                    LEFT JOIN tablet_types tt ON ws.inventory_item_id = tt.inventory_item_id
                    LEFT JOIN product_details pd ON tt.id = pd.tablet_type_id
                    WHERE ws.bag_id = ? AND ws.submission_type = 'packaged'
                    GROUP BY ws.id
                ) sub
            ''', (bag_id,)).fetchone()

            # Bottle submissions (bottle-only products with bag_id)
            bottle_direct = conn.execute('''
                SELECT COALESCE(SUM(sub.tablet_count), 0) as total
                FROM (
                    SELECT
                        ws.id,
                        COALESCE(ws.bottles_made, 0) * COALESCE(pd.tablets_per_bottle, 0) as tablet_count
                    FROM warehouse_submissions ws
                    LEFT JOIN tablet_types tt ON ws.inventory_item_id = tt.inventory_item_id
                    LEFT JOIN product_details pd ON tt.id = pd.tablet_type_id
                    WHERE ws.submission_type = 'bottle' AND ws.bag_id = ?
                    GROUP BY ws.id
                ) sub
            ''', (bag_id,)).fetchone()

            # Variety pack deductions via junction table
            bottle_junction = conn.execute('''
                SELECT COALESCE(SUM(sbd.tablets_deducted), 0) as total
                FROM submission_bag_deductions sbd
                WHERE sbd.bag_id = ?
            ''', (bag_id,)).fetchone()

            packaged_count = (packaged_total['total'] if packaged_total else 0) + \
                             (bottle_direct['total'] if bottle_direct else 0) + \
                             (bottle_junction['total'] if bottle_junction else 0)
            remaining_count = max(0, original_count - packaged_count)

            # Toggle reservation
            current_reserved = bag.get('reserved_for_bottles', 0)
            new_reserved = 0 if current_reserved else 1

            conn.execute('''
                UPDATE bags
                SET reserved_for_bottles = ?
                WHERE id = ?
            ''', (new_reserved, bag_id))

            action = 'reserved for bottles' if new_reserved else 'unreserved'
            bag_info = f"{bag.get('tablet_type_name', 'Unknown')} - Box {bag.get('box_number', 'N/A')}, Bag {bag.get('bag_number', 'N/A')}"

            return jsonify({
                'success': True,
                'reserved_for_bottles': bool(new_reserved),
                'remaining_count': remaining_count,
                'original_count': original_count,
                'packaged_count': packaged_count,
                'message': f'Successfully {action}: {bag_info} ({remaining_count} tablets remaining)'
            })
    except Exception as e:
        current_app.logger.error(f"Error reserving bag {bag_id}: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Failed to reserve bag: {str(e)}'}), 500


@bp.route('/api/bags/reserved-for-bottles', methods=['GET'])
@role_required('dashboard')
def get_reserved_bags():
    """Get all bags reserved for bottle production, grouped by tablet type

    Returns bags with remaining tablet counts for bottle submission form.
    """
    try:
        with db_read_only() as conn:
            reserved_bags = conn.execute('''
                SELECT b.id, b.bag_number, b.bag_label_count, b.pill_count,
                       sb.box_number, r.po_id,
                       tt.id as tablet_type_id, tt.tablet_type_name,
                       po.po_number
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN receiving r ON sb.receiving_id = r.id
                LEFT JOIN tablet_types tt ON b.tablet_type_id = tt.id
                LEFT JOIN purchase_orders po ON r.po_id = po.id
                WHERE b.reserved_for_bottles = 1
                AND COALESCE(b.status, 'Available') != 'Closed'
                ORDER BY tt.tablet_type_name, b.bag_number
            ''').fetchall()

            # Group by tablet type and calculate remaining counts
            grouped = {}
            for bag_row in reserved_bags:
                bag = dict(bag_row)
                tt_id = bag['tablet_type_id']

                # Calculate remaining tablets for this bag (including bottle deductions)
                original_count = bag.get('bag_label_count') or bag.get('pill_count') or 0

                # Packaged submissions (card products)
                packaged_total = conn.execute('''
                    SELECT COALESCE(SUM(sub.tablet_count), 0) as total
                    FROM (
                        SELECT
                            ws.id,
                            (COALESCE(ws.displays_made, 0) * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0)) +
                            (COALESCE(ws.packs_remaining, 0) * COALESCE(pd.tablets_per_package, 0)) as tablet_count
                        FROM warehouse_submissions ws
                        LEFT JOIN tablet_types tt ON ws.inventory_item_id = tt.inventory_item_id
                        LEFT JOIN product_details pd ON tt.id = pd.tablet_type_id
                        WHERE ws.bag_id = ? AND ws.submission_type = 'packaged'
                        GROUP BY ws.id
                    ) sub
                ''', (bag['id'],)).fetchone()

                # Bottle submissions (bottle-only products with bag_id)
                bottle_direct = conn.execute('''
                    SELECT COALESCE(SUM(sub.tablet_count), 0) as total
                    FROM (
                        SELECT
                            ws.id,
                            COALESCE(ws.bottles_made, 0) * COALESCE(pd.tablets_per_bottle, 0) as tablet_count
                        FROM warehouse_submissions ws
                        LEFT JOIN tablet_types tt ON ws.inventory_item_id = tt.inventory_item_id
                        LEFT JOIN product_details pd ON tt.id = pd.tablet_type_id
                        WHERE ws.submission_type = 'bottle' AND ws.bag_id = ?
                        GROUP BY ws.id
                    ) sub
                ''', (bag['id'],)).fetchone()

                # Variety pack deductions via junction table
                bottle_junction = conn.execute('''
                    SELECT COALESCE(SUM(sbd.tablets_deducted), 0) as total
                    FROM submission_bag_deductions sbd
                    WHERE sbd.bag_id = ?
                ''', (bag['id'],)).fetchone()

                packaged_count = (packaged_total['total'] if packaged_total else 0) + \
                                 (bottle_direct['total'] if bottle_direct else 0) + \
                                 (bottle_junction['total'] if bottle_junction else 0)
                remaining_count = max(0, original_count - packaged_count)

                bag['original_count'] = original_count
                bag['packaged_count'] = packaged_count
                bag['remaining_count'] = remaining_count

                if tt_id not in grouped:
                    grouped[tt_id] = {
                        'tablet_type_id': tt_id,
                        'tablet_type_name': bag['tablet_type_name'],
                        'bags': [],
                        'total_remaining': 0
                    }

                grouped[tt_id]['bags'].append(bag)
                grouped[tt_id]['total_remaining'] += remaining_count

            return jsonify({
                'success': True,
                'reserved_bags': list(grouped.values())
            })
    except Exception as e:
        current_app.logger.error(f"Error getting reserved bags: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/bag/<int:bag_id>/push_to_zoho', methods=['POST'])
@role_required('dashboard')
def push_bag_to_zoho(bag_id):
    """
    Push a closed bag to Zoho as a purchase receive.

    Creates a purchase receive in Zoho Inventory with:
    - Line item quantity = packaged_count
    - Notes with shipment/box/bag info and counts
    - Chart image attachment showing received vs packaged

    Request JSON (optional):
        custom_notes: Additional notes to append
    """
    try:
        user_role = session.get('employee_role')
        is_admin = session.get('admin_authenticated')
        if user_role not in ['manager', 'admin'] and not is_admin:
            return jsonify({'success': False, 'error': 'Only managers and admins can push to Zoho'}), 403

        # Get optional custom notes from request
        data = request.get_json() or {}
        custom_notes = data.get('custom_notes', '').strip() if data.get('custom_notes') else None

        # Get bag with all required details
        bag = get_bag_with_packaged_count(bag_id)
        if not bag:
            return jsonify({'success': False, 'error': 'Bag not found'}), 404

        # Verify bag is closed
        if bag.get('status') != 'Closed':
            return jsonify({
                'success': False,
                'error': 'Bag must be closed before pushing to Zoho. Please close the bag first.'
            }), 400

        # Check if already pushed
        if bag.get('zoho_receive_pushed'):
            return jsonify({
                'success': False,
                'error': 'This bag has already been pushed to Zoho.',
                'zoho_receive_id': bag.get('zoho_receive_id')
            }), 400

        # Validate required fields
        zoho_po_id = bag.get('zoho_po_id')
        if not zoho_po_id:
            return jsonify({
                'success': False,
                'error': (
                    'Cannot push to Zoho: PO does not have a Zoho PO ID. '
                    'Run Sync Zoho POs once so this receive is linked to Zoho, or assign a synced PO.'
                ),
            }), 400

        # Refresh PO lines from Zoho so local zoho_line_item_id stays current without manual Sync before every push
        try:
            with db_transaction() as conn:
                zoho_api.refresh_tablet_po_lines(conn, bag['po_id'], zoho_po_id)
        except Exception as e:
            current_app.logger.warning(f"refresh_tablet_po_lines (parent PO) skipped: {e}")
        bag = get_bag_with_packaged_count(bag_id)
        if not bag:
            return jsonify({'success': False, 'error': 'Bag not found'}), 404

        zoho_line_item_id = bag.get('zoho_line_item_id')
        if not zoho_line_item_id:
            return jsonify({
                'success': False,
                'error': (
                    'Cannot push to Zoho: no tablet line item for this product on the PO in Zoho '
                    '(or it is not linked in TabletTracker tablet types). '
                    'Check Zoho has a line for this inventory item, then run Sync Zoho POs if needed.'
                ),
            }), 400

        # Get values for notes
        receive_name = bag.get('receive_name', '')
        current_app.logger.info(f"📝 Building notes - receive_name from DB: '{receive_name}'")
        shipment_number = extract_shipment_number(receive_name)
        current_app.logger.info(f"📝 Extracted shipment_number: '{shipment_number}'")
        box_number = bag.get('box_number', 1)
        bag_number = bag.get('bag_number', 1)
        bag_label_count = bag.get('bag_label_count', 0) or 0
        packaged_count = bag.get('packaged_count', 0) or 0

        # Generate chart image with context information (attach to main PO receive when splitting)
        chart_image = generate_bag_chart_image(
            bag_label_count=bag_label_count,
            packaged_count=packaged_count,
            tablet_type_name=bag.get('tablet_type_name'),
            box_number=bag.get('box_number'),
            bag_number=bag.get('bag_number'),
            receive_name=receive_name
        )
        chart_filename = f"bag_{bag_id}_stats.png" if chart_image else None

        today = datetime.now().strftime('%Y-%m-%d')
        stats = get_zoho_po_line_receive_stats(
            zoho_po_id, zoho_line_item_id, bag.get('inventory_item_id')
        )
        if stats is None:
            return jsonify({
                'success': False,
                'error': (
                    'Could not read this PO line from Zoho (line may have been restructured). '
                    'Try Push again after a moment, or run Sync Zoho POs once if the PO changed in Zoho.'
                ),
            }), 400

        effective_line_id = str(zoho_line_item_id or '').strip()
        mid = (stats.get('matched_line_item_id') or '').strip()
        if mid and mid != effective_line_id:
            current_app.logger.warning(
                f"Bag {bag_id}: Zoho line_item_id from GET ({mid}) differs from DB ({effective_line_id}); "
                'using Zoho value for this receive'
            )
            effective_line_id = mid
            try:
                with db_transaction() as conn:
                    conn.execute(
                        '''
                        UPDATE po_lines SET zoho_line_item_id = ?
                        WHERE po_id = ? AND inventory_item_id = ?
                        ''',
                        (mid, bag['po_id'], bag['inventory_item_id']),
                    )
            except Exception as e:
                current_app.logger.warning(f"Could not persist corrected zoho_line_item_id: {e}")

        # Split push: main PO + overs PO when packaged count exceeds remaining capacity on the main line
        if packaged_count > 0:
            ordered = stats['ordered']
            recv_zoho = stats['received_in_zoho_before_push']
            remaining_zoho = max(0, ordered - recv_zoho)
            if packaged_count > remaining_zoho:
                main_qty = remaining_zoho
                overs_qty = packaged_count - main_qty
                parent_po_number = bag.get('po_number') or ''
                overs_po_number = f"{parent_po_number}-OVERS"
                overs_zoho_po_id = None
                overs_zoho_line_id = None
                overs_local_po_id = None
                with db_read_only() as conn:
                    opro = conn.execute(
                        'SELECT id, zoho_po_id FROM purchase_orders WHERE po_number = ?',
                        (overs_po_number,),
                    ).fetchone()
                    if opro:
                        opro = dict(opro)
                        overs_local_po_id = opro['id']
                        overs_zoho_po_id = opro.get('zoho_po_id')
                        plr = conn.execute(
                            '''
                            SELECT zoho_line_item_id FROM po_lines
                            WHERE po_id = ? AND inventory_item_id = ?
                            ''',
                            (opro['id'], bag.get('inventory_item_id')),
                        ).fetchone()
                        if plr and plr['zoho_line_item_id']:
                            overs_zoho_line_id = plr['zoho_line_item_id']
                if not overs_zoho_po_id:
                    name = stats['line_item_name']
                    ordered = stats['ordered']
                    recv_zoho = stats['received_in_zoho_before_push']
                    error_detail = f'''❌ Zoho Quantity Limit — split required

📦 Product: {name}

📊 This PO line in Zoho (before this push):
  • Ordered: {ordered:,} tablets
  • Already received in Zoho: {recv_zoho:,} tablets
  • Remaining capacity on the main line: {remaining_zoho:,} tablets

This bag’s packaged quantity ({packaged_count:,}) exceeds that remaining capacity. Receiving the full bag requires an overs PO with this tablet line synced in TabletTracker.

Use “Create / add to overs PO” below, then run **Sync Zoho POs** so the overs line gets a Zoho line item ID, then push again.

🎒 Split if pushed: main PO {main_qty:,} tablets + overs PO {overs_qty:,} tablets.'''
                    return jsonify({
                        'success': False,
                        'error': error_detail,
                        'zoho_push_overs': {
                            'parent_po_id': bag['po_id'],
                            'overage_tablets': overs_qty,
                            'inventory_item_id': bag.get('inventory_item_id'),
                            'line_item_name': name,
                        },
                    }), 400

                if overs_local_po_id is not None:
                    try:
                        with db_transaction() as conn:
                            zoho_api.refresh_tablet_po_lines(conn, overs_local_po_id, overs_zoho_po_id)
                    except Exception as e:
                        current_app.logger.warning(f"refresh_tablet_po_lines (overs PO) skipped: {e}")

                # Always resolve overs line from Zoho by item_id — SQLite can point at the wrong flavor line
                # when the overs PO has multiple tablet lines (stale or duplicate zoho_line_item_id).
                resolved_overs_line = _resolve_zoho_line_item_id_for_po_item(
                    overs_zoho_po_id, bag.get('inventory_item_id')
                )
                if not resolved_overs_line:
                    name = stats.get('line_item_name') or bag.get('tablet_type_name') or 'Line item'
                    err_detail = (
                        '❌ Overs PO is missing this product line in Zoho.\n\n'
                        f'📦 Product: {name}\n\n'
                        'TabletTracker found the overs PO, but Zoho has no line whose inventory item '
                        'matches this bag’s tablet type. Add the line with **Create / add to overs PO** '
                        'below, then push again (Sync is optional; push refreshes lines).\n\n'
                        f'🎒 Overage for overs PO: {overs_qty:,} tablets.'
                    )
                    return jsonify({
                        'success': False,
                        'error': err_detail,
                        'zoho_push_overs': {
                            'parent_po_id': bag['po_id'],
                            'overage_tablets': overs_qty,
                            'inventory_item_id': bag.get('inventory_item_id'),
                            'line_item_name': name,
                        },
                    }), 400
                if overs_zoho_line_id and str(overs_zoho_line_id) != str(resolved_overs_line):
                    current_app.logger.warning(
                        f"Bag {bag_id}: overs PO line_item_id from SQLite ({overs_zoho_line_id}) "
                        f"differs from Zoho GET ({resolved_overs_line}); using Zoho value for receive"
                    )
                overs_zoho_line_id = resolved_overs_line
                if overs_local_po_id is not None:
                    try:
                        with db_transaction() as conn:
                            conn.execute(
                                '''
                                UPDATE po_lines SET zoho_line_item_id = ?
                                WHERE po_id = ? AND inventory_item_id = ?
                                ''',
                                (resolved_overs_line, overs_local_po_id, bag['inventory_item_id']),
                            )
                    except Exception as e:
                        current_app.logger.warning(f"Could not persist overs po_lines zoho_line_item_id: {e}")

                current_app.logger.info(
                    f"Split Zoho push bag {bag_id}: main_qty={main_qty} overs_qty={overs_qty}"
                )
                # Overs PO is still a normal PO line in Zoho: ordered − already_received must cover overs_qty.
                # Without this check, Zoho returns "Quantity recorded cannot be more than quantity ordered".
                overs_stats = get_zoho_po_line_receive_stats(
                    overs_zoho_po_id, overs_zoho_line_id, bag.get('inventory_item_id')
                )
                if not overs_stats:
                    return jsonify({
                        'success': False,
                        'error': (
                            'Could not read the overs PO line from Zoho before push. '
                            'Try **Sync Zoho POs** once, or confirm the overs PO has a line for this product.'
                        ),
                    }), 400
                ov_ordered = overs_stats['ordered']
                ov_recv = overs_stats['received_in_zoho_before_push']
                ov_remaining = max(0, ov_ordered - ov_recv)
                name_ov = overs_stats.get('line_item_name') or stats.get('line_item_name') or 'Line item'
                if overs_qty > ov_remaining:
                    shortfall = overs_qty - ov_remaining
                    inv_id = bag.get('inventory_item_id')
                    if not inv_id:
                        return jsonify({
                            'success': False,
                            'error': (
                                'Cannot bump overs PO: this bag has no inventory item id. '
                                'Re-save the bag or contact support.'
                            ),
                        }), 400
                    current_app.logger.info(
                        f"Bag {bag_id}: overs PO needs +{shortfall:,} ordered on draft line "
                        f"(have {ov_remaining:,} receive room; need {overs_qty:,}). Bumping via Zoho PUT."
                    )
                    bump = create_or_update_overs_po_for_push(
                        bag['po_id'],
                        shortfall,
                        inv_id,
                        name_ov,
                    )
                    if not bump.get('success'):
                        err_detail = (
                            f'Could not raise the overs PO draft line in Zoho by **{shortfall:,}** tablets.\n\n'
                            f'{bump.get("error") or "Unknown error"}\n\n'
                            f'You can try **Create / add to overs PO** manually, then push again.'
                        )
                        return jsonify({
                            'success': False,
                            'error': err_detail,
                            'zoho_push_overs': {
                                'parent_po_id': bag['po_id'],
                                'overage_tablets': shortfall,
                                'inventory_item_id': bag.get('inventory_item_id'),
                                'line_item_name': name_ov,
                            },
                        }), 400
                    if overs_local_po_id is not None and overs_zoho_po_id:
                        try:
                            with db_transaction() as conn:
                                zoho_api.refresh_tablet_po_lines(conn, overs_local_po_id, overs_zoho_po_id)
                        except Exception as e:
                            current_app.logger.warning(f"refresh_tablet_po_lines after overs bump (bag {bag_id}): {e}")
                    # Re-resolve line id in case Zoho merged lines; re-read capacity
                    resolved_after = _resolve_zoho_line_item_id_for_po_item(
                        overs_zoho_po_id, bag.get('inventory_item_id')
                    )
                    if resolved_after:
                        overs_zoho_line_id = resolved_after
                    overs_stats = get_zoho_po_line_receive_stats(
                        overs_zoho_po_id, overs_zoho_line_id, bag.get('inventory_item_id')
                    )
                    if not overs_stats:
                        return jsonify({
                            'success': False,
                            'error': (
                                'Overs PO was updated in Zoho, but TabletTracker could not re-read the line. '
                                'Try **Sync Zoho POs**, then push again.'
                            ),
                        }), 400
                    ov_ordered = overs_stats['ordered']
                    ov_recv = overs_stats['received_in_zoho_before_push']
                    ov_remaining = max(0, ov_ordered - ov_recv)
                    if overs_qty > ov_remaining:
                        return jsonify({
                            'success': False,
                            'error': (
                                f'After bumping the overs draft line, Zoho still shows only **{ov_remaining:,}** tablets '
                                f'receivable (need **{overs_qty:,}**). Check the overs PO in Zoho for duplicate lines '
                                f'or sync issues, then try again.'
                            ),
                        }), 400

                rid_main = None
                if main_qty > 0:
                    notes_main = build_zoho_receive_notes(
                        shipment_number=shipment_number,
                        box_number=box_number,
                        bag_number=bag_number,
                        bag_label_count=bag_label_count,
                        packaged_count=main_qty,
                        batch_number=bag.get('batch_number'),
                        batch_source=bag.get('batch_source'),
                        custom_notes=custom_notes,
                        split_main_qty=main_qty,
                        split_overs_qty=overs_qty,
                        split_receive_role='main',
                    )
                    result_main = zoho_api.create_purchase_receive(
                        purchaseorder_id=zoho_po_id,
                        line_items=[{'line_item_id': effective_line_id, 'quantity': main_qty}],
                        date=today,
                        notes=notes_main,
                        image_bytes=chart_image if chart_image else None,
                        image_filename=chart_filename
                    )
                    if result_main is None:
                        current_app.logger.error(
                            "Zoho API returned None on split main receive — timeout or network failure"
                        )
                        return jsonify({
                            'success': False,
                            'error': (
                                'Could not reach Zoho or the request timed out on the main PO receive. '
                                'Check your network and Zoho status.'
                            ),
                        }), 500
                    if result_main.get('code') is not None and result_main.get('code') != 0:
                        em = result_main.get('message', 'Unknown Zoho API error')
                        current_app.logger.error(f"Zoho split main receive error: {em}")
                        return jsonify({'success': False, 'error': f'Zoho error (main PO receive): {em}'}), 500
                    rid_main = _extract_zoho_receive_id_from_result(result_main)
                    if not rid_main:
                        current_app.logger.error(
                            f"Zoho main receive returned no receive id (bag {bag_id}): {json.dumps(result_main, default=str)[:2000]}"
                        )
                        return jsonify({
                            'success': False,
                            'error': (
                                'Zoho did not return a purchase receive id for the main PO line. '
                                'Check Zoho for duplicate receives before retrying.'
                            ),
                        }), 500

                notes_ov = build_zoho_receive_notes(
                    shipment_number=shipment_number,
                    box_number=box_number,
                    bag_number=bag_number,
                    bag_label_count=bag_label_count,
                    packaged_count=overs_qty,
                    batch_number=bag.get('batch_number'),
                    batch_source=bag.get('batch_source'),
                    custom_notes=custom_notes,
                    split_main_qty=main_qty,
                    split_overs_qty=overs_qty,
                    split_receive_role='overs',
                )
                result_overs = zoho_api.create_purchase_receive(
                    purchaseorder_id=overs_zoho_po_id,
                    line_items=[{'line_item_id': overs_zoho_line_id, 'quantity': overs_qty}],
                    date=today,
                    notes=notes_ov,
                    image_bytes=None,
                    image_filename=None
                )
                if result_overs is None:
                    current_app.logger.error(
                        "Zoho API returned None on overs PO receive — timeout or network failure"
                    )
                    return jsonify({
                        'success': False,
                        'error': (
                            'Main PO receive may have succeeded but overs PO receive failed or timed out. '
                            'Check Zoho for duplicate receives before retrying.'
                        ),
                    }), 500
                if result_overs.get('code') is not None and result_overs.get('code') != 0:
                    em = result_overs.get('message', 'Unknown Zoho API error')
                    current_app.logger.error(f"Zoho overs receive error: {em}")
                    return jsonify({'success': False, 'error': f'Zoho error (overs PO receive): {em}'}), 500
                rid_overs = _extract_zoho_receive_id_from_result(result_overs)
                if not rid_overs:
                    current_app.logger.error(
                        f"Zoho overs receive returned no receive id (bag {bag_id}): {json.dumps(result_overs, default=str)[:2000]}"
                    )
                    return jsonify({
                        'success': False,
                        'error': (
                            'Zoho did not return a purchase receive id for the overs PO line. '
                            'Check Zoho for duplicate receives before retrying.'
                        ),
                    }), 500

                with db_transaction() as conn:
                    _update_bag_zoho_push(
                        conn,
                        bag_id,
                        str(rid_main) if rid_main else None,
                        str(rid_overs) if rid_overs else None,
                    )

                bag_info = f"{bag.get('tablet_type_name', 'Unknown')} - Box {box_number}, Bag {bag_number}"
                split_msg = f'Successfully pushed {bag_info} to Zoho (split: main + overs PO)'
                if main_qty <= 0:
                    split_msg = (
                        f'Successfully pushed {bag_info} to Zoho on the overs PO only. '
                        f'Zoho shows the main line as full (ordered {ordered:,}, already received {recv_zoho:,}). '
                        f'Overs receive: {overs_qty:,} tablets.'
                    )
                return jsonify({
                    'success': True,
                    'zoho_receive_pushed': True,
                    'message': split_msg,
                    'zoho_receive_id': str(rid_main) if rid_main else None,
                    'zoho_receive_overs_id': str(rid_overs) if rid_overs else None,
                    'split_main_qty': main_qty,
                    'split_overs_qty': overs_qty,
                })

        # Single receive path
        notes = build_zoho_receive_notes(
            shipment_number=shipment_number,
            box_number=box_number,
            bag_number=bag_number,
            bag_label_count=bag_label_count,
            packaged_count=packaged_count,
            batch_number=bag.get('batch_number'),
            batch_source=bag.get('batch_source'),
            custom_notes=custom_notes
        )

        line_items = [{
            'line_item_id': effective_line_id,
            'quantity': packaged_count
        }]

        current_app.logger.info(f"Pushing bag {bag_id} to Zoho:")
        current_app.logger.info(f"  - Zoho PO ID: {zoho_po_id}")
        current_app.logger.info(f"  - Zoho Line Item ID (effective): {effective_line_id}")
        current_app.logger.info(f"  - Line items: {line_items}")
        current_app.logger.info(f"  - Date: {today}")
        current_app.logger.info(f"  - Has chart image: {bool(chart_image)}")

        result = zoho_api.create_purchase_receive(
            purchaseorder_id=zoho_po_id,
            line_items=line_items,
            date=today,
            notes=notes,
            image_bytes=chart_image if chart_image else None,
            image_filename=chart_filename
        )

        if result is None:
            current_app.logger.error("Zoho API returned None — timeout or network failure (no JSON body)")
            return jsonify({
                'success': False,
                'error': (
                    'Could not reach Zoho or the request timed out. Check your network, Zoho Inventory status, '
                    'and that ZOHO_* credentials in .env are valid. See Flask logs for details.'
                )
            }), 500

        # Check for errors in Zoho response
        if result.get('code') is not None and result.get('code') != 0:
            error_code = result.get('code')
            error_msg = result.get('message', 'Unknown Zoho API error')
            current_app.logger.error(f"Zoho API error (code {error_code}): {error_msg}")

            if error_code == -1:
                return jsonify({
                    'success': False,
                    'error': f'Zoho authentication/configuration error: {error_msg}'
                }), 500

            # Handle specific error codes with helpful messages
            if error_code == 36012:
                # Quantity recorded cannot be more than quantity ordered (Zoho-side rule).
                # Use live Zoho PO line (quantity + quantity_received), not local po_lines.good_count
                # (local counts reflect TabletTracker credits, not Zoho receives).
                stats = get_zoho_po_line_receive_stats(
                    zoho_po_id, effective_line_id, bag.get('inventory_item_id')
                )
                if stats:
                    name = stats['line_item_name']
                    ordered = stats['ordered']
                    recv_zoho = stats['received_in_zoho_before_push']
                    remaining_zoho = max(0, ordered - recv_zoho)
                    total_after_push = recv_zoho + packaged_count
                    overage = max(0, total_after_push - ordered)
                    error_detail = f'''❌ Zoho Quantity Limit Exceeded

📦 Product: {name}

📊 This PO line in Zoho (before this push):
  • Ordered: {ordered:,} tablets
  • Already received in Zoho: {recv_zoho:,} tablets
  • Remaining you can still receive: {remaining_zoho:,} tablets

🎒 This bag (this push):
  • Quantity you are trying to push: {packaged_count:,} tablets

📈 If this push succeeded, Zoho would show:
  • Total received: {recv_zoho:,} + {packaged_count:,} = {total_after_push:,} tablets
  • Overage (amount past the order): {overage:,} tablets

⚠️ Zoho enforces strict limits — you cannot receive more than ordered on the line.

💡 Options:
  1. Reduce this bag’s packaged quantity (e.g. adjust submissions) so the push stays within remaining capacity.
  2. Increase the ordered quantity on this line in Zoho (then sync POs here).
  3. Receive the excess on another PO / overs order in Zoho.

Zoho API: {error_msg}'''
                    payload = {
                        'success': False,
                        'error': error_detail,
                    }
                    if overage > 0:
                        payload['zoho_push_overs'] = {
                            'parent_po_id': bag['po_id'],
                            'overage_tablets': overage,
                            'inventory_item_id': bag.get('inventory_item_id'),
                            'line_item_name': name,
                        }
                    return jsonify(payload), 400

                # Fallback: could not read PO from Zoho — keep local context only for product name / ordered
                try:
                    with db_read_only() as conn:
                        po_line_info = conn.execute('''
                        SELECT pl.line_item_name, pl.quantity_ordered
                        FROM po_lines pl
                        WHERE pl.po_id = (SELECT po_id FROM receiving WHERE id = (
                            SELECT receiving_id FROM small_boxes WHERE id = (
                                SELECT small_box_id FROM bags WHERE id = ?
                            )
                        ))
                        AND pl.inventory_item_id = ?
                        LIMIT 1
                    ''', (bag_id, bag.get('inventory_item_id'))).fetchone()
                    line_hint = ''
                    if po_line_info:
                        pl = dict(po_line_info)
                        line_hint = (
                            f"\n\n📦 (from TabletTracker DB) Product: {pl.get('line_item_name', 'Unknown')}\n"
                            f"   Ordered on file: {pl.get('quantity_ordered', 0):,} tablets — "
                            "verify in Zoho; local DB may not match Zoho received totals."
                        )
                except Exception as e:
                    current_app.logger.error(f"Error getting PO line fallback details: {e}")
                    line_hint = ''

                error_detail = f'''❌ Zoho Quantity Limit Exceeded

Could not load this PO line from Zoho to show “already received” exactly as Zoho sees it (required for a precise breakdown). Open Zoho Inventory, Purchase Orders, this PO, and compare Ordered vs Received on the line; Zoho rejects when (received + this push) is greater than ordered.

🎒 This push quantity: {packaged_count:,} tablets

Zoho’s rule: total received after this push would exceed the ordered quantity on the line.{line_hint}

💡 Options:
  1. Reduce packaged quantity for this bag, or split receiving in Zoho.
  2. Increase ordered quantity on the PO line in Zoho, then sync POs here.
  3. Use another PO for excess quantity.

Zoho API: {error_msg}'''
                return jsonify({
                    'success': False,
                    'error': error_detail
                }), 400
            else:
                return jsonify({
                    'success': False,
                    'error': f'Zoho API error (code {error_code}): {error_msg}'
                }), 500

        # Get the created receive ID - try multiple possible field names
        zoho_receive_id = None
        if result.get('purchasereceive'):
            zoho_receive_id = (
                result['purchasereceive'].get('purchasereceive_id') or
                result['purchasereceive'].get('purchase_receive_id') or
                result['purchasereceive'].get('id') or
                result['purchasereceive'].get('receive_id')
            )
            current_app.logger.info(f"Extracted zoho_receive_id from purchasereceive: {zoho_receive_id}")
        else:
            # Try direct fields in case response structure is different
            zoho_receive_id = (
                result.get('purchasereceive_id') or
                result.get('purchase_receive_id') or
                result.get('id') or
                result.get('receive_id')
            )
            current_app.logger.info(f"Extracted zoho_receive_id from root: {zoho_receive_id}")

        # Log the full response if receive ID is still None (for debugging)
        if not zoho_receive_id:
            current_app.logger.warning(f"⚠️ Could not extract zoho_receive_id. Full response: {json.dumps(result, indent=2, default=str)[:1000]}")

        # Update bag to mark as pushed
        with db_transaction() as conn:
            _update_bag_zoho_push(conn, bag_id, zoho_receive_id, None)

        bag_info = f"{bag.get('tablet_type_name', 'Unknown')} - Box {box_number}, Bag {bag_number}"
        current_app.logger.info(f"Successfully pushed bag {bag_id} to Zoho receive {zoho_receive_id}")

        return jsonify({
            'success': True,
            'zoho_receive_pushed': True,
            'message': f'Successfully pushed {bag_info} to Zoho',
            'zoho_receive_id': zoho_receive_id
        })

    except Exception as e:
        current_app.logger.error(f"Error pushing bag {bag_id} to Zoho: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Failed to push to Zoho: {str(e)}'}), 500


