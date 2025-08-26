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

# Additional shipping routes would go here...
# (Create shipment, update tracking, receive packages, etc.)
