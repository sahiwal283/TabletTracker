"""
Receiving routes - shipment receiving and tracking
"""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session, current_app
import traceback
from app.utils.db_utils import db_read_only, db_transaction
from app.utils.auth_utils import admin_required, role_required

bp = Blueprint('receiving', __name__)


@bp.route('/receiving')
@role_required('shipping')
def receiving_list():
    """Receiving page - record shipments that arrive"""
    try:
        with db_read_only() as conn:
            # Get all tablet types for the form dropdown
            tablet_types_rows = conn.execute('''
            SELECT id, tablet_type_name, category
            FROM tablet_types 
            ORDER BY tablet_type_name
            ''').fetchall()
            tablet_types = [dict(row) for row in tablet_types_rows]
        
        # Get unique categories for dropdown grouping
            categories = sorted(list(set(tt['category'] for tt in tablet_types if tt.get('category'))))
        
        # Get all OPEN POs for managers/admin to assign (closed POs can't receive new shipments)
            purchase_orders = []
            if session.get('employee_role') in ['manager', 'admin'] or session.get('admin_authenticated'):
                po_rows = conn.execute('''
                SELECT id, po_number, closed, internal_status, zoho_status
                FROM purchase_orders
                WHERE closed = FALSE
                AND COALESCE(internal_status, '') != 'Cancelled'
                ORDER BY po_number DESC
            ''').fetchall()
            purchase_orders = [dict(row) for row in po_rows]
        
        # Get all receiving records with their boxes and bags
            receiving_records = conn.execute('''
            SELECT r.*, 
                   COUNT(DISTINCT sb.id) as box_count,
                   COUNT(DISTINCT b.id) as total_bags,
                   po.po_number,
                   po.closed as po_closed
            FROM receiving r
            LEFT JOIN small_boxes sb ON r.id = sb.receiving_id
            LEFT JOIN bags b ON sb.id = b.small_box_id
            LEFT JOIN purchase_orders po ON r.po_id = po.id
            GROUP BY r.id
            ORDER BY r.received_date DESC
            ''').fetchall()
        
        # Calculate shipment numbers for each PO (numbered sequentially by received_date)
        # Group shipments by PO and assign numbers
            po_shipment_counts = {}
            for rec in receiving_records:
                po_id = rec['po_id']
            if po_id:
                if po_id not in po_shipment_counts:
                    # Get all shipments for this PO ordered by received_date
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
            # Add shipment number if PO is assigned
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
            
            # Get bags for each box with tablet type info
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
        
        # NEW: Group shipments by PO for better organization
        # Group by PO and sort receives within each PO (oldest first = bottom when reversed for display)
        po_groups = {}
        shipments_without_po = []
        
        for shipment in shipments:
            po_id = shipment['receiving']['po_id']
            if po_id:
                if po_id not in po_groups:
                    po_groups[po_id] = {
                        'po_number': shipment['receiving']['po_number'],
                        'po_closed': shipment['receiving']['po_closed'],
                        'po_id': po_id,
                        'receives': []
                    }
                po_groups[po_id]['receives'].append(shipment)
            else:
                shipments_without_po.append(shipment)
        
        # Sort receives within each PO group (newest first, oldest at bottom)
        for po_id, po_group in po_groups.items():
            po_group['receives'].sort(key=lambda x: x['receiving']['received_date'], reverse=True)
        
        # Convert to list and sort by PO number (newest PO first)
        grouped_shipments = [po_groups[po_id] for po_id in sorted(po_groups.keys(), 
                                                                    key=lambda pid: po_groups[pid]['po_number'], 
                                                                    reverse=True)]
        
        return render_template('receiving.html', 
                             tablet_types=tablet_types,
                             categories=categories,
                             purchase_orders=purchase_orders,
                             grouped_shipments=grouped_shipments,
                                 shipments_without_po=shipments_without_po,
                                 user_role=session.get('employee_role'))
    except Exception as e:
        error_details = traceback.format_exc()
        current_app.logger.error(f"Error in shipping_unified: {str(e)}\n{error_details}")
        return render_template('error.html', 
                             error_message=f"Error loading shipping page: {str(e)}\n\nFull traceback:\n{error_details}"), 500


@bp.route('/receiving')
@admin_required  
def receiving_management_v2():
    """Receiving management page - REBUILT VERSION"""
    try:
        with db_read_only() as conn:
        
        # Simple query first - just check if we can access receiving table
            try:
                test_query = conn.execute('SELECT COUNT(*) as count FROM receiving').fetchone()
                receiving_count = test_query['count'] if test_query else 0
            except Exception as e:
                return f"""
                <h2>Database Error (v1.7.6 REBUILT)</h2>
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
        # If template fails, return simple HTML with version
            return f"""
            <h2>Receiving Page Error (v1.7.6 REBUILT)</h2>
            <p>Template error: {str(e)}</p>
            <p><a href="/receiving/debug">View debug info</a></p>
            <p><a href="/debug/server-info">Check Server Info</a></p>
            <p><a href="/admin">Back to admin</a></p>
            """


@bp.route('/shipments')
def public_shipments():
    """Read-only shipment status page for staff (no login required)."""
    try:
        with db_read_only() as conn:
            rows = conn.execute('''
            SELECT po.po_number, s.id as shipment_id, s.tracking_number, s.carrier, s.tracking_status,
                   s.estimated_delivery, s.last_checkpoint, s.actual_delivery, s.updated_at
            FROM shipments s
            JOIN purchase_orders po ON po.id = s.po_id
            ORDER BY s.updated_at DESC
            LIMIT 200
            ''').fetchall()
            return render_template('shipments_public.html', shipments=rows)
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        current_app.logger.error(f"❌ Error loading public shipments: {str(e)}")
        current_app.logger.error(f"Traceback: {error_trace}")
        flash('Failed to load shipments. Please try again later.', 'error')
        return render_template('shipments_public.html', shipments=[])



@bp.route('/receiving/debug')
@admin_required
def receiving_debug():
    """Debug route to test receiving functionality"""
    try:
        with db_read_only() as conn:
        
        # Test database connections
            po_count = conn.execute('SELECT COUNT(*) as count FROM purchase_orders').fetchone()
            shipment_count = conn.execute('SELECT COUNT(*) as count FROM shipments').fetchone()
            receiving_count = conn.execute('SELECT COUNT(*) as count FROM receiving').fetchone()
        
        # Test the actual query
            pending_shipments = conn.execute('''
            SELECT s.*, po.po_number
            FROM shipments s
            JOIN purchase_orders po ON s.po_id = po.id
            LEFT JOIN receiving r ON s.id = r.shipment_id
            WHERE s.tracking_status = 'Delivered' AND r.id IS NULL
            ORDER BY s.delivered_at DESC, s.created_at DESC
            ''').fetchall()
        
            debug_info = {
            'status': 'success',
            'database_counts': {
                'purchase_orders': po_count['count'] if po_count else 0,
                'shipments': shipment_count['count'] if shipment_count else 0,
                'receiving': receiving_count['count'] if receiving_count else 0
            },
            'pending_shipments': len(pending_shipments),
            'template_exists': 'receiving_management.html exists',
            'version': '1.7.1'
            }
        
            return f"""
            <h2>Receiving Debug Info (v1.7.1)</h2>
            <pre>{debug_info}</pre>
            <p><a href="/receiving">Go to actual receiving page</a></p>
            """
    except Exception as e:
        return f"""
        <h2>Receiving Debug Error</h2>
        <p>Error: {str(e)}</p>
        <p><a href="/receiving">Try receiving page anyway</a></p>
        """



@bp.route('/receiving/<int:receiving_id>')
@admin_required
def receiving_details(receiving_id):
    """View detailed information about a specific receiving record"""
    try:
        with db_read_only() as conn:
        
        # Get receiving record with PO and shipment info
            receiving = conn.execute('''
            SELECT r.*, po.po_number, s.tracking_number, s.carrier
            FROM receiving r
            JOIN purchase_orders po ON r.po_id = po.id
            LEFT JOIN shipments s ON r.shipment_id = s.id
            WHERE r.id = ?
            ''', (receiving_id,)).fetchone()
        
            if not receiving:
                flash('Receiving record not found', 'error')
            return redirect(url_for('shipping.receiving_management_v2'))
        
        # Get box and bag details
            boxes = conn.execute('''
            SELECT sb.*, 
                   GROUP_CONCAT(b.bag_number) as bag_numbers, 
                   COUNT(b.id) as bag_count,
                   GROUP_CONCAT('Bag ' || b.bag_number || ': ' || COALESCE(b.pill_count, 'N/A') || ' pills') as pill_counts
            FROM small_boxes sb
            LEFT JOIN bags b ON sb.id = b.small_box_id
            WHERE sb.receiving_id = ?
            GROUP BY sb.id
            ORDER BY sb.box_number
            ''', (receiving_id,)).fetchall()
        
            return render_template('receiving_details.html', 
                                 receiving=dict(receiving),
                                 boxes=[dict(box) for box in boxes])
    except Exception as e:
        flash(f'Error loading receiving details: {str(e)}', 'error')
        return redirect(url_for('receiving.receiving_management_v2'))


# Backwards-compatible route alias (deprecated)
@bp.route('/shipping')
@role_required('shipping')
def shipping_unified():
    """DEPRECATED: Use /receiving instead. Redirects for backwards compatibility."""
    import logging
    logging.warning("Route /shipping is deprecated, use /receiving instead")
    return receiving_list()
