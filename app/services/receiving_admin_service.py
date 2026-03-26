"""
Receiving admin workflows extracted from blueprint handlers.
"""
from typing import Dict, Any, Optional


def _require_manager_or_admin(user_role: Optional[str], is_admin: bool, action_message: str) -> Optional[Dict[str, Any]]:
    if user_role not in ['manager', 'admin'] and not is_admin:
        return {'success': False, 'status_code': 403, 'error': action_message}
    return None


def toggle_receiving_closed(conn, receiving_id: int, user_role: Optional[str], is_admin: bool) -> Dict[str, Any]:
    denied = _require_manager_or_admin(
        user_role,
        is_admin,
        'Only managers and admins can close receives'
    )
    if denied:
        return denied

    receiving = conn.execute(
        '''
        SELECT r.id, r.closed, po.po_number
        FROM receiving r
        LEFT JOIN purchase_orders po ON r.po_id = po.id
        WHERE r.id = ?
        ''',
        (receiving_id,)
    ).fetchone()
    if not receiving:
        return {'success': False, 'status_code': 404, 'error': 'Receiving record not found'}

    current_closed = bool(receiving['closed'])
    new_closed = not current_closed
    conn.execute('UPDATE receiving SET closed = ? WHERE id = ?', (new_closed, receiving_id))

    if new_closed:
        conn.execute(
            '''
            UPDATE bags
            SET status = 'Closed'
            WHERE small_box_id IN (
                SELECT id FROM small_boxes WHERE receiving_id = ?
            )
            ''',
            (receiving_id,)
        )
    else:
        conn.execute(
            '''
            UPDATE bags
            SET status = 'Available'
            WHERE small_box_id IN (
                SELECT id FROM small_boxes WHERE receiving_id = ?
            )
            ''',
            (receiving_id,)
        )

    po_info = receiving['po_number'] or 'Unassigned'
    action = 'closed' if new_closed else 'reopened'
    return {
        'success': True,
        'closed': new_closed,
        'message': f'Successfully {action} receive (PO: {po_info})'
    }


def toggle_bag_closed(conn, bag_id: int, user_role: Optional[str], is_admin: bool) -> Dict[str, Any]:
    denied = _require_manager_or_admin(
        user_role,
        is_admin,
        'Only managers and admins can close bags'
    )
    if denied:
        return denied

    bag_row = conn.execute(
        '''
        SELECT b.id, COALESCE(b.status, 'Available') as status, b.bag_number, sb.box_number, tt.tablet_type_name
        FROM bags b
        JOIN small_boxes sb ON b.small_box_id = sb.id
        JOIN tablet_types tt ON b.tablet_type_id = tt.id
        WHERE b.id = ?
        ''',
        (bag_id,)
    ).fetchone()
    if not bag_row:
        return {'success': False, 'status_code': 404, 'error': 'Bag not found'}

    bag = dict(bag_row)
    new_status = 'Closed' if bag.get('status') != 'Closed' else 'Available'
    conn.execute('UPDATE bags SET status = ? WHERE id = ?', (new_status, bag_id))
    action = 'closed' if new_status == 'Closed' else 'reopened'
    bag_info = f"{bag.get('tablet_type_name', 'Unknown')} - Box {bag.get('box_number', 'N/A')}, Bag {bag.get('bag_number', 'N/A')}"
    return {
        'success': True,
        'status': new_status,
        'message': f'Successfully {action} bag: {bag_info}'
    }


def publish_receiving(conn, receiving_id: int) -> Dict[str, Any]:
    receive = conn.execute('SELECT status FROM receiving WHERE id = ?', (receiving_id,)).fetchone()
    if not receive:
        return {'success': False, 'status_code': 404, 'error': 'Receive not found'}
    if (receive['status'] or 'published') == 'published':
        return {'success': False, 'status_code': 400, 'error': 'Receive is already published'}

    conn.execute('UPDATE receiving SET status = ? WHERE id = ?', ('published', receiving_id))
    return {
        'success': True,
        'message': 'Receive published successfully! Now available for production.',
        'status': 'published'
    }


def unpublish_receiving(conn, receiving_id: int) -> Dict[str, Any]:
    receive = conn.execute('SELECT status FROM receiving WHERE id = ?', (receiving_id,)).fetchone()
    if not receive:
        return {'success': False, 'status_code': 404, 'error': 'Receive not found'}
    if (receive['status'] or 'published') == 'draft':
        return {'success': False, 'status_code': 400, 'error': 'Receive is already a draft'}

    submission_count = conn.execute(
        '''
        SELECT COUNT(*) as count
        FROM warehouse_submissions ws
        JOIN bags b ON ws.bag_id = b.id
        JOIN small_boxes sb ON b.small_box_id = sb.id
        WHERE sb.receiving_id = ?
        ''',
        (receiving_id,)
    ).fetchone()
    if submission_count and submission_count['count'] > 0:
        return {
            'success': False,
            'status_code': 400,
            'error': f'Cannot unpublish: {submission_count["count"]} submission(s) already exist for this receive. Delete submissions first.'
        }

    conn.execute('UPDATE receiving SET status = ? WHERE id = ?', ('draft', receiving_id))
    return {
        'success': True,
        'message': 'Receive moved to draft. Will not appear in production until published again.',
        'status': 'draft'
    }


def assign_po_to_receiving(conn, receiving_id: int, po_id: Optional[int], user_role: Optional[str]) -> Dict[str, Any]:
    if user_role not in ['manager', 'admin']:
        return {'success': False, 'status_code': 403, 'error': 'Only managers and admins can assign POs'}

    receiving = conn.execute('SELECT id FROM receiving WHERE id = ?', (receiving_id,)).fetchone()
    if not receiving:
        return {'success': False, 'status_code': 404, 'error': 'Receiving record not found'}

    normalized_po_id = po_id if po_id else None
    conn.execute('UPDATE receiving SET po_id = ? WHERE id = ?', (normalized_po_id, receiving_id))

    po_number = None
    if normalized_po_id:
        po = conn.execute('SELECT po_number FROM purchase_orders WHERE id = ?', (normalized_po_id,)).fetchone()
        if po:
            po_number = po['po_number']

    return {
        'success': True,
        'message': 'PO assignment updated successfully',
        'po_number': po_number
    }
