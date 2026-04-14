"""
Admin routes
"""
import sqlite3
import json
import traceback
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session, current_app

from config import Config
from app.services.workflow_finalize import force_release_card
from app.services.workflow_txn import run_with_busy_retry
from app.utils.auth_utils import admin_required
from app.utils.db_utils import db_read_only, db_transaction, get_db
from app.utils.route_helpers import ensure_app_settings_table

bp = Blueprint('admin', __name__)

@bp.route('/admin')
def admin_panel():
    """Admin panel with quick actions and product management"""
    # Check for admin session
    if not session.get('admin_authenticated'):
        return render_template('admin_login.html')
    
    try:
        ensure_app_settings_table()  # Ensure table exists
        with db_read_only() as conn:
            # Get current settings
            cards_per_turn = conn.execute(
                'SELECT setting_value FROM app_settings WHERE setting_key = ?',
                ('cards_per_turn',)
            ).fetchone()
            cards_per_turn_value = int(cards_per_turn['setting_value']) if cards_per_turn else 1
            return render_template('admin_panel.html', cards_per_turn=cards_per_turn_value)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return render_template('admin_panel.html', cards_per_turn=1)



@bp.route('/admin/login', methods=['POST'])
def admin_login():
    """Handle admin login with enhanced security"""
    password = request.form.get('password') or request.json.get('password')
    
    # Get admin password from environment variable with secure default
    admin_password = Config.ADMIN_PASSWORD
    
    if password == admin_password:
        session['admin_authenticated'] = True
        session['employee_role'] = 'admin'  # Set admin role for navigation
        session['login_time'] = datetime.now().isoformat()
        session.permanent = True  # Make session permanent
        # Note: session lifetime is set in app factory
        
        return redirect(url_for('admin.admin_panel')) if request.form else jsonify({'success': True})
    else:
        # Log failed login attempt
        current_app.logger.warning(f"Failed admin login attempt from {request.remote_addr} at {datetime.now()}")
        
        if request.form:
            flash('Invalid password', 'error')
            return render_template('admin_login.html')
        else:
            return jsonify({'success': False, 'error': 'Invalid password'})



@bp.route('/admin/logout')
def admin_logout():
    """Logout admin - redirect to unified logout"""
    return redirect(url_for('auth.logout'))



@bp.route('/admin/products')
@admin_required
def product_mapping():
    """Redirect to unified product configuration page"""
    return redirect(url_for('admin.product_config'))


@bp.route('/admin/tablet_types')
@admin_required
def tablet_types_config():
    """Redirect to unified product configuration page"""
    return redirect(url_for('admin.product_config'))


@bp.route('/admin/config')
@admin_required
def product_config():
    """Unified product & tablet type configuration page"""
    try:
        with db_transaction() as conn:
            # Get all products with their tablet type and calculation details
            products = conn.execute('''
                SELECT pd.*, tt.tablet_type_name, tt.inventory_item_id, 
                       COALESCE(pd.category, tt.category) as category
                FROM product_details pd
                LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                ORDER BY COALESCE(pd.category, tt.category, 'ZZZ'), pd.product_name
            ''').fetchall()
            
            # Check if category column exists and add it if missing
            table_info = conn.execute("PRAGMA table_info(tablet_types)").fetchall()
            has_category_column = any(col[1] == 'category' for col in table_info)
            
            if not has_category_column:
                try:
                    conn.execute('ALTER TABLE tablet_types ADD COLUMN category TEXT')
                    conn.commit()
                    has_category_column = True
                except Exception as e:
                    current_app.logger.warning(f"Warning: Could not add category column: {e}")
            
            # Get all tablet types
            tablet_types_rows = conn.execute('''
                SELECT * FROM tablet_types 
                ORDER BY COALESCE(category, 'ZZZ'), tablet_type_name
            ''').fetchall()
            tablet_types = [dict(row) for row in tablet_types_rows]
            
            # Get unique categories from tablet_types (in use)
            categories = conn.execute('''
                SELECT DISTINCT category FROM tablet_types 
                WHERE category IS NOT NULL AND category != "" 
                ORDER BY category
            ''').fetchall()
            category_list = [cat['category'] for cat in categories] if categories else []
            category_set = set(category_list)
            
            # Get created categories from app_settings (may not be in use yet)
            try:
                created_categories_json = conn.execute('''
                    SELECT setting_value FROM app_settings WHERE setting_key = 'created_categories'
                ''').fetchone()
                if created_categories_json and created_categories_json['setting_value']:
                    created_categories = json.loads(created_categories_json['setting_value'])
                    # Add to category list (union)
                    for cat in created_categories:
                        if cat and cat not in category_set:
                            category_list.append(cat)
                            category_set.add(cat)
            except Exception as e:
                current_app.logger.warning(f"Warning: Could not load created categories: {e}")
            
            # Get deleted categories from app_settings
            deleted_categories_set = set()
            try:
                deleted_categories_json = conn.execute('''
                    SELECT setting_value FROM app_settings WHERE setting_key = 'deleted_categories'
                ''').fetchone()
                if deleted_categories_json and deleted_categories_json['setting_value']:
                    deleted_categories_set = set(json.loads(deleted_categories_json['setting_value']))
            except Exception as e:
                current_app.logger.warning(f"Warning: Could not load deleted categories: {e}")
            
            # Get category order from app_settings
            try:
                category_order_json = conn.execute('''
                    SELECT setting_value FROM app_settings WHERE setting_key = 'category_order'
                ''').fetchone()
                if category_order_json and category_order_json['setting_value']:
                    preferred_order = json.loads(category_order_json['setting_value'])
                else:
                    preferred_order = sorted(category_list)
            except Exception as e:
                current_app.logger.warning(f"Warning: Could not load category order: {e}")
                preferred_order = sorted(category_list)
            
            # Filter out deleted categories
            all_categories = [cat for cat in category_list if cat not in deleted_categories_set]
            all_categories.sort(key=lambda x: (preferred_order.index(x) if x in preferred_order else len(preferred_order) + 1, x))
            
            # Find tablet types that don't have product configurations yet
            product_tablet_type_ids = set(p['tablet_type_id'] for p in products if p['tablet_type_id'])
            tablet_types_without_products = [tt for tt in tablet_types if tt['id'] not in product_tablet_type_ids]
            
            return render_template('product_config.html', 
                                   products=products, 
                                   tablet_types=tablet_types, 
                                   categories=all_categories, 
                                   tablet_types_without_products=tablet_types_without_products)
    except Exception as e:
        current_app.logger.error(f"Error loading product config: {str(e)}")
        flash(f'Error loading configuration: {str(e)}', 'error')
        return render_template('product_config.html', products=[], tablet_types=[], categories=[], tablet_types_without_products=[])



@bp.route('/admin/fix-bags')
@admin_required
def fix_bags_page():
    """Page to fix bag assignments"""
    return render_template('fix_bags.html')


@bp.route('/admin/employees')
@admin_required
def manage_employees():
    """Employee management page"""
    try:
        with db_read_only() as conn:
            employees = conn.execute('''
                SELECT id, username, full_name, role, is_active, created_at
                FROM employees 
                ORDER BY role, full_name
            ''').fetchall()
            
            return render_template('employee_management.html', employees=employees)
    except Exception as e:
        current_app.logger.error(f"Error in manage_employees: {e}")
        traceback.print_exc()
        flash('An error occurred while loading employees', 'error')
        return render_template('employee_management.html', employees=[])


@bp.route("/admin/workflow-qr")
@admin_required
def workflow_qr_management():
    """List workflow stations and QR cards; release card↔bag assignments."""
    try:
        with db_read_only() as conn:
            stations = []
            cards = []
            sealing_machines = []
            try:
                stations = conn.execute(
                    """
                    SELECT ws.id, ws.label, ws.station_scan_token, ws.station_code, ws.machine_id,
                           m.machine_name AS machine_name
                    FROM workflow_stations ws
                    LEFT JOIN machines m ON m.id = ws.machine_id
                    ORDER BY ws.id
                    """
                ).fetchall()
                stations = [dict(r) for r in stations]
            except sqlite3.OperationalError:
                try:
                    stations = conn.execute(
                        """
                        SELECT id, label, station_scan_token, station_code, NULL AS machine_id,
                               NULL AS machine_name
                        FROM workflow_stations
                        ORDER BY id
                        """
                    ).fetchall()
                    stations = [dict(r) for r in stations]
                except sqlite3.OperationalError:
                    pass
            try:
                sealing_machines = conn.execute(
                    """
                    SELECT id, machine_name
                    FROM machines
                    WHERE COALESCE(is_active, 1) = 1 AND machine_role = 'sealing'
                    ORDER BY machine_name
                    """
                ).fetchall()
                sealing_machines = [dict(r) for r in sealing_machines]
            except sqlite3.OperationalError:
                pass
            try:
                cards = conn.execute(
                    """
                    SELECT qc.id, qc.label, qc.scan_token, qc.status, qc.assigned_workflow_bag_id,
                           wb.inventory_bag_id
                    FROM qr_cards qc
                    LEFT JOIN workflow_bags wb ON wb.id = qc.assigned_workflow_bag_id
                    ORDER BY qc.id
                    """
                ).fetchall()
                cards = [dict(r) for r in cards]
            except sqlite3.OperationalError:
                pass
        return render_template(
            "admin_workflow_qr.html",
            stations=stations,
            sealing_machines=sealing_machines,
            cards=cards,
        )
    except Exception as e:
        current_app.logger.error("workflow_qr_management: %s", e)
        traceback.print_exc()
        flash("Could not load workflow QR data.", "error")
        return render_template(
            "admin_workflow_qr.html",
            stations=[],
            sealing_machines=[],
            cards=[],
        )


@bp.route("/admin/workflow-qr/release", methods=["POST"])
@admin_required
def workflow_qr_release_card():
    """Undo card assignment (same policy as staff force-release)."""
    workflow_bag_id = request.form.get("workflow_bag_id", type=int)
    qr_card_id = request.form.get("qr_card_id", type=int)
    reason = (request.form.get("reason") or "admin_panel_release").strip()
    uid = session.get("employee_id")
    if session.get("admin_authenticated"):
        uid = None
    if not workflow_bag_id or not qr_card_id:
        flash("workflow_bag_id and qr_card_id are required.", "error")
        return redirect(url_for("admin.workflow_qr_management"))

    conn = get_db()
    try:

        def _run():
            return force_release_card(
                conn,
                workflow_bag_id=workflow_bag_id,
                qr_card_id=qr_card_id,
                reason=reason,
                user_id=uid,
            )

        try:
            st, body = run_with_busy_retry(_run, op_name="admin_force_release")
        except sqlite3.OperationalError:
            flash("Database busy; retry.", "error")
            return redirect(url_for("admin.workflow_qr_management"))

        if st == "reject":
            flash(body.get("code", "release rejected"), "error")
        elif st == "duplicate":
            flash("Card was already idle (no change).", "info")
        else:
            conn.commit()
            flash(f"Released QR card #{qr_card_id} from workflow bag #{workflow_bag_id}.", "success")
    finally:
        conn.close()
    return redirect(url_for("admin.workflow_qr_management"))


@bp.route("/admin/workflow-qr/station-machine", methods=["POST"])
@admin_required
def workflow_qr_map_station_machine():
    """Link a workflow sealing station to a production machine (machine count form)."""
    station_id = request.form.get("station_id", type=int)
    raw_mid = request.form.get("machine_id")
    machine_id = None
    if raw_mid is not None and str(raw_mid).strip() != "":
        machine_id = int(str(raw_mid).strip())
    if not station_id:
        flash("station_id is required.", "error")
        return redirect(url_for("admin.workflow_qr_management"))

    try:
        with db_transaction() as conn:
            st = conn.execute(
                "SELECT id FROM workflow_stations WHERE id = ?", (station_id,)
            ).fetchone()
            if not st:
                flash("Unknown sealing station.", "error")
                return redirect(url_for("admin.workflow_qr_management"))
            if machine_id is not None:
                m = conn.execute(
                    """
                    SELECT id FROM machines
                    WHERE id = ? AND COALESCE(is_active, 1) = 1 AND machine_role = 'sealing'
                    """,
                    (machine_id,),
                ).fetchone()
                if not m:
                    flash("Invalid or inactive sealing machine.", "error")
                    return redirect(url_for("admin.workflow_qr_management"))
            conn.execute(
                "UPDATE workflow_stations SET machine_id = ? WHERE id = ?",
                (machine_id, station_id),
            )
        flash("Sealing station ↔ machine mapping saved.", "success")
    except sqlite3.OperationalError as oe:
        current_app.logger.error("workflow_qr_map_station_machine: %s", oe)
        flash("Could not update mapping (database error).", "error")
    except Exception as e:
        current_app.logger.error("workflow_qr_map_station_machine: %s", e)
        flash(str(e), "error")
    return redirect(url_for("admin.workflow_qr_management"))

