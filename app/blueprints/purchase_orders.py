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
def purchase_orders_list():
    """Full purchase orders page showing all POs with filtering"""
    conn = None
    try:
        conn = get_db()
        
        # Get ALL POs with line counts, submission counts, and aggregated counts (matching modal format)
        all_pos = conn.execute('''
            SELECT po.*, 
                   COUNT(DISTINCT pl.id) as line_count,
                   COALESCE(SUM(pl.quantity_ordered), 0) as total_ordered,
                   COALESCE(po.internal_status, 'Active') as status_display,
                   (SELECT COUNT(DISTINCT ws.id) 
                    FROM warehouse_submissions ws 
                    WHERE ws.assigned_po_id = po.id) as submission_count,
                   -- Calculate machine count (aggregated across all line items)
                   -- For machine submissions: use tablets_pressed_into_cards column (fallback to loose_tablets for old data)
                   COALESCE((
                       SELECT SUM(COALESCE(ws.tablets_pressed_into_cards, ws.loose_tablets, 0))
                       FROM warehouse_submissions ws
                       WHERE ws.assigned_po_id = po.id 
                       AND ws.submission_type = 'machine'
                   ), 0) as machine_count,
                   -- Calculate packaged count (aggregated across all line items)
                   COALESCE((
                       SELECT SUM(
                           (COALESCE(ws.displays_made, 0) * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0)) +
                           (COALESCE(ws.packs_remaining, 0) * COALESCE(pd.tablets_per_package, 0)) +
                           COALESCE(ws.loose_tablets, 0)
                       )
                       FROM warehouse_submissions ws
                       LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                       WHERE ws.assigned_po_id = po.id 
                       AND ws.submission_type IN ('packaged', 'bag')
                   ), 0) as packaged_count,
                   -- Calculate received count (from bags)
                   COALESCE((
                       SELECT SUM(b.bag_label_count)
                       FROM bags b
                       JOIN small_boxes sb ON b.small_box_id = sb.id
                       JOIN receiving r ON sb.receiving_id = r.id
                       WHERE r.po_id = po.id
                   ), 0) as received_count
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
    return purchase_orders_list()
