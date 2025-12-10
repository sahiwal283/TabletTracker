"""
Purchase Orders routes
"""
from flask import Blueprint, render_template, flash
import traceback
from app.utils.db_utils import get_db
from app.utils.auth_utils import role_required

bp = Blueprint('purchase_orders', __name__)


@bp.route('/purchase-orders')
@role_required('dashboard')
def all_purchase_orders():
    """Full purchase orders page showing all POs with filtering"""
    conn = None
    try:
        conn = get_db()
        
        # Get ALL POs with line counts and submission counts
        all_pos = conn.execute('''
            SELECT po.*, 
                   COUNT(DISTINCT pl.id) as line_count,
                   COALESCE(SUM(pl.quantity_ordered), 0) as total_ordered,
                   COALESCE(po.internal_status, 'Active') as status_display,
                   (SELECT COUNT(DISTINCT ws.id) 
                    FROM warehouse_submissions ws 
                    WHERE ws.assigned_po_id = po.id) as submission_count
            FROM purchase_orders po
            LEFT JOIN po_lines pl ON po.id = pl.po_id
            GROUP BY po.id
            ORDER BY po.po_number DESC
        ''').fetchall()
        
        # Organize POs: group overs POs under their parents
        organized_pos = []
        overs_pos = {}  # Key: parent_po_number, Value: list of overs POs
        
        # First pass: separate overs POs
        for po in all_pos:
            po_dict = dict(po)
            if po_dict.get('parent_po_number'):
                # This is an overs PO
                parent_num = po_dict['parent_po_number']
                if parent_num not in overs_pos:
                    overs_pos[parent_num] = []
                overs_pos[parent_num].append(po_dict)
            else:
                # Regular PO - will be added in second pass
                pass
        
        # Second pass: add parent POs and their overs
        for po in all_pos:
            po_dict = dict(po)
            if not po_dict.get('parent_po_number'):
                # Add parent PO
                po_dict['is_overs'] = False
                organized_pos.append(po_dict)
                
                # Add any overs POs for this parent
                if po_dict['po_number'] in overs_pos:
                    for overs_po in overs_pos[po_dict['po_number']]:
                        overs_po['is_overs'] = True
                        organized_pos.append(overs_po)
        
        return render_template('purchase_orders.html', purchase_orders=organized_pos)
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ ALL PURCHASE ORDERS ERROR: {str(e)}")
        print(error_trace)
        flash(f'Error loading purchase orders: {str(e)}', 'error')
        return render_template('purchase_orders.html', purchase_orders=[])
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


# Backwards-compatible route alias (deprecated)
@bp.route('/purchase_orders')
@role_required('dashboard')
def purchase_orders_deprecated():
    """DEPRECATED: Use /purchase-orders instead"""
    import logging
    logging.warning("Route /purchase_orders is deprecated, use /purchase-orders instead")
    return all_purchase_orders()
