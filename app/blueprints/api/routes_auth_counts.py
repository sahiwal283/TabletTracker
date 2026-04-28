"""
API routes - all /api/* endpoints
"""
from datetime import datetime, timedelta

from flask import current_app, flash, jsonify, redirect, render_template, request, session, url_for

from app.utils.auth_utils import (
    role_required,
    verify_password,
)
from app.utils.db_utils import db_read_only, db_transaction

from . import bp


@bp.route('/api/po/<int:po_id>/max_bag_numbers', methods=['GET'])
@role_required('shipping')
def get_po_max_bag_numbers(po_id):
    """Get the maximum bag number for each flavor (tablet_type) in a PO across all receives.

    Query param ``exclude_receiving_id`` (optional): omit bags on that receiving row so
    draft-edit / form reload does not double-count the receive being edited when building
    flavor bag baselines.
    """
    try:
        exclude_raw = request.args.get('exclude_receiving_id')
        exclude_receiving_id = None
        if exclude_raw is not None and str(exclude_raw).strip() != '':
            try:
                exclude_receiving_id = int(exclude_raw)
            except (TypeError, ValueError):
                exclude_receiving_id = None

        with db_read_only() as conn:
            # Get max bag number per tablet_type_id for all bags in this PO
            # Join through receiving -> small_boxes -> bags
            params: list = [po_id]
            where_extra = ''
            if exclude_receiving_id is not None and exclude_receiving_id > 0:
                where_extra = ' AND r.id != ?'
                params.append(exclude_receiving_id)

            max_bag_numbers = conn.execute(
                f'''
                SELECT b.tablet_type_id, MAX(b.bag_number) as max_bag_number
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN receiving r ON sb.receiving_id = r.id
                WHERE r.po_id = ?{where_extra}
                GROUP BY b.tablet_type_id
                ''',
                tuple(params),
            ).fetchall()

            # Convert to dictionary: {tablet_type_id: max_bag_number}
            result = {}
            for row in max_bag_numbers:
                result[row['tablet_type_id']] = row['max_bag_number'] or 0

            return jsonify({
                'success': True,
                'max_bag_numbers': result
            })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# Route moved to api_receiving.py

# Route moved to api_purchase_orders.py



@bp.route('/login')
def employee_login():
    """Employee login page"""
    return render_template('employee_login.html')

@bp.route('/login', methods=['POST'])
def employee_login_post():
    """Handle employee login"""
    try:
        username = request.form.get('username') or request.json.get('username')
        password = request.form.get('password') or request.json.get('password')

        if not username or not password:
            if request.form:
                flash('Username and password required', 'error')
                return render_template('employee_login.html')
            else:
                return jsonify({'success': False, 'error': 'Username and password required'})

        with db_read_only() as conn:
            employee = conn.execute('''
            SELECT id, username, full_name, password_hash, role, is_active
            FROM employees
            WHERE username = ? AND is_active = TRUE
            ''', (username,)).fetchone()

            if employee and verify_password(password, employee['password_hash']):
                session['employee_authenticated'] = True
                session['employee_id'] = employee['id']
                session['employee_name'] = employee['full_name']
                session['employee_username'] = employee['username']
                session['employee_role'] = employee['role'] if employee['role'] else 'warehouse_staff'
                session.permanent = True
                current_app.permanent_session_lifetime = timedelta(hours=8)

                return redirect(url_for('production.warehouse_form')) if request.form else jsonify({'success': True})
            else:
                # Log failed login attempt
                current_app.logger.warning(f"Failed employee login attempt for {username} from {request.remote_addr} at {datetime.now()}")

                if request.form:
                    flash('Invalid username or password', 'error')
                    return render_template('employee_login.html')
                else:
                    return jsonify({'success': False, 'error': 'Invalid username or password'})
    except Exception as e:
        # Log error but don't expose details to user
        current_app.logger.error(f"Login error: {str(e)}")
        if request.form:
            flash('An error occurred during login', 'error')
            return render_template('employee_login.html')
        else:
            return jsonify({'success': False, 'error': 'An error occurred during login'}), 500

@bp.route('/api/set-language', methods=['POST'])
def set_language():
    """Set language preference for current session and save to employee profile"""
    try:
        data = request.get_json()
        language = data.get('language', '').strip()

        # Validate language
        if language not in current_app.config['LANGUAGES']:
            return jsonify({'success': False, 'error': 'Invalid language'}), 400

        # Set session language with manual override flag
        session['language'] = language
        session['manual_language_override'] = True
        session.permanent = True

        # Save to employee profile if authenticated
        if session.get('employee_authenticated') and session.get('employee_id'):
            try:
                with db_transaction() as conn:
                    conn.execute('''
                        UPDATE employees
                        SET preferred_language = ?
                        WHERE id = ?
                    ''', (language, session.get('employee_id')))
                    current_app.logger.info(f"Language preference saved to database: {language} for employee {session.get('employee_id')}")
            except Exception as e:
                current_app.logger.error(f"Failed to save language preference to database: {str(e)}")
                # Continue without database save - session is still set

        current_app.logger.info(f"Language manually set to {language} for session")

        return jsonify({'success': True, 'message': f'Language set to {language}'})

    except Exception as e:
        current_app.logger.error(f"Language setting error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
