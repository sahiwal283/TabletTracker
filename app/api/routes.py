"""
API endpoints for TabletTracker
RESTful API for all data operations
"""

from flask import request, jsonify, session, current_app
from . import bp
from ..utils.decorators import admin_required, employee_required
from ..utils.auth import hash_password
from ..models.database import get_db

# Language API
@bp.route('/set-language', methods=['POST'])
def set_language():
    """Set language preference for current session"""
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
        
        current_app.logger.info(f"Language manually set to {language} for session")
        
        return jsonify({'success': True, 'message': f'Language set to {language}'})
        
    except Exception as e:
        current_app.logger.error(f"Language setting error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# Employee Management API
@bp.route('/employees', methods=['POST'])
@admin_required
def add_employee():
    """Add a new employee"""
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        full_name = data.get('full_name', '').strip()
        password = data.get('password', '').strip()
        role = data.get('role', 'warehouse_staff').strip()
        preferred_language = data.get('preferred_language', 'en').strip()
        
        # Validation
        if not all([username, full_name, password]):
            return jsonify({'success': False, 'error': 'All fields are required'}), 400
        
        if role not in ['warehouse_staff', 'manager', 'admin']:
            return jsonify({'success': False, 'error': 'Invalid role'}), 400
        
        if preferred_language not in current_app.config['LANGUAGES']:
            return jsonify({'success': False, 'error': 'Invalid language'}), 400
        
        # Hash password
        password_hash = hash_password(password)
        
        conn = get_db()
        
        # Check if username already exists
        existing = conn.execute('SELECT id FROM employees WHERE username = ?', (username,)).fetchone()
        if existing:
            conn.close()
            return jsonify({'success': False, 'error': 'Username already exists'}), 400
        
        # Auto-migration for role and preferred_language columns
        try:
            conn.execute('''
                INSERT INTO employees (username, full_name, password_hash, role, preferred_language)
                VALUES (?, ?, ?, ?, ?)
            ''', (username, full_name, password_hash, role, preferred_language))
        except Exception as e:
            if "no column named" in str(e).lower():
                # Add missing columns and retry
                try:
                    conn.execute('ALTER TABLE employees ADD COLUMN role TEXT DEFAULT "warehouse_staff"')
                    conn.execute('ALTER TABLE employees ADD COLUMN preferred_language TEXT DEFAULT "en"')
                    conn.commit()
                    conn.execute('''
                        INSERT INTO employees (username, full_name, password_hash, role, preferred_language)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (username, full_name, password_hash, role, preferred_language))
                except:
                    raise e
            else:
                raise e
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Employee added successfully'})
        
    except Exception as e:
        current_app.logger.error(f"Employee creation error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@bp.route('/employees/<int:employee_id>/role', methods=['PUT'])
@admin_required
def update_employee_role(employee_id):
    """Update an employee's role"""
    try:
        data = request.get_json()
        new_role = data.get('role', '').strip()
        
        if new_role not in ['warehouse_staff', 'manager', 'admin']:
            return jsonify({'success': False, 'error': 'Invalid role'}), 400
        
        conn = get_db()
        
        # Auto-migration for role column
        try:
            result = conn.execute('''
                UPDATE employees SET role = ? WHERE id = ?
            ''', (new_role, employee_id))
        except Exception as e:
            if "no column named role" in str(e).lower():
                # Add missing column and retry
                conn.execute('ALTER TABLE employees ADD COLUMN role TEXT DEFAULT "warehouse_staff"')
                conn.commit()
                result = conn.execute('''
                    UPDATE employees SET role = ? WHERE id = ?
                ''', (new_role, employee_id))
            else:
                raise e
        
        conn.commit()
        conn.close()
        
        if result.rowcount == 0:
            return jsonify({'success': False, 'error': 'Employee not found'}), 404
        
        return jsonify({'success': True, 'message': f'Role updated to {new_role}'})
        
    except Exception as e:
        current_app.logger.error(f"Role update error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@bp.route('/employees/<int:employee_id>/language', methods=['PUT'])
@admin_required
def update_employee_language(employee_id):
    """Update an employee's preferred language"""
    conn = None
    try:
        data = request.get_json()
        new_language = data.get('preferred_language', '').strip()

        current_app.logger.info(f"Updating employee {employee_id} language to {new_language}")

        # Validate language
        if new_language not in current_app.config['LANGUAGES']:
            return jsonify({'success': False, 'error': 'Invalid language specified'}), 400

        conn = get_db()

        # Check if employee exists first
        employee = conn.execute('SELECT id FROM employees WHERE id = ?', (employee_id,)).fetchone()
        if not employee:
            return jsonify({'success': False, 'error': 'Employee not found'}), 404

        # Ensure preferred_language column exists
        try:
            # Test if column exists
            conn.execute('SELECT preferred_language FROM employees LIMIT 1').fetchone()
            current_app.logger.info("preferred_language column exists")
        except Exception:
            # Add column
            current_app.logger.info("Adding preferred_language column")
            conn.execute('ALTER TABLE employees ADD COLUMN preferred_language TEXT DEFAULT "en"')
            conn.commit()
            current_app.logger.info("Column added successfully")

        # Update the language
        result = conn.execute('''
            UPDATE employees
            SET preferred_language = ?
            WHERE id = ?
        ''', (new_language, employee_id))
        conn.commit()

        current_app.logger.info(f"Update result: {result.rowcount} rows affected")

        if result.rowcount == 0:
            return jsonify({'success': False, 'error': 'Employee not found'}), 404

        return jsonify({'success': True, 'message': f'Language updated to {new_language}'})

    except Exception as e:
        current_app.logger.error(f"Language update error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            conn.close()

@bp.route('/employees/<int:employee_id>/toggle', methods=['POST'])
@admin_required
def toggle_employee(employee_id):
    """Toggle employee active status"""
    try:
        conn = get_db()
        
        # Get current status
        employee = conn.execute('SELECT is_active FROM employees WHERE id = ?', (employee_id,)).fetchone()
        if not employee:
            conn.close()
            return jsonify({'success': False, 'error': 'Employee not found'}), 404
        
        # Toggle status
        new_status = not employee['is_active']
        conn.execute('UPDATE employees SET is_active = ? WHERE id = ?', (new_status, employee_id))
        conn.commit()
        conn.close()
        
        status_text = 'activated' if new_status else 'deactivated'
        return jsonify({'success': True, 'message': f'Employee {status_text} successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# Version endpoint
@bp.route('/version')
def version():
    """Get application version info"""
    from ..__version__ import __version__, __title__, __description__
    return jsonify({
        'version': __version__,
        'title': __title__,
        'description': __description__
    })

# Health check
@bp.route('/health')
def health_check():
    """Application health check"""
    return jsonify({'status': 'healthy', 'timestamp': 'now'})

# Additional API endpoints would be added here for:
# - Product management
# - Purchase order operations  
# - Warehouse submissions
# - Shipment tracking
# - Reporting data
