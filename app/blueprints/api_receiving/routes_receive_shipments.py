"""Receiving and Shipping API routes (subsection)."""

import traceback

from flask import current_app, jsonify, render_template, request, session

from app.services.receiving_service import (
    get_receiving_with_details,
)
from app.services.tracking_service import refresh_shipment_row
from app.services.zoho_service import parse_zoho_item_weight_grams, zoho_api
from app.utils.auth_utils import employee_required, role_required
from app.utils.db_utils import db_read_only, db_transaction

from . import bp


@bp.route('/api/tablet-types/<int:tablet_type_id>/zoho-item-weight', methods=['GET'])
@employee_required
def zoho_item_weight_for_tablet_type(tablet_type_id):
    """Return whether Zoho has a unit weight (grams) for this tablet type's inventory item."""
    try:
        with db_read_only() as conn:
            row = conn.execute(
                'SELECT inventory_item_id FROM tablet_types WHERE id = ?',
                (tablet_type_id,),
            ).fetchone()
        if not row or not row['inventory_item_id']:
            return jsonify({'has_weight': False, 'grams_per_tablet': None})
        zoho_item = zoho_api.get_item(row['inventory_item_id'])
        grams = parse_zoho_item_weight_grams(zoho_item)
        ok = grams is not None and grams > 0
        return jsonify({'has_weight': ok, 'grams_per_tablet': grams if ok else None})
    except Exception as e:
        current_app.logger.error(f"zoho_item_weight_for_tablet_type: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/receive/<int:receive_id>/details', methods=['GET'])
@role_required('shipping')
def get_receiving_details(receive_id):
    """Get receiving details with submission counts (similar to PO details modal)"""
    try:
        receiving = get_receiving_with_details(receive_id)
        if not receiving:
            return jsonify({'error': 'Receive not found'}), 404

        with db_read_only() as conn:
            receive_dict = receiving
            bags = receiving.get('bags', [])

            # Group by product -> box -> bag
            products = {}
            for bag in bags:
                inventory_item_id = bag.get('inventory_item_id')
                tablet_type_name = bag.get('tablet_type_name')
                box_number = bag.get('box_number')
                bag_number = bag.get('bag_number')
                bag_label_count = bag.get('bag_label_count', 0) or 0

                if not inventory_item_id:
                    continue

                if inventory_item_id not in products:
                    products[inventory_item_id] = {
                        'tablet_type_name': tablet_type_name,
                        'inventory_item_id': inventory_item_id,
                        'boxes': {}
                    }

                if box_number not in products[inventory_item_id]['boxes']:
                    products[inventory_item_id]['boxes'][box_number] = {}

                # Get submission counts for this specific bag
                bag_id = bag.get('id')
                po_id = receive_dict.get('po_id')

                # Get submissions with product_name to look up correct config per submission
                # Machine submissions
                machine_submissions = conn.execute('''
                    SELECT ws.tablets_pressed_into_cards, ws.packs_remaining, ws.product_name
                    FROM warehouse_submissions ws
                    LEFT JOIN bags b_verify ON ws.bag_id = b_verify.id
                    LEFT JOIN small_boxes sb_verify ON b_verify.small_box_id = sb_verify.id
                    WHERE ws.submission_type = 'machine'
                    AND (
                        (ws.bag_id = ? AND ws.assigned_po_id = ? AND sb_verify.receiving_id = ?)
                        OR (
                            ws.bag_id IS NULL AND ws.inventory_item_id = ? AND ws.bag_number = ?
                            AND ws.assigned_po_id = ? AND ws.box_number = ?
                        )
                    )
                ''', (bag_id, po_id, receive_id, inventory_item_id, bag_number, po_id, box_number)).fetchall()

                machine_total = 0
                for sub in machine_submissions:
                    sub_dict = dict(sub)
                    tablets_pressed = sub_dict.get('tablets_pressed_into_cards') or 0

                    if tablets_pressed:
                        machine_total += tablets_pressed
                    else:
                        # Need config for fallback calculation
                        product_name = sub_dict.get('product_name')
                        if product_name:
                            config = conn.execute('SELECT tablets_per_package FROM product_details WHERE TRIM(LOWER(product_name)) = TRIM(LOWER(?))', (product_name,)).fetchone()
                            if config:
                                tpp = dict(config).get('tablets_per_package') or 0
                                cards = sub_dict.get('packs_remaining') or 0
                                machine_total += (cards * tpp)

                # Packaged submissions - get with product_name
                packaged_submissions = conn.execute('''
                    SELECT ws.displays_made, ws.packs_remaining, ws.product_name
                    FROM warehouse_submissions ws
                    LEFT JOIN bags b_verify ON ws.bag_id = b_verify.id
                    LEFT JOIN small_boxes sb_verify ON b_verify.small_box_id = sb_verify.id
                    WHERE ws.submission_type = 'packaged'
                    AND (
                        (ws.bag_id = ? AND ws.assigned_po_id = ? AND sb_verify.receiving_id = ?)
                        OR (
                            ws.bag_id IS NULL AND ws.inventory_item_id = ? AND ws.bag_number = ?
                            AND ws.assigned_po_id = ? AND ws.box_number = ?
                        )
                    )
                ''', (bag_id, po_id, receive_id, inventory_item_id, bag_number, po_id, box_number)).fetchall()

                total_packaged = 0
                for sub in packaged_submissions:
                    sub_dict = dict(sub)
                    displays = sub_dict.get('displays_made') or 0
                    cards = sub_dict.get('packs_remaining') or 0
                    product_name = sub_dict.get('product_name')

                    config = None
                    if product_name:
                        # Get config for THIS submission's product (case-insensitive match)
                        config = conn.execute('''
                            SELECT packages_per_display, tablets_per_package
                            FROM product_details
                            WHERE TRIM(LOWER(product_name)) = TRIM(LOWER(?))
                        ''', (product_name,)).fetchone()

                    # Fallback to inventory_item_id if product_name lookup failed
                    if not config:
                        config = conn.execute('''
                            SELECT pd.packages_per_display, pd.tablets_per_package
                            FROM tablet_types tt
                            LEFT JOIN product_details pd ON tt.id = pd.tablet_type_id
                            WHERE tt.inventory_item_id = ?
                            AND pd.id IS NOT NULL
                            AND pd.packages_per_display IS NOT NULL
                            ORDER BY pd.packages_per_display DESC
                            LIMIT 1
                        ''', (inventory_item_id,)).fetchone()

                    if config:
                        config = dict(config)
                        ppd = config.get('packages_per_display') or 0
                        tpp = config.get('tablets_per_package') or 0
                        sub_total = (displays * ppd * tpp) + (cards * tpp)
                        total_packaged += sub_total

                # Bottle submissions (bottle-only products with bag_id)
                bottle_submissions = conn.execute('''
                    SELECT ws.bottles_made, ws.product_name
                    FROM warehouse_submissions ws
                    WHERE ws.submission_type = 'bottle' AND ws.bag_id = ?
                ''', (bag_id,)).fetchall()

                bottle_direct_total = 0
                for sub in bottle_submissions:
                    sub_dict = dict(sub)
                    bottles = sub_dict.get('bottles_made') or 0
                    product_name = sub_dict.get('product_name')

                    if bottles and product_name:
                        # Get config for this bottle product
                        config = conn.execute('SELECT tablets_per_bottle FROM product_details WHERE TRIM(LOWER(product_name)) = TRIM(LOWER(?))', (product_name,)).fetchone()
                        if config:
                            tpb = dict(config).get('tablets_per_bottle') or 0
                            bottle_direct_total += (bottles * tpb)

                # Variety pack deductions via junction table
                bottle_junction_count = conn.execute('''
                    SELECT COALESCE(SUM(sbd.tablets_deducted), 0) as total_junction
                    FROM submission_bag_deductions sbd
                    WHERE sbd.bag_id = ?
                ''', (bag_id,)).fetchone()
                bottle_junction_total = dict(bottle_junction_count)['total_junction'] if bottle_junction_count else 0

                total_packaged = total_packaged + bottle_direct_total + bottle_junction_total

                # Bag count submissions
                bag_count = conn.execute('''
                    SELECT COALESCE(SUM(COALESCE(ws.loose_tablets, 0)), 0) as total_bag
                    FROM warehouse_submissions ws
                    LEFT JOIN bags b_verify ON ws.bag_id = b_verify.id
                    LEFT JOIN small_boxes sb_verify ON b_verify.small_box_id = sb_verify.id
                    WHERE ws.submission_type = 'bag'
                    AND (
                        (ws.bag_id = ? AND ws.assigned_po_id = ? AND sb_verify.receiving_id = ?)
                        OR (
                            ws.bag_id IS NULL AND ws.inventory_item_id = ? AND ws.bag_number = ?
                            AND ws.assigned_po_id = ? AND ws.box_number = ?
                        )
                    )
                ''', (bag_id, po_id, receive_id, inventory_item_id, bag_number, po_id, box_number)).fetchone()

                # Build bag data entry with all fields needed for both views
                bag_entry = {
                    'bag_id': bag_id,
                    'tablet_type_id': bag.get('tablet_type_id'),
                    'bag_number': bag_number,
                    'box_number': box_number,
                    'tablet_type_name': tablet_type_name,
                    'inventory_item_id': inventory_item_id,
                    'status': bag.get('status', 'Available'),
                    'received_count': bag_label_count,
                    'machine_count': machine_total,
                    'packaged_count': total_packaged,
                    'bag_count': dict(bag_count)['total_bag'] if bag_count else 0,
                    'zoho_receive_pushed': bool(bag.get('zoho_receive_pushed', False)),
                    'zoho_receive_id': bag.get('zoho_receive_id'),
                    'zoho_receive_overs_id': bag.get('zoho_receive_overs_id'),
                    'reserved_for_bottles': bool(bag.get('reserved_for_bottles', False)),
                    'batch_number': bag.get('batch_number'),
                    'batch_source': bag.get('batch_source'),
                    'bag_weight_kg': bag.get('bag_weight_kg'),
                    'estimated_tablets_from_weight': bag.get('estimated_tablets_from_weight'),
                }
                products[inventory_item_id]['boxes'][box_number][bag_number] = bag_entry

            # Convert nested dict to list format (flavor view)
            products_list = []
            for inventory_item_id, product_data in products.items():
                product_entry = {
                    'tablet_type_name': product_data['tablet_type_name'],
                    'inventory_item_id': inventory_item_id,
                    'boxes': []
                }
                for box_number, bags_in_box in sorted(product_data['boxes'].items()):
                    box_entry = {
                        'box_number': box_number,
                        'bags': []
                    }
                    for bag_number, bag_data in sorted(bags_in_box.items()):
                        box_entry['bags'].append({
                            'bag_number': bag_number,
                            **bag_data
                        })
                    product_entry['boxes'].append(box_entry)
                products_list.append(product_entry)

            # Build boxes_view: organized by box -> bags (with flavor info per bag)
            # This view groups all bags by their physical box location
            boxes_dict = {}
            for _inventory_item_id, product_data in products.items():
                for box_number, bags_in_box in product_data['boxes'].items():
                    if box_number not in boxes_dict:
                        boxes_dict[box_number] = {
                            'box_number': box_number,
                            'bags': []
                        }
                    for bag_number, bag_data in bags_in_box.items():
                        boxes_dict[box_number]['bags'].append({
                            'bag_number': bag_number,
                            **bag_data
                        })

            # Convert to sorted list and sort bags within each box
            boxes_view = []
            for box_number in sorted(boxes_dict.keys()):
                box_data = boxes_dict[box_number]
                # Sort bags by bag_number within each box
                box_data['bags'] = sorted(box_data['bags'], key=lambda b: b['bag_number'])
                boxes_view.append(box_data)

            box_batch_defaults_rows = conn.execute('''
                SELECT box_number, batch_number_default
                FROM small_boxes
                WHERE receiving_id = ?
            ''', (receive_id,)).fetchall()
            box_batch_defaults = {
                row['box_number']: row['batch_number_default']
                for row in box_batch_defaults_rows
            }
            for box_data in boxes_view:
                box_data['box_batch_number'] = box_batch_defaults.get(box_data['box_number'])

            shipment_batch_defaults = conn.execute('''
                SELECT tablet_type_id, batch_number
                FROM receiving_flavor_batches
                WHERE receiving_id = ?
                ORDER BY tablet_type_id
            ''', (receive_id,)).fetchall()

            return jsonify({
                'success': True,
                'receive': receive_dict,
                'products': products_list,
                'boxes_view': boxes_view,
                'shipment_batch_defaults': [dict(row) for row in shipment_batch_defaults]
            })
    except Exception as e:
        current_app.logger.error(f"Error getting receiving details: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/shipping')
@role_required('shipping')
def receiving_list():
    """Shipments Received page - record shipments that arrive"""
    try:
        with db_read_only() as conn:
            # Get all tablet types for the form dropdown
            tablet_types = conn.execute('''
                SELECT id, tablet_type_name
                FROM tablet_types
                ORDER BY tablet_type_name
            ''').fetchall()

            # Get all POs for warehouse leads/managers/admins to assign
            purchase_orders = []
            if session.get('employee_role') in ['warehouse_lead', 'manager', 'admin']:
                purchase_orders = conn.execute('''
                    SELECT id, po_number, closed, internal_status, zoho_status
                    FROM purchase_orders
                    ORDER BY po_number DESC
                ''').fetchall()

            # Get all receiving records with their boxes and bags
            receiving_records = conn.execute('''
                SELECT r.*,
                       COUNT(DISTINCT sb.id) as box_count,
                       COUNT(DISTINCT b.id) as total_bags,
                       po.po_number
                FROM receiving r
                LEFT JOIN small_boxes sb ON r.id = sb.receiving_id
                LEFT JOIN bags b ON sb.id = b.small_box_id
                LEFT JOIN purchase_orders po ON r.po_id = po.id
                GROUP BY r.id
                ORDER BY r.received_date DESC
            ''').fetchall()

            # Calculate shipment numbers for each PO
            po_shipment_counts = {}
            for rec in receiving_records:
                po_id = rec['po_id']
                if po_id and po_id not in po_shipment_counts:
                    po_shipments = conn.execute('''
                        SELECT id, received_date
                        FROM receiving
                        WHERE po_id = ?
                        ORDER BY received_date ASC, id ASC
                    ''', (po_id,)).fetchall()
                    po_shipment_counts[po_id] = {
                        shipment['id']: idx + 1
                        for idx, shipment in enumerate(po_shipments)
                    }

            # For each receiving record, get its boxes and bags
            shipments = []
            for rec in receiving_records:
                rec_dict = dict(rec)
                if rec['po_id'] and rec['po_id'] in po_shipment_counts:
                    rec_dict['shipment_number'] = po_shipment_counts[rec['po_id']].get(rec['id'], 1)
                else:
                    rec_dict['shipment_number'] = None
                boxes = conn.execute('''
                    SELECT sb.*, COUNT(b.id) as bag_count
                    FROM small_boxes sb
                    LEFT JOIN bags b ON sb.id = b.small_box_id
                    WHERE sb.receiving_id = ?
                    GROUP BY sb.id
                    ORDER BY sb.box_number
                ''', (rec['id'],)).fetchall()

                boxes_with_bags = []
                for box in boxes:
                    bags = conn.execute('''
                        SELECT b.*, tt.tablet_type_name
                        FROM bags b
                        LEFT JOIN tablet_types tt ON b.tablet_type_id = tt.id
                        WHERE b.small_box_id = ?
                        ORDER BY b.bag_number
                    ''', (box['id'],)).fetchall()
                    boxes_with_bags.append({
                        'box': dict(box),
                        'bags': [dict(bag) for bag in bags]
                    })

                shipments.append({
                    'receiving': rec_dict,
                    'boxes': boxes_with_bags
                })

            return render_template('shipping_unified.html',
                                 tablet_types=tablet_types,
                                 purchase_orders=purchase_orders,
                                 shipments=shipments,
                                 user_role=session.get('employee_role'))
    except Exception as e:
        error_details = traceback.format_exc()
        current_app.logger.error(f"Error in receiving_list: {str(e)}\n{error_details}")
        return render_template('error.html',
                             error_message=f"Error loading shipping page: {str(e)}\n\nFull traceback:\n{error_details}"), 500


@bp.route('/api/shipments/<int:shipment_id>/refresh', methods=['POST'])
@role_required('dashboard')
def refresh_shipment_tracking(shipment_id: int):
    """Manually refresh a single shipment's tracking status."""
    try:
        with db_transaction() as conn:
            result = refresh_shipment_row(conn, shipment_id)
            if result.get('success'):
                return jsonify(result)
            return jsonify(result), 400
    except Exception as e:
        current_app.logger.error(f"Error refreshing shipment: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/shipment/<int:shipment_id>', methods=['GET'])
@role_required('dashboard')
def get_shipment_details(shipment_id: int):
    """Get shipment details by ID"""
    try:
        with db_read_only() as conn:
            row = conn.execute('''
                SELECT id, po_id, tracking_number, carrier, shipped_date, estimated_delivery, actual_delivery, notes
                FROM shipments WHERE id = ?
            ''', (shipment_id,)).fetchone()
            if not row:
                return jsonify({'success': False, 'error': 'Not found'}), 404
            return jsonify({'success': True, 'shipment': dict(row)})
    except Exception as e:
        current_app.logger.error(f"Error getting shipment: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/shipment/<int:shipment_id>', methods=['DELETE'])
@role_required('dashboard')
def delete_shipment(shipment_id: int):
    """Delete a shipment"""
    try:
        with db_transaction() as conn:
            conn.execute('DELETE FROM shipments WHERE id = ?', (shipment_id,))
            return jsonify({'success': True})
    except Exception as e:
        current_app.logger.error(f"Error deleting shipment: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/save_shipment', methods=['POST'])
@role_required('dashboard')
def save_shipment():
    """Save shipment information (supports multiple shipments per PO)"""
    try:
        data = request.get_json()

        if not data.get('po_id'):
            return jsonify({'success': False, 'error': 'po_id is required'}), 400

        try:
            po_id = int(data['po_id'])
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid po_id'}), 400

        with db_transaction() as conn:
            shipment_id = data.get('shipment_id')

            if shipment_id:
                try:
                    shipment_id = int(shipment_id)
                except (ValueError, TypeError):
                    return jsonify({'success': False, 'error': 'Invalid shipment_id'}), 400

                conn.execute('''
                UPDATE shipments
                SET tracking_number = ?, carrier = ?, shipped_date = ?,
                    estimated_delivery = ?, actual_delivery = ?, notes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (data.get('tracking_number'), data.get('carrier'), data.get('shipped_date'),
                  data.get('estimated_delivery'), data.get('actual_delivery'),
                      data.get('notes'), shipment_id))
            else:
                conn.execute('''
                INSERT INTO shipments (po_id, tracking_number, carrier, shipped_date,
                                     estimated_delivery, actual_delivery, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (po_id, data.get('tracking_number'), data.get('carrier'),
                      data.get('shipped_date'), data.get('estimated_delivery'),
                      data.get('actual_delivery'), data.get('notes')))
                conn.execute('UPDATE shipments SET carrier_code = LOWER(?) WHERE rowid = last_insert_rowid()', (data.get('carrier'),))

            # Auto-progress PO to "Shipped" status when tracking info is added
            if data.get('tracking_number'):
                current_status = conn.execute(
                    'SELECT internal_status FROM purchase_orders WHERE id = ?',
                    (po_id,)
                ).fetchone()

                if current_status and current_status['internal_status'] in ['Draft', 'Issued']:
                    conn.execute('''
                        UPDATE purchase_orders
                        SET internal_status = 'Shipped', updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    ''', (po_id,))
                    current_app.logger.info(f"Auto-progressed PO {po_id} to Shipped (tracking added)")

            # Trigger immediate UPS refresh when applicable
            if data.get('tracking_number') and (data.get('carrier', '').lower() in ('ups','fedex','fed ex')):
                sh = conn.execute('''
                    SELECT id FROM shipments WHERE po_id = ? AND tracking_number = ?
                    ORDER BY updated_at DESC LIMIT 1
                ''', (po_id, data.get('tracking_number'))).fetchone()
                if sh:
                    try:
                        result = refresh_shipment_row(conn, sh['id'])
                        current_app.logger.info(f"UPS refresh result: {result}")
                    except Exception as exc:
                        current_app.logger.error(f"UPS refresh error: {exc}")

            return jsonify({'success': True, 'message': 'Shipment saved; tracking refreshed if supported'})
    except Exception as e:
        current_app.logger.error(f"Error saving shipment: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

