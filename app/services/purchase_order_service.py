"""
Purchase Order service for business logic related to purchase orders.
"""

from datetime import datetime
from typing import Any

from app.services.zoho_service import zoho_api
from app.utils.db_utils import PurchaseOrderRepository, db_read_only, db_transaction


def get_purchase_order_with_details(po_id: int) -> dict[str, Any] | None:
    """
    Get purchase order with all related details.

    Args:
        po_id: Purchase order ID

    Returns:
        Dictionary with PO details or None if not found
    """
    with db_read_only() as conn:
        po = PurchaseOrderRepository.get_by_id(conn, po_id)
        if not po:
            return None

        po_dict = dict(po)

        # Get line items
        lines = conn.execute(
            '''
            SELECT * FROM po_lines WHERE po_id = ? ORDER BY line_item_name
        ''',
            (po_id,),
        ).fetchall()
        po_dict['lines'] = [dict(line) for line in lines]

        # Get shipment info
        shipment = conn.execute(
            '''
            SELECT * FROM shipments WHERE po_id = ? ORDER BY shipped_date DESC LIMIT 1
        ''',
            (po_id,),
        ).fetchone()
        if shipment:
            po_dict['shipment'] = dict(shipment)

        return po_dict


def calculate_po_totals(po_id: int) -> dict[str, Any]:
    """
    Calculate totals for a purchase order.

    Args:
        po_id: Purchase order ID

    Returns:
        Dictionary with calculated totals:
            - total_ordered
            - total_good
            - total_damaged
            - total_remaining
            - line_totals (list of line item totals)
    """
    with db_read_only() as conn:
        po = PurchaseOrderRepository.get_by_id(conn, po_id)
        if not po:
            return {}

        # Get line items
        lines = conn.execute(
            '''
            SELECT * FROM po_lines WHERE po_id = ?
        ''',
            (po_id,),
        ).fetchall()

        total_ordered = 0
        total_good = 0
        total_damaged = 0
        line_totals = []

        for line in lines:
            line_dict = dict(line)
            ordered = line_dict.get('quantity_ordered', 0) or 0
            good = line_dict.get('good_count', 0) or 0
            damaged = line_dict.get('damaged_count', 0) or 0
            remaining = ordered - good - damaged

            total_ordered += ordered
            total_good += good
            total_damaged += damaged

            line_totals.append(
                {
                    'inventory_item_id': line_dict.get('inventory_item_id'),
                    'line_item_name': line_dict.get('line_item_name'),
                    'ordered': ordered,
                    'good': good,
                    'damaged': damaged,
                    'remaining': remaining,
                }
            )

        return {
            'total_ordered': total_ordered,
            'total_good': total_good,
            'total_damaged': total_damaged,
            'total_remaining': total_ordered - total_good - total_damaged,
            'line_totals': line_totals,
        }


def sync_po_from_zoho(po_id: int | None = None) -> dict[str, Any]:
    """
    Sync purchase orders from Zoho.

    Args:
        po_id: Optional specific PO ID to sync (if None, syncs all)

    Returns:
        Dictionary with sync results:
            - success (bool)
            - message (str)
            - synced_count (int)
    """
    try:
        with db_transaction() as conn:
            success, message = zoho_api.sync_tablet_pos_to_db(conn)

            if success:
                # Count synced POs
                synced_count = conn.execute('''
                    SELECT COUNT(*) as count FROM purchase_orders WHERE zoho_po_id IS NOT NULL
                ''').fetchone()['count']

                return {'success': True, 'message': message, 'synced_count': synced_count}
            else:
                return {'success': False, 'message': message, 'synced_count': 0}
    except Exception as e:
        return {'success': False, 'message': f'Sync failed: {str(e)}', 'synced_count': 0}


def _create_zoho_overs_draft_po(po_data: dict, overs_po_number: str):
    """
    POST a draft PO. If Zoho rejects a custom purchaseorder_number (auto-numbering), retry
    without it and set reference_number to overs_po_number so sync can treat it as ...-OVERS.
    Returns (result_dict_or_none, optional_note_for_ui).
    """
    result = zoho_api.create_purchase_order(po_data)
    if result and 'purchaseorder' in result:
        return result, None
    err_l = str((result or {}).get('message', '')).lower()
    if 'auto-generated' in err_l or 'auto generation' in err_l or 'does not match' in err_l:
        po_auto = {k: v for k, v in po_data.items() if k != 'purchaseorder_number'}
        po_auto['reference_number'] = overs_po_number
        result = zoho_api.create_purchase_order(po_auto)
        if result and 'purchaseorder' in result:
            return result, (f'Zoho uses auto PO numbering; reference is set to "{overs_po_number}" for sync.')
    return result, None


def create_overs_po(parent_po_id: int) -> dict[str, Any]:
    """
    Create an overs PO in Zoho for a parent PO.

    Args:
        parent_po_id: ID of the parent PO

    Returns:
        Dictionary with creation results:
            - success (bool)
            - overs_po_number (str)
            - zoho_po_id (str, optional)
            - total_overs (int)
            - error (str, optional)
    """
    with db_transaction() as conn:
        # Get parent PO details
        parent_po = PurchaseOrderRepository.get_by_id(conn, parent_po_id)
        if not parent_po:
            return {'success': False, 'error': 'Parent PO not found'}

        # Calculate overs (negative remaining_quantity means overs)
        remaining = parent_po.get('remaining_quantity', 0) or 0
        overs_quantity = abs(min(0, remaining))

        if overs_quantity == 0:
            return {'success': False, 'error': 'No overs found for this PO'}

        # Get line items with overs
        lines_with_overs = conn.execute(
            '''
            SELECT pl.*,
                   (pl.quantity_ordered - pl.good_count - pl.damaged_count) as line_remaining
            FROM po_lines pl
            WHERE pl.po_id = ?
            AND (pl.quantity_ordered - pl.good_count - pl.damaged_count) < 0
        ''',
            (parent_po_id,),
        ).fetchall()

        if not lines_with_overs:
            return {'success': False, 'error': 'No line items with overs found'}

        # Generate overs PO number
        overs_po_number = f"{parent_po['po_number']}-OVERS"

        # Get parent PO details from Zoho to use as template
        parent_zoho_po = None
        zoho_po_id = parent_po.get('zoho_po_id')
        if zoho_po_id:
            parent_zoho_po = zoho_api.get_purchase_order_details(zoho_po_id)

        # Build line items for overs PO
        line_items = []
        for line in lines_with_overs:
            line_overs = abs(line['line_remaining'])
            line_items.append(
                {
                    'item_id': line['inventory_item_id'],
                    'name': line['line_item_name'],
                    'quantity': line_overs,
                    'rate': 0,  # Free/overs items typically have $0 rate
                }
            )

        # Build PO data for Zoho
        po_data = {
            'purchaseorder_number': overs_po_number,
            'date': datetime.now().date().isoformat(),
            'line_items': line_items,
            'cf_tablets': True,  # Mark as tablet PO
            'notes': f'Overs PO for {parent_po["po_number"]} - {overs_quantity:,} tablets',
            'status': 'draft',  # Create as draft so it can be reviewed
        }

        # Copy vendor and other details from parent PO if available
        if parent_zoho_po and 'purchaseorder' in parent_zoho_po:
            parent_data = parent_zoho_po['purchaseorder']
            if 'vendor_id' in parent_data:
                po_data['vendor_id'] = parent_data['vendor_id']
            if 'vendor_name' in parent_data:
                po_data['vendor_name'] = parent_data['vendor_name']
            if 'currency_code' in parent_data:
                po_data['currency_code'] = parent_data['currency_code']

        result, note = _create_zoho_overs_draft_po(po_data, overs_po_number)

        if result and 'purchaseorder' in result:
            created_po = result['purchaseorder']
            out = {
                'success': True,
                'overs_po_number': overs_po_number,
                'zoho_po_id': created_po.get('purchaseorder_id'),
                'total_overs': overs_quantity,
            }
            if note:
                out['zoho_note'] = note
            return out
        error_msg = result.get('message', 'Unknown error') if result else 'No response from Zoho API'
        return {'success': False, 'error': f'Failed to create PO in Zoho: {error_msg}'}


def _zoho_line_items_for_overs_put(
    purchaseorder: dict,
    inventory_item_id: str,
    line_item_name: str,
    quantity_to_add: int,
) -> list[dict]:
    """Build line_items array for PUT: bump quantity on matching item_id or append a line."""
    inv = str(inventory_item_id)
    lines_out: list[dict] = []
    found = False
    for li in purchaseorder.get('line_items') or []:
        item_id = str(li.get('item_id') or '')
        qty = int(round(float(li.get('quantity') or 0)))
        rate = float(li.get('rate') or 0)
        if item_id == inv:
            qty = qty + quantity_to_add
            found = True
        entry = {
            'line_item_id': li.get('line_item_id'),
            'item_id': item_id,
            'name': li.get('name') or line_item_name,
            'quantity': qty,
            'rate': rate,
        }
        lines_out.append(entry)
    if not found:
        lines_out.append(
            {
                'item_id': inv,
                'name': line_item_name,
                'quantity': quantity_to_add,
                'rate': 0,
            }
        )
    return lines_out


def _apply_overs_po_draft_update(
    overs_zoho_id: str,
    overs_po_number: str,
    inventory_item_id: str,
    line_item_name: str,
    overage_tablets: int,
    parent_data: dict,
) -> dict[str, Any]:
    """Increment overs draft PO line quantity (or add line) via Zoho PUT."""
    det = zoho_api.get_purchase_order_details(overs_zoho_id)
    if not det or 'purchaseorder' not in det:
        return {'success': False, 'error': 'Could not load overs PO from Zoho'}
    pur = det['purchaseorder']
    new_lines = _zoho_line_items_for_overs_put(pur, inventory_item_id, line_item_name, overage_tablets)
    prev_note = (pur.get('notes') or '').strip()
    add_note = f'Overs from TabletTracker Zoho push: +{overage_tablets:,} tablets for {line_item_name}'
    merged_notes = f"{prev_note}\n{add_note}".strip() if prev_note else add_note
    po_body = {
        'purchaseorder_number': pur.get('purchaseorder_number') or overs_po_number,
        'date': pur.get('date') or datetime.now().date().isoformat(),
        'vendor_id': pur.get('vendor_id') or parent_data.get('vendor_id'),
        'vendor_name': pur.get('vendor_name') or parent_data.get('vendor_name'),
        'line_items': new_lines,
        'notes': merged_notes,
        'status': 'draft',
        'cf_tablets': True,
    }
    if parent_data.get('currency_code'):
        po_body['currency_code'] = parent_data['currency_code']
    result = zoho_api.update_purchase_order(overs_zoho_id, po_body)
    if result and result.get('purchaseorder'):
        return {
            'success': True,
            'overs_po_number': overs_po_number,
            'zoho_po_id': overs_zoho_id,
            'action': 'updated',
            'total_overs_added': overage_tablets,
        }
    err = (result or {}).get('message', 'Unknown error') if result else 'No response from Zoho API'
    return {'success': False, 'error': f'Failed to update overs PO in Zoho: {err}'}


def create_or_update_overs_po_for_push(
    parent_po_id: int,
    overage_tablets: int,
    inventory_item_id: str,
    line_item_name: str,
) -> dict[str, Any]:
    """
    Create a draft overs PO in Zoho or add quantity to an existing draft overs PO line,
    using Zoho-computed overage from a failed push (not local negative remaining).

    Overs PO number: {parent_po_number}-OVERS
    """
    if overage_tablets <= 0:
        return {'success': False, 'error': 'overage_tablets must be a positive integer'}
    if not inventory_item_id:
        return {'success': False, 'error': 'inventory_item_id is required'}

    with db_read_only() as conn:
        parent = PurchaseOrderRepository.get_by_id(conn, parent_po_id)
        if not parent:
            return {'success': False, 'error': 'Parent PO not found'}
        parent = dict(parent)
        parent_po_number = parent.get('po_number') or ''
        parent_zoho_id = parent.get('zoho_po_id')
        if not parent_zoho_id:
            return {'success': False, 'error': 'Parent PO has no Zoho PO ID. Sync POs from Zoho first.'}

        overs_po_number = f"{parent_po_number}-OVERS"
        overs_row = conn.execute(
            '''
            SELECT id, zoho_po_id, po_number
            FROM purchase_orders
            WHERE po_number = ?
            ''',
            (overs_po_number,),
        ).fetchone()

    overs_zoho_id = None
    if overs_row:
        overs_zoho_id = dict(overs_row).get('zoho_po_id')
    if not overs_zoho_id:
        overs_zoho_id = zoho_api.find_purchase_order_id_by_number(
            overs_po_number
        ) or zoho_api.find_purchase_order_id_by_reference(overs_po_number)

    parent_zoho_po = zoho_api.get_purchase_order_details(parent_zoho_id)
    if not parent_zoho_po or 'purchaseorder' not in parent_zoho_po:
        return {'success': False, 'error': 'Could not load parent PO from Zoho'}

    parent_data = parent_zoho_po['purchaseorder']

    if overs_zoho_id:
        return _apply_overs_po_draft_update(
            str(overs_zoho_id),
            overs_po_number,
            inventory_item_id,
            line_item_name,
            overage_tablets,
            parent_data,
        )

    line_items = [
        {
            'item_id': inventory_item_id,
            'name': line_item_name,
            'quantity': overage_tablets,
            'rate': 0,
        }
    ]
    po_data = {
        'purchaseorder_number': overs_po_number,
        'date': datetime.now().date().isoformat(),
        'line_items': line_items,
        'cf_tablets': True,
        'notes': f'Overs PO for {parent_po_number} — TabletTracker push: {overage_tablets:,} tablets ({line_item_name})',
        'status': 'draft',
    }
    if 'vendor_id' in parent_data:
        po_data['vendor_id'] = parent_data['vendor_id']
    if 'vendor_name' in parent_data:
        po_data['vendor_name'] = parent_data['vendor_name']
    if 'currency_code' in parent_data:
        po_data['currency_code'] = parent_data['currency_code']

    result, auto_note = _create_zoho_overs_draft_po(po_data, overs_po_number)
    if result and 'purchaseorder' in result:
        created = result['purchaseorder']
        out = {
            'success': True,
            'overs_po_number': overs_po_number,
            'zoho_po_id': created.get('purchaseorder_id'),
            'action': 'created',
            'total_overs_added': overage_tablets,
        }
        if auto_note:
            out['zoho_note'] = auto_note
        return out
    err = result.get('message', 'Unknown error') if result else 'No response from Zoho API'

    alt_id = zoho_api.find_purchase_order_id_by_number(overs_po_number) or zoho_api.find_purchase_order_id_by_reference(
        overs_po_number
    )
    if alt_id:
        return _apply_overs_po_draft_update(
            str(alt_id),
            overs_po_number,
            inventory_item_id,
            line_item_name,
            overage_tablets,
            parent_data,
        )
    return {'success': False, 'error': f'Failed to create overs PO in Zoho: {err}'}


def get_overs_po_preview(parent_po_id: int) -> dict[str, Any]:
    """
    Build preview information for creating an overs PO.
    """
    with db_read_only() as conn:
        parent_po = conn.execute(
            '''
            SELECT po_number, tablet_type, ordered_quantity, current_good_count,
                   current_damaged_count, remaining_quantity
            FROM purchase_orders
            WHERE id = ?
            ''',
            (parent_po_id,),
        ).fetchone()
        if not parent_po:
            return {'success': False, 'error': 'Parent PO not found'}

        overs_quantity = abs(min(0, parent_po['remaining_quantity']))
        lines_with_overs = conn.execute(
            '''
            SELECT pl.*,
                   (pl.quantity_ordered - pl.good_count - pl.damaged_count) as line_remaining
            FROM po_lines pl
            WHERE pl.po_id = ?
            AND (pl.quantity_ordered - pl.good_count - pl.damaged_count) < 0
            ''',
            (parent_po_id,),
        ).fetchall()

        overs_line_items = []
        for line in lines_with_overs:
            line_overs = abs(line['line_remaining'])
            overs_line_items.append(
                {
                    'inventory_item_id': line['inventory_item_id'],
                    'line_item_name': line['line_item_name'],
                    'overs_quantity': line_overs,
                    'original_ordered': line['quantity_ordered'],
                }
            )

        return {
            'success': True,
            'parent_po_number': parent_po['po_number'],
            'overs_po_number': f"{parent_po['po_number']}-OVERS",
            'tablet_type': parent_po['tablet_type'],
            'total_overs': overs_quantity,
            'line_items': overs_line_items,
            'instructions': 'Click "Create in Zoho" to automatically create this overs PO in Zoho, or copy details to create manually.',
        }
