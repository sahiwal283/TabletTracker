"""
Submission query service for building reusable SQL queries.

This service extracts common SQL query patterns for submissions
to reduce duplication across blueprint files.
"""
import sqlite3
from typing import Dict, List, Optional, Sequence, Tuple, Any
from app.services.submission_calculator import calculate_submission_total_with_fallback

ALLOWED_ORDER_FIELDS = {
    'created_at': 'ws.created_at',
    'submission_date': 'COALESCE(ws.submission_date, DATE(ws.created_at))',
    'employee_name': 'ws.employee_name',
    'product_name': 'ws.product_name',
    'submission_type': 'COALESCE(ws.submission_type, \'packaged\')',
}


def build_safe_order_by(
    sort_field: Optional[str] = None,
    sort_direction: Optional[str] = None
) -> str:
    """
    Build a safe ORDER BY clause from a whitelisted field/direction pair.

    Falls back to newest-first ordering for unknown values.
    """
    field_key = (sort_field or 'created_at').strip().lower()
    direction_key = (sort_direction or 'desc').strip().lower()
    direction_sql = 'ASC' if direction_key == 'asc' else 'DESC'
    field_sql = ALLOWED_ORDER_FIELDS.get(field_key, ALLOWED_ORDER_FIELDS['created_at'])
    return f'{field_sql} {direction_sql}'


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
               COALESCE(tt.id, tt_fallback.id, tt_bag.id) AS tablet_type_id,
               COALESCE(tt.tablet_type_name, tt_fallback.tablet_type_name, tt_bag.tablet_type_name) AS tablet_type_name,
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
               COALESCE(sb.box_number, ws.box_number) AS resolved_box_number,
               COALESCE(b.bag_number, ws.bag_number) AS resolved_bag_number
        FROM warehouse_submissions ws
        LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
        LEFT JOIN product_details pd
               ON TRIM(LOWER(ws.product_name)) = TRIM(LOWER(pd.product_name))
        LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
        LEFT JOIN tablet_types tt_fallback ON ws.inventory_item_id = tt_fallback.inventory_item_id
        LEFT JOIN product_details pd_fallback ON tt_fallback.id = pd_fallback.tablet_type_id
        LEFT JOIN bags b ON ws.bag_id = b.id
        LEFT JOIN tablet_types tt_bag ON b.tablet_type_id = tt_bag.id
        LEFT JOIN small_boxes sb ON b.small_box_id = sb.id
        LEFT JOIN receiving r ON sb.receiving_id = r.id
    '''
    return query


def apply_resolved_bag_fields(sub_dict: Dict[str, Any]) -> None:
    """Merge bag coordinates from JOIN onto box_number / bag_number for display.

    Queries use ``SELECT ws.*`` plus ``COALESCE(sb..., ws...)``. Duplicate SQLite
    column names ``box_number`` / ``bag_number`` resolve to the *first* occurrence
    (NULL on repack rows that only set ``bag_id``). Use ``resolved_*`` aliases and
    copy them here after ``dict(row)``.
    """
    rb = sub_dict.get("resolved_box_number")
    rbg = sub_dict.get("resolved_bag_number")
    if rb is not None:
        sub_dict["box_number"] = rb
    if rbg is not None:
        sub_dict["bag_number"] = rbg


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
    sort_field: Optional[str] = None,
    sort_direction: Optional[str] = None,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Get submissions with calculated totals using Python calculation.
    
    This function executes the query and then calculates totals using
    the submission_calculator service for consistency.
    
    Args:
        conn: Database connection object
        filters: Optional filter dictionary (see build_submission_filters)
        sort_field: Optional field name for sorting
        sort_direction: Optional direction ('asc' or 'desc')
        limit: Optional LIMIT clause (integer)
    
    Returns:
        List of submission dictionaries with calculated_total field added
    """
    if filters is None:
        filters = {}
    
    # Build query
    query, params = build_submission_filters(filters)
    
    query += f' ORDER BY {build_safe_order_by(sort_field, sort_direction)}'
    
    # Add LIMIT
    if limit:
        safe_limit = max(1, min(int(limit), 500))
        query += f' LIMIT {safe_limit}'
    
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


def longest_common_hyphen_prefix(labels: Sequence[str]) -> Optional[str]:
    """
    Given full bag labels like PO-00195-3-18-1, return the longest shared prefix
    (e.g. PO-00195-3 when boxes/bags differ; PO-00195 when shipments differ).
    """
    cleaned = [str(s).strip() for s in labels if s and str(s).strip()]
    if not cleaned:
        return None
    if len(cleaned) == 1:
        return cleaned[0]
    parts_list: List[List[str]] = [s.split('-') for s in cleaned]
    min_len = min(len(p) for p in parts_list)
    common: List[str] = []
    for i in range(min_len):
        seg = parts_list[0][i]
        if all(len(p) > i and p[i] == seg for p in parts_list):
            common.append(seg)
        else:
            break
    if not common:
        return cleaned[0]
    return '-'.join(common)


def common_receive_label_from_deductions(conn: sqlite3.Connection, submission_id: Optional[int]) -> Optional[str]:
    """
    For bottle / variety-pack rows with no single ws.bag_id, derive a display label
    from submission_bag_deductions → bags → receiving (longest common prefix of full labels).

    When ``receiving.receive_name`` is empty (common for some receives), build a base label
    from ``purchase_orders.po_number`` and the receive sequence on that PO so rows do not show
    as **Unassigned** in the submissions UI.
    """
    if not submission_id:
        return None
    rows = conn.execute(
        """
        SELECT r.receive_name, sb.box_number, b.bag_number,
               po.po_number,
               (
                   SELECT COUNT(*) + 1
                   FROM receiving r2
                   WHERE r2.po_id = r.po_id
                   AND (
                       r2.received_date < r.received_date
                       OR (
                           r2.received_date = r.received_date
                           AND r2.id < r.id
                       )
                   )
               ) AS receive_seq
        FROM submission_bag_deductions sbd
        JOIN bags b ON sbd.bag_id = b.id
        JOIN small_boxes sb ON b.small_box_id = sb.id
        JOIN receiving r ON sb.receiving_id = r.id
        LEFT JOIN purchase_orders po ON r.po_id = po.id
        WHERE sbd.submission_id = ?
        """,
        (int(submission_id),),
    ).fetchall()
    if not rows:
        return None
    labels: List[str] = []
    for row in rows:
        d = dict(row)
        rn = (d.get('receive_name') or '').strip()
        po_number = (d.get('po_number') or '').strip()
        receive_seq = d.get('receive_seq')
        bx = d.get('box_number')
        bn = d.get('bag_number')
        base: Optional[str] = None
        if rn:
            base = rn
        elif po_number and receive_seq is not None:
            base = f"{po_number}-{receive_seq}"
        if not base:
            continue
        if bx is not None and bn is not None:
            labels.append(f"{base}-{bx}-{bn}")
        elif bn is not None:
            labels.append(f"{base}-{bn}")
        else:
            labels.append(base)
    if not labels:
        return None
    return longest_common_hyphen_prefix(labels)

