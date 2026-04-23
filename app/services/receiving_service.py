"""
Receiving service for business logic related to receiving operations.
"""

from collections.abc import Sequence
from typing import Any

from app.utils.db_utils import BagRepository, ReceivingRepository, db_read_only, db_transaction


def get_receiving_with_details(receiving_id: int) -> dict[str, Any] | None:
    """
    Get receiving with all related details.

    Args:
        receiving_id: Receiving ID

    Returns:
        Dictionary with receiving details or None if not found
    """
    with db_read_only() as conn:
        receiving = ReceivingRepository.get_by_id(conn, receiving_id)
        if not receiving:
            return None

        receiving_dict = dict(receiving)

        # Get all bags for this receiving
        bags = BagRepository.get_by_receiving_id(conn, receiving_id)
        receiving_dict['bags'] = bags

        # Get small boxes
        small_boxes = conn.execute(
            '''
            SELECT * FROM small_boxes WHERE receiving_id = ? ORDER BY box_number
        ''',
            (receiving_id,),
        ).fetchall()
        receiving_dict['small_boxes'] = [dict(box) for box in small_boxes]

        return receiving_dict


def process_receiving_data(data: dict[str, Any]) -> dict[str, Any]:
    """
    Process receiving data and validate it.

    Args:
        data: Receiving data dictionary with fields:
            - po_id (int, required)
            - received_date (str, optional)
            - total_small_boxes (int, optional)
            - received_by (str, optional)
            - notes (str, optional)
            - boxes (list, optional) - list of box data

    Returns:
        Dictionary with processed data and validation results:
            - valid (bool)
            - errors (list of str)
            - processed_data (dict)
    """
    errors = []
    processed_data = {}

    # Validate required fields
    if 'po_id' not in data or not data['po_id']:
        errors.append('PO ID is required')
    else:
        processed_data['po_id'] = int(data['po_id'])

    # Process optional fields
    if 'received_date' in data:
        processed_data['received_date'] = data['received_date']

    if 'total_small_boxes' in data:
        processed_data['total_small_boxes'] = int(data['total_small_boxes']) if data['total_small_boxes'] else 0

    if 'received_by' in data:
        processed_data['received_by'] = data['received_by'].strip() if data['received_by'] else None

    if 'notes' in data:
        processed_data['notes'] = data['notes'].strip() if data['notes'] else None

    # Process boxes if provided
    if 'boxes' in data and isinstance(data['boxes'], list):
        processed_data['boxes'] = data['boxes']

    return {'valid': len(errors) == 0, 'errors': errors, 'processed_data': processed_data}


def get_available_boxes_bags(po_id: int) -> dict[str, Any]:
    """
    Get available boxes and bags for a purchase order.

    Args:
        po_id: Purchase order ID

    Returns:
        Dictionary with available boxes and bags:
            - boxes (list of box dictionaries)
            - total_boxes (int)
            - total_bags (int)
    """
    with db_read_only() as conn:
        # Get all receivings for this PO
        receivings = ReceivingRepository.get_by_po_id(conn, po_id)

        boxes = []
        total_bags = 0

        for receiving in receivings:
            receiving_id = receiving['id']
            bags = BagRepository.get_by_receiving_id(conn, receiving_id)

            # Group bags by box
            boxes_dict = {}
            for bag in bags:
                box_number = bag.get('box_number')
                if box_number not in boxes_dict:
                    boxes_dict[box_number] = {'box_number': box_number, 'receiving_id': receiving_id, 'bags': []}
                boxes_dict[box_number]['bags'].append(bag)

            boxes.extend(boxes_dict.values())
            total_bags += len(bags)

        return {'boxes': boxes, 'total_boxes': len(boxes), 'total_bags': total_bags}


def close_receiving(receiving_id: int) -> bool:
    """
    Close a receiving (mark as closed).

    Args:
        receiving_id: Receiving ID

    Returns:
        True if successful, False otherwise
    """
    try:
        with db_transaction() as conn:
            # Check if receiving exists
            receiving = ReceivingRepository.get_by_id(conn, receiving_id)
            if not receiving:
                return False

            # Update receiving to closed
            conn.execute(
                '''
                UPDATE receiving SET closed = TRUE WHERE id = ?
            ''',
                (receiving_id,),
            )

            return True
    except Exception:
        return False


def get_bag_with_packaged_count(bag_id: int) -> dict[str, Any] | None:
    """
    Get bag details including calculated packaged_count from submissions.

    Args:
        bag_id: Bag ID

    Returns:
        Dictionary with bag details including packaged_count, or None if not found
    """
    with db_read_only() as conn:
        # Get bag with related info, including zoho_line_item_id from po_lines
        bag_row = conn.execute(
            '''
            SELECT b.*,
                   sb.box_number,
                   sb.receiving_id,
                   r.po_id,
                   r.receive_name,
                   r.received_date,
                   po.po_number,
                   po.zoho_po_id,
                   po.vendor_name,
                   po.closed AS po_closed,
                   tt.tablet_type_name,
                   tt.inventory_item_id,
                   pl.zoho_line_item_id
            FROM bags b
            JOIN small_boxes sb ON b.small_box_id = sb.id
            JOIN receiving r ON sb.receiving_id = r.id
            JOIN purchase_orders po ON r.po_id = po.id
            LEFT JOIN tablet_types tt ON b.tablet_type_id = tt.id
            LEFT JOIN po_lines pl ON pl.po_id = po.id AND pl.inventory_item_id = tt.inventory_item_id
            WHERE b.id = ?
        ''',
            (bag_id,),
        ).fetchone()

        if not bag_row:
            return None

        bag = dict(bag_row)

        # If receive_name is missing, compute it from PO number and receive sequence
        if not bag.get('receive_name') and bag.get('po_number') and bag.get('receiving_id'):
            # Count how many receives exist for this PO before this one (inclusive)
            receive_number_row = conn.execute(
                '''
                SELECT COUNT(*) as receive_number
                FROM receiving r2
                WHERE r2.po_id = ?
                AND r2.id <= ?
            ''',
                (bag['po_id'], bag['receiving_id']),
            ).fetchone()

            receive_number = receive_number_row['receive_number'] if receive_number_row else 1
            bag['receive_name'] = f"{bag['po_number']}-{receive_number}"

        # Calculate packaged_count from ALL submission types
        # Packaged submissions (card products)
        packaged_count_row = conn.execute(
            '''
            SELECT COALESCE(SUM(
                (COALESCE(ws.displays_made, 0) * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0)) +
                (COALESCE(ws.packs_remaining, 0) * COALESCE(pd.tablets_per_package, 0)) +
                COALESCE(ws.loose_tablets, 0)
            ), 0) as total_packaged
            FROM warehouse_submissions ws
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
            WHERE ws.bag_id = ?
            AND ws.submission_type = 'packaged'
        ''',
            (bag_id,),
        ).fetchone()

        # Bottle submissions (bottle-only products with bag_id)
        bottle_direct_row = conn.execute(
            '''
            SELECT COALESCE(SUM(
                COALESCE(ws.bottles_made, 0) * COALESCE(pd.tablets_per_bottle, 0)
            ), 0) as total_bottle
            FROM warehouse_submissions ws
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
            WHERE ws.submission_type = 'bottle' AND ws.bag_id = ?
        ''',
            (bag_id,),
        ).fetchone()

        # Variety pack deductions via junction table
        bottle_junction_row = conn.execute(
            '''
            SELECT COALESCE(SUM(sbd.tablets_deducted), 0) as total_junction
            FROM submission_bag_deductions sbd
            WHERE sbd.bag_id = ?
        ''',
            (bag_id,),
        ).fetchone()

        # Total packaged = packaged + bottles + variety pack deductions
        bag['packaged_count'] = (
            (packaged_count_row['total_packaged'] if packaged_count_row else 0)
            + (bottle_direct_row['total_bottle'] if bottle_direct_row else 0)
            + (bottle_junction_row['total_junction'] if bottle_junction_row else 0)
        )

        return bag


def get_packaged_counts_for_bag_ids(conn, bag_ids: Sequence[int]) -> dict[int, int]:
    """
    Batch packaged tablet totals per bag, matching get_bag_with_packaged_count
    (packaged + bottle + variety-pack deductions).
    """
    ids = [int(b) for b in bag_ids if b is not None]
    if not ids:
        return {}
    placeholders = ','.join('?' * len(ids))
    rows = conn.execute(
        f'''
        SELECT b.id AS bag_id,
               (
                 COALESCE((
                   SELECT SUM(
                     (COALESCE(ws.displays_made, 0) * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0)) +
                     (COALESCE(ws.packs_remaining, 0) * COALESCE(pd.tablets_per_package, 0)) +
                     COALESCE(ws.loose_tablets, 0)
                   )
                   FROM warehouse_submissions ws
                   LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                   WHERE ws.bag_id = b.id AND ws.submission_type = 'packaged'
                 ), 0) +
                 COALESCE((
                   SELECT SUM(COALESCE(ws.bottles_made, 0) * COALESCE(pd.tablets_per_bottle, 0))
                   FROM warehouse_submissions ws
                   LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                   WHERE ws.submission_type = 'bottle' AND ws.bag_id = b.id
                 ), 0) +
                 COALESCE((
                   SELECT SUM(sbd.tablets_deducted)
                   FROM submission_bag_deductions sbd
                   WHERE sbd.bag_id = b.id
                 ), 0)
               ) AS packaged_count
        FROM bags b
        WHERE b.id IN ({placeholders})
        ''',
        tuple(ids),
    ).fetchall()
    out: dict[int, int] = {}
    for row in rows:
        d = dict(row)
        out[int(d['bag_id'])] = int(d['packaged_count'] or 0)
    return out


def extract_shipment_number(receive_name: str | None) -> str:
    """
    Extract the shipment number from a receive_name.

    Receive name formats:
    - "PO-00162-3" -> shipment number is "3"
    - "PO-00162-3-1-1" -> shipment number is "3" (the first number after PO number)

    Args:
        receive_name: The receive_name string (e.g., "PO-00162-3")

    Returns:
        The shipment number as a string, or "1" if cannot be parsed
    """
    if not receive_name:
        return "1"

    # Split by hyphen
    parts = receive_name.split('-')

    # Format is typically: PO-XXXXX-N or PO-XXXXX-N-box-bag
    # We need to find the shipment number which comes after the PO number

    if len(parts) >= 3:
        # Try to find the shipment number
        # PO-00162-3 -> parts = ['PO', '00162', '3']
        # PO-00162-3-1-1 -> parts = ['PO', '00162', '3', '1', '1']

        # The shipment number is typically the 3rd part (index 2)
        try:
            shipment_num = int(parts[2])
            return str(shipment_num)
        except (ValueError, IndexError):
            pass

    # Fallback: try to get the last numeric part before any box/bag numbers
    # This handles edge cases
    return "1"


def build_zoho_receive_notes(
    shipment_number: str,
    box_number: int,
    bag_number: int,
    bag_label_count: int,
    packaged_count: int,
    batch_number: str | None = None,
    batch_source: str | None = None,
    custom_notes: str | None = None,
    split_main_qty: int | None = None,
    split_overs_qty: int | None = None,
    split_receive_role: str | None = None,
) -> str:
    """
    Build the notes string for a Zoho purchase receive.

    Format:
    Shipment 3 - Box 1, Bag 1:
    bag label: 20000 || packaged: 19760

    [custom notes if provided]

    Args:
        shipment_number: The shipment number
        box_number: The box number
        bag_number: The bag number
        bag_label_count: Count from bag label
        packaged_count: Calculated packaged count
        batch_number: Effective batch used for this bag
        batch_source: Batch source label (shipment default, box default, bag specific)
        custom_notes: Optional additional notes
        split_main_qty: If set with split_overs_qty, append bag-split explanation (main PO tablets)
        split_overs_qty: Overs PO tablet portion for a split receive
        split_receive_role: 'main' or 'overs' — which receive this note is for

    Returns:
        Formatted notes string
    """
    # Build notes with proper line breaks
    # Note: Using double newlines for better visibility in Zoho
    notes = f"Shipment {shipment_number} - Box {box_number}, Bag {bag_number}:"
    notes += f"\n\nbag label: {bag_label_count:,} || packaged: {packaged_count:,}"

    if batch_number:
        source_label = (batch_source or 'unknown').replace('_', ' ').strip()
        notes += f"\n\nbatch: {batch_number} || source: {source_label}"

    if custom_notes and custom_notes.strip():
        notes += f"\n\n{custom_notes.strip()}"

    if split_main_qty is not None and split_overs_qty is not None:
        notes += (
            "\n\nBAG SPLIT — PO line capacity / overs:"
            f"\n• Main PO portion: {split_main_qty:,} tablets"
            f"\n• Overs PO portion: {split_overs_qty:,} tablets"
        )
        if split_receive_role == 'main':
            notes += f"\n(This purchase receive is the {split_main_qty:,} tablets on the main PO line.)"
        elif split_receive_role == 'overs':
            notes += f"\n(This purchase receive is the {split_overs_qty:,} tablets on the overs PO line.)"

    return notes
