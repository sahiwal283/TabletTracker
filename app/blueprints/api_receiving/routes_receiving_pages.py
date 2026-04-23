"""Receiving and Shipping API routes (subsection)."""

import traceback

from flask import current_app, flash, jsonify, redirect, render_template, request, session, url_for

from app.services.receiving_admin_service import (
    toggle_bag_closed as toggle_bag_closed_service,
)
from app.services.receiving_admin_service import (
    toggle_receiving_closed as toggle_receiving_closed_service,
)
from app.services.receiving_service import (
    get_receiving_with_details,
)
from app.utils.auth_utils import admin_required, role_required
from app.utils.db_utils import db_read_only, db_transaction

from . import bp
from .helpers import normalize_batch_number


@bp.route('/receiving')
@admin_required
def receiving_management():
    """Receiving management page"""
    try:
        with db_read_only() as conn:
            try:
                test_query = conn.execute('SELECT COUNT(*) as count FROM receiving').fetchone()
                test_query['count'] if test_query else 0
            except Exception as e:
                return f"""
                <h2>Database Error</h2>
                <p>Cannot access receiving table: {str(e)}</p>
                <p><a href="/debug/server-info">Check Database</a></p>
                """

            # Get pending shipments (delivered but not yet received)
            pending_shipments = conn.execute('''
                SELECT s.*, po.po_number
                FROM shipments s
                JOIN purchase_orders po ON s.po_id = po.id
                LEFT JOIN receiving r ON s.id = r.shipment_id
                WHERE s.tracking_status = 'Delivered' AND r.id IS NULL
                ORDER BY s.delivered_at DESC, s.created_at DESC
            ''').fetchall()

            # Get recent receiving history
            recent_receiving = conn.execute('''
                SELECT r.*, po.po_number,
                       COUNT(sb.id) as total_boxes,
                       SUM(sb.total_bags) as total_bags
                FROM receiving r
                JOIN purchase_orders po ON r.po_id = po.id
                LEFT JOIN small_boxes sb ON r.id = sb.receiving_id
                GROUP BY r.id
                ORDER BY r.received_date DESC
                LIMIT 20
            ''').fetchall()

            return render_template('receiving_management.html',
                                 pending_shipments=pending_shipments,
                                 recent_receiving=recent_receiving)
    except Exception as e:
        current_app.logger.error(f"Error in receiving_management: {str(e)}")
        return f"""
        <h2>Receiving Page Error</h2>
        <p>Template error: {str(e)}</p>
        <p><a href="/receiving/debug">View debug info</a></p>
        <p><a href="/debug/server-info">Check Server Info</a></p>
        <p><a href="/admin">Back to admin</a></p>
        """


@bp.route('/receiving/<int:receiving_id>')
@admin_required
def receiving_details_view(receiving_id):
    """View detailed information about a specific receiving record"""
    try:
        receiving = get_receiving_with_details(receiving_id)
        if not receiving:
            flash('Receiving record not found', 'error')
            return redirect(url_for('api_receiving.receiving_management'))

        boxes = receiving.get('small_boxes', [])
        return render_template('receiving_details.html',
                             receiving=receiving,
                             boxes=boxes)
    except Exception as e:
        current_app.logger.error(f"Error loading receiving details: {str(e)}")
        flash(f'Error loading receiving details: {str(e)}', 'error')
        return redirect(url_for('api_receiving.receiving_management'))


@bp.route('/api/receiving/<int:receiving_id>', methods=['DELETE'])
@role_required('shipping')
def delete_receiving(receiving_id):
    """Delete a receiving record with verification"""
    try:
        user_role = session.get('employee_role')
        if user_role not in ['manager', 'admin']:
            return jsonify({'success': False, 'error': 'Only managers and admins can delete shipments'}), 403

        with db_transaction() as conn:
            receiving = conn.execute('''
                SELECT r.id, r.po_id, po.po_number, r.received_date, r.received_by
                FROM receiving r
                LEFT JOIN purchase_orders po ON r.po_id = po.id
                WHERE r.id = ?
            ''', (receiving_id,)).fetchone()

            if not receiving:
                return jsonify({'success': False, 'error': 'Receiving record not found'}), 404

            # Delete in correct order due to foreign key constraints
            conn.execute('DELETE FROM bags WHERE small_box_id IN (SELECT id FROM small_boxes WHERE receiving_id = ?)', (receiving_id,))
            conn.execute('DELETE FROM small_boxes WHERE receiving_id = ?', (receiving_id,))
            conn.execute('DELETE FROM receiving WHERE id = ?', (receiving_id,))

            po_info = receiving['po_number'] if receiving['po_number'] else 'No PO'
            return jsonify({
                'success': True,
                'message': f'Successfully deleted shipment (PO: {po_info})'
            })
    except Exception as e:
        current_app.logger.error(f"Error deleting receiving: {str(e)}")
        return jsonify({'success': False, 'error': f'Failed to delete receiving record: {str(e)}'}), 500


@bp.route('/api/receiving/<int:receiving_id>/close', methods=['POST'])
@role_required('dashboard')
def close_receiving_endpoint(receiving_id):
    """Close a receiving record when all bags are physically emptied"""
    try:
        user_role = session.get('employee_role')
        is_admin = session.get('admin_authenticated')
        with db_transaction() as conn:
            result = toggle_receiving_closed_service(conn, receiving_id, user_role, bool(is_admin))
            if not result.get('success'):
                return jsonify({'success': False, 'error': result.get('error', 'Close receive failed')}), result.get('status_code', 400)
            return jsonify(result)
    except Exception as e:
        current_app.logger.error(f"Error closing receiving: {str(e)}")
        return jsonify({'success': False, 'error': f'Failed to close receiving: {str(e)}'}), 500


@bp.route('/api/bag/<int:bag_id>/close', methods=['POST'])
@role_required('dashboard')
def close_bag(bag_id):
    """Close a specific bag when it's physically emptied"""
    try:
        user_role = session.get('employee_role')
        is_admin = session.get('admin_authenticated')
        with db_transaction() as conn:
            result = toggle_bag_closed_service(conn, bag_id, user_role, bool(is_admin))
            if not result.get('success'):
                return jsonify({'success': False, 'error': result.get('error', 'Close bag failed')}), result.get('status_code', 400)
            return jsonify(result)
    except Exception as e:
        current_app.logger.error(f"Error closing bag {bag_id}: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Failed to close bag: {str(e)}'}), 500


@bp.route('/api/bag/<int:bag_id>/batch', methods=['POST'])
@role_required('dashboard')
def update_bag_batch(bag_id):
    """Quick-update bag-specific batch and recompute effective batch/source."""
    try:
        user_role = session.get('employee_role')
        is_admin = session.get('admin_authenticated')
        if user_role not in ['manager', 'admin'] and not is_admin:
            return jsonify({'success': False, 'error': 'Only managers and admins can edit bag batch'}), 403

        data = request.get_json() or {}
        bag_specific_batch_number = normalize_batch_number(data.get('bag_specific_batch_number'))

        with db_transaction() as conn:
            bag_row = conn.execute('''
                SELECT b.id, b.bag_number, b.tablet_type_id, sb.box_number, sb.batch_number_default, sb.receiving_id,
                       tt.tablet_type_name
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                LEFT JOIN tablet_types tt ON b.tablet_type_id = tt.id
                WHERE b.id = ?
            ''', (bag_id,)).fetchone()

            if not bag_row:
                return jsonify({'success': False, 'error': 'Bag not found'}), 404

            bag = dict(bag_row)
            shipment_default_row = conn.execute('''
                SELECT batch_number
                FROM receiving_flavor_batches
                WHERE receiving_id = ? AND tablet_type_id = ?
                LIMIT 1
            ''', (bag['receiving_id'], bag['tablet_type_id'])).fetchone()

            shipment_default_batch = shipment_default_row['batch_number'] if shipment_default_row else None
            box_default_batch = bag.get('batch_number_default')

            effective_batch = None
            batch_source = None
            if bag_specific_batch_number:
                effective_batch = bag_specific_batch_number
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
                'message': 'Bag batch updated successfully.',
                'bag_id': bag_id,
                'bag_number': bag.get('bag_number'),
                'box_number': bag.get('box_number'),
                'tablet_type_name': bag.get('tablet_type_name'),
                'effective_batch_number': effective_batch,
                'effective_batch_source': batch_source
            })
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error updating bag batch for bag {bag_id}: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Failed to update bag batch: {str(e)}'}), 500

