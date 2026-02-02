"""
Bag matching service for finding bags that match submission criteria.

This service extracts the bag matching logic that was previously
duplicated in blueprint files.
"""
import sqlite3
from typing import Dict, List, Optional, Any, Tuple


def find_matching_bags(
    conn: sqlite3.Connection,
    submission_dict: Dict[str, Any],
    exclude_closed_bags: bool = False
) -> List[Dict[str, Any]]:
    """
    Find all bags that match a submission's criteria.
    
    Matching criteria:
    - tablet_type_id must match
    - bag_number must match
    - box_number must match (if provided, for old-style receives)
    - Receiving must not be closed
    - Bag status must not be 'Closed' (if exclude_closed_bags is True)
    
    Args:
        conn: Database connection object
        submission_dict: Submission dictionary with fields:
            - tablet_type_id (int, optional)
            - inventory_item_id (str, optional) - used to find tablet_type_id if not provided
            - bag_number (int, required)
            - box_number (int, optional) - None for flavor-based receives
        exclude_closed_bags: If True, exclude bags with status 'Closed'
            (typically True for machine count submissions, False for packaging)
    
    Returns:
        List of matching bag dictionaries with fields:
            - bag_id
            - box_number
            - bag_number
            - bag_label_count
            - receive_id
            - received_date
            - stored_receive_name
            - po_number
            - po_id
            - tablet_type_name
    """
    # Get tablet_type_id - try from submission_dict first, then lookup via inventory_item_id
    tablet_type_id = submission_dict.get('tablet_type_id')
    if not tablet_type_id and submission_dict.get('inventory_item_id'):
        tt_row = conn.execute('''
            SELECT id FROM tablet_types WHERE inventory_item_id = ?
        ''', (submission_dict.get('inventory_item_id'),)).fetchone()
        if tt_row:
            tablet_type_id = tt_row['id']
    
    if not tablet_type_id:
        return []
    
    bag_number = submission_dict.get('bag_number')
    if not bag_number:
        return []
    
    # Normalize box_number - empty strings/None become None for flavor-based matching
    box_number_raw = submission_dict.get('box_number')
    box_number = box_number_raw if (box_number_raw and str(box_number_raw).strip()) else None
    
    # Build query based on whether box_number is provided
    if box_number is not None:
        # Old style: match with box number
        if exclude_closed_bags:
            query = '''
                SELECT b.id as bag_id, 
                       sb.box_number, 
                       b.bag_number, 
                       b.bag_label_count,
                       r.id as receive_id,
                       r.received_date,
                       r.receive_name as stored_receive_name,
                       po.po_number,
                       po.id as po_id,
                       tt.tablet_type_name
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN receiving r ON sb.receiving_id = r.id
                JOIN purchase_orders po ON r.po_id = po.id
                JOIN tablet_types tt ON b.tablet_type_id = tt.id
                WHERE b.tablet_type_id = ? 
                AND sb.box_number = ? 
                AND b.bag_number = ?
                AND COALESCE(b.status, 'Available') != 'Closed'
                AND (r.closed IS NULL OR r.closed = FALSE)
                AND (po.closed IS NULL OR po.closed = 0)
                ORDER BY r.received_date DESC
            '''
            params = (tablet_type_id, box_number, bag_number)
        else:
            query = '''
                SELECT b.id as bag_id, 
                       sb.box_number, 
                       b.bag_number, 
                       b.bag_label_count,
                       r.id as receive_id,
                       r.received_date,
                       r.receive_name as stored_receive_name,
                       po.po_number,
                       po.id as po_id,
                       tt.tablet_type_name
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN receiving r ON sb.receiving_id = r.id
                JOIN purchase_orders po ON r.po_id = po.id
                JOIN tablet_types tt ON b.tablet_type_id = tt.id
                WHERE b.tablet_type_id = ? 
                AND sb.box_number = ? 
                AND b.bag_number = ?
                AND (r.closed IS NULL OR r.closed = FALSE)
                AND (po.closed IS NULL OR po.closed = 0)
                ORDER BY r.received_date DESC
            '''
            params = (tablet_type_id, box_number, bag_number)
    else:
        # New flavor-based: match without box number
        if exclude_closed_bags:
            query = '''
                SELECT b.id as bag_id, 
                       sb.box_number, 
                       b.bag_number, 
                       b.bag_label_count,
                       r.id as receive_id,
                       r.received_date,
                       r.receive_name as stored_receive_name,
                       po.po_number,
                       po.id as po_id,
                       tt.tablet_type_name
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN receiving r ON sb.receiving_id = r.id
                JOIN purchase_orders po ON r.po_id = po.id
                JOIN tablet_types tt ON b.tablet_type_id = tt.id
                WHERE b.tablet_type_id = ? 
                AND b.bag_number = ?
                AND COALESCE(b.status, 'Available') != 'Closed'
                AND (r.closed IS NULL OR r.closed = FALSE)
                AND (po.closed IS NULL OR po.closed = 0)
                ORDER BY r.received_date DESC
            '''
            params = (tablet_type_id, bag_number)
        else:
            query = '''
                SELECT b.id as bag_id, 
                       sb.box_number, 
                       b.bag_number, 
                       b.bag_label_count,
                       r.id as receive_id,
                       r.received_date,
                       r.receive_name as stored_receive_name,
                       po.po_number,
                       po.id as po_id,
                       tt.tablet_type_name
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN receiving r ON sb.receiving_id = r.id
                JOIN purchase_orders po ON r.po_id = po.id
                JOIN tablet_types tt ON b.tablet_type_id = tt.id
                WHERE b.tablet_type_id = ? 
                AND b.bag_number = ?
                AND (r.closed IS NULL OR r.closed = FALSE)
                AND (po.closed IS NULL OR po.closed = 0)
                ORDER BY r.received_date DESC
            '''
            params = (tablet_type_id, bag_number)
    
    # Execute query
    matching_bags = conn.execute(query, params).fetchall()
    
    # Convert to list of dicts
    result = []
    for bag_row in matching_bags:
        result.append(dict(bag_row))
    
    return result


def build_receive_name(
    bag: Dict[str, Any],
    conn: sqlite3.Connection
) -> str:
    """
    Build receive name from bag information.
    
    Priority:
    1. Use stored_receive_name from database and append box-bag (e.g., "PO-00164-1-5-3")
    2. Calculate receive_number dynamically and build name (e.g., "PO-00164-1-5-3")
    
    Args:
        bag: Bag dictionary with fields:
            - stored_receive_name (str, optional)
            - box_number (int, optional)
            - bag_number (int, required)
            - po_id (int, required)
            - po_number (str, required)
            - receive_id (int, required)
        conn: Database connection object
    
    Returns:
        Receive name string (e.g., "PO-00164-1-5-3")
    """
    stored_receive_name = bag.get('stored_receive_name')
    box_number = bag.get('box_number')
    bag_number = bag.get('bag_number')
    
    # Priority 1: Use stored receive_name and append box-bag
    if stored_receive_name and box_number is not None and bag_number is not None:
        return f"{stored_receive_name}-{box_number}-{bag_number}"
    
    # Priority 2: Calculate receive_number dynamically (fallback for legacy records)
    po_id = bag.get('po_id')
    receive_id = bag.get('receive_id')
    po_number = bag.get('po_number')
    
    if po_id and receive_id and po_number:
        receive_number_result = conn.execute('''
            SELECT COUNT(*) + 1 as receive_number
            FROM receiving r2
            WHERE r2.po_id = ?
            AND (r2.received_date < (SELECT received_date FROM receiving WHERE id = ?)
                 OR (r2.received_date = (SELECT received_date FROM receiving WHERE id = ?) 
                     AND r2.id < ?))
        ''', (po_id, receive_id, receive_id, receive_id)).fetchone()
        
        receive_number = receive_number_result['receive_number'] if receive_number_result else 1
        
        if box_number is not None and bag_number is not None:
            return f"{po_number}-{receive_number}-{box_number}-{bag_number}"
        else:
            # Flavor-based: no box number
            return f"{po_number}-{receive_number}"
    
    # Fallback: just use what we have
    if bag_number is not None:
        return f"bag-{bag_number}"
    return "unknown"


def find_matching_bags_with_receive_names(
    conn: sqlite3.Connection,
    submission_dict: Dict[str, Any],
    exclude_closed_bags: bool = False
) -> List[Dict[str, Any]]:
    """
    Find matching bags and build receive names for each.
    
    This is a convenience function that combines find_matching_bags
    and build_receive_name.
    
    Args:
        conn: Database connection object
        submission_dict: Submission dictionary (see find_matching_bags)
        exclude_closed_bags: If True, exclude closed bags
    
    Returns:
        List of bag dictionaries with receive_name field added
    """
    matching_bags = find_matching_bags(conn, submission_dict, exclude_closed_bags)
    
    # Add receive_name to each bag
    for bag in matching_bags:
        bag['receive_name'] = build_receive_name(bag, conn)
    
    return matching_bags


def reevaluate_flagged_submissions(conn: sqlite3.Connection) -> int:
    """
    Re-evaluate all submissions flagged for review (needs_review = 1) that are unassigned.
    
    After a PO is closed, some submissions that previously had multiple matches
    may now have only one match. This function auto-assigns those submissions.
    
    Args:
        conn: Database connection object (must support writes)
    
    Returns:
        Number of submissions that were auto-assigned
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Get all flagged, unassigned submissions
    flagged_submissions = conn.execute('''
        SELECT ws.id, ws.inventory_item_id, ws.bag_number, ws.box_number, ws.submission_type, ws.product_name
        FROM warehouse_submissions ws
        WHERE ws.needs_review = 1
        AND ws.bag_id IS NULL
    ''').fetchall()
    
    if not flagged_submissions:
        return 0
    
    auto_assigned_count = 0
    
    for submission in flagged_submissions:
        sub_dict = dict(submission)
        submission_id = sub_dict['id']
        submission_type = sub_dict.get('submission_type', 'packaged')
        exclude_closed_bags = (submission_type != 'packaged')
        
        # Get tablet_type_id from inventory_item_id
        tablet_type_id = None
        if sub_dict.get('inventory_item_id'):
            tt_row = conn.execute('''
                SELECT id FROM tablet_types WHERE inventory_item_id = ?
            ''', (sub_dict['inventory_item_id'],)).fetchone()
            if tt_row:
                tablet_type_id = tt_row['id']
        
        # Fallback: get from product_details
        if not tablet_type_id and sub_dict.get('product_name'):
            pd_row = conn.execute('''
                SELECT tablet_type_id FROM product_details WHERE product_name = ?
            ''', (sub_dict['product_name'],)).fetchone()
            if pd_row:
                tablet_type_id = pd_row['tablet_type_id']
        
        if not tablet_type_id or not sub_dict.get('bag_number'):
            continue
        
        sub_dict['tablet_type_id'] = tablet_type_id
        
        # Find matching bags (will exclude closed POs now)
        matching_bags = find_matching_bags(conn, sub_dict, exclude_closed_bags)
        
        # If exactly 1 match, auto-assign
        if len(matching_bags) == 1:
            bag = matching_bags[0]
            conn.execute('''
                UPDATE warehouse_submissions 
                SET bag_id = ?, assigned_po_id = ?, needs_review = 0
                WHERE id = ?
            ''', (bag['id'], bag.get('po_id'), submission_id))
            
            logger.info(f"Auto-assigned submission {submission_id} to bag {bag['id']} during re-evaluation")
            auto_assigned_count += 1
    
    return auto_assigned_count

