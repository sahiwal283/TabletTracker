"""
Submission assignment service helpers.

Keeps assignment/approval business logic outside blueprint handlers.
"""
from typing import Dict, Any

from app.services.submission_calculator import calculate_repack_output_good


def approve_submission_assignment(conn, submission_id: int) -> Dict[str, Any]:
    """Approve and lock PO assignment for a submission."""
    submission = conn.execute(
        '''
        SELECT id, assigned_po_id, po_assignment_verified
        FROM warehouse_submissions
        WHERE id = ?
        ''',
        (submission_id,)
    ).fetchone()

    if not submission:
        return {'success': False, 'status_code': 404, 'error': 'Submission not found'}
    if submission['po_assignment_verified']:
        return {'success': False, 'status_code': 400, 'error': 'Submission already verified and locked'}
    if not submission['assigned_po_id']:
        return {'success': False, 'status_code': 400, 'error': 'Cannot approve unassigned submission'}

    conn.execute(
        '''
        UPDATE warehouse_submissions
        SET po_assignment_verified = TRUE
        WHERE id = ?
        ''',
        (submission_id,)
    )
    return {'success': True, 'message': 'PO assignment approved and locked'}


def _refresh_po_header_totals(conn, po_id: int) -> None:
    totals = conn.execute(
        '''
        SELECT
            COALESCE(SUM(quantity_ordered), 0) as total_ordered,
            COALESCE(SUM(good_count), 0) as total_good,
            COALESCE(SUM(damaged_count), 0) as total_damaged
        FROM po_lines
        WHERE po_id = ?
        ''',
        (po_id,)
    ).fetchone()
    remaining = totals['total_ordered'] - totals['total_good'] - totals['total_damaged']
    conn.execute(
        '''
        UPDATE purchase_orders
        SET ordered_quantity = ?, current_good_count = ?,
            current_damaged_count = ?, remaining_quantity = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        ''',
        (
            totals['total_ordered'],
            totals['total_good'],
            totals['total_damaged'],
            remaining,
            po_id
        )
    )


def _calculate_submission_counts(submission: Dict[str, Any]) -> Dict[str, int]:
    submission_type = submission.get('submission_type', 'packaged')
    if submission_type == 'machine':
        good_tablets = submission.get('tablets_pressed_into_cards', 0) or 0
    elif submission_type == 'repack':
        packages_per_display = submission.get('packages_per_display') or 0
        tablets_per_package = submission.get('tablets_per_package') or 0
        good_tablets = calculate_repack_output_good(
            submission, packages_per_display, tablets_per_package
        )
    else:
        packages_per_display = submission.get('packages_per_display') or 0
        tablets_per_package = submission.get('tablets_per_package') or 0
        good_tablets = (
            (submission.get('displays_made', 0) or 0) * packages_per_display * tablets_per_package
            + (submission.get('packs_remaining', 0) or 0) * tablets_per_package
            + (submission.get('loose_tablets', 0) or 0)
        )
    # damaged_tablets column = cards re-opened (packaging); do not apply to PO damaged_count
    return {'good': good_tablets, 'damaged': 0}


def reassign_submission_to_po(conn, submission_id: int, new_po_id: int) -> Dict[str, Any]:
    """Reassign submission to a different PO and recalculate totals."""
    submission_row = conn.execute(
        '''
        SELECT ws.*, pd.packages_per_display, pd.tablets_per_package, tt.inventory_item_id,
               COALESCE(ws.submission_type, 'packaged') as submission_type
        FROM warehouse_submissions ws
        LEFT JOIN product_details pd ON ws.product_name = pd.product_name
        LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
        WHERE ws.id = ?
        ''',
        (submission_id,)
    ).fetchone()
    if not submission_row:
        return {'success': False, 'status_code': 404, 'error': 'Submission not found'}

    submission = dict(submission_row)
    if submission['po_assignment_verified']:
        return {'success': False, 'status_code': 403, 'error': 'Cannot reassign: PO assignment is already verified and locked'}

    inventory_item_id = submission.get('inventory_item_id')
    if not inventory_item_id:
        return {'success': False, 'status_code': 400, 'error': 'Submission inventory item is missing'}

    new_po_check = conn.execute(
        '''
        SELECT COUNT(*) as count
        FROM po_lines pl
        WHERE pl.po_id = ? AND pl.inventory_item_id = ?
        ''',
        (new_po_id, inventory_item_id)
    ).fetchone()
    if new_po_check['count'] == 0:
        return {'success': False, 'status_code': 400, 'error': 'Selected PO does not have this product'}

    counts = _calculate_submission_counts(submission)
    good_tablets = counts['good']
    damaged_tablets = counts['damaged']
    old_po_id = submission.get('assigned_po_id')

    if old_po_id:
        old_line = conn.execute(
            '''
            SELECT id FROM po_lines
            WHERE po_id = ? AND inventory_item_id = ?
            LIMIT 1
            ''',
            (old_po_id, inventory_item_id)
        ).fetchone()
        if old_line:
            current_line = conn.execute(
                'SELECT good_count, damaged_count FROM po_lines WHERE id = ?',
                (old_line['id'],)
            ).fetchone()
            new_good = max(0, (current_line['good_count'] or 0) - good_tablets)
            new_damaged = max(0, (current_line['damaged_count'] or 0) - damaged_tablets)
            conn.execute(
                '''
                UPDATE po_lines
                SET good_count = ?, damaged_count = ?
                WHERE id = ?
                ''',
                (new_good, new_damaged, old_line['id'])
            )
            _refresh_po_header_totals(conn, old_po_id)

    new_line = conn.execute(
        '''
        SELECT id FROM po_lines
        WHERE po_id = ? AND inventory_item_id = ?
        LIMIT 1
        ''',
        (new_po_id, inventory_item_id)
    ).fetchone()
    if not new_line:
        return {'success': False, 'status_code': 400, 'error': 'New PO line not found for this product'}

    conn.execute(
        '''
        UPDATE po_lines
        SET good_count = good_count + ?, damaged_count = damaged_count + ?
        WHERE id = ?
        ''',
        (good_tablets, damaged_tablets, new_line['id'])
    )
    _refresh_po_header_totals(conn, new_po_id)

    conn.execute(
        '''
        UPDATE warehouse_submissions
        SET assigned_po_id = ?, po_assignment_verified = TRUE
        WHERE id = ?
        ''',
        (new_po_id, submission_id)
    )
    new_po = conn.execute(
        'SELECT po_number FROM purchase_orders WHERE id = ?',
        (new_po_id,)
    ).fetchone()
    return {
        'success': True,
        'message': f'Submission reassigned to PO-{new_po["po_number"]} and locked',
        'new_po_number': new_po['po_number']
    }
