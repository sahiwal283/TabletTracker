"""
Receiving routes - shipment receiving and tracking
"""
import traceback

from flask import Blueprint, current_app, flash, render_template, session

from app.utils.auth_utils import employee_required, role_required
from app.utils.db_utils import db_read_only

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

            po_columns = [row['name'] for row in conn.execute("PRAGMA table_info(purchase_orders)").fetchall()]
            has_vendor_name = 'vendor_name' in po_columns
            vendor_select = 'vendor_name' if has_vendor_name else "NULL as vendor_name"
            vendor_po_sql = 'po.vendor_name AS vendor_name' if has_vendor_name else "NULL AS vendor_name"

            # Get all OPEN POs for warehouse leads/managers/admins to assign
            # (closed POs can't receive new shipments)
            purchase_orders = []
            if session.get('employee_role') in ['warehouse_lead', 'manager', 'admin'] or session.get('admin_authenticated'):
                po_rows = conn.execute(f'''
                SELECT id, po_number, {vendor_select}, closed, internal_status, zoho_status
                FROM purchase_orders
                WHERE closed = FALSE
                AND COALESCE(internal_status, '') != 'Cancelled'
                ORDER BY po_number DESC
                ''').fetchall()
                purchase_orders = [dict(row) for row in po_rows]

            # Map each PO to the tablet_type IDs that can be received for that PO
            po_tablet_type_ids_by_po = {}
            if purchase_orders:
                po_ids = [po['id'] for po in purchase_orders if po.get('id') is not None]
                if po_ids:
                    placeholders = ','.join('?' * len(po_ids))
                    po_tablet_rows = conn.execute(f'''
                        SELECT DISTINCT pl.po_id, tt.id AS tablet_type_id
                        FROM po_lines pl
                        JOIN tablet_types tt ON tt.inventory_item_id = pl.inventory_item_id
                        WHERE pl.po_id IN ({placeholders})
                        ORDER BY pl.po_id, tt.tablet_type_name
                    ''', tuple(po_ids)).fetchall()
                    for row in po_tablet_rows:
                        po_key = str(row['po_id'])
                        po_tablet_type_ids_by_po.setdefault(po_key, []).append(row['tablet_type_id'])

            # Get all receiving records with their boxes and bags (include status, PO vendor)
            receiving_records = conn.execute(f'''
            SELECT r.*,
                   COUNT(DISTINCT sb.id) as box_count,
                   COUNT(DISTINCT b.id) as total_bags,
                   po.po_number,
                   po.closed as po_closed,
                   {vendor_po_sql},
                   COALESCE(r.status, 'published') as status
            FROM receiving r
            LEFT JOIN small_boxes sb ON r.id = sb.receiving_id
            LEFT JOIN bags b ON sb.id = b.small_box_id
            LEFT JOIN purchase_orders po ON r.po_id = po.id
            GROUP BY r.id
            ORDER BY CASE WHEN COALESCE(r.status, 'published') = 'draft' THEN 0 ELSE 1 END, r.received_date DESC
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
                        _vn = shipment['receiving'].get('vendor_name')
                        if isinstance(_vn, str):
                            _vn = _vn.strip() or None
                        po_groups[po_id] = {
                            'po_number': shipment['receiving']['po_number'],
                            'po_closed': shipment['receiving']['po_closed'],
                            'po_id': po_id,
                            'vendor_name': _vn,
                            'receives': []
                        }
                    po_groups[po_id]['receives'].append(shipment)
                else:
                    shipments_without_po.append(shipment)

            # Sort receives within each PO group (newest first, oldest at bottom)
            for _po_id, po_group in po_groups.items():
                po_group['receives'].sort(key=lambda x: x['receiving']['received_date'], reverse=True)

            # Convert to list and sort by PO number (newest PO first)
            grouped_shipments = [po_groups[po_id] for po_id in sorted(po_groups.keys(),
                                                                        key=lambda pid: po_groups[pid]['po_number'],
                                                                        reverse=True)]

            return render_template('receiving.html',
                                 tablet_types=tablet_types,
                                 categories=categories,
                                 purchase_orders=purchase_orders,
                                 po_tablet_type_ids_by_po=po_tablet_type_ids_by_po,
                                 grouped_shipments=grouped_shipments,
                                 shipments_without_po=shipments_without_po,
                                 user_role=session.get('employee_role'))
    except Exception as e:
        error_details = traceback.format_exc()
        current_app.logger.error(f"Error in shipping_unified: {str(e)}\n{error_details}")
        return render_template('error.html',
                             error_message=f"Error loading shipping page: {str(e)}\n\nFull traceback:\n{error_details}"), 500


@bp.route('/shipments')
@employee_required
def public_shipments():
    """Read-only shipment status — requires employee or admin login."""
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

# Backwards-compatible route alias (deprecated)
@bp.route('/shipping')
@role_required('shipping')
def shipping_unified():
    """DEPRECATED: Use /receiving instead. Redirects for backwards compatibility."""
    import logging
    logging.warning("Route /shipping is deprecated, use /receiving instead")
    return receiving_list()
