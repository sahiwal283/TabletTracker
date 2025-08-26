"""
Admin panel routes
"""

from flask import render_template, request, session, redirect, url_for, flash, jsonify, current_app
from datetime import datetime
from . import bp
from ..utils.decorators import admin_required
from ..models.database import get_db

@bp.route('/')
@admin_required
def admin_panel():
    """Main admin panel with quick actions and product management"""
    return render_template('admin_panel.html')

@bp.route('/employees')
@admin_required
def manage_employees():
    """Employee management page"""
    conn = get_db()
    
    # Robust query with multiple fallbacks
    try:
        # Try with both role and preferred_language columns
        employees = conn.execute('''
            SELECT id, username, full_name, role, is_active, created_at, preferred_language
            FROM employees 
            ORDER BY role, full_name
        ''').fetchall()
    except Exception as e:
        try:
            # Try with just role column (no preferred_language)
            employees = conn.execute('''
                SELECT id, username, full_name, role, is_active, created_at, 'en' as preferred_language
                FROM employees 
                ORDER BY role, full_name
            ''').fetchall()
        except Exception:
            try:
                # Try with just preferred_language column (no role)  
                employees = conn.execute('''
                    SELECT id, username, full_name, 'warehouse_staff' as role, is_active, created_at, preferred_language
                    FROM employees 
                    ORDER BY full_name
                ''').fetchall()
            except Exception:
                # Fallback to basic query with defaults
                employees = conn.execute('''
                    SELECT id, username, full_name, 'warehouse_staff' as role, is_active, created_at, 'en' as preferred_language
                    FROM employees 
                    ORDER BY full_name
                ''').fetchall()
    
    conn.close()
    return render_template('employee_management.html', employees=employees)

@bp.route('/products')
@admin_required
def product_mapping():
    """Product configuration and mapping page"""
    conn = get_db()
    
    # Get all products with their tablet type info
    products = conn.execute('''
        SELECT pd.*, tt.tablet_type_name, tt.inventory_item_id
        FROM product_details pd
        LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
        ORDER BY pd.product_name
    ''').fetchall()
    
    # Get all tablet types for dropdown
    tablet_types = conn.execute('''
        SELECT * FROM tablet_types ORDER BY tablet_type_name
    ''').fetchall()
    
    conn.close()
    return render_template('product_mapping.html', products=products, tablet_types=tablet_types)

@bp.route('/tablet_types')
@admin_required  
def tablet_types_config():
    """Tablet types configuration page"""
    conn = get_db()
    tablet_types = conn.execute('''
        SELECT * FROM tablet_types ORDER BY tablet_type_name
    ''').fetchall()
    conn.close()
    return render_template('tablet_types_config.html', tablet_types=tablet_types)

@bp.route('/shipments')
@admin_required
def shipments_management():
    """Shipments management page"""
    conn = get_db()
    
    # Get POs with shipping info
    pos_with_shipments = conn.execute('''
        SELECT po.*, s.tracking_number, s.carrier, s.status as shipment_status
        FROM purchase_orders po
        LEFT JOIN shipments s ON po.id = s.po_id
        WHERE po.closed = FALSE
        ORDER BY po.po_number DESC
    ''').fetchall()
    
    conn.close()
    return render_template('shipments_management.html', pos_with_shipments=pos_with_shipments)

@bp.route('/login', methods=['POST'])
def admin_login():
    """Handle admin login with enhanced security"""
    password = request.form.get('password', '').strip()
    
    if not password:
        flash('Password is required', 'error')
        return redirect(url_for('auth.index'))
    
    # Simple password check (in production, use proper authentication)
    from ..config import Config
    if password == Config.ADMIN_PASSWORD:
        session['admin_authenticated'] = True
        session.permanent = True
        from datetime import timedelta
        current_app.permanent_session_lifetime = timedelta(hours=8)
        
        # Clear any existing employee session
        session.pop('employee_authenticated', None)
        session.pop('employee_id', None)
        session.pop('employee_name', None)
        session.pop('employee_role', None)
        
        return redirect(url_for('admin.admin_panel'))
    else:
        flash('Invalid admin password', 'error')
        return redirect(url_for('auth.index'))

@bp.route('/logout')
def admin_logout():
    """Admin logout (redirects to unified logout)"""
    return redirect(url_for('auth.logout'))
