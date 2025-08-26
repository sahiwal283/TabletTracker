"""
Warehouse operations routes
"""

from flask import render_template, request, session, redirect, url_for, flash, jsonify
from . import bp
from ..utils.decorators import employee_required
from ..models.database import get_db

@bp.route('/')
@bp.route('/form')
@employee_required
def warehouse_form():
    """Mobile-optimized form for warehouse staff"""
    try:
        conn = get_db()
        
        # Get product list for dropdown
        products = conn.execute('''
            SELECT pd.product_name, tt.tablet_type_name, pd.packages_per_display, pd.tablets_per_package
            FROM product_details pd
            JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            ORDER BY pd.product_name
        ''').fetchall()
        
        # Get employee info for display - with fallback
        employee = None
        employee_id = session.get('employee_id')
        if employee_id:
            employee = conn.execute('''
                SELECT full_name FROM employees WHERE id = ?
            ''', (employee_id,)).fetchone()
        
        # Fallback to session name if database lookup fails
        if not employee and session.get('employee_name'):
            employee = {'full_name': session.get('employee_name')}
        
        conn.close()
        return render_template('warehouse_form.html', products=products, employee=employee)
        
    except Exception as e:
        flash(f'Error loading warehouse form: {str(e)}', 'error')
        return redirect(url_for('auth.index'))

@bp.route('/count')
@employee_required
def count_form():
    """Manual count form"""
    return render_template('count_form.html')

# Additional warehouse routes would go here...
# (Submit warehouse, product mapping, etc.)
