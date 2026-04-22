"""
Receive-based tracking utilities for matching submissions to receives/bags
"""
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.product_tablet_allowlist import allowed_tablet_type_ids_for_product

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
    
    Submission type determines matching rules:
    - 'packaged': Can match closed bags (bags may be closed after production but still need packaging submissions)
    - Other types (machine, bag): Only matches open bags (closed bags should not accept new machine counts)
    - 'packaged' and 'machine': Can match bags reserved for bottles (caller may require confirmation before submit)
    - 'bag': Still excludes bags reserved for bottles
    
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
    
    # Allow reserved bags for machine/packaged workflows (confirmation handled by caller).
    allow_reserved_bags = submission_type in ('packaged', 'machine')

    # Build query based on whether box_number is provided
    if box_number is not None:
        # Old-style: match with box number (for grandfathered receives)
        if allow_closed_bags:
            # For packaging: allow closed bags.
            reserved_filter = '' if allow_reserved_bags else "AND COALESCE(b.reserved_for_bottles, 0) = 0"
            matching_bags = conn.execute(f'''
                SELECT b.*, sb.box_number, sb.receiving_id, r.po_id, r.received_date
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN receiving r ON sb.receiving_id = r.id
                WHERE b.tablet_type_id = ? 
                AND sb.box_number = ? 
                AND b.bag_number = ?
                AND COALESCE(r.closed, 0) = 0
                AND COALESCE(r.status, 'published') = 'published'
                {reserved_filter}
                ORDER BY r.received_date DESC
                ''', (tablet_type_id, box_number, bag_number)).fetchall()
        else:
            # For non-packaging: exclude closed bags and draft receives.
            reserved_filter = '' if allow_reserved_bags else "AND COALESCE(b.reserved_for_bottles, 0) = 0"
            matching_bags = conn.execute(f'''
                SELECT b.*, sb.box_number, sb.receiving_id, r.po_id, r.received_date
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN receiving r ON sb.receiving_id = r.id
                WHERE b.tablet_type_id = ? 
                AND sb.box_number = ? 
                AND b.bag_number = ?
                AND COALESCE(b.status, 'Available') != 'Closed'
                AND COALESCE(r.closed, 0) = 0
                AND COALESCE(r.status, 'published') = 'published'
                {reserved_filter}
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
            # For packaging: allow closed bags.
            reserved_filter = '' if allow_reserved_bags else "AND COALESCE(b.reserved_for_bottles, 0) = 0"
            matching_bags = conn.execute(f'''
                SELECT b.*, sb.box_number, sb.receiving_id, r.po_id, r.received_date
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN receiving r ON sb.receiving_id = r.id
                WHERE b.tablet_type_id = ? 
                AND b.bag_number = ?
                AND COALESCE(r.closed, 0) = 0
                AND COALESCE(r.status, 'published') = 'published'
                {reserved_filter}
                ORDER BY r.received_date DESC
                ''', (tablet_type_id, bag_number)).fetchall()
        else:
            # For non-packaging: exclude closed bags and draft receives.
            reserved_filter = '' if allow_reserved_bags else "AND COALESCE(b.reserved_for_bottles, 0) = 0"
            matching_bags = conn.execute(f'''
                SELECT b.*, sb.box_number, sb.receiving_id, r.po_id, r.received_date
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN receiving r ON sb.receiving_id = r.id
                WHERE b.tablet_type_id = ? 
                AND b.bag_number = ?
                AND COALESCE(b.status, 'Available') != 'Closed'
                AND COALESCE(r.closed, 0) = 0
                AND COALESCE(r.status, 'published') = 'published'
                {reserved_filter}
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


def find_bag_for_submission_allowlist(
    conn: sqlite3.Connection,
    tablet_type_ids: Sequence[int],
    bag_number: int,
    box_number: Optional[int] = None,
    submission_type: str = "packaged",
) -> Tuple[Optional[Dict[str, Any]], bool, Optional[str]]:
    """
    Like ``find_bag_for_submission`` but match any of several tablet types (product allowlist).
    """
    ids: List[int] = []
    for t in tablet_type_ids:
        try:
            ids.append(int(t))
        except (TypeError, ValueError):
            continue
    ids = sorted(set(ids))
    if not ids:
        return None, False, "No tablet types configured for bag lookup."

    allow_closed_bags = submission_type == "packaged"
    allow_reserved_bags = submission_type in ("packaged", "machine")
    placeholders = ",".join("?" * len(ids))
    params_base: Tuple[Any, ...] = tuple(ids)

    if box_number is not None:
        if allow_closed_bags:
            reserved_filter = "" if allow_reserved_bags else "AND COALESCE(b.reserved_for_bottles, 0) = 0"
            matching_bags = conn.execute(
                f"""
                SELECT b.*, sb.box_number, sb.receiving_id, r.po_id, r.received_date
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN receiving r ON sb.receiving_id = r.id
                WHERE b.tablet_type_id IN ({placeholders})
                AND sb.box_number = ?
                AND b.bag_number = ?
                AND COALESCE(r.closed, 0) = 0
                AND COALESCE(r.status, 'published') = 'published'
                {reserved_filter}
                ORDER BY r.received_date DESC
                """,
                params_base + (box_number, bag_number),
            ).fetchall()
        else:
            reserved_filter = "" if allow_reserved_bags else "AND COALESCE(b.reserved_for_bottles, 0) = 0"
            matching_bags = conn.execute(
                f"""
                SELECT b.*, sb.box_number, sb.receiving_id, r.po_id, r.received_date
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN receiving r ON sb.receiving_id = r.id
                WHERE b.tablet_type_id IN ({placeholders})
                AND sb.box_number = ?
                AND b.bag_number = ?
                AND COALESCE(b.status, 'Available') != 'Closed'
                AND COALESCE(r.closed, 0) = 0
                AND COALESCE(r.status, 'published') = 'published'
                {reserved_filter}
                ORDER BY r.received_date DESC
                """,
                params_base + (box_number, bag_number),
            ).fetchall()

        if not matching_bags:
            if allow_closed_bags:
                return (
                    None,
                    False,
                    f"No open receive found for this product, Box #{box_number}, Bag #{bag_number}. "
                    "The receive may be closed. Please check receiving records or contact your manager.",
                )
            return (
                None,
                False,
                f"No open receive found for this product, Box #{box_number}, Bag #{bag_number}. "
                "The bag/receive may be closed. Please check receiving records or contact your manager.",
            )
    else:
        if allow_closed_bags:
            reserved_filter = "" if allow_reserved_bags else "AND COALESCE(b.reserved_for_bottles, 0) = 0"
            matching_bags = conn.execute(
                f"""
                SELECT b.*, sb.box_number, sb.receiving_id, r.po_id, r.received_date
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN receiving r ON sb.receiving_id = r.id
                WHERE b.tablet_type_id IN ({placeholders})
                AND b.bag_number = ?
                AND COALESCE(r.closed, 0) = 0
                AND COALESCE(r.status, 'published') = 'published'
                {reserved_filter}
                ORDER BY r.received_date DESC
                """,
                params_base + (bag_number,),
            ).fetchall()
        else:
            reserved_filter = "" if allow_reserved_bags else "AND COALESCE(b.reserved_for_bottles, 0) = 0"
            matching_bags = conn.execute(
                f"""
                SELECT b.*, sb.box_number, sb.receiving_id, r.po_id, r.received_date
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN receiving r ON sb.receiving_id = r.id
                WHERE b.tablet_type_id IN ({placeholders})
                AND b.bag_number = ?
                AND COALESCE(b.status, 'Available') != 'Closed'
                AND COALESCE(r.closed, 0) = 0
                AND COALESCE(r.status, 'published') = 'published'
                {reserved_filter}
                ORDER BY r.received_date DESC
                """,
                params_base + (bag_number,),
            ).fetchall()

        if not matching_bags:
            if allow_closed_bags:
                return (
                    None,
                    False,
                    f"No open receive found for this product, Bag #{bag_number}. "
                    "The receive may be closed. Please check receiving records or contact your manager.",
                )
            return (
                None,
                False,
                f"No open receive found for this product, Bag #{bag_number}. "
                "The bag/receive may be closed. Please check receiving records or contact your manager.",
            )

    if len(matching_bags) == 1:
        return dict(matching_bags[0]), False, None
    return None, True, None


def find_bag_for_submission_for_product(
    conn: sqlite3.Connection,
    product_id: int,
    bag_number: int,
    box_number: Optional[int] = None,
    submission_type: str = "packaged",
) -> Tuple[Optional[Dict[str, Any]], bool, Optional[str]]:
    """Resolve bag using ``product_allowed_tablet_types`` (or primary ``product_details.tablet_type_id``)."""
    tids = allowed_tablet_type_ids_for_product(conn, int(product_id))
    if not tids:
        return None, False, "Product has no tablet types configured."
    return find_bag_for_submission_allowlist(conn, tids, bag_number, box_number, submission_type)
