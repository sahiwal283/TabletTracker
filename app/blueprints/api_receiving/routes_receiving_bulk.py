"""Receiving and Shipping API routes (subsection)."""

import os
import traceback
from datetime import datetime

from flask import current_app, jsonify, request, session
from werkzeug.utils import secure_filename

from app.services.bag_matching_service import (
    build_receive_name,
    find_matching_bags_with_receive_names,
)
from app.services.receiving_admin_service import (
    assign_po_to_receiving as assign_po_to_receiving_service,
)
from app.services.receiving_admin_service import (
    publish_receiving as publish_receiving_service,
)
from app.services.receiving_admin_service import (
    unpublish_receiving as unpublish_receiving_service,
)
from app.services.receiving_service import (
    apply_contiguous_flavor_bag_numbers_on_save,
    get_packaged_counts_for_bag_ids,
)
from app.services.zoho_service import parse_zoho_item_weight_grams, zoho_api
from app.utils.auth_utils import admin_required, employee_required, role_required
from app.utils.db_utils import BagRepository, db_read_only, db_transaction

from . import bp
from .helpers import _receipt_family_root, normalize_batch_number


@bp.route('/api/process_receiving', methods=['POST'])
@admin_required
def process_receiving():
    """Process a new shipment receiving with photos and box/bag tracking"""
    try:
        with db_transaction() as conn:
            shipment_id = request.form.get('shipment_id')
            if not shipment_id:
                return jsonify({'error': 'Shipment ID required'}), 400

            try:
                total_small_boxes = int(request.form.get('total_small_boxes', 0))
            except (ValueError, TypeError):
                return jsonify({'error': 'Invalid total_small_boxes value'}), 400

            received_by = request.form.get('received_by')
            notes = request.form.get('notes', '')

            # Get shipment and PO info
            shipment = conn.execute('''
                SELECT s.*, po.po_number, po.id as po_id
                FROM shipments s
                JOIN purchase_orders po ON s.po_id = po.id
                WHERE s.id = ?
            ''', (shipment_id,)).fetchone()

            if not shipment:
                return jsonify({'error': 'Shipment not found'}), 404

            # Handle photo upload with validation
            delivery_photo = request.files.get('delivery_photo')
            photo_path = None
            zoho_photo_id = None

            ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif'}
            MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

            def allowed_file(filename):
                return '.' in filename and \
                       filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

            if delivery_photo and delivery_photo.filename:
                if not allowed_file(delivery_photo.filename):
                    return jsonify({'error': 'Invalid file type. Only JPG, JPEG, PNG, and GIF are allowed.'}), 400

                delivery_photo.seek(0, os.SEEK_END)
                file_size = delivery_photo.tell()
                delivery_photo.seek(0)
                if file_size > MAX_FILE_SIZE:
                    return jsonify({'error': f'File too large. Maximum size is {MAX_FILE_SIZE / (1024*1024):.0f}MB'}), 400

                try:
                    shipment_id_int = int(shipment_id)
                except (ValueError, TypeError):
                    return jsonify({'error': 'Invalid shipment_id'}), 400

                safe_filename = secure_filename(delivery_photo.filename)
                original_ext = safe_filename.rsplit('.', 1)[1].lower() if '.' in safe_filename else 'jpg'

                upload_dir = os.path.join(current_app.root_path, '..', 'static', 'uploads', 'receiving')
                upload_dir = os.path.abspath(upload_dir)

                allowed_base = os.path.abspath(os.path.join(current_app.root_path, '..', 'static', 'uploads'))
                if not upload_dir.startswith(allowed_base):
                    return jsonify({'error': 'Invalid upload path'}), 400

                os.makedirs(upload_dir, exist_ok=True)

                filename = f"shipment_{shipment_id_int}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{original_ext}"
                photo_path = os.path.join(upload_dir, filename)
                delivery_photo.save(photo_path)

            # Calculate receive number for this PO
            receive_number_result = conn.execute('''
                SELECT COUNT(*) + 1 as receive_number
                FROM receiving
                WHERE po_id = ?
            ''', (shipment['po_id'],)).fetchone()

            receive_number = receive_number_result['receive_number'] if receive_number_result else 1
            receive_name = f"{shipment['po_number']}-{receive_number}"

            # Create receiving record
            receiving_cursor = conn.execute('''
                INSERT INTO receiving (po_id, shipment_id, total_small_boxes, received_by, notes, delivery_photo_path, delivery_photo_zoho_id, receive_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (shipment['po_id'], shipment_id, total_small_boxes, received_by, notes, photo_path, zoho_photo_id, receive_name))

            receiving_id = receiving_cursor.lastrowid

            # Process box details with sequential bag numbering
            total_bags = 0
            all_bag_data = {}

            for key in request.form.keys():
                if key.startswith('bag_') and key.endswith('_pill_count'):
                    try:
                        key_parts = key.split('_')
                        if len(key_parts) < 2:
                            continue
                        bag_num = int(key_parts[1])
                        if bag_num not in all_bag_data:
                            all_bag_data[bag_num] = {}

                        try:
                            all_bag_data[bag_num]['pill_count'] = int(request.form[key])
                        except (ValueError, TypeError):
                            all_bag_data[bag_num]['pill_count'] = 0

                        try:
                            all_bag_data[bag_num]['box'] = int(request.form.get(f'bag_{bag_num}_box', 0))
                        except (ValueError, TypeError):
                            all_bag_data[bag_num]['box'] = 0

                        all_bag_data[bag_num]['notes'] = request.form.get(f'bag_{bag_num}_notes', '')
                    except (ValueError, TypeError, IndexError):
                        continue

            # Process boxes and their bags
            for box_num in range(1, total_small_boxes + 1):
                try:
                    bags_in_box = int(request.form.get(f'box_{box_num}_bags', 0))
                except (ValueError, TypeError):
                    bags_in_box = 0

                box_notes = request.form.get(f'box_{box_num}_notes', '')

                box_cursor = conn.execute('''
                    INSERT INTO small_boxes (receiving_id, box_number, total_bags, notes)
                    VALUES (?, ?, ?, ?)
                ''', (receiving_id, box_num, bags_in_box, box_notes))

                small_box_id = box_cursor.lastrowid

                for bag_data_key, bag_data in all_bag_data.items():
                    if bag_data['box'] == box_num:
                        conn.execute('''
                            INSERT INTO bags (small_box_id, bag_number, pill_count, status)
                            VALUES (?, ?, ?, 'Available')
                        ''', (small_box_id, bag_data_key, bag_data['pill_count']))
                        total_bags += 1

            # Update shipment status
            conn.execute('''
                UPDATE shipments SET actual_delivery = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (shipment_id,))

            return jsonify({
                'success': True,
                'message': f'Successfully received shipment for PO {shipment["po_number"]}. Processed {total_small_boxes} boxes with {total_bags} total bags.',
                'receiving_id': receiving_id
            })
    except Exception as e:
        current_app.logger.error(f"Error processing receiving: {str(e)}")
        return jsonify({'error': f'Failed to process receiving: {str(e)}'}), 500


@bp.route('/api/receiving/<int:receiving_id>/editable', methods=['GET'])
@role_required('shipping')
def get_receive_editable(receiving_id):
    """Get receive data in format suitable for editing (boxes and bags structure)"""
    try:
        with db_read_only() as conn:
            # Get receive details
            receive = conn.execute('''
                SELECT r.*, po.po_number
                FROM receiving r
                LEFT JOIN purchase_orders po ON r.po_id = po.id
                WHERE r.id = ?
            ''', (receiving_id,)).fetchone()

            if not receive:
                return jsonify({'success': False, 'error': 'Receive not found'}), 404

            # Get boxes with bags
            boxes = conn.execute('''
                SELECT sb.id, sb.box_number, sb.total_bags, sb.batch_number_default
                FROM small_boxes sb
                WHERE sb.receiving_id = ?
                ORDER BY sb.box_number
            ''', (receiving_id,)).fetchall()

            boxes_data = []
            for box in boxes:
                # Get bags for this box
                bags = conn.execute('''
                    SELECT b.id, b.bag_number, b.bag_label_count, b.tablet_type_id, b.status,
                           b.batch_number, b.batch_source,
                           b.bag_weight_kg, b.estimated_tablets_from_weight
                    FROM bags b
                    WHERE b.small_box_id = ?
                    ORDER BY b.bag_number
                ''', (box['id'],)).fetchall()

                boxes_data.append({
                    'box_number': box['box_number'],
                    'batch_number_default': box['batch_number_default'],
                    'bags': [dict(bag) for bag in bags]
                })

            shipment_batch_defaults = conn.execute('''
                SELECT tablet_type_id, batch_number
                FROM receiving_flavor_batches
                WHERE receiving_id = ?
                ORDER BY tablet_type_id
            ''', (receiving_id,)).fetchall()

            return jsonify({
                'success': True,
                'receive': dict(receive),
                'boxes': boxes_data,
                'shipment_batch_defaults': [dict(row) for row in shipment_batch_defaults]
            })
    except Exception as e:
        current_app.logger.error(f"Error getting editable receive: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/save_receives', methods=['POST'])
@role_required('shipping')
def save_receives():
    """Save received shipment data (boxes and bags)"""
    try:
        data = request.get_json()
        boxes_data = data.get('boxes', [])
        shipment_batch_defaults_raw = data.get('shipment_batch_defaults', [])
        po_id = data.get('po_id')
        status = data.get('status', 'published')  # Default to published for backward compatibility
        receiving_id = data.get('receiving_id')  # If provided, update existing receive

        # Validate status
        if status not in ['draft', 'published']:
            status = 'published'

        if not boxes_data:
            return jsonify({'success': False, 'error': 'No boxes data provided'}), 400

        shipment_batch_defaults = {}
        if shipment_batch_defaults_raw:
            if not isinstance(shipment_batch_defaults_raw, list):
                return jsonify({'success': False, 'error': 'shipment_batch_defaults must be a list'}), 400
            for entry in shipment_batch_defaults_raw:
                if not isinstance(entry, dict):
                    continue
                tablet_type_id = entry.get('tablet_type_id')
                batch_number = normalize_batch_number(entry.get('batch_number'))
                if not tablet_type_id or not batch_number:
                    continue
                shipment_batch_defaults[int(tablet_type_id)] = batch_number

        user_role = session.get('employee_role')
        if po_id and user_role not in ['warehouse_lead', 'manager', 'admin']:
            return jsonify({'success': False, 'error': 'Only warehouse leads, managers, and admins can assign POs'}), 403

        with db_transaction() as conn:
            # Ensure tablet_type_id column exists
            c = conn.cursor()
            c.execute('PRAGMA table_info(bags)')
            existing_bags_cols = [row[1] for row in c.fetchall()]
            if 'tablet_type_id' not in existing_bags_cols:
                try:
                    conn.execute('ALTER TABLE bags ADD COLUMN tablet_type_id INTEGER')
                    conn.commit()
                except Exception as e:
                    if conn:
                        try:
                            conn.rollback()
                        except Exception:
                            # Keep original migration warning path.
                            pass
                    current_app.logger.warning(f"Could not add tablet_type_id column: {e}")

            # Get current user name
            received_by = 'Unknown'
            if session.get('employee_id'):
                employee = conn.execute('SELECT full_name FROM employees WHERE id = ?', (session.get('employee_id'),)).fetchone()
                if employee:
                    received_by = employee['full_name']
            elif session.get('admin_authenticated'):
                received_by = 'Admin'

            # If updating existing receive, only delete and recreate if explicitly updating
            # CRITICAL: This is destructive - only use when form has ALL data loaded
            if receiving_id:
                # Verify receive exists and is editable
                existing = conn.execute('SELECT status FROM receiving WHERE id = ?', (receiving_id,)).fetchone()
                if not existing:
                    return jsonify({'success': False, 'error': 'Receive not found'}), 404

                # Only allow updates to draft receives to prevent data loss
                if existing['status'] != 'draft':
                    return jsonify({
                        'success': False,
                        'error': 'Can only edit draft receives. Publish receives are locked to prevent accidental data loss.'
                    }), 400

                # CRITICAL SAFETY CHECK: Warn if this looks like data loss
                old_count = conn.execute('''
                    SELECT COUNT(*) as count FROM small_boxes WHERE receiving_id = ?
                ''', (receiving_id,)).fetchone()

                if old_count and old_count['count'] > len(boxes_data):
                    current_app.logger.warning(f"⚠️ UPDATE WARNING: Receive {receiving_id} had {old_count['count']} boxes, new data has {len(boxes_data)}. Potential data loss!")

                # Delete existing bags and boxes (will be replaced with form data)
                conn.execute('''
                    DELETE FROM bags
                    WHERE small_box_id IN (SELECT id FROM small_boxes WHERE receiving_id = ?)
                ''', (receiving_id,))

                conn.execute('DELETE FROM small_boxes WHERE receiving_id = ?', (receiving_id,))
                conn.execute('DELETE FROM receiving_flavor_batches WHERE receiving_id = ?', (receiving_id,))

                # Update receiving record
                conn.execute('''
                    UPDATE receiving
                    SET po_id = ?, total_small_boxes = ?, notes = ?, status = ?
                    WHERE id = ?
                ''', (po_id if po_id else None, len(boxes_data), f'Updated: {len(boxes_data)} box(es)', status, receiving_id))
            else:
                # Create new receiving record with status
                receiving_cursor = conn.execute('''
                    INSERT INTO receiving (po_id, received_by, received_date, total_small_boxes, notes, status)
                    VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?, ?)
                ''', (po_id if po_id else None, received_by, len(boxes_data), f'Recorded {len(boxes_data)} box(es)', status))

                receiving_id = receiving_cursor.lastrowid

            for tablet_type_id, batch_number in shipment_batch_defaults.items():
                conn.execute('''
                    INSERT OR REPLACE INTO receiving_flavor_batches (receiving_id, tablet_type_id, batch_number)
                    VALUES (?, ?, ?)
                ''', (receiving_id, tablet_type_id, batch_number))

            # Dense flavor bag numbers per PO (fixes gaps from client/UI drift); ordered by box then bag row.
            apply_contiguous_flavor_bag_numbers_on_save(conn, int(po_id) if po_id else None, boxes_data)

            total_bags = 0

            # Process each box
            for box_data in boxes_data:
                box_number = box_data.get('box_number')
                bags = box_data.get('bags', [])
                box_batch_number_default = normalize_batch_number(box_data.get('box_batch_number'))

                if not bags:
                    continue

                box_cursor = conn.execute('''
                    INSERT INTO small_boxes (receiving_id, box_number, total_bags, batch_number_default)
                    VALUES (?, ?, ?, ?)
                ''', (receiving_id, box_number, len(bags), box_batch_number_default))

                small_box_id = box_cursor.lastrowid

                for bag in bags:
                    tablet_type_id = bag.get('tablet_type_id')
                    bag_count = bag.get('bag_count', 0)
                    bag_number = bag.get('bag_number')
                    bag_specific_batch_number = normalize_batch_number(bag.get('bag_specific_batch_number'))

                    if not tablet_type_id or not bag_number:
                        continue

                    tablet_type_id_int = int(tablet_type_id)
                    effective_batch_number = None
                    batch_source = None
                    if bag_specific_batch_number:
                        effective_batch_number = bag_specific_batch_number
                        batch_source = 'bag_specific'
                    elif box_batch_number_default:
                        effective_batch_number = box_batch_number_default
                        batch_source = 'box_default'
                    elif shipment_batch_defaults.get(tablet_type_id_int):
                        effective_batch_number = shipment_batch_defaults[tablet_type_id_int]
                        batch_source = 'shipment_default'

                    bag_weight_kg = None
                    estimated_tablets_from_weight = None
                    bw_raw = bag.get('bag_weight_kg')
                    if bw_raw is not None and str(bw_raw).strip() != '':
                        try:
                            bag_weight_kg = float(bw_raw)
                        except (TypeError, ValueError):
                            return jsonify({
                                'success': False,
                                'error': f'Invalid bag weight (kg) for bag {bag_number}',
                            }), 400
                        if bag_weight_kg < 0:
                            return jsonify({'success': False, 'error': 'Bag weight cannot be negative'}), 400
                        tt_row = conn.execute(
                            'SELECT inventory_item_id FROM tablet_types WHERE id = ?',
                            (tablet_type_id_int,),
                        ).fetchone()
                        if not tt_row or not tt_row['inventory_item_id']:
                            return jsonify({
                                'success': False,
                                'error': 'Tablet type has no Zoho inventory item; cannot record bag weight.',
                            }), 400
                        zoho_item = zoho_api.get_item(tt_row['inventory_item_id'])
                        grams = parse_zoho_item_weight_grams(zoho_item)
                        if not grams:
                            return jsonify({
                                'success': False,
                                'error': (
                                    'No weight configured in Zoho for this item. '
                                    'Remove the weight field or add weight in Zoho Inventory.'
                                ),
                            }), 400
                        estimated_tablets_from_weight = int((bag_weight_kg * 1000.0) / grams)

                    conn.execute('''
                        INSERT INTO bags (
                            small_box_id, bag_number, bag_label_count, tablet_type_id, status, batch_number, batch_source,
                            bag_weight_kg, estimated_tablets_from_weight
                        )
                        VALUES (?, ?, ?, ?, 'Available', ?, ?, ?, ?)
                    ''', (
                        small_box_id, bag_number, bag_count, tablet_type_id_int, effective_batch_number, batch_source,
                        bag_weight_kg, estimated_tablets_from_weight,
                    ))
                    total_bags += 1

            conn.execute('''
                UPDATE receiving SET total_small_boxes = ?
                WHERE id = ?
            ''', (len(boxes_data), receiving_id))

            # Determine success message
            if data.get('receiving_id'):
                action = 'updated'
            else:
                action = 'recorded'

            status_message = 'as DRAFT (not live yet)' if status == 'draft' else 'and published (now live)'

            return jsonify({
                'success': True,
                'message': f'Successfully {action} {len(boxes_data)} box(es) with {total_bags} bag(s) {status_message}',
                'receiving_id': receiving_id,
                'status': status
            })
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error saving receives: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/receiving/<int:receiving_id>/batch_info', methods=['POST'])
@role_required('shipping')
def update_receiving_batch_info(receiving_id):
    """Update batch information for an existing receive without changing bag/box structure."""
    try:
        user_role = session.get('employee_role')
        is_admin = session.get('admin_authenticated')
        if user_role not in ['manager', 'admin'] and not is_admin:
            return jsonify({'success': False, 'error': 'Only managers and admins can edit batch info'}), 403

        data = request.get_json() or {}
        shipment_batch_defaults_raw = data.get('shipment_batch_defaults', [])
        box_defaults_raw = data.get('box_defaults', [])
        bag_specific_batches_raw = data.get('bag_specific_batches', [])

        shipment_batch_defaults = {}
        for row in shipment_batch_defaults_raw:
            if not isinstance(row, dict):
                continue
            tablet_type_id = row.get('tablet_type_id')
            if not tablet_type_id:
                continue
            shipment_batch_defaults[int(tablet_type_id)] = normalize_batch_number(row.get('batch_number'))

        box_defaults = {}
        for row in box_defaults_raw:
            if not isinstance(row, dict):
                continue
            box_number = row.get('box_number')
            if not box_number:
                continue
            box_defaults[int(box_number)] = normalize_batch_number(row.get('batch_number_default'))

        bag_specific_batches = {}
        for row in bag_specific_batches_raw:
            if not isinstance(row, dict):
                continue
            bag_id = row.get('bag_id')
            if not bag_id:
                continue
            bag_specific_batches[int(bag_id)] = normalize_batch_number(row.get('batch_number'))

        with db_transaction() as conn:
            receive_row = conn.execute('SELECT id FROM receiving WHERE id = ?', (receiving_id,)).fetchone()
            if not receive_row:
                return jsonify({'success': False, 'error': 'Receive not found'}), 404

            conn.execute('DELETE FROM receiving_flavor_batches WHERE receiving_id = ?', (receiving_id,))
            for tablet_type_id, batch_number in shipment_batch_defaults.items():
                if not batch_number:
                    continue
                conn.execute('''
                    INSERT INTO receiving_flavor_batches (receiving_id, tablet_type_id, batch_number)
                    VALUES (?, ?, ?)
                ''', (receiving_id, tablet_type_id, batch_number))

            small_boxes = conn.execute('''
                SELECT id, box_number
                FROM small_boxes
                WHERE receiving_id = ?
            ''', (receiving_id,)).fetchall()
            for small_box in small_boxes:
                batch_number_default = box_defaults.get(small_box['box_number'])
                conn.execute('''
                    UPDATE small_boxes
                    SET batch_number_default = ?
                    WHERE id = ?
                ''', (batch_number_default, small_box['id']))

            bags = conn.execute('''
                SELECT b.id, b.tablet_type_id, b.batch_number, b.batch_source, sb.box_number
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                WHERE sb.receiving_id = ?
            ''', (receiving_id,)).fetchall()

            for bag in bags:
                bag_id = bag['id']
                tablet_type_id = bag['tablet_type_id']
                box_number = bag['box_number']

                has_explicit_specific = bag_id in bag_specific_batches
                current_specific = bag['batch_number'] if bag['batch_source'] == 'bag_specific' else None
                bag_specific_batch = bag_specific_batches[bag_id] if has_explicit_specific else current_specific
                box_default_batch = box_defaults.get(box_number)
                shipment_default_batch = shipment_batch_defaults.get(tablet_type_id)

                effective_batch = None
                batch_source = None
                if bag_specific_batch:
                    effective_batch = bag_specific_batch
                    batch_source = 'bag_specific'
                elif box_default_batch:
                    effective_batch = box_default_batch
                    batch_source = 'box_default'
                elif shipment_default_batch:
                    effective_batch = shipment_default_batch
                    batch_source = 'shipment_default'

                conn.execute('''
                    UPDATE bags
                    SET batch_number = ?, batch_source = ?
                    WHERE id = ?
                ''', (effective_batch, batch_source, bag_id))

            return jsonify({
                'success': True,
                'message': 'Batch information updated successfully.',
                'updated_bags': len(bags)
            })
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error updating batch info for receive {receiving_id}: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/receiving/<int:receiving_id>/publish', methods=['POST'])
@role_required('shipping')
def publish_receiving(receiving_id):
    """Publish a draft receive to make it live and available for production"""
    try:
        with db_transaction() as conn:
            result = publish_receiving_service(conn, receiving_id)
            if not result.get('success'):
                return jsonify({'success': False, 'error': result.get('error', 'Publish failed')}), result.get('status_code', 400)
            return jsonify(result)
    except Exception as e:
        current_app.logger.error(f"Error publishing receive: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/receiving/<int:receiving_id>/unpublish', methods=['POST'])
@role_required('shipping')
def unpublish_receiving(receiving_id):
    """Unpublish a receive (move back to draft) - only if no submissions exist"""
    try:
        with db_transaction() as conn:
            result = unpublish_receiving_service(conn, receiving_id)
            if not result.get('success'):
                return jsonify({'success': False, 'error': result.get('error', 'Unpublish failed')}), result.get('status_code', 400)
            return jsonify(result)
    except Exception as e:
        current_app.logger.error(f"Error unpublishing receive: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/receiving/<int:receiving_id>/assign_po', methods=['POST'])
@role_required('shipping')
def assign_po_to_receiving(receiving_id):
    """Update PO assignment for a receiving record (managers and admins only)"""
    try:
        user_role = session.get('employee_role')
        data = request.get_json() or {}
        po_id = data.get('po_id')
        if po_id not in (None, ''):
            try:
                po_id = int(po_id)
            except (TypeError, ValueError):
                return jsonify({'success': False, 'error': 'Invalid po_id'}), 400

        with db_transaction() as conn:
            result = assign_po_to_receiving_service(conn, receiving_id, po_id, user_role)
            if not result.get('success'):
                return jsonify({'success': False, 'error': result.get('error', 'Assignment failed')}), result.get('status_code', 400)
            return jsonify(result)
    except Exception as e:
        current_app.logger.error(f"Error assigning PO to receiving: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/available_boxes_bags/<int:po_id>')
@employee_required
def get_available_boxes_bags_for_po(po_id):
    """Get available boxes and bags for a PO (for warehouse form dropdowns)"""
    try:
        with db_read_only() as conn:
            # Get all receiving records for this PO with available bags
            receiving_data = conn.execute('''
                SELECT r.id as receiving_id, sb.box_number, b.bag_number, b.id as bag_id, b.bag_label_count
                FROM receiving r
                JOIN small_boxes sb ON r.id = sb.receiving_id
                JOIN bags b ON sb.id = b.small_box_id
                WHERE r.po_id = ? AND b.status = 'Available'
                ORDER BY sb.box_number, b.bag_number
            ''', (po_id,)).fetchall()

            # Structure data for frontend
            boxes = {}
            for row in receiving_data:
                box_num = row['box_number']
                if box_num not in boxes:
                    boxes[box_num] = []
                boxes[box_num].append({
                    'bag_number': row['bag_number'],
                    'bag_id': row['bag_id'],
                    'bag_label_count': row['bag_label_count']
                })

            return jsonify({'boxes': boxes})
    except Exception as e:
        current_app.logger.error(f"Error getting available boxes/bags: {str(e)}")
        return jsonify({'error': str(e)}), 500


@bp.route('/api/create_sample_receiving_data', methods=['POST'])
@admin_required
def create_sample_receiving_data():
    """Create sample PO and shipment data for testing receiving workflow"""
    try:
        import random

        with db_transaction() as conn:
            timestamp = datetime.now().strftime('%m%d-%H%M')
            po_number = f'TEST-{timestamp}'
            tracking_suffix = random.randint(100000, 999999)
            tracking_number = f'1Z999AA{tracking_suffix}'

            po_cursor = conn.execute('''
                INSERT INTO purchase_orders (po_number, tablet_type, zoho_status, ordered_quantity, internal_status)
                VALUES (?, ?, ?, ?, ?)
            ''', (po_number, 'Test Tablets', 'confirmed', 1000, 'Active'))

            po_id = po_cursor.lastrowid

            shipment_cursor = conn.execute('''
                INSERT INTO shipments (po_id, tracking_number, carrier, tracking_status, delivered_at, created_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ''', (po_id, tracking_number, 'UPS', 'Delivered'))

            shipment_id = shipment_cursor.lastrowid

            return jsonify({
                'success': True,
                'message': f'Created sample PO {po_number} with delivered UPS shipment. Ready for receiving!',
                'po_id': po_id,
                'shipment_id': shipment_id
            })
    except Exception as e:
        current_app.logger.error(f"Error creating sample receiving data: {str(e)}")
        return jsonify({'error': f'Failed to create sample data: {str(e)}'}), 500


@bp.route('/api/po/<int:po_id>/receives', methods=['GET'])
@role_required('dashboard')
def get_po_receives(po_id):
    """Get all receives (shipments received) for a specific PO"""
    try:
        with db_read_only() as conn:
            po = conn.execute('''
                SELECT po_number
                FROM purchase_orders
                WHERE id = ?
            ''', (po_id,)).fetchone()

            if not po:
                return jsonify({'error': 'PO not found'}), 404

            receiving_records = conn.execute('''
                SELECT r.*,
                       COUNT(DISTINCT sb.id) as box_count,
                       COUNT(DISTINCT b.id) as total_bags
                FROM receiving r
                LEFT JOIN small_boxes sb ON r.id = sb.receiving_id
                LEFT JOIN bags b ON sb.id = b.small_box_id
                WHERE r.po_id = ?
                GROUP BY r.id
                ORDER BY r.received_date ASC, r.id ASC
            ''', (po_id,)).fetchall()

            po_shipment_counts = {}
            po_shipments = conn.execute('''
                SELECT id, received_date
                FROM receiving
                WHERE po_id = ?
                ORDER BY received_date ASC, id ASC
            ''', (po_id,)).fetchall()
            po_shipment_counts = {
                dict(shipment)['id']: idx + 1
                for idx, shipment in enumerate(po_shipments)
            }

            receives = []
            all_bag_ids = []
            for rec in receiving_records:
                rec_dict = dict(rec)
                rec_id = rec_dict['id']
                if rec_id in po_shipment_counts:
                    rec_dict['shipment_number'] = po_shipment_counts[rec_id]
                else:
                    rec_dict['shipment_number'] = None
                boxes = conn.execute('''
                    SELECT sb.*, COUNT(b.id) as bag_count
                    FROM small_boxes sb
                    LEFT JOIN bags b ON sb.id = b.small_box_id
                    WHERE sb.receiving_id = ?
                    GROUP BY sb.id
                    ORDER BY sb.box_number
                ''', (rec_id,)).fetchall()

                boxes_with_bags = []
                for box in boxes:
                    box_dict = dict(box)
                    bags = conn.execute('''
                        SELECT b.*, tt.tablet_type_name, tt.inventory_item_id
                        FROM bags b
                        LEFT JOIN tablet_types tt ON b.tablet_type_id = tt.id
                        WHERE b.small_box_id = ?
                        ORDER BY b.bag_number
                    ''', (box_dict['id'],)).fetchall()
                    bag_dicts = [dict(bag) for bag in bags]
                    for bd in bag_dicts:
                        all_bag_ids.append(bd['id'])
                    boxes_with_bags.append({
                        'box': box_dict,
                        'bags': bag_dicts
                    })

                receives.append({
                    'receiving': rec_dict,
                    'boxes': boxes_with_bags
                })

            packaged_by_bag = get_packaged_counts_for_bag_ids(conn, all_bag_ids)
            for recv in receives:
                for box_data in recv['boxes']:
                    for bag in box_data['bags']:
                        bid = bag.get('id')
                        bag['packaged_count'] = packaged_by_bag.get(bid, 0) if bid is not None else 0

            return jsonify({
                'success': True,
                'po': dict(po),
                'receives': receives
            })
    except Exception as e:
        current_app.logger.error(f"Error getting PO receives: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


RECEIVES_LIST_CACHE_KEY = 'api_receives_list'
RECEIVES_LIST_CACHE_TTL = 30.0


@bp.route('/api/receives/list', methods=['GET'])
@role_required('dashboard')
def get_receives_list():
    """Get list of all receives for reporting (cached 30s)."""
    from app.utils.cache_utils import get as cache_get
    from app.utils.cache_utils import set as cache_set
    cached = cache_get(RECEIVES_LIST_CACHE_KEY)
    if cached is not None:
        return jsonify(cached)
    try:
        with db_read_only() as conn:
            receives = conn.execute('''
                SELECT r.id,
                       r.received_date,
                       po.po_number,
                       r.po_id,
                       r.receive_name
                FROM receiving r
                LEFT JOIN purchase_orders po ON r.po_id = po.id
                ORDER BY COALESCE(r.received_date, r.created_at) DESC, r.id DESC
                LIMIT 100
            ''').fetchall()

            receives_list = []
            for r in receives:
                receive_dict = dict(r)
                if not receive_dict.get('receive_name') and receive_dict.get('po_number'):
                    receive_number_result = conn.execute('''
                        SELECT COUNT(*) + 1 as receive_number
                        FROM receiving r2
                        WHERE r2.po_id = ?
                        AND (r2.received_date < ?
                             OR (r2.received_date = ? AND r2.id < ?))
                    ''', (receive_dict['po_id'], receive_dict.get('received_date'), receive_dict.get('received_date'), receive_dict.get('id'))).fetchone()
                    receive_number = receive_number_result['receive_number'] if receive_number_result else 1
                    receive_dict['receive_name'] = f"{receive_dict['po_number']}-{receive_number}"
                receives_list.append(receive_dict)

            payload = {'success': True, 'receives': receives_list}
            cache_set(RECEIVES_LIST_CACHE_KEY, payload, RECEIVES_LIST_CACHE_TTL)
            return jsonify(payload)
    except Exception as e:
        current_app.logger.error(f"Error getting receives list: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/api/submission/<int:submission_id>/possible-receives', methods=['GET'])
@employee_required
def get_possible_receives_for_submission(submission_id):
    """Get all possible receives that match a submission's flavor, box, bag"""
    try:
        with db_read_only() as conn:
            submission = conn.execute('''
                SELECT ws.*, tt.id as tablet_type_id, tt.tablet_type_name
                FROM warehouse_submissions ws
                LEFT JOIN tablet_types tt ON ws.inventory_item_id = tt.inventory_item_id
                WHERE ws.id = ?
            ''', (submission_id,)).fetchone()

            if not submission:
                return jsonify({'success': False, 'error': 'Submission not found'}), 404

            submission_dict = dict(submission)
            submission_type = submission_dict.get('submission_type', 'packaged')
            exclude_closed_bags = (submission_type != 'packaged')

            # Variety/bottle submissions may not have direct box/bag on warehouse_submissions.
            # If bag deductions exist, derive assignable receives from those linked bags.
            if submission_type == 'bottle':
                deduction_receives = conn.execute('''
                    SELECT
                        r.id as receive_id,
                        r.receive_name as stored_receive_name,
                        r.received_date,
                        po.id as po_id,
                        po.po_number,
                        MIN(b.id) as bag_id,
                        MIN(sb.box_number) as box_number,
                        MIN(b.bag_number) as bag_number,
                        MIN(b.bag_label_count) as bag_label_count,
                        COUNT(DISTINCT b.id) as bags_used,
                        COALESCE(SUM(sbd.tablets_deducted), 0) as tablets_deducted
                    FROM submission_bag_deductions sbd
                    JOIN bags b ON sbd.bag_id = b.id
                    JOIN small_boxes sb ON b.small_box_id = sb.id
                    JOIN receiving r ON sb.receiving_id = r.id
                    JOIN purchase_orders po ON r.po_id = po.id
                    WHERE sbd.submission_id = ?
                    AND (r.closed IS NULL OR r.closed = FALSE)
                    AND (po.closed IS NULL OR po.closed = 0)
                    GROUP BY r.id, r.receive_name, r.received_date, po.id, po.po_number
                    ORDER BY r.received_date DESC, r.id DESC
                ''', (submission_id,)).fetchall()

                if deduction_receives:
                    receives = []
                    for row in deduction_receives:
                        rec = dict(row)
                        stored_receive_name = rec.get('stored_receive_name')
                        if stored_receive_name:
                            receive_name = stored_receive_name
                        else:
                            receive_number = conn.execute('''
                                SELECT COUNT(*) + 1
                                FROM receiving r2
                                WHERE r2.po_id = ?
                                AND (r2.received_date < (SELECT received_date FROM receiving WHERE id = ?)
                                     OR (r2.received_date = (SELECT received_date FROM receiving WHERE id = ?)
                                         AND r2.id < ?))
                            ''', (rec['po_id'], rec['receive_id'], rec['receive_id'], rec['receive_id'])).fetchone()[0]
                            receive_name = f"{rec['po_number']}-{receive_number}"

                        receives.append({
                            'bag_id': rec['bag_id'],
                            'receive_id': rec['receive_id'],
                            'receive_name': receive_name,
                            'po_number': rec['po_number'],
                            'received_date': rec['received_date'],
                            'box_number': rec['box_number'],
                            'bag_number': rec['bag_number'],
                            'bag_label_count': rec['bag_label_count'],
                            'tablet_type_name': submission_dict.get('product_name') or 'Variety Pack',
                            'bags_used': rec.get('bags_used', 0),
                            'tablets_deducted': rec.get('tablets_deducted', 0)
                        })

                    return jsonify({
                        'success': True,
                        'submission': submission_dict,
                        'possible_receives': receives,
                        'warning': 'Using bag deductions to determine possible receives for this bottle/variety submission.'
                    })

            # Ensure tablet_type_id is populated - try fallback lookup if missing
            # This handles cases where LEFT JOIN didn't match but inventory_item_id exists
            tablet_type_id = submission_dict.get('tablet_type_id')
            if not tablet_type_id and submission_dict.get('inventory_item_id'):
                tt_row = conn.execute('''
                    SELECT id FROM tablet_types WHERE inventory_item_id = ?
                ''', (submission_dict.get('inventory_item_id'),)).fetchone()
                if tt_row:
                    tablet_type_id = tt_row['id']
                    submission_dict['tablet_type_id'] = tablet_type_id

            # Additional fallback: try to get tablet_type_id from product_name via product_details
            # This handles cases where inventory_item_id lookup failed (data inconsistency)
            if not tablet_type_id and submission_dict.get('product_name'):
                product_row = conn.execute('''
                    SELECT tablet_type_id FROM product_details WHERE product_name = ?
                ''', (submission_dict.get('product_name'),)).fetchone()
                if product_row:
                    tablet_type_id = product_row['tablet_type_id']
                    submission_dict['tablet_type_id'] = tablet_type_id

            # Use bag matching service
            matching_bags = find_matching_bags_with_receive_names(
                conn,
                submission_dict,
                exclude_closed_bags
            )

            # Legacy workflow rows may still carry lane/event suffix receipts
            # (e.g. 1893-4-seal-e5). If direct box/bag matching yields nothing,
            # derive possible receives from sibling rows in the same receipt family.
            if not matching_bags:
                source_receipt = (submission_dict.get('receipt_number') or '').strip()
                family_root = _receipt_family_root(source_receipt)
                if family_root:
                    family_rows = conn.execute(
                        '''
                        SELECT DISTINCT ws.bag_id,
                               b.bag_number,
                               b.bag_label_count,
                               sb.box_number,
                               r.id AS receive_id,
                               r.received_date,
                               r.receive_name AS stored_receive_name,
                               po.po_number,
                               po.id AS po_id,
                               tt.tablet_type_name
                        FROM warehouse_submissions ws
                        JOIN bags b ON b.id = ws.bag_id
                        JOIN small_boxes sb ON sb.id = b.small_box_id
                        JOIN receiving r ON r.id = sb.receiving_id
                        JOIN purchase_orders po ON po.id = r.po_id
                        LEFT JOIN tablet_types tt ON tt.id = b.tablet_type_id
                        WHERE ws.bag_id IS NOT NULL
                          AND ws.id != ?
                          AND (
                            ws.receipt_number = ?
                            OR ws.receipt_number LIKE ?
                            OR ws.receipt_number LIKE ?
                            OR ws.receipt_number LIKE ?
                            OR ws.receipt_number LIKE ?
                          )
                        ORDER BY r.received_date DESC, ws.bag_id DESC
                        ''',
                        (
                            submission_id,
                            family_root,
                            family_root + '-seal%',
                            family_root + '-blister%',
                            family_root + '-pkg-e%',
                            family_root + '-take-e%',
                        ),
                    ).fetchall()
                    if family_rows:
                        matching_bags = []
                        for row in family_rows:
                            bag = dict(row)
                            bag['receive_name'] = build_receive_name(bag, conn)
                            matching_bags.append(bag)

            if not submission_dict.get('bag_number'):
                # Fallback: try to find receives by tablet type
                if tablet_type_id:
                    if exclude_closed_bags:
                        fallback_receives = conn.execute('''
                            SELECT DISTINCT b.id as bag_id,
                                   sb.box_number,
                                   b.bag_number,
                                   b.bag_label_count,
                                   r.id as receive_id,
                                   r.received_date,
                                   r.receive_name as stored_receive_name,
                                   po.po_number,
                                   po.id as po_id,
                                   tt.tablet_type_name
                            FROM bags b
                            JOIN small_boxes sb ON b.small_box_id = sb.id
                            JOIN receiving r ON sb.receiving_id = r.id
                            JOIN purchase_orders po ON r.po_id = po.id
                            JOIN tablet_types tt ON b.tablet_type_id = tt.id
                            WHERE tt.id = ?
                            AND COALESCE(b.status, 'Available') != 'Closed'
                            AND (r.closed IS NULL OR r.closed = FALSE)
                            AND (po.closed IS NULL OR po.closed = 0)
                            ORDER BY r.received_date DESC
                            LIMIT 20
                        ''', (tablet_type_id,)).fetchall()
                    else:
                        fallback_receives = conn.execute('''
                            SELECT DISTINCT b.id as bag_id,
                                   sb.box_number,
                                   b.bag_number,
                                   b.bag_label_count,
                                   r.id as receive_id,
                                   r.received_date,
                                   r.receive_name as stored_receive_name,
                                   po.po_number,
                                   po.id as po_id,
                                   tt.tablet_type_name
                            FROM bags b
                            JOIN small_boxes sb ON b.small_box_id = sb.id
                            JOIN receiving r ON sb.receiving_id = r.id
                            JOIN purchase_orders po ON r.po_id = po.id
                            JOIN tablet_types tt ON b.tablet_type_id = tt.id
                            WHERE tt.id = ?
                            AND (r.closed IS NULL OR r.closed = FALSE)
                            AND (po.closed IS NULL OR po.closed = 0)
                            ORDER BY r.received_date DESC
                            LIMIT 20
                        ''', (tablet_type_id,)).fetchall()

                    if fallback_receives:
                        receives = []
                        for bag_row in fallback_receives:
                            bag = dict(bag_row)
                            stored_receive_name = bag.get('stored_receive_name')
                            if stored_receive_name:
                                receive_name = stored_receive_name
                            else:
                                receive_number = conn.execute('''
                                    SELECT COUNT(*) + 1
                                    FROM receiving r2
                                    WHERE r2.po_id = ?
                                    AND (r2.received_date < (SELECT received_date FROM receiving WHERE id = ?)
                                         OR (r2.received_date = (SELECT received_date FROM receiving WHERE id = ?)
                                             AND r2.id < ?))
                                ''', (bag['po_id'], bag['receive_id'], bag['receive_id'], bag['receive_id'])).fetchone()[0]
                                receive_name = f"{bag['po_number']}-{receive_number}"

                            receives.append({
                                'bag_id': bag['bag_id'],
                                'receive_id': bag['receive_id'],
                                'receive_name': receive_name,
                                'po_number': bag['po_number'],
                                'received_date': bag['received_date'],
                                'box_number': bag['box_number'],
                                'bag_number': bag['bag_number'],
                                'bag_label_count': bag['bag_label_count'],
                                'tablet_type_name': bag['tablet_type_name']
                            })

                        return jsonify({
                            'success': True,
                            'submission': submission_dict,
                            'possible_receives': receives,
                            'warning': 'Submission missing bag_number. Showing all available receives for this product.'
                        })

                return jsonify({
                    'success': False,
                    'error': 'Submission missing bag_number. Cannot find matching receives. Please check if the bag number was entered when submitting.'
                }), 400

            if not submission_dict.get('tablet_type_id'):
                return jsonify({
                    'success': False,
                    'error': f'Could not determine tablet_type_id for submission. Product: {submission_dict.get("product_name")}, inventory_item_id: {submission_dict.get("inventory_item_id")}'
                }), 400

            # AUTO-ASSIGN: If exactly 1 match and submission is currently unassigned, assign it now
            if len(matching_bags) == 1 and not submission_dict.get('bag_id'):
                bag = matching_bags[0]
                # Use a new connection for the update (db_read_only doesn't allow writes)
                from app.utils.db_utils import db_transaction
                with db_transaction() as write_conn:
                    write_conn.execute('''
                        UPDATE warehouse_submissions
                        SET bag_id = ?, assigned_po_id = ?, needs_review = 0
                        WHERE id = ?
                    ''', (bag['bag_id'], bag.get('po_id'), submission_id))
                    current_app.logger.info(f"Auto-assigned submission {submission_id} to bag {bag['bag_id']} (only 1 match)")

                return jsonify({
                    'success': True,
                    'auto_assigned': True,
                    'submission': submission_dict,
                    'assigned_bag': bag,
                    'message': f"Automatically assigned to {bag['receive_name']} (only matching receive)"
                })

            return jsonify({
                'success': True,
                'submission': submission_dict,
                'possible_receives': matching_bags
            })
    except Exception as e:
        current_app.logger.error(f"Error getting possible receives: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/submission/<int:submission_id>/assign-receive', methods=['POST'])
@employee_required
def assign_submission_to_receive(submission_id):
    """Assign a submission to a specific receive bag"""
    try:
        data = request.get_json()
        with db_transaction() as conn:
            bag_id = data.get('bag_id')

            if not bag_id:
                return jsonify({'success': False, 'error': 'bag_id is required'}), 400

            bag = BagRepository.get_by_id(conn, bag_id)
            if not bag:
                return jsonify({'success': False, 'error': 'Bag not found'}), 404

            submission = conn.execute(
                '''
                SELECT id, receipt_number, employee_name, submission_date
                FROM warehouse_submissions
                WHERE id = ?
                ''',
                (submission_id,),
            ).fetchone()
            if not submission:
                return jsonify({'success': False, 'error': 'Submission not found'}), 404

            submission = dict(submission)
            source_receipt = (submission.get('receipt_number') or '').strip()
            source_submission_date = submission.get('submission_date')

            target_ids = [submission_id]
            if source_receipt and source_submission_date:
                receipt_root = _receipt_family_root(source_receipt) or source_receipt
                siblings = conn.execute(
                    '''
                    SELECT id
                    FROM warehouse_submissions
                    WHERE id != ?
                      AND (
                        receipt_number = ?
                        OR receipt_number = ?
                        OR receipt_number LIKE ?
                        OR receipt_number LIKE ?
                        OR receipt_number LIKE ?
                        OR receipt_number LIKE ?
                      )
                      AND submission_date = ?
                      AND COALESCE(submission_type, 'packaged') != 'repack'
                    ''',
                    (
                        submission_id,
                        source_receipt,
                        receipt_root,
                        receipt_root + '-seal%',
                        receipt_root + '-blister%',
                        receipt_root + '-pkg-e%',
                        receipt_root + '-take-e%',
                        source_submission_date,
                    ),
                ).fetchall()
                target_ids.extend([int(r['id']) for r in siblings])

            placeholders = ','.join(['?'] * len(target_ids))
            conn.execute(
                f'''
                UPDATE warehouse_submissions
                SET bag_id = ?, assigned_po_id = ?, needs_review = FALSE,
                    box_number = ?, bag_number = ?, bag_label_count = COALESCE(?, bag_label_count)
                WHERE id IN ({placeholders})
                ''',
                (
                    bag_id,
                    bag['po_id'],
                    bag.get('box_number'),
                    bag.get('bag_number'),
                    bag.get('bag_label_count'),
                    *target_ids,
                ),
            )

            return jsonify({
                'success': True,
                'message': (
                    'Submission assigned successfully'
                    if len(target_ids) <= 1
                    else f'Assigned {len(target_ids)} submissions from this receipt'
                ),
                'updated_count': len(target_ids)
            })
    except Exception as e:
        current_app.logger.error(f"Error assigning submission to receive: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

