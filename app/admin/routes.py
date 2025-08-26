"""
Admin panel routes
"""

from flask import render_template, request, session, redirect, url_for, flash, jsonify
from . import bp
from ..utils.decorators import admin_required
from ..models.database import get_db

@bp.route('/')
@admin_required
def admin_panel():
    """Main admin panel"""
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

# Additional admin routes would go here...
# (Product configuration, tablet types, etc.)
