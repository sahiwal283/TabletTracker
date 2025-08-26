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

# Zoho Integration API
@bp.route('/sync_zoho_pos', methods=['POST'])
@admin_required
def sync_zoho_pos():
    """Sync Purchase Orders from Zoho Inventory"""
    try:
        from zoho_integration import zoho_api
        success, message = zoho_api.sync_purchase_orders()
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        current_app.logger.error(f"Zoho sync error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@bp.route('/test_zoho_connection')
def test_zoho_connection():
    """Test if Zoho API credentials are working"""
    try:
        from zoho_integration import zoho_api
        result = zoho_api.test_connection()
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# Product Management API
@bp.route('/save_product', methods=['POST'])
@admin_required
def save_product():
    """Save or update product configuration"""
    try:
        data = request.get_json()
        product_name = data.get('product_name', '').strip()
        tablet_type_id = data.get('tablet_type_id', type=int)
        packages_per_display = data.get('packages_per_display', type=int)
        tablets_per_package = data.get('tablets_per_package', type=int)
        
        if not all([product_name, tablet_type_id, packages_per_display, tablets_per_package]):
            return jsonify({'success': False, 'error': 'All fields are required'}), 400
        
        conn = get_db()
        
        # Check if product exists
        existing = conn.execute('SELECT id FROM product_details WHERE product_name = ?', (product_name,)).fetchone()
        
        if existing:
            # Update existing
            conn.execute('''
                UPDATE product_details 
                SET tablet_type_id = ?, packages_per_display = ?, tablets_per_package = ?
                WHERE product_name = ?
            ''', (tablet_type_id, packages_per_display, tablets_per_package, product_name))
        else:
            # Insert new
            conn.execute('''
                INSERT INTO product_details (product_name, tablet_type_id, packages_per_display, tablets_per_package)
                VALUES (?, ?, ?, ?)
            ''', (product_name, tablet_type_id, packages_per_display, tablets_per_package))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Product saved successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@bp.route('/delete_product/<int:product_id>', methods=['DELETE'])
@admin_required
def delete_product(product_id):
    """Delete a product configuration"""
    try:
        conn = get_db()
        
        # Get product name first
        product = conn.execute('SELECT product_name FROM product_details WHERE id = ?', (product_id,)).fetchone()
        if not product:
            return jsonify({'success': False, 'error': 'Product not found'}), 404
        
        # Delete the product
        conn.execute('DELETE FROM product_details WHERE id = ?', (product_id,))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f'Deleted {product["product_name"]}'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# Tablet Type Management API
@bp.route('/add_tablet_type', methods=['POST'])
@admin_required
def add_tablet_type():
    """Add a new tablet type"""
    try:
        data = request.get_json()
        tablet_type_name = data.get('tablet_type_name', '').strip()
        inventory_item_id = data.get('inventory_item_id', '').strip()
        
        if not tablet_type_name:
            return jsonify({'success': False, 'error': 'Tablet type name is required'}), 400
        
        conn = get_db()
        
        # Check if already exists
        existing = conn.execute('SELECT id FROM tablet_types WHERE tablet_type_name = ?', (tablet_type_name,)).fetchone()
        if existing:
            return jsonify({'success': False, 'error': 'Tablet type already exists'}), 400
        
        # Insert new tablet type
        conn.execute('''
            INSERT INTO tablet_types (tablet_type_name, inventory_item_id)
            VALUES (?, ?)
        ''', (tablet_type_name, inventory_item_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Tablet type added successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@bp.route('/delete_tablet_type/<int:tablet_type_id>', methods=['DELETE'])
@admin_required
def delete_tablet_type(tablet_type_id):
    """Delete a tablet type and its associated products"""
    try:
        conn = get_db()
        
        # Get tablet type info
        tablet_type = conn.execute('SELECT tablet_type_name FROM tablet_types WHERE id = ?', (tablet_type_id,)).fetchone()
        if not tablet_type:
            return jsonify({'success': False, 'error': 'Tablet type not found'}), 404
        
        # Delete associated products first
        conn.execute('DELETE FROM product_details WHERE tablet_type_id = ?', (tablet_type_id,))
        
        # Delete tablet type
        conn.execute('DELETE FROM tablet_types WHERE id = ?', (tablet_type_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f'Deleted {tablet_type["tablet_type_name"]} and its products'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# PO Management API
@bp.route('/po_lines/<int:po_id>')
def get_po_lines(po_id):
    """Get line items for a specific PO"""
    try:
        conn = get_db()
        lines = conn.execute('''
            SELECT * FROM po_lines WHERE po_id = ? ORDER BY line_item_name
        ''', (po_id,)).fetchall()
        conn.close()
        
        return jsonify([dict(line) for line in lines])
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/clear_po_data', methods=['POST'])
@admin_required
def clear_po_data():
    """Clear all PO data (dangerous operation)"""
    try:
        conn = get_db()
        conn.execute('DELETE FROM warehouse_submissions')
        conn.execute('DELETE FROM po_lines')  
        conn.execute('DELETE FROM purchase_orders')
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'All PO data cleared'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# Shipment Management API
@bp.route('/save_shipment', methods=['POST'])
@admin_required
def save_shipment():
    """Save shipment information (supports multiple shipments per PO)"""
    try:
        data = request.get_json()
        po_id = data.get('po_id', type=int)
        tracking_number = data.get('tracking_number', '').strip()
        carrier = data.get('carrier', '').strip()
        
        if not all([po_id, tracking_number, carrier]):
            return jsonify({'success': False, 'error': 'All fields are required'}), 400
        
        conn = get_db()
        
        # Insert shipment
        conn.execute('''
            INSERT INTO shipments (po_id, tracking_number, carrier, status, created_at)
            VALUES (?, ?, ?, 'Pending', ?)
        ''', (po_id, tracking_number, carrier, datetime.now()))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Shipment saved successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# Receiving Management API  
@bp.route('/process_receiving', methods=['POST'])
@admin_required
def process_receiving():
    """Process receiving of shipment"""
    try:
        data = request.get_json()
        po_id = data.get('po_id', type=int)
        shipment_id = data.get('shipment_id', type=int)
        package_condition = data.get('package_condition', '').strip()
        received_by = data.get('received_by', '').strip()
        notes = data.get('notes', '').strip()
        
        if not all([po_id, package_condition, received_by]):
            return jsonify({'success': False, 'error': 'Required fields missing'}), 400
        
        conn = get_db()
        
        # Insert receiving record
        receiving_id = conn.execute('''
            INSERT INTO receiving (po_id, shipment_id, package_condition, received_by, notes, received_date)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (po_id, shipment_id, package_condition, received_by, notes, datetime.now())).lastrowid
        
        # Update shipment status if provided
        if shipment_id:
            conn.execute('''
                UPDATE shipments SET status = 'Delivered', actual_delivery = ? WHERE id = ?
            ''', (datetime.now().date(), shipment_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Receiving processed successfully', 'receiving_id': receiving_id})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
