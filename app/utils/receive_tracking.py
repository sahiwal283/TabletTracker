"""
Receive-based tracking utilities for matching submissions to receives/bags
"""

def find_bag_for_submission(conn, tablet_type_id, box_number, bag_number):
    """
    Find matching bag in receives by tablet_type_id, box_number, bag_number.
    
    If exactly 1 match: Returns bag, assigns automatically
    If 2+ matches: Returns None for bag, flags for manual review
    If 0 matches: Returns error
    
    Returns: (bag_row or None, needs_review_flag, error_message)
    """
    # Check for duplicates FIRST (same tablet_type + box + bag in multiple receives)
    matching_bags = conn.execute('''
        SELECT b.*, sb.box_number, sb.receiving_id, r.po_id, r.received_date
        FROM bags b
        JOIN small_boxes sb ON b.small_box_id = sb.id
        JOIN receiving r ON sb.receiving_id = r.id
        WHERE b.tablet_type_id = ? 
        AND sb.box_number = ? 
        AND b.bag_number = ?
        ORDER BY r.received_date DESC
    ''', (tablet_type_id, box_number, bag_number)).fetchall()
    
    if not matching_bags:
        return None, False, f'No receive found for this product, Box #{box_number}, Bag #{bag_number}. Please check receiving records or contact your manager.'
    
    # If exactly 1 match: auto-assign
    if len(matching_bags) == 1:
        return dict(matching_bags[0]), False, None
    
    # If 2+ matches: needs manual review, don't auto-assign
    return None, True, None

