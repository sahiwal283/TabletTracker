"""
Shipping and receiving routes
"""

from flask import render_template, request, session, redirect, url_for, flash, jsonify
from . import bp
from ..utils.decorators import role_required
from ..models.database import get_db

@bp.route('/')
@role_required('shipping')
def shipping_unified():
    """Unified shipping and receiving page"""
    try:
        conn = get_db()
        
        # Get POs with shipments for outbound tab
        pos_with_shipments = conn.execute('''
            SELECT po.*, s.tracking_number, s.carrier, s.status as shipment_status,
                   s.estimated_delivery, s.last_checkpoint
            FROM purchase_orders po
            LEFT JOIN shipments s ON po.id = s.po_id
            WHERE po.closed = FALSE
            ORDER BY po.po_number DESC
            LIMIT 50
        ''').fetchall()
        
        # Get pending shipments
        pending_shipments = conn.execute('''
            SELECT s.*, po.po_number
            FROM shipments s
            JOIN purchase_orders po ON s.po_id = po.id
            WHERE s.status != 'Delivered'
            ORDER BY s.created_at DESC
            LIMIT 20
        ''').fetchall()
        
        # Get recent receiving records
        recent_receives = conn.execute('''
            SELECT r.*, po.po_number, s.tracking_number
            FROM receiving r
            JOIN purchase_orders po ON r.po_id = po.id
            LEFT JOIN shipments s ON r.shipment_id = s.id
            ORDER BY r.received_date DESC
            LIMIT 20
        ''').fetchall()
        
        conn.close()
        
        return render_template('shipping_unified.html',
                             pos_with_shipments=pos_with_shipments,
                             pending_shipments=pending_shipments,
                             recent_receives=recent_receives)
                             
    except Exception as e:
        flash(f'Error loading shipping page: {str(e)}', 'error')
        return redirect(url_for('auth.index'))

@bp.route('/receiving')
@role_required('shipping')  
def receiving_management_v2():
    """Enhanced receiving management page"""
    try:
        conn = get_db()
        
        # Get recent receiving records
        recent_receives = conn.execute('''
            SELECT r.*, po.po_number, s.tracking_number, s.carrier
            FROM receiving r
            JOIN purchase_orders po ON r.po_id = po.id
            LEFT JOIN shipments s ON r.shipment_id = s.id
            ORDER BY r.received_date DESC
            LIMIT 50
        ''').fetchall()
        
        # Get pending shipments for receiving
        pending_shipments = conn.execute('''
            SELECT s.*, po.po_number
            FROM shipments s
            JOIN purchase_orders po ON s.po_id = po.id
            WHERE s.status != 'Delivered'
            ORDER BY s.created_at DESC
        ''').fetchall()
        
        conn.close()
        return render_template('receiving_management.html', 
                             recent_receives=recent_receives,
                             pending_shipments=pending_shipments)
        
    except Exception as e:
        flash(f'Error loading receiving page: {str(e)}', 'error')
        return redirect(url_for('auth.index'))

@bp.route('/receiving/<int:receiving_id>')
@role_required('shipping')
def receiving_details(receiving_id):
    """View details of a specific receiving record"""
    try:
        conn = get_db()
        
        # Get receiving record with related data
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
        
        # Get associated boxes and bags
        boxes = conn.execute('''
            SELECT sb.*, COUNT(b.id) as bag_count
            FROM small_boxes sb
            LEFT JOIN bags b ON sb.id = b.small_box_id
            WHERE sb.receiving_id = ?
            GROUP BY sb.id
            ORDER BY sb.box_number
        ''', (receiving_id,)).fetchall()
        
        conn.close()
        return render_template('receiving_details.html', receiving=receiving, boxes=boxes)
        
    except Exception as e:
        flash(f'Error loading receiving details: {str(e)}', 'error')
        return redirect(url_for('shipping.receiving_management_v2'))

@bp.route('/public')
def public_shipments():
    """Read-only shipment status page for staff (no login required)"""
    try:
        conn = get_db()
        
        # Get shipments with basic info only
        shipments = conn.execute('''
            SELECT po.po_number, s.tracking_number, s.carrier, s.status, s.estimated_delivery
            FROM shipments s
            JOIN purchase_orders po ON s.po_id = po.id
            ORDER BY s.created_at DESC
            LIMIT 20
        ''').fetchall()
        
        conn.close()
        return render_template('shipments_public.html', shipments=shipments)
        
    except Exception as e:
        return f"Error loading shipments: {str(e)}", 500

@bp.route('/shipments')
def public_shipments_alt():
    """Alternative route for public shipments"""
    return redirect(url_for('shipping.public_shipments'))
