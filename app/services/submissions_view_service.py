"""Helpers for submissions list/export query composition."""
from typing import Dict, Any, List, Tuple


ALLOWED_SORT_COLUMNS = {
    'created_at': 'ws.created_at',
    'receipt_number': 'ws.receipt_number',
    'employee_name': 'ws.employee_name',
    'product_name': 'ws.product_name',
    'total': 'calculated_total',
}


def append_submission_common_filters(query: str, params: List[Any], filters: Dict[str, Any]) -> Tuple[str, List[Any]]:
    filter_po_id = filters.get('po_id')
    filter_item_id = filters.get('item_id')
    filter_date_from = filters.get('date_from')
    filter_date_to = filters.get('date_to')
    filter_tablet_type_id = filters.get('tablet_type_id')
    filter_submission_type = filters.get('submission_type')
    filter_receipt_number = filters.get('receipt_number')

    if filter_po_id:
        query += ' AND ws.assigned_po_id = ?'
        params.append(filter_po_id)
    if filter_item_id:
        query += ' AND tt.inventory_item_id = ?'
        params.append(filter_item_id)
    if filter_date_from:
        query += ' AND COALESCE(ws.submission_date, DATE(ws.created_at)) >= ?'
        params.append(filter_date_from)
    if filter_date_to:
        query += ' AND COALESCE(ws.submission_date, DATE(ws.created_at)) <= ?'
        params.append(filter_date_to)
    if filter_tablet_type_id:
        query += ' AND tt.id = ?'
        params.append(filter_tablet_type_id)
    if filter_submission_type:
        query += " AND COALESCE(ws.submission_type, 'packaged') = ?"
        params.append(filter_submission_type)
    if filter_receipt_number:
        query += ' AND ws.receipt_number LIKE ?'
        params.append(f'%{filter_receipt_number}%')

    return query, params


def append_submission_archive_tab_filters(query: str, show_archived: bool, active_tab: str) -> str:
    if not show_archived:
        query += ' AND (po.closed IS NULL OR po.closed = FALSE)'
    else:
        query += ' AND po.closed = TRUE'

    if active_tab == 'packaged_machine':
        query += " AND COALESCE(ws.submission_type, 'packaged') IN ('packaged', 'machine', 'repack')"
    elif active_tab == 'bottles':
        query += " AND COALESCE(ws.submission_type, 'packaged') = 'bottle'"
    elif active_tab == 'bag':
        query += " AND COALESCE(ws.submission_type, 'packaged') = 'bag'"
    return query


def append_submission_sort(query: str, sort_by: str, sort_order: str) -> str:
    sort_column = ALLOWED_SORT_COLUMNS.get(sort_by, 'ws.created_at')
    sort_direction = 'ASC' if str(sort_order).lower() == 'asc' else 'DESC'
    if sort_by == 'receipt_number':
        query += f""" ORDER BY
            CASE WHEN ws.receipt_number IS NULL THEN 1 ELSE 0 END,
            CAST(SUBSTR(ws.receipt_number, 1, INSTR(ws.receipt_number, '-') - 1) AS INTEGER) {sort_direction},
            CAST(SUBSTR(ws.receipt_number, INSTR(ws.receipt_number, '-') + 1) AS INTEGER) {sort_direction}
        """
    else:
        query += f' ORDER BY {sort_column} {sort_direction}'
    return query
