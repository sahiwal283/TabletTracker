"""
Receiving service for business logic related to receiving operations.
"""
from typing import Dict, List, Optional, Any
from app.utils.db_utils import db_read_only, db_transaction, ReceivingRepository, BagRepository


def get_receiving_with_details(receiving_id: int) -> Optional[Dict[str, Any]]:
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
        small_boxes = conn.execute('''
            SELECT * FROM small_boxes WHERE receiving_id = ? ORDER BY box_number
        ''', (receiving_id,)).fetchall()
        receiving_dict['small_boxes'] = [dict(box) for box in small_boxes]
        
        return receiving_dict


def process_receiving_data(data: Dict[str, Any]) -> Dict[str, Any]:
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
    
    return {
        'valid': len(errors) == 0,
        'errors': errors,
        'processed_data': processed_data
    }


def get_available_boxes_bags(po_id: int) -> Dict[str, Any]:
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
                    boxes_dict[box_number] = {
                        'box_number': box_number,
                        'receiving_id': receiving_id,
                        'bags': []
                    }
                boxes_dict[box_number]['bags'].append(bag)
            
            boxes.extend(boxes_dict.values())
            total_bags += len(bags)
        
        return {
            'boxes': boxes,
            'total_boxes': len(boxes),
            'total_bags': total_bags
        }


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
            conn.execute('''
                UPDATE receiving SET closed = TRUE WHERE id = ?
            ''', (receiving_id,))
            
            return True
    except Exception:
        return False

