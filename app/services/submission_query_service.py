"""
Submission query service for building reusable SQL queries.

This service extracts common SQL query patterns for submissions
to reduce duplication across blueprint files.
"""
import sqlite3
from typing import Dict, List, Optional, Tuple, Any
from app.services.submission_calculator import calculate_submission_total_with_fallback


def build_submission_base_query(include_calculated_total: bool = True) -> str:
    """
    Build the base SELECT query for submissions with all common joins.
    
    This query includes:
    - warehouse_submissions (ws)
    - purchase_orders (po)
    - product_details (pd) - primary
    - tablet_types (tt) - from product_details
    - tablet_types (tt_fallback) - from inventory_item_id
    - product_details (pd_fallback) - from fallback tablet_type
    - bags (b)
    - small_boxes (sb)
    - receiving (r)
    
    Args:
        include_calculated_total: If True, includes calculated_total in SELECT
            (Note: This will be calculated in Python, not SQL, for consistency)
    
    Returns:
        SQL SELECT query string (without WHERE clause)
    """
    query = '''
        SELECT ws.*, 
               po.po_number, 
               po.closed as po_closed, 
               po.id as po_id_for_filter, 
               po.zoho_po_id,
               pd.packages_per_display, 
               pd.tablets_per_package,
               COALESCE(pd.tablets_per_package, pd_fallback.tablets_per_package) as tablets_per_package_final,
               tt.inventory_item_id, 
               tt.id as tablet_type_id, 
               tt.tablet_type_name,
               COALESCE(ws.po_assignment_verified, 0) as po_verified,
               COALESCE(ws.needs_review, 0) as needs_review,
               ws.admin_notes,
               COALESCE(ws.submission_type, 'packaged') as submission_type,
               COALESCE(ws.submission_date, DATE(ws.created_at)) as filter_date,
               COALESCE(b.bag_label_count, ws.bag_label_count, 0) as bag_label_count,
               b.bag_label_count as receive_bag_count,
               ws.bag_id,
               r.id as receive_id,
               r.received_date,
               r.receive_name as stored_receive_name,
               sb.box_number,
               b.bag_number
        FROM warehouse_submissions ws
        LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
        LEFT JOIN product_details pd ON ws.product_name = pd.product_name
        LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
        LEFT JOIN tablet_types tt_fallback ON ws.inventory_item_id = tt_fallback.inventory_item_id
        LEFT JOIN product_details pd_fallback ON tt_fallback.id = pd_fallback.tablet_type_id
        LEFT JOIN bags b ON ws.bag_id = b.id
        LEFT JOIN small_boxes sb ON b.small_box_id = sb.id
        LEFT JOIN receiving r ON sb.receiving_id = r.id
    '''
    return query


def build_submission_filters(
    filters: Dict[str, Any],
    base_query: Optional[str] = None
) -> Tuple[str, List[Any]]:
    """
    Build WHERE clause and parameters for submission queries.
    
    Supported filters:
    - po_id: Filter by purchase order ID
    - po_number: Filter by purchase order number
    - tablet_type_id: Filter by tablet type ID
    - submission_type: Filter by submission type ('packaged', 'bag', 'machine')
    - needs_review: Filter by needs_review flag (bool)
    - po_verified: Filter by po_assignment_verified flag (bool)
    - date_from: Filter by date (submission_date or created_at) >= date_from
    - date_to: Filter by date (submission_date or created_at) <= date_to
    - product_name: Filter by product name
    - employee_name: Filter by employee name
    
    Args:
        filters: Dictionary of filter criteria
        base_query: Optional base query string (if None, uses build_submission_base_query)
    
    Returns:
        Tuple of (complete_query_string, parameter_list)
    """
    if base_query is None:
        query = build_submission_base_query()
    else:
        query = base_query
    
    where_clauses = ['1=1']  # Start with always-true condition for easy WHERE building
    params = []
    
    # PO ID filter
    if 'po_id' in filters and filters['po_id'] is not None:
        where_clauses.append('ws.assigned_po_id = ?')
        params.append(filters['po_id'])
    
    # PO Number filter
    if 'po_number' in filters and filters['po_number']:
        where_clauses.append('po.po_number = ?')
        params.append(filters['po_number'])
    
    # Tablet Type ID filter
    if 'tablet_type_id' in filters and filters['tablet_type_id'] is not None:
        where_clauses.append('tt.id = ?')
        params.append(filters['tablet_type_id'])
    
    # Submission Type filter
    if 'submission_type' in filters and filters['submission_type']:
        where_clauses.append('COALESCE(ws.submission_type, \'packaged\') = ?')
        params.append(filters['submission_type'])
    
    # Needs Review filter
    if 'needs_review' in filters and filters['needs_review'] is not None:
        if filters['needs_review']:
            where_clauses.append('COALESCE(ws.needs_review, 0) = 1')
        else:
            where_clauses.append('COALESCE(ws.needs_review, 0) = 0')
    
    # PO Verified filter
    if 'po_verified' in filters and filters['po_verified'] is not None:
        if filters['po_verified']:
            where_clauses.append('COALESCE(ws.po_assignment_verified, 0) = 1')
        else:
            where_clauses.append('COALESCE(ws.po_assignment_verified, 0) = 0')
    
    # Date From filter
    if 'date_from' in filters and filters['date_from']:
        where_clauses.append('COALESCE(ws.submission_date, DATE(ws.created_at)) >= ?')
        params.append(filters['date_from'])
    
    # Date To filter
    if 'date_to' in filters and filters['date_to']:
        where_clauses.append('COALESCE(ws.submission_date, DATE(ws.created_at)) <= ?')
        params.append(filters['date_to'])
    
    # Product Name filter
    if 'product_name' in filters and filters['product_name']:
        where_clauses.append('ws.product_name = ?')
        params.append(filters['product_name'])
    
    # Employee Name filter
    if 'employee_name' in filters and filters['employee_name']:
        where_clauses.append('ws.employee_name = ?')
        params.append(filters['employee_name'])
    
    # Build complete query
    query += ' WHERE ' + ' AND '.join(where_clauses)
    
    return query, params


def get_submissions_with_totals(
    conn: sqlite3.Connection,
    filters: Optional[Dict[str, Any]] = None,
    order_by: Optional[str] = None,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Get submissions with calculated totals using Python calculation.
    
    This function executes the query and then calculates totals using
    the submission_calculator service for consistency.
    
    Args:
        conn: Database connection object
        filters: Optional filter dictionary (see build_submission_filters)
        order_by: Optional ORDER BY clause (e.g., 'ws.created_at DESC')
        limit: Optional LIMIT clause (integer)
    
    Returns:
        List of submission dictionaries with calculated_total field added
    """
    if filters is None:
        filters = {}
    
    # Build query
    query, params = build_submission_filters(filters)
    
    # Add ORDER BY
    if order_by:
        query += f' ORDER BY {order_by}'
    else:
        query += ' ORDER BY ws.created_at DESC'
    
    # Add LIMIT
    if limit:
        query += f' LIMIT {limit}'
    
    # Execute query
    rows = conn.execute(query, params).fetchall()
    
    # Convert to dicts and calculate totals
    submissions = []
    for row in rows:
        submission_dict = dict(row)
        
        # Extract product details
        product_details = None
        if submission_dict.get('packages_per_display') is not None:
            product_details = {
                'packages_per_display': submission_dict.get('packages_per_display'),
                'tablets_per_package': submission_dict.get('tablets_per_package')
            }
        
        fallback_product_details = None
        if submission_dict.get('tablets_per_package_final') is not None:
            fallback_product_details = {
                'tablets_per_package': submission_dict.get('tablets_per_package_final')
            }
        
        # Calculate total using service
        calculated_total = calculate_submission_total_with_fallback(
            submission_dict,
            product_details,
            fallback_product_details
        )
        
        submission_dict['calculated_total'] = calculated_total
        submissions.append(submission_dict)
    
    return submissions

