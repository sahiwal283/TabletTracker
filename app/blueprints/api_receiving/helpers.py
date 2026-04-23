"""Internal helpers for api_receiving routes."""

from flask import current_app

from app.services.zoho_service import zoho_api

from .constants import BATCH_VALUE_PATTERN, WORKFLOW_RECEIPT_SUFFIX_PATTERN


def _receipt_family_root(receipt_number: str) -> str:
    """Collapse workflow lane/event suffixes to canonical receipt root."""
    s = (receipt_number or '').strip()
    if not s:
        return ''
    return WORKFLOW_RECEIPT_SUFFIX_PATTERN.sub('', s)


def _parse_zoho_po_quantity(value):
    """Parse quantity fields from Zoho JSON (may be int, float, or string)."""
    try:
        if value is None:
            return 0
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def _extract_zoho_receive_id_from_result(result):
    """Parse Zoho purchase receive create response for receive id."""
    if not result or not isinstance(result, dict):
        return None
    if result.get('purchasereceive'):
        pr = result['purchasereceive']
        return (
            pr.get('purchasereceive_id') or pr.get('purchase_receive_id')
            or pr.get('id') or pr.get('receive_id')
        )
    return (
        result.get('purchasereceive_id') or result.get('purchase_receive_id')
        or result.get('id') or result.get('receive_id')
    )


def _line_stats_from_zoho_line(line: dict) -> dict:
    """Build receive stats dict from one Zoho PO line item (GET purchaseorders/{id})."""
    return {
        'line_item_name': line.get('name') or 'Unknown',
        'ordered': _parse_zoho_po_quantity(line.get('quantity')),
        'received_in_zoho_before_push': _parse_zoho_po_quantity(line.get('quantity_received')),
        'matched_line_item_id': str(line.get('line_item_id', '') or ''),
    }


def get_zoho_po_line_receive_stats(zoho_po_id, zoho_line_item_id, inventory_item_id=None):
    """
    Fetch ordered quantity and quantity_received for one PO line from Zoho GET purchaseorders/{id}.

    Matches by line_item_id first; if not found (stale ID after Zoho edits), matches a unique line by item_id.

    Zoho error 36012 is enforced against Zoho's own received totals, not TabletTracker's po_lines.good_count
    (which tracks in-app credits and can be zero even when Zoho already shows receives).
    """
    if not zoho_po_id or not zoho_line_item_id:
        return None
    po_details = zoho_api.get_purchase_order_details(zoho_po_id)
    if not po_details or not isinstance(po_details, dict):
        return None
    po = po_details.get('purchaseorder')
    if not po:
        return None
    lines = po.get('line_items') or []
    zid = str(zoho_line_item_id)
    for line in lines:
        if str(line.get('line_item_id', '')) == zid:
            return _line_stats_from_zoho_line(line)
    if inventory_item_id:
        inv = str(inventory_item_id)
        matches = [li for li in lines if str(li.get('item_id') or '') == inv]
        if len(matches) == 1:
            current_app.logger.warning(
                f"Zoho PO {zoho_po_id}: stored line_item_id {zid} not in GET response; "
                f"using unique line matched by item_id {inv}"
            )
            return _line_stats_from_zoho_line(matches[0])
        if len(matches) > 1:
            current_app.logger.warning(
                f"Zoho PO {zoho_po_id}: multiple lines for item_id {inv}; cannot resolve line stats"
            )
    return None


def _resolve_zoho_line_item_id_for_po_item(zoho_po_id, inventory_item_id) -> str | None:
    """
    GET purchaseorders/{id} and return line_item_id for the line whose item_id matches inventory_item_id.

    Use this for overs PO (and any multi-line PO) so we never post a receive to the wrong flavor line when
    SQLite po_lines.zoho_line_item_id is stale or duplicated across items.
    """
    if not zoho_po_id or not inventory_item_id:
        return None
    po_details = zoho_api.get_purchase_order_details(zoho_po_id)
    if not po_details or not isinstance(po_details, dict):
        return None
    po = po_details.get('purchaseorder')
    if not po:
        return None
    inv = str(inventory_item_id)
    matches = [li for li in (po.get('line_items') or []) if str(li.get('item_id') or '') == inv]
    if len(matches) == 1:
        lid = str(matches[0].get('line_item_id') or '').strip()
        return lid or None
    if len(matches) > 1:
        current_app.logger.warning(
            f"Zoho PO {zoho_po_id}: multiple lines for item_id {inv}; cannot pick line_item_id"
        )
    return None


def _update_bag_zoho_push(conn, bag_id: int, zoho_receive_id, zoho_receive_overs_id) -> None:
    """Mark bag pushed; raises RuntimeError if no row was updated."""
    cur = conn.execute(
        '''
        UPDATE bags
        SET zoho_receive_pushed = 1,
            zoho_receive_id = ?,
            zoho_receive_overs_id = ?
        WHERE id = ?
        ''',
        (zoho_receive_id, zoho_receive_overs_id, bag_id),
    )
    if cur.rowcount != 1:
        raise RuntimeError(
            f'Expected to update 1 bag row (id={bag_id}), updated {cur.rowcount}. '
            'Zoho may have recorded the receive; check Zoho and do not retry blindly.'
        )
def normalize_batch_number(value):
    """Normalize and validate batch values (letters, numbers, hyphen)."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if not BATCH_VALUE_PATTERN.fullmatch(text):
        raise ValueError(
            f"Invalid batch number '{text}'. Batch numbers may contain letters, numbers, and hyphens."
        )
    return text
