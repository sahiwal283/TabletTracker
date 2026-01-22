"""
Receive-based tracking utilities for matching submissions to receives/bags
"""
import sqlite3
from typing import Optional, Tuple, Dict, Any

def find_bag_for_submission(
    conn: sqlite3.Connection,
    tablet_type_id: int,
    bag_number: int,
    box_number: Optional[int] = None,
    submission_type: str = 'packaged'
) -> Tuple[Optional[Dict[str, Any]], bool, Optional[str]]:
    """
    Find matching bag in receives by tablet_type_id and bag_number.
    
    Box number is optional for backward compatibility:
    - If provided: Uses old box-based matching (flavor + box + bag)
    - If None: Uses new flavor-based matching (flavor + bag only)
    
    Submission type determines bag closure rules:
    - 'packaged': Can match closed bags (bags may be closed after production but still need packaging submissions)
    - Other types (machine, bag): Only matches open bags (closed bags should not accept new machine counts)
    
    Always excludes closed receives (receives should remain closed).
    
    If exactly 1 match: Returns bag, assigns automatically
    If 2+ matches: Returns None for bag, flags for manual review
    If 0 matches: Returns error
    
    Returns: (bag_row or None, needs_review_flag, error_message)
    """
    # Allow closed bags only for packaging submissions
    # Packaging may happen after a bag is marked closed (right after production)
    # But machine counts should only go to open bags
    allow_closed_bags = (submission_type == 'packaged')
    
    # Build query based on whether box_number is provided
    if box_number is not None:
        # Old-style: match with box number (for grandfathered receives)
        if allow_closed_bags:
            # For packaging: allow closed bags but still exclude closed receives and reserved bags
            matching_bags = conn.execute('''
                SELECT b.*, sb.box_number, sb.receiving_id, r.po_id, r.received_date
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN receiving r ON sb.receiving_id = r.id
                WHERE b.tablet_type_id = ? 
                AND sb.box_number = ? 
                AND b.bag_number = ?
                AND COALESCE(r.closed, 0) = 0
                AND COALESCE(b.reserved_for_bottles, 0) = 0
                ORDER BY r.received_date DESC
                ''', (tablet_type_id, box_number, bag_number)).fetchall()
        else:
            # For other submission types (machine, etc): exclude closed bags and reserved bags
            matching_bags = conn.execute('''
                SELECT b.*, sb.box_number, sb.receiving_id, r.po_id, r.received_date
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN receiving r ON sb.receiving_id = r.id
                WHERE b.tablet_type_id = ? 
                AND sb.box_number = ? 
                AND b.bag_number = ?
                AND COALESCE(b.status, 'Available') != 'Closed'
                AND COALESCE(r.closed, 0) = 0
                AND COALESCE(b.reserved_for_bottles, 0) = 0
                ORDER BY r.received_date DESC
            ''', (tablet_type_id, box_number, bag_number)).fetchall()
        
        if not matching_bags:
            if allow_closed_bags:
                return None, False, f'No open receive found for this product, Box #{box_number}, Bag #{bag_number}. The receive may be closed. Please check receiving records or contact your manager.'
            else:
                return None, False, f'No open receive found for this product, Box #{box_number}, Bag #{bag_number}. The bag/receive may be closed. Please check receiving records or contact your manager.'
    else:
        # New flavor-based: match without box number (flavor + bag only)
        if allow_closed_bags:
            # For packaging: allow closed bags but still exclude closed receives and reserved bags
            matching_bags = conn.execute('''
                SELECT b.*, sb.box_number, sb.receiving_id, r.po_id, r.received_date
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN receiving r ON sb.receiving_id = r.id
                WHERE b.tablet_type_id = ? 
                AND b.bag_number = ?
                AND COALESCE(r.closed, 0) = 0
                AND COALESCE(b.reserved_for_bottles, 0) = 0
                ORDER BY r.received_date DESC
                ''', (tablet_type_id, bag_number)).fetchall()
        else:
            # For other submission types (machine, etc): exclude closed bags and reserved bags
            matching_bags = conn.execute('''
                SELECT b.*, sb.box_number, sb.receiving_id, r.po_id, r.received_date
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN receiving r ON sb.receiving_id = r.id
                WHERE b.tablet_type_id = ? 
                AND b.bag_number = ?
                AND COALESCE(b.status, 'Available') != 'Closed'
                AND COALESCE(r.closed, 0) = 0
                AND COALESCE(b.reserved_for_bottles, 0) = 0
                ORDER BY r.received_date DESC
            ''', (tablet_type_id, bag_number)).fetchall()
        
        if not matching_bags:
            if allow_closed_bags:
                return None, False, f'No open receive found for this product, Bag #{bag_number}. The receive may be closed. Please check receiving records or contact your manager.'
            else:
                return None, False, f'No open receive found for this product, Bag #{bag_number}. The bag/receive may be closed. Please check receiving records or contact your manager.'
    
    # If exactly 1 match: auto-assign
    if len(matching_bags) == 1:
        return dict(matching_bags[0]), False, None
    
    # If 2+ matches: needs manual review, don't auto-assign
    return None, True, None
