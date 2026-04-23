"""
API routes - all /api/* endpoints
"""

from flask import current_app, jsonify, request

from app.services.submission_assignment_service import (
    approve_submission_assignment as approve_submission_assignment_service,
)
from app.services.submission_assignment_service import (
    reassign_submission_to_po as reassign_submission_to_po_service,
)
from app.services.submission_calculator import calculate_repack_output_good
from app.utils.auth_utils import (
    admin_required,
    role_required,
)
from app.utils.db_utils import db_read_only, db_transaction

from . import bp


@bp.route('/api/update_submission_date', methods=['POST'])
@role_required('dashboard')
def update_submission_date():
    """Update the submission date for an existing submission"""
    try:
        data = request.get_json()
        submission_id = data.get('submission_id')
        submission_date = data.get('submission_date')

        if not submission_id or not submission_date:
            return jsonify({'error': 'Missing submission_id or submission_date'}), 400

        with db_transaction() as conn:
            # Update the submission date
            conn.execute('''
                UPDATE warehouse_submissions
                SET submission_date = ?
                WHERE id = ?
            ''', (submission_date, submission_id))

            return jsonify({
                'success': True,
                'message': f'Submission date updated to {submission_date}'
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500



@bp.route('/api/submission/<int:submission_id>/available_pos', methods=['GET'])
@role_required('dashboard')
def get_available_pos_for_submission(submission_id):
    """Get list of POs that can accept this submission (filtered by product/inventory_item_id)"""
    try:
        with db_read_only() as conn:
            # Get submission details
            submission = conn.execute('''
                SELECT ws.*, pd.packages_per_display, pd.tablets_per_package, tt.inventory_item_id
                FROM warehouse_submissions ws
                LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                WHERE ws.id = ?
            ''', (submission_id,)).fetchone()

            if not submission:
                return jsonify({'error': 'Submission not found'}), 404

            inventory_item_id = submission['inventory_item_id']
            if not inventory_item_id:
                return jsonify({'error': 'Could not determine product inventory_item_id'}), 400

            # Get all POs (open and closed) that have this inventory_item_id
            # Exclude Draft POs, order newest first (DESC) for less scrolling
            pos = conn.execute('''
                SELECT DISTINCT po.id, po.po_number, po.closed, po.internal_status,
                       po.ordered_quantity, po.current_good_count, po.current_damaged_count
                FROM purchase_orders po
                INNER JOIN po_lines pl ON po.id = pl.po_id
                WHERE pl.inventory_item_id = ?
                AND COALESCE(po.internal_status, '') != 'Draft'
                ORDER BY po.po_number DESC
            ''', (inventory_item_id,)).fetchall()

            pos_list = []
            for po in pos:
                pos_list.append({
                    'id': po['id'],
                    'po_number': po['po_number'],
                    'closed': bool(po['closed']),
                    'status': 'Cancelled' if po['internal_status'] == 'Cancelled' else ('Closed' if po['closed'] else (po['internal_status'] or 'Active')),
                    'ordered': po['ordered_quantity'] or 0,
                    'good': po['current_good_count'] or 0,
                    'damaged': po['current_damaged_count'] or 0,
                    'remaining': (po['ordered_quantity'] or 0) - (po['current_good_count'] or 0) - (po['current_damaged_count'] or 0)
                })

            return jsonify({
                'success': True,
                'available_pos': pos_list,
                'submission_product': submission['product_name'],
                'current_po_id': submission['assigned_po_id']
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500



@bp.route('/api/submission/<int:submission_id>/approve', methods=['POST'])
@role_required('dashboard')
def approve_submission_assignment(submission_id):
    """Approve and lock the current PO assignment for a submission"""
    try:
        with db_transaction() as conn:
            result = approve_submission_assignment_service(conn, submission_id)
            if not result.get('success'):
                return jsonify({'error': result.get('error', 'Approval failed')}), result.get('status_code', 400)
            return jsonify({'success': True, 'message': result['message']})
    except Exception as e:
        return jsonify({'error': str(e)}), 500



@bp.route('/api/submission/<int:submission_id>/reassign', methods=['POST'])
@role_required('dashboard')
def reassign_submission_to_po(submission_id):
    """Reassign a submission to a different PO (manager verification/correction)"""
    try:
        data = request.get_json() or {}
        new_po_id = data.get('new_po_id')
        if not new_po_id:
            return jsonify({'error': 'Missing new_po_id'}), 400
        try:
            new_po_id = int(new_po_id)
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid new_po_id'}), 400

        with db_transaction() as conn:
            result = reassign_submission_to_po_service(conn, submission_id, new_po_id)
            if not result.get('success'):
                return jsonify({'error': result.get('error', 'Reassignment failed')}), result.get('status_code', 400)
            return jsonify({
                'success': True,
                'message': result['message'],
                'new_po_number': result.get('new_po_number'),
                'updated_count': result.get('updated_count', 1),
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500



@bp.route('/api/reassign_all_submissions', methods=['POST'])
@admin_required
def reassign_all_submissions():
    """Reassign ALL submissions to POs using correct PO order (by PO number, not created_at)"""
    try:
        with db_transaction() as conn:
            # Step 1: Clear all PO assignments and counts (soft reassign - reset verification)
            current_app.logger.info("Clearing all PO assignments and counts...")
            conn.execute('UPDATE warehouse_submissions SET assigned_po_id = NULL, po_assignment_verified = FALSE')
            conn.execute('UPDATE po_lines SET good_count = 0, damaged_count = 0')
            conn.execute('UPDATE purchase_orders SET current_good_count = 0, current_damaged_count = 0, remaining_quantity = ordered_quantity')

            # Step 2: Get all submissions in order with their creation timestamp
            all_submissions_rows = conn.execute('''
                SELECT ws.id, ws.product_name, ws.displays_made,
                       ws.packs_remaining, ws.loose_tablets, ws.cards_reopened, ws.tablets_pressed_into_cards,
                       COALESCE(ws.submission_type, 'packaged') as submission_type, ws.created_at
                FROM warehouse_submissions ws
                ORDER BY ws.created_at ASC
            ''').fetchall()

            all_submissions = [dict(row) for row in all_submissions_rows]

            if not all_submissions:
                return jsonify({'success': True, 'message': 'No submissions found'})

            matched_count = 0
            updated_pos = set()

            # Track running totals for each PO line during reassignment
            # This helps us know when to move to the next PO (when current one has enough)
            po_line_running_totals = {}  # {line_id: {'good': count, 'damaged': count}}

            # Step 3: Reassign each submission using correct PO order
            for submission in all_submissions:
                try:
                    # Get product details
                    product_row = conn.execute('''
                    SELECT tt.inventory_item_id, pd.packages_per_display, pd.tablets_per_package
                    FROM product_details pd
                    JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                    WHERE pd.product_name = ?
                ''', (submission['product_name'],)).fetchone()

                    if not product_row:
                        # Try direct tablet_type match
                        product_row = conn.execute('''
                        SELECT inventory_item_id, 0 as packages_per_display, 0 as tablets_per_package
                        FROM tablet_types
                        WHERE tablet_type_name = ?
                    ''', (submission['product_name'],)).fetchone()

                    if not product_row:
                        continue

                    product = dict(product_row)
                    inventory_item_id = product.get('inventory_item_id')

                    if not inventory_item_id:
                        continue

                    # Find OPEN PO lines only - ORDER BY PO NUMBER
                    # Automatic bulk reassignment assigns to open POs only
                    # Managers can still manually reassign to closed POs via "Change" button
                    # Exclude Draft POs - only assign to Active/Issued open POs
                    # Note: We do NOT filter by available quantity - POs can receive more than ordered
                    po_lines_rows = conn.execute('''
                        SELECT pl.*, po.closed, po.po_number
                        FROM po_lines pl
                        JOIN purchase_orders po ON pl.po_id = po.id
                        WHERE pl.inventory_item_id = ?
                        AND COALESCE(po.internal_status, '') != 'Draft'
                        AND po.closed = FALSE
                        AND COALESCE(po.internal_status, '') != 'Cancelled'
                        ORDER BY po.po_number ASC
                    ''', (inventory_item_id,)).fetchall()

                    po_lines = [dict(row) for row in po_lines_rows]

                    if not po_lines:
                        continue

                    # Calculate good and damaged counts based on submission type
                    submission_type = submission.get('submission_type', 'packaged')
                    if submission_type == 'machine':
                        good_tablets = submission.get('tablets_pressed_into_cards', 0) or 0
                    elif submission_type == 'repack':
                        packages_per_display = product.get('packages_per_display') or 0
                        tablets_per_package = product.get('tablets_per_package') or 0
                        good_tablets = calculate_repack_output_good(
                            submission, packages_per_display, tablets_per_package
                        )
                    else:
                        packages_per_display = product.get('packages_per_display') or 0
                        tablets_per_package = product.get('tablets_per_package') or 0
                        good_tablets = (submission.get('displays_made', 0) * packages_per_display * tablets_per_package +
                                      submission.get('packs_remaining', 0) * tablets_per_package +
                                      submission.get('loose_tablets', 0))
                    # cards_re-opened (cards_reopened) does not apply to po_lines.damaged_count
                    packaging_cards_reopened = 0

                    # Find the first PO that hasn't reached its ordered quantity yet
                    # This allows sequential filling: complete PO-127, then PO-131, then PO-135, etc.
                    # But final counts can still exceed ordered quantities (no artificial cap)
                    assigned_po_id = None
                    for line in po_lines:
                        # Initialize running total if first time seeing this line
                        if line['id'] not in po_line_running_totals:
                            po_line_running_totals[line['id']] = {'good': 0, 'damaged': 0, 'quantity_ordered': line['quantity_ordered']}

                        # Check if this PO line still needs more tablets
                        current_total = po_line_running_totals[line['id']]['good'] + po_line_running_totals[line['id']]['damaged']
                        if current_total < line['quantity_ordered']:
                            # This PO still has room, assign to it
                            assigned_po_id = line['po_id']
                            break

                    # If all POs are at or above their ordered quantities, assign to the last (newest) PO
                    if assigned_po_id is None and po_lines:
                        assigned_po_id = po_lines[-1]['po_id']
                    conn.execute('''
                        UPDATE warehouse_submissions
                        SET assigned_po_id = ?
                        WHERE id = ?
                    ''', (assigned_po_id, submission['id']))

                    # IMPORTANT: Only allocate counts to lines from the ASSIGNED PO
                    # This ensures older POs are completely filled before newer ones receive submissions
                    assigned_po_lines = [line for line in po_lines if line['po_id'] == assigned_po_id]

                    # Allocate counts to PO lines from the assigned PO only
                    # Note: We do NOT cap at ordered quantity - actual production may exceed the PO
                    remaining_good = good_tablets
                    remaining_damaged = packaging_cards_reopened

                    for line in assigned_po_lines:
                        if remaining_good <= 0 and remaining_damaged <= 0:
                            break

                        # Apply all remaining good count to this line
                        if remaining_good > 0:
                            conn.execute('''
                                UPDATE po_lines
                                SET good_count = good_count + ?
                                WHERE id = ?
                            ''', (remaining_good, line['id']))
                            # Update running total
                            if line['id'] in po_line_running_totals:
                                po_line_running_totals[line['id']]['good'] += remaining_good
                            remaining_good = 0

                        # Apply all remaining damaged count to this line
                        if remaining_damaged > 0:
                            conn.execute('''
                                UPDATE po_lines
                                SET damaged_count = damaged_count + ?
                                WHERE id = ?
                            ''', (remaining_damaged, line['id']))
                            # Update running total
                            if line['id'] in po_line_running_totals:
                                po_line_running_totals[line['id']]['damaged'] += remaining_damaged
                            remaining_damaged = 0

                        updated_pos.add(line['po_id'])
                        break  # All counts applied to first line

                    matched_count += 1
                except Exception as e:
                    current_app.logger.error(f"Error processing submission {submission.get('id')}: {e}")
                    continue

            # Step 4: Update PO header totals
            for po_id in updated_pos:
                totals_row = conn.execute('''
                    SELECT
                        COALESCE(SUM(quantity_ordered), 0) as total_ordered,
                        COALESCE(SUM(good_count), 0) as total_good,
                        COALESCE(SUM(damaged_count), 0) as total_damaged
                    FROM po_lines
                    WHERE po_id = ?
                ''', (po_id,)).fetchone()

                totals = dict(totals_row)
                remaining = totals.get('total_ordered', 0) - totals.get('total_good', 0) - totals.get('total_damaged', 0)

                conn.execute('''
                    UPDATE purchase_orders
                    SET ordered_quantity = ?, current_good_count = ?,
                        current_damaged_count = ?, remaining_quantity = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (totals.get('total_ordered', 0), totals.get('total_good', 0),
                      totals.get('total_damaged', 0), remaining, po_id))

            return jsonify({
                'success': True,
                'message': f'✅ Reassigned all {matched_count} submissions to POs using correct order (by PO number)',
                'matched': matched_count,
                'total_submissions': len(all_submissions)
            })
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        current_app.logger.error(f"REASSIGN ERROR: {str(e)}")
        current_app.logger.error(error_trace)
        return jsonify({'error': str(e), 'trace': error_trace}), 500



@bp.route('/api/recalculate_po_counts', methods=['POST'])
@admin_required
def recalculate_po_counts():
    """
    Recalculate PO line counts based on currently assigned submissions.
    Does NOT change any PO assignments - just fixes the counts to match actual submissions.
    """
    try:
        with db_transaction() as conn:
            current_app.logger.info("🔄 Recalculating PO counts without changing assignments...")

            # Step 1: Reset all PO line counts to zero
            conn.execute('UPDATE po_lines SET good_count = 0, damaged_count = 0')

            # Step 2: Get all submissions with inventory_item_id (now stored directly!)
            # Use COALESCE to fallback to JOIN for old submissions without inventory_item_id
            submissions_query = '''
                SELECT
                    ws.id as submission_id,
                    ws.assigned_po_id,
                    ws.product_name,
                    ws.displays_made,
                    ws.packs_remaining,
                    ws.loose_tablets,
                    ws.cards_reopened,
                    ws.tablets_pressed_into_cards,
                    COALESCE(ws.submission_type, 'packaged') as submission_type,
                    ws.created_at,
                    pd.packages_per_display,
                    pd.tablets_per_package,
                    COALESCE(ws.inventory_item_id, tt.inventory_item_id) as inventory_item_id
                FROM warehouse_submissions ws
                LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                WHERE ws.assigned_po_id IS NOT NULL
                ORDER BY ws.created_at ASC
            '''
            submissions = conn.execute(submissions_query).fetchall()

            # Group submissions by PO and inventory_item_id
            po_line_totals = {}  # {(po_id, inventory_item_id): {'good': X, 'damaged': Y}}
            skipped_submissions = []

            for sub in submissions:
                po_id = sub['assigned_po_id']
                inventory_item_id = sub['inventory_item_id']

                if not inventory_item_id:
                    submission_type = sub.get('submission_type', 'packaged')
                    if submission_type == 'machine':
                        good_tablets = sub.get('tablets_pressed_into_cards', 0) or 0
                    elif submission_type == 'repack':
                        packages_per_display = sub['packages_per_display'] or 0
                        tablets_per_package = sub['tablets_per_package'] or 0
                        good_tablets = (
                            (sub['displays_made'] or 0) * packages_per_display * tablets_per_package +
                            (sub['packs_remaining'] or 0) * tablets_per_package
                        )
                    else:
                        packages_per_display = sub['packages_per_display'] or 0
                        tablets_per_package = sub['tablets_per_package'] or 0
                        good_tablets = (
                            (sub['displays_made'] or 0) * packages_per_display * tablets_per_package +
                            (sub['packs_remaining'] or 0) * tablets_per_package +
                            (sub['loose_tablets'] or 0)
                        )
                    skipped_submissions.append({
                        'submission_id': sub['submission_id'],
                        'product_name': sub['product_name'],
                        'good_tablets': good_tablets,
                        'cards_reopened': sub['cards_reopened'] or 0,
                        'created_at': sub['created_at'],
                        'po_id': sub['assigned_po_id']
                    })
                    current_app.logger.warning(f"⚠️ Skipped submission ID {sub['submission_id']}: {sub['product_name']} - {good_tablets} tablets (no inventory_item_id)")
                    continue

                # Calculate good and receiving-line damaged counts (packaging cards_reopened never here)
                submission_type = sub.get('submission_type', 'packaged')
                if submission_type == 'machine':
                    good_tablets = sub.get('tablets_pressed_into_cards', 0) or 0
                    line_damaged_delta = 0
                elif submission_type == 'repack':
                    packages_per_display = sub['packages_per_display'] or 0
                    tablets_per_package = sub['tablets_per_package'] or 0
                    good_tablets = (
                        (sub['displays_made'] or 0) * packages_per_display * tablets_per_package +
                        (sub['packs_remaining'] or 0) * tablets_per_package
                    )
                    line_damaged_delta = 0
                else:
                    packages_per_display = sub['packages_per_display'] or 0
                    tablets_per_package = sub['tablets_per_package'] or 0
                    good_tablets = (
                        (sub['displays_made'] or 0) * packages_per_display * tablets_per_package +
                        (sub['packs_remaining'] or 0) * tablets_per_package +
                        (sub['loose_tablets'] or 0)
                    )
                    line_damaged_delta = 0

                # Add to cumulative totals for this PO line
                key = (po_id, inventory_item_id)
                if key not in po_line_totals:
                    po_line_totals[key] = {'good': 0, 'damaged': 0}

                po_line_totals[key]['good'] += good_tablets
                po_line_totals[key]['damaged'] += line_damaged_delta

            # Step 3: Update each PO line with the calculated totals
            updated_count = 0
            for (po_id, inventory_item_id), totals in po_line_totals.items():
                # Find the PO line for this PO and inventory item
                line = conn.execute('''
                    SELECT id FROM po_lines
                    WHERE po_id = ? AND inventory_item_id = ?
                    LIMIT 1
                ''', (po_id, inventory_item_id)).fetchone()

                if line:
                    conn.execute('''
                        UPDATE po_lines
                        SET good_count = ?, damaged_count = ?
                        WHERE id = ?
                    ''', (totals['good'], totals['damaged'], line['id']))
                    updated_count += 1
                    current_app.logger.debug(f"✅ Updated PO line {line['id']}: {totals['good']} good, {totals['damaged']} damaged")

            # Step 4: Update PO header totals from line totals
            conn.execute('''
                UPDATE purchase_orders
                SET
                    ordered_quantity = (
                        SELECT COALESCE(SUM(quantity_ordered), 0)
                        FROM po_lines
                        WHERE po_lines.po_id = purchase_orders.id
                    ),
                    current_good_count = (
                        SELECT COALESCE(SUM(good_count), 0)
                        FROM po_lines
                        WHERE po_lines.po_id = purchase_orders.id
                    ),
                    current_damaged_count = (
                        SELECT COALESCE(SUM(damaged_count), 0)
                        FROM po_lines
                        WHERE po_lines.po_id = purchase_orders.id
                    ),
                    remaining_quantity = (
                        SELECT COALESCE(SUM(quantity_ordered), 0) - COALESCE(SUM(good_count), 0) - COALESCE(SUM(damaged_count), 0)
                        FROM po_lines
                        WHERE po_lines.po_id = purchase_orders.id
                    ),
                    updated_at = CURRENT_TIMESTAMP
            ''')

            # Build response message
            message = f'Successfully recalculated counts for {updated_count} PO lines. No assignments were changed.'
            skipped_by_product = {}

            if skipped_submissions:
                # Group skipped by product
                for skip in skipped_submissions:
                    product = skip['product_name']
                    if product not in skipped_by_product:
                        skipped_by_product[product] = {'good': 0, 'damaged': 0}
                    skipped_by_product[product]['good'] += skip['good_tablets']
                    skipped_by_product[product]['damaged'] += skip['cards_reopened']

                message += f'\n\n⚠️ WARNING: {len(skipped_submissions)} submissions were skipped (missing product configuration):\n'
                for product, totals in skipped_by_product.items():
                    message += f'\n• {product}: {totals["good"]} tablets (damaged: {totals["damaged"]})'
                message += '\n\nTo fix: Go to "Manage Products" and ensure each product is linked to a tablet type with an inventory_item_id.'

            return jsonify({
                'success': True,
                'message': message,
                'skipped_count': len(skipped_submissions),
                'skipped_details': skipped_by_product
            })
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        current_app.logger.error(f"RECALCULATE ERROR: {str(e)}")
        current_app.logger.error(error_trace)
        return jsonify({'error': str(e), 'trace': error_trace}), 500
