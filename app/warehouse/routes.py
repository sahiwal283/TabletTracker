"""
Warehouse operations routes
"""

from flask import render_template, request, session, redirect, url_for, flash, jsonify, current_app
from datetime import datetime
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
        current_app.logger.error(f"Warehouse form error: {str(e)}")
        flash(f'Error loading warehouse form: {str(e)}', 'error')
        return redirect(url_for('auth.index'))

@bp.route('/submit', methods=['POST'])
@employee_required
def submit_warehouse():
    """Process warehouse form submission"""
    try:
        # Get form data
        product_name = request.form.get('product_name')
        box_number = request.form.get('box_number', type=int)
        bag_number = request.form.get('bag_number', type=int)
        bag_label_count = request.form.get('bag_label_count', type=int)
        displays_made = request.form.get('displays_made', type=int, default=0)
        packs_remaining = request.form.get('packs_remaining', type=int, default=0)
        loose_tablets = request.form.get('loose_tablets', type=int, default=0)
        damaged_tablets = request.form.get('damaged_tablets', type=int, default=0)
        
        # Get employee info
        employee_name = session.get('employee_name', 'Unknown')
        
        # Validation
        if not all([product_name, box_number, bag_number, bag_label_count is not None]):
            flash('All required fields must be filled', 'error')
            return redirect(url_for('warehouse.warehouse_form'))
        
        conn = get_db()
        
        # Get product details for calculation
        product_details = conn.execute('''
            SELECT packages_per_display, tablets_per_package 
            FROM product_details 
            WHERE product_name = ?
        ''', (product_name,)).fetchone()
        
        if not product_details:
            flash(f'Product details not found for {product_name}', 'error')
            return redirect(url_for('warehouse.warehouse_form'))
        
        # Calculate total tablets
        packages_per_display = product_details['packages_per_display'] or 0
        tablets_per_package = product_details['tablets_per_package'] or 0
        
        calculated_total = (
            (displays_made * packages_per_display * tablets_per_package) +
            (packs_remaining * tablets_per_package) + 
            loose_tablets + 
            damaged_tablets
        )
        
        # Check for discrepancy
        discrepancy_flag = (bag_label_count != calculated_total)
        
        # Find matching PO for allocation
        tablet_type = conn.execute('''
            SELECT tt.tablet_type_name, tt.inventory_item_id
            FROM product_details pd
            JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            WHERE pd.product_name = ?
        ''', (product_name,)).fetchone()
        
        assigned_po_id = None
        if tablet_type and tablet_type['inventory_item_id']:
            # Find oldest open PO with matching inventory item ID
            matching_po = conn.execute('''
                SELECT po.id
                FROM purchase_orders po
                JOIN po_lines pl ON po.id = pl.po_id
                WHERE pl.inventory_item_id = ? 
                AND po.closed = FALSE
                AND po.remaining_quantity > 0
                ORDER BY po.po_number ASC
                LIMIT 1
            ''', (tablet_type['inventory_item_id'],)).fetchone()
            
            if matching_po:
                assigned_po_id = matching_po['id']
        
        # Insert warehouse submission
        submission_id = conn.execute('''
            INSERT INTO warehouse_submissions (
                employee_name, product_name, box_number, bag_number, bag_label_count,
                displays_made, packs_remaining, loose_tablets, damaged_tablets,
                discrepancy_flag, assigned_po_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            employee_name, product_name, box_number, bag_number, bag_label_count,
            displays_made, packs_remaining, loose_tablets, damaged_tablets,
            discrepancy_flag, assigned_po_id, datetime.now()
        )).lastrowid
        
        # Update PO quantities if assigned
        if assigned_po_id:
            conn.execute('''
                UPDATE purchase_orders 
                SET current_good_count = current_good_count + ?,
                    current_damaged_count = current_damaged_count + ?,
                    remaining_quantity = ordered_quantity - current_good_count - current_damaged_count - ?,
                    updated_at = ?
                WHERE id = ?
            ''', (calculated_total - damaged_tablets, damaged_tablets, damaged_tablets, datetime.now(), assigned_po_id))
        
        conn.commit()
        conn.close()
        
        # Success message
        message = f'Submission recorded! Total: {calculated_total} tablets'
        if discrepancy_flag:
            message += f' (Discrepancy: Label shows {bag_label_count})'
        if assigned_po_id:
            message += f' - Assigned to PO'
        
        flash(message, 'success')
        return redirect(url_for('warehouse.warehouse_form'))
        
    except Exception as e:
        current_app.logger.error(f"Warehouse submission error: {str(e)}")
        flash(f'Error processing submission: {str(e)}', 'error')
        return redirect(url_for('warehouse.warehouse_form'))

@bp.route('/count')
@employee_required
def count_form():
    """Manual count form for PO close-outs"""
    try:
        conn = get_db()
        
        # Get open POs for selection
        open_pos = conn.execute('''
            SELECT id, po_number, tablet_type, ordered_quantity, 
                   current_good_count, current_damaged_count, remaining_quantity
            FROM purchase_orders 
            WHERE closed = FALSE 
            ORDER BY po_number
        ''').fetchall()
        
        conn.close()
        return render_template('count_form.html', open_pos=open_pos)
        
    except Exception as e:
        current_app.logger.error(f"Count form error: {str(e)}")
        flash(f'Error loading count form: {str(e)}', 'error')
        return redirect(url_for('auth.index'))

@bp.route('/submit_count', methods=['POST'])
@employee_required
def submit_count():
    """Process manual count submission for PO close-outs"""
    try:
        po_id = request.form.get('po_id', type=int)
        good_count = request.form.get('good_count', type=int)
        damaged_count = request.form.get('damaged_count', type=int)
        notes = request.form.get('notes', '').strip()
        employee_name = session.get('employee_name', 'Unknown')
        
        if not all([po_id, good_count is not None, damaged_count is not None]):
            flash('All count fields are required', 'error')
            return redirect(url_for('warehouse.count_form'))
        
        conn = get_db()
        
        # Get PO info
        po = conn.execute('''
            SELECT po_number, ordered_quantity FROM purchase_orders WHERE id = ?
        ''', (po_id,)).fetchone()
        
        if not po:
            flash('Purchase Order not found', 'error')
            return redirect(url_for('warehouse.count_form'))
        
        # Update PO with final counts
        conn.execute('''
            UPDATE purchase_orders 
            SET current_good_count = ?, 
                current_damaged_count = ?,
                remaining_quantity = ordered_quantity - ? - ?,
                closed = CASE WHEN (? + ?) >= ordered_quantity THEN TRUE ELSE FALSE END,
                updated_at = ?
            WHERE id = ?
        ''', (good_count, damaged_count, good_count, damaged_count, 
              good_count, damaged_count, datetime.now(), po_id))
        
        # Record the count submission
        conn.execute('''
            INSERT INTO warehouse_submissions (
                employee_name, product_name, bag_label_count, 
                loose_tablets, damaged_tablets, assigned_po_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (employee_name, f'Manual Count - PO {po["po_number"]}', 
              good_count + damaged_count, good_count, damaged_count, 
              po_id, datetime.now()))
        
        conn.commit()
        conn.close()
        
        total_counted = good_count + damaged_count
        status = "CLOSED" if total_counted >= po['ordered_quantity'] else "UPDATED"
        
        flash(f'PO {po["po_number"]} {status}: {good_count} good, {damaged_count} damaged', 'success')
        return redirect(url_for('warehouse.count_form'))
        
    except Exception as e:
        current_app.logger.error(f"Count submission error: {str(e)}")
        flash(f'Error processing count: {str(e)}', 'error')
        return redirect(url_for('warehouse.count_form'))
