from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from datetime import datetime, timedelta
import sqlite3
import json
import os
import requests
import hashlib
from functools import wraps
from config import Config
from zoho_integration import zoho_api
from __version__ import __version__, __title__, __description__
from tracking_service import refresh_shipment_row
from report_service import ProductionReportGenerator
from flask_babel import Babel, gettext, ngettext, lazy_gettext, get_locale

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY

# Configure Babel for internationalization
app.config['LANGUAGES'] = {
    'en': 'English',
    'es': 'Español'
}
app.config['BABEL_DEFAULT_LOCALE'] = 'en'
app.config['BABEL_DEFAULT_TIMEZONE'] = 'UTC'

def get_locale():
    # 1. Check if user explicitly chose a language
    if request.args.get('lang'):
        session['language'] = request.args.get('lang')
        session['manual_language_override'] = True
    
    # 2. Use session language if manually set
    if (session.get('manual_language_override') and 
        'language' in session and session['language'] in app.config['LANGUAGES']):
        return session['language']
    
    # 3. Check employee's preferred language from database (if authenticated)
    if (session.get('employee_authenticated') and session.get('employee_id') and 
        not session.get('manual_language_override')):
        try:
            conn = get_db()
            employee = conn.execute('''
                SELECT preferred_language FROM employees WHERE id = ?
            ''', (session.get('employee_id'),)).fetchone()
            if employee and employee['preferred_language'] and employee['preferred_language'] in app.config['LANGUAGES']:
                session['language'] = employee['preferred_language']
                conn.close()
                return employee['preferred_language']
            conn.close()
        except:
            pass  # Continue to fallback if database query fails
    
    # 4. Use session language if available
    if 'language' in session and session['language'] in app.config['LANGUAGES']:
        return session['language']
    
    # 5. Use browser's preferred language if available
    fallback_lang = request.accept_languages.best_match(app.config['LANGUAGES'].keys()) or app.config['BABEL_DEFAULT_LOCALE']
    session['language'] = fallback_lang
    return fallback_lang

babel = Babel()
babel.init_app(app, locale_selector=get_locale)
# Configure session settings for production security
if Config.ENV == 'production':
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    
# Set permanent session lifetime
app.permanent_session_lifetime = timedelta(seconds=Config.PERMANENT_SESSION_LIFETIME)

# Production error handling
@app.errorhandler(404)
def not_found_error(error):
    if Config.ENV == 'production':
        return render_template('base.html'), 404
    return str(error), 404

@app.errorhandler(500)
def internal_error(error):
    if Config.ENV == 'production':
        return render_template('base.html'), 500
    return str(error), 500

# Security headers for production
@app.after_request
def after_request(response):
    if Config.ENV == 'production':
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

# Database setup
def init_db():
    conn = sqlite3.connect('tablet_counter.db')
    c = conn.cursor()
    
    # Purchase Orders table
    c.execute('''CREATE TABLE IF NOT EXISTS purchase_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        po_number TEXT UNIQUE NOT NULL,
        zoho_po_id TEXT UNIQUE,
        tablet_type TEXT,
        zoho_status TEXT,
        ordered_quantity INTEGER DEFAULT 0,
        current_good_count INTEGER DEFAULT 0,
        current_damaged_count INTEGER DEFAULT 0,
        remaining_quantity INTEGER DEFAULT 0,
        closed BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Add zoho_status column if it doesn't exist (for existing databases)
    try:
        c.execute('ALTER TABLE purchase_orders ADD COLUMN zoho_status TEXT')
    except:
        pass  # Column already exists
        
    # Add internal_status column for your workflow tracking
    try:
        c.execute('ALTER TABLE purchase_orders ADD COLUMN internal_status TEXT DEFAULT "Active"')
    except:
        pass  # Column already exists
    
    # PO Line Items table
    c.execute('''CREATE TABLE IF NOT EXISTS po_lines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        po_id INTEGER,
        po_number TEXT,
        inventory_item_id TEXT NOT NULL,
        line_item_name TEXT,
        quantity_ordered INTEGER DEFAULT 0,
        good_count INTEGER DEFAULT 0,
        damaged_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (po_id) REFERENCES purchase_orders (id)
    )''')
    
    # Tablet Types table
    c.execute('''CREATE TABLE IF NOT EXISTS tablet_types (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tablet_type_name TEXT UNIQUE NOT NULL,
        inventory_item_id TEXT UNIQUE
    )''')
    
    # Product Details table
    c.execute('''CREATE TABLE IF NOT EXISTS product_details (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_name TEXT UNIQUE NOT NULL,
        tablet_type_id INTEGER,
        packages_per_display INTEGER DEFAULT 0,
        tablets_per_package INTEGER DEFAULT 0,
        FOREIGN KEY (tablet_type_id) REFERENCES tablet_types (id)
    )''')
    
    # Warehouse Submissions table
    c.execute('''CREATE TABLE IF NOT EXISTS warehouse_submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_name TEXT NOT NULL,
        product_name TEXT NOT NULL,
        box_number INTEGER,
        bag_number INTEGER,
        bag_label_count INTEGER,
        displays_made INTEGER DEFAULT 0,
        packs_remaining INTEGER DEFAULT 0,
        loose_tablets INTEGER DEFAULT 0,
        damaged_tablets INTEGER DEFAULT 0,
        discrepancy_flag BOOLEAN DEFAULT FALSE,
        assigned_po_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (assigned_po_id) REFERENCES purchase_orders (id)
    )''')
    
    # Shipments table (+ tracking columns)
    c.execute('''CREATE TABLE IF NOT EXISTS shipments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        po_id INTEGER,
        tracking_number TEXT,
        carrier TEXT,
        carrier_code TEXT,
        shipped_date DATE,
        estimated_delivery DATE,
        actual_delivery DATE,
        tracking_status TEXT,
        last_checkpoint TEXT,
        delivered_at DATE,
        last_checked_at TIMESTAMP,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (po_id) REFERENCES purchase_orders (id)
    )''')

    # Add submission_date column to warehouse_submissions if upgrading existing DB
    c.execute('PRAGMA table_info(warehouse_submissions)')
    existing_ws_cols = [row[1] for row in c.fetchall()]
    if 'submission_date' not in existing_ws_cols:
        try:
            c.execute('ALTER TABLE warehouse_submissions ADD COLUMN submission_date DATE')
            # Backfill existing records with date from created_at
            c.execute('UPDATE warehouse_submissions SET submission_date = DATE(created_at) WHERE submission_date IS NULL')
            print("Added submission_date column to warehouse_submissions table")
        except Exception:
            pass
    
    # Add tracking columns if upgrading existing DB
    # Safe ALTERs to backfill missing columns
    c.execute('PRAGMA table_info(shipments)')
    existing_cols = [row[1] for row in c.fetchall()]
    alters = {
        'carrier_code': 'TEXT',
        'tracking_status': 'TEXT',
        'last_checkpoint': 'TEXT',
        'delivered_at': 'DATE',
        'last_checked_at': 'TIMESTAMP',
    }
    for col, coltype in alters.items():
        if col not in existing_cols:
            try:
                c.execute(f'ALTER TABLE shipments ADD COLUMN {col} {coltype}')
            except Exception:
                pass
    
    # Add pill_count column to bags table if it doesn't exist
    try:
        c.execute('SELECT pill_count FROM bags LIMIT 1')
    except Exception:
        try:
            c.execute('ALTER TABLE bags ADD COLUMN pill_count INTEGER')
        except Exception:
            pass
    
    # Receiving table - tracks shipment arrival and photos
    c.execute('''CREATE TABLE IF NOT EXISTS receiving (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        po_id INTEGER,
        shipment_id INTEGER,
        received_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        delivery_photo_path TEXT,
        delivery_photo_zoho_id TEXT,
        total_small_boxes INTEGER DEFAULT 0,
        received_by TEXT,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (po_id) REFERENCES purchase_orders (id),
        FOREIGN KEY (shipment_id) REFERENCES shipments (id)
    )''')
    
    # Small boxes table - tracks individual boxes within shipment
    c.execute('''CREATE TABLE IF NOT EXISTS small_boxes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        receiving_id INTEGER,
        box_number INTEGER,
        total_bags INTEGER DEFAULT 0,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (receiving_id) REFERENCES receiving (id)
    )''')
    
    # Bags table - tracks individual bags within boxes
    c.execute('''                CREATE TABLE IF NOT EXISTS bags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    small_box_id INTEGER,
                    bag_number INTEGER,
                    bag_label_count INTEGER,
                    pill_count INTEGER,
                    status TEXT DEFAULT 'Available',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (small_box_id) REFERENCES small_boxes (id)
                )''')

    # Employees table for user authentication
    c.execute('''CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        full_name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect('tablet_counter.db')
    conn.row_factory = sqlite3.Row
    return conn

# Helper function to require login for admin views
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Allow if admin authenticated OR if employee authenticated with admin role
        if not (session.get('admin_authenticated') or 
                (session.get('employee_authenticated') and session.get('employee_role') == 'admin')):
            return redirect(url_for('index'))  # Redirect to unified login
        return f(*args, **kwargs)
    return decorated_function

# Role-based access control system
ROLE_PERMISSIONS = {
    'warehouse_staff': ['warehouse', 'count'],

    'manager': ['warehouse', 'count', 'dashboard', 'shipping', 'reports'],
    'admin': ['all']  # Special case - admin has access to everything
}

def get_employee_role(username):
    """Get the role of an employee"""
    conn = get_db()
    try:
        result = conn.execute(
            'SELECT role FROM employees WHERE username = ? AND is_active = 1',
            (username,)
        ).fetchone()
        conn.close()
        return result['role'] if result else None
    except:
        conn.close()
        return None

def has_permission(username, required_permission):
    """Check if an employee has a specific permission"""
    role = get_employee_role(username)
    if not role:
        return False
    
    permissions = ROLE_PERMISSIONS.get(role, [])
    return 'all' in permissions or required_permission in permissions

def role_required(required_permission):
    """Decorator that requires a specific permission/role"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Allow admin users to access any role-based route
            if session.get('admin_authenticated'):
                return f(*args, **kwargs)
                
            # Check employee authentication and permissions
            if not session.get('employee_authenticated') or not session.get('employee_id'):
                return redirect(url_for('index'))  # Redirect to unified login
            
            username = session.get('employee_username')
            if not username or not has_permission(username, required_permission):
                flash(f'Access denied. You need {required_permission} permission to access this page.', 'error')
                return redirect(url_for('warehouse_form'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Helper function to require employee login
def employee_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Allow if employee authenticated OR if admin authenticated
        if not (session.get('employee_authenticated') or session.get('admin_authenticated')):
            return redirect(url_for('index'))  # Redirect to unified login
        return f(*args, **kwargs)
    return decorated_function

# Password hashing functions
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password, hash):
    return hashlib.sha256(password.encode()).hexdigest() == hash

@app.route('/', methods=['GET', 'POST'])
def index():
    """Unified login system for both employees and admin"""
    # Check if already authenticated
    if session.get('admin_authenticated'):
        return redirect(url_for('admin_panel'))
    
    if session.get('employee_authenticated'):
        # Smart redirect based on role
        role = session.get('employee_role', 'warehouse_staff')
        if role in ['manager', 'admin']:
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('warehouse_form'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        login_type = request.form.get('login_type', 'employee')
        
        if not username or not password:
            flash('Username and password are required', 'error')
            return render_template('unified_login.html')
        
        if login_type == 'admin':
            # Admin login
            admin_password = Config.ADMIN_PASSWORD
            if password == admin_password and username.lower() == 'admin':
                session['admin_authenticated'] = True
                session['employee_role'] = 'admin'  # Set admin role for navigation
                session['login_time'] = datetime.now().isoformat()
                session.permanent = True
                app.permanent_session_lifetime = timedelta(hours=8)
                flash('Welcome back, Admin!', 'success')
                return redirect(url_for('admin_panel'))
            else:
                flash('Invalid admin credentials', 'error')
                return render_template('unified_login.html')
        else:
            # Employee login
            conn = get_db()
            employee = conn.execute('''
                SELECT id, username, full_name, password_hash, role, is_active 
                FROM employees 
                WHERE username = ? AND is_active = TRUE
            ''', (username,)).fetchone()
            
            conn.close()
            
            if employee and verify_password(password, employee['password_hash']):
                session['employee_authenticated'] = True
                session['employee_id'] = employee['id']
                session['employee_name'] = employee['full_name']
                session['employee_username'] = employee['username']
                session['employee_role'] = employee['role'] if employee['role'] else 'warehouse_staff'
                session.permanent = True
                app.permanent_session_lifetime = timedelta(hours=8)
                
                # Smart redirect based on role
                role = employee['role'] if employee['role'] else 'warehouse_staff'
                if role in ['manager', 'admin']:
                    flash(f'Welcome back, {employee["full_name"]}!', 'success')
                    return redirect(url_for('admin_dashboard'))
                else:
                    flash(f'Welcome back, {employee["full_name"]}!', 'success')
                    return redirect(url_for('warehouse_form'))
            else:
                flash('Invalid employee credentials', 'error')
                return render_template('unified_login.html')
    
    # Show unified login page
    return render_template('unified_login.html')

@app.route('/version')
def version():
    """Get application version information"""
    return jsonify({
        'version': __version__,
        'title': __title__,
        'description': __description__
    })

@app.route('/warehouse')
@employee_required
def warehouse_form():
    """Mobile-optimized form for warehouse staff"""
    conn = get_db()
    
    # Get product list for dropdown
    products = conn.execute('''
        SELECT pd.product_name, tt.tablet_type_name, pd.packages_per_display, pd.tablets_per_package
        FROM product_details pd
        JOIN tablet_types tt ON pd.tablet_type_id = tt.id
        ORDER BY pd.product_name
    ''').fetchall()
    
    # Get employee info for display
    employee = conn.execute('''
        SELECT full_name FROM employees WHERE id = ?
    ''', (session.get('employee_id'),)).fetchone()
    
    conn.close()
    
    # Get today's date for the date picker
    today_date = datetime.now().date().isoformat()
    
    return render_template('warehouse_form.html', products=products, employee=employee, today_date=today_date)

@app.route('/submit_warehouse', methods=['POST'])
@employee_required
def submit_warehouse():
    """Process warehouse submission and update PO counts"""
    try:
        data = request.get_json() if request.is_json else request.form
        
        # Get employee name from session
        conn = get_db()
        employee = conn.execute('''
            SELECT full_name FROM employees WHERE id = ?
        ''', (session.get('employee_id'),)).fetchone()
        
        if not employee:
            return jsonify({'error': 'Employee not found'}), 400
        
        # Override employee name with logged-in user
        employee_name = employee['full_name']
        
        # Get product details
        product = conn.execute('''
            SELECT pd.*, tt.inventory_item_id, tt.tablet_type_name
            FROM product_details pd
            JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            WHERE pd.product_name = ?
        ''', (data['product_name'],)).fetchone()
        
        if not product:
            return jsonify({'error': 'Product not found'}), 400
        
        # Calculate tablet counts
        displays_made = int(data.get('displays_made', 0))
        packs_remaining = int(data.get('packs_remaining', 0))
        loose_tablets = int(data.get('loose_tablets', 0))
        damaged_tablets = int(data.get('damaged_tablets', 0))
        
        good_tablets = (displays_made * product['packages_per_display'] * product['tablets_per_package'] + 
                       packs_remaining * product['tablets_per_package'] + 
                       loose_tablets)
        
        # Get submission_date (defaults to today if not provided)
        submission_date = data.get('submission_date', datetime.now().date().isoformat())
        
        # Insert submission record using logged-in employee name
        conn.execute('''
            INSERT INTO warehouse_submissions 
            (employee_name, product_name, box_number, bag_number, bag_label_count,
             displays_made, packs_remaining, loose_tablets, damaged_tablets, submission_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (employee_name, data['product_name'], data.get('box_number'),
              data.get('bag_number'), data.get('bag_label_count'),
              displays_made, packs_remaining, loose_tablets, damaged_tablets, submission_date))
        
        # Find open PO lines for this inventory item
        print(f"Looking for PO lines with inventory_item_id: {product['inventory_item_id']}")
        # Order by PO number (oldest PO numbers first) since they represent issue order
        # Exclude Draft POs - only assign to Issued/Active POs
        po_lines = conn.execute('''
            SELECT pl.*, po.closed
            FROM po_lines pl
            JOIN purchase_orders po ON pl.po_id = po.id
            WHERE pl.inventory_item_id = ? AND po.closed = FALSE
            AND COALESCE(po.internal_status, '') != 'Draft'
            AND (pl.quantity_ordered - pl.good_count - pl.damaged_count) > 0
            ORDER BY po.po_number ASC
        ''', (product['inventory_item_id'],)).fetchall()
        
        print(f"Found {len(po_lines)} matching PO lines")
        
        if not po_lines:
            conn.commit()
            conn.close()
            return jsonify({'warning': f'No open PO found for this tablet type (inventory_item_id: {product["inventory_item_id"]})', 'submission_saved': True})
        
        # Get the PO we'll assign to (first available line's PO)
        assigned_po_id = po_lines[0]['po_id'] if po_lines else None
        
        # Update submission with assigned PO
        if assigned_po_id:
            conn.execute('''
                UPDATE warehouse_submissions 
                SET assigned_po_id = ?
                WHERE rowid = last_insert_rowid()
            ''', (assigned_po_id,))
        
        # Allocate counts to PO lines
        remaining_good = good_tablets
        remaining_damaged = damaged_tablets
        
        for line in po_lines:
            if remaining_good <= 0 and remaining_damaged <= 0:
                break
                
            available = line['quantity_ordered'] - line['good_count'] - line['damaged_count']
            if available <= 0:
                continue
            
            # Apply good tablets first
            apply_good = min(remaining_good, available)
            available -= apply_good
            remaining_good -= apply_good
            
            # Then damaged tablets
            apply_damaged = min(remaining_damaged, available)
            remaining_damaged -= apply_damaged
            
            # Update the line
            conn.execute('''
                UPDATE po_lines 
                SET good_count = good_count + ?, damaged_count = damaged_count + ?
                WHERE id = ?
            ''', (apply_good, apply_damaged, line['id']))
            
            print(f"Updated PO line {line['id']}: +{apply_good} good, +{apply_damaged} damaged")
        
        # Update PO header totals and auto-progress internal status
        updated_pos = set()
        for line in po_lines:
            if line['po_id'] not in updated_pos:
                # Get totals for this PO
                totals = conn.execute('''
                    SELECT 
                        COALESCE(SUM(quantity_ordered), 0) as total_ordered,
                        COALESCE(SUM(good_count), 0) as total_good,
                        COALESCE(SUM(damaged_count), 0) as total_damaged
                    FROM po_lines 
                    WHERE po_id = ?
                ''', (line['po_id'],)).fetchone()
                
                remaining = totals['total_ordered'] - totals['total_good'] - totals['total_damaged']
                
                # Auto-progress internal status based on your workflow
                current_status = conn.execute(
                    'SELECT internal_status FROM purchase_orders WHERE id = ?',
                    (line['po_id'],)
                ).fetchone()
                
                new_internal_status = current_status['internal_status'] if current_status else 'Active'
                
                # Auto-progression rules
                if remaining == 0 and new_internal_status not in ['Complete', 'Reconciled', 'Ready for Payment']:
                    new_internal_status = 'Complete'
                    print(f"Auto-progressed PO {line['po_id']} to Complete (remaining = 0)")
                elif totals['total_good'] > 0 and new_internal_status == 'Active':
                    new_internal_status = 'Processing'
                    print(f"Auto-progressed PO {line['po_id']} to Processing (first submission)")
                
                print(f"PO {line['po_id']}: Ordered={totals['total_ordered']}, Good={totals['total_good']}, Damaged={totals['total_damaged']}, Remaining={remaining}, Status={new_internal_status}")
                
                conn.execute('''
                    UPDATE purchase_orders 
                    SET ordered_quantity = ?, current_good_count = ?, 
                        current_damaged_count = ?, remaining_quantity = ?,
                        internal_status = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (totals['total_ordered'], totals['total_good'], 
                      totals['total_damaged'], remaining, new_internal_status, line['po_id']))
                
                updated_pos.add(line['po_id'])
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'good_applied': good_tablets - remaining_good,
            'damaged_applied': damaged_tablets - remaining_damaged,
            'message': 'Submission processed successfully'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/dashboard')
@role_required('dashboard')
def admin_dashboard():
    """Desktop dashboard for managers/admins"""
    conn = get_db()
    
    # Get active POs (not closed)
    active_pos = conn.execute('''
        SELECT po.*, 
               COUNT(pl.id) as line_count,
               COALESCE(SUM(pl.quantity_ordered), 0) as total_ordered,
               COALESCE(po.internal_status, 'Active') as status_display
        FROM purchase_orders po
        LEFT JOIN po_lines pl ON po.id = pl.po_id
        WHERE po.closed = FALSE
        GROUP BY po.id
        ORDER BY po.po_number DESC
        LIMIT 50
    ''').fetchall()
    
    # Get closed POs for historical reference
    closed_pos = conn.execute('''
        SELECT po.*, 
               COUNT(pl.id) as line_count,
               COALESCE(SUM(pl.quantity_ordered), 0) as total_ordered,
               'Closed' as status_display
        FROM purchase_orders po
        LEFT JOIN po_lines pl ON po.id = pl.po_id
        WHERE po.closed = TRUE
        GROUP BY po.id
        ORDER BY po.po_number DESC
        LIMIT 20
    ''').fetchall()
    
    # Get recent submissions with calculated totals and discrepancy detection
    submissions = conn.execute('''
        SELECT ws.*, po.po_number,
               pd.packages_per_display, pd.tablets_per_package,
               (
                   (ws.displays_made * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0)) +
                   (ws.packs_remaining * COALESCE(pd.tablets_per_package, 0)) + 
                   ws.loose_tablets + ws.damaged_tablets
               ) as calculated_total,
               CASE 
                   WHEN ws.bag_label_count != (
                       (ws.displays_made * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0)) +
                       (ws.packs_remaining * COALESCE(pd.tablets_per_package, 0)) + 
                       ws.loose_tablets + ws.damaged_tablets
                   ) THEN 1
                   ELSE 0
               END as has_discrepancy
        FROM warehouse_submissions ws
        LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
        LEFT JOIN product_details pd ON ws.product_name = pd.product_name
        ORDER BY ws.created_at DESC
        LIMIT 50
    ''').fetchall()
    
    # Get summary stats using internal status (only count synced POs, not test data)
    stats = conn.execute('''
        SELECT 
            COUNT(CASE WHEN internal_status NOT IN ('Closed', 'Ready for Payment') AND zoho_po_id IS NOT NULL THEN 1 END) as open_pos,
            COUNT(CASE WHEN internal_status = 'Closed' AND zoho_po_id IS NOT NULL THEN 1 END) as closed_pos,
            COUNT(CASE WHEN internal_status = 'Draft' AND zoho_po_id IS NOT NULL THEN 1 END) as draft_pos,
            COALESCE(SUM(CASE WHEN internal_status NOT IN ('Closed', 'Ready for Payment') AND zoho_po_id IS NOT NULL THEN 
                (ordered_quantity - current_good_count - current_damaged_count) END), 0) as total_remaining
        FROM purchase_orders
    ''').fetchone()
    
    conn.close()
    return render_template('dashboard.html', active_pos=active_pos, closed_pos=closed_pos, submissions=submissions, stats=stats)

@app.route('/shipments')
def public_shipments():
    """Read-only shipment status page for staff (no login required)."""
    conn = get_db()
    rows = conn.execute('''
        SELECT po.po_number, s.id as shipment_id, s.tracking_number, s.carrier, s.tracking_status,
               s.estimated_delivery, s.last_checkpoint, s.actual_delivery, s.updated_at
        FROM shipments s
        JOIN purchase_orders po ON po.id = s.po_id
        ORDER BY s.updated_at DESC
        LIMIT 200
    ''').fetchall()
    conn.close()
    return render_template('shipments_public.html', shipments=rows)

@app.route('/api/sync_zoho_pos')
@admin_required
def sync_zoho_pos():
    """Sync Purchase Orders from Zoho Inventory"""
    try:
        conn = get_db()
        success, message = zoho_api.sync_tablet_pos_to_db(conn)
        conn.close()
        
        if success:
            return jsonify({'message': message, 'success': True})
        else:
            return jsonify({'error': message, 'success': False}), 400
            
    except Exception as e:
        return jsonify({'error': f'Sync failed: {str(e)}', 'success': False}), 500

@app.route('/api/po_lines/<int:po_id>')
def get_po_lines(po_id):
    """Get line items for a specific PO"""
    conn = get_db()
    lines = conn.execute('''
        SELECT * FROM po_lines WHERE po_id = ? ORDER BY line_item_name
    ''', (po_id,)).fetchall()
    conn.close()
    
    return jsonify([dict(line) for line in lines])

@app.route('/admin/products')
@admin_required
def product_mapping():
    """Show product → tablet mapping and calculation examples"""
    conn = get_db()
    
    # Get all products with their tablet type and calculation details
    products = conn.execute('''
        SELECT pd.*, tt.tablet_type_name, tt.inventory_item_id
        FROM product_details pd
        JOIN tablet_types tt ON pd.tablet_type_id = tt.id
        ORDER BY tt.tablet_type_name, pd.product_name
    ''').fetchall()
    
    # Get tablet types for dropdown
    tablet_types = conn.execute('SELECT * FROM tablet_types ORDER BY tablet_type_name').fetchall()
    
    conn.close()
    return render_template('product_mapping.html', products=products, tablet_types=tablet_types)

@app.route('/admin/tablet_types')
@admin_required
def tablet_types_config():
    """Configuration page for tablet types and their inventory item IDs"""
    conn = get_db()
    
    # Get all tablet types with their current inventory item IDs
    tablet_types = conn.execute('''
        SELECT * FROM tablet_types 
        ORDER BY tablet_type_name
    ''').fetchall()
    
    conn.close()
    return render_template('tablet_types_config.html', tablet_types=tablet_types)

@app.route('/admin/shipments')
@admin_required
def shipments_management():
    """Shipment tracking management page"""
    conn = get_db()
    
    # Get all POs with optional shipment info
    pos_with_shipments = conn.execute('''
        SELECT po.*, s.id as shipment_id, s.tracking_number, s.carrier, s.tracking_status,
               s.last_checkpoint, s.shipped_date, s.estimated_delivery, s.actual_delivery,
               s.notes as shipment_notes
        FROM purchase_orders po
        LEFT JOIN shipments s ON po.id = s.po_id
        ORDER BY po.po_number DESC
    ''').fetchall()
    
    conn.close()
    return render_template('shipments_management.html', pos_with_shipments=pos_with_shipments)

@app.route('/shipping')
@role_required('shipping')
def shipping_unified():
    """Unified shipping and receiving management page"""
    try:
        conn = get_db()
        current_date = datetime.now().date()
        
        # Get all POs with shipment info (for shipments tab)
        pos_with_shipments = conn.execute('''
            SELECT po.*, s.id as shipment_id, s.tracking_number, s.carrier, s.tracking_status,
                   s.last_checkpoint, s.shipped_date as ship_date, s.estimated_delivery, s.actual_delivery,
                   s.notes as shipment_notes
            FROM purchase_orders po
            LEFT JOIN shipments s ON po.id = s.po_id
            ORDER BY po.po_number DESC
        ''').fetchall()
        
        # Add current_date and tracking_url to each PO for template compatibility
        pos_with_shipments_enhanced = []
        for po in pos_with_shipments:
            po_dict = dict(po)
            po_dict['current_date'] = current_date
            # Generate tracking URL if we have tracking number and carrier
            if po_dict.get('tracking_number') and po_dict.get('carrier'):
                if po_dict['carrier'].upper() == 'UPS':
                    po_dict['tracking_url'] = f"https://www.ups.com/track?track=yes&trackNums={po_dict['tracking_number']}"
                elif po_dict['carrier'].upper() == 'FEDEX':
                    po_dict['tracking_url'] = f"https://www.fedex.com/apps/fedextrack/?tracknumbers={po_dict['tracking_number']}"
                elif po_dict['carrier'].upper() == 'USPS':
                    po_dict['tracking_url'] = f"https://tools.usps.com/go/TrackConfirmAction?qtc_tLabels1={po_dict['tracking_number']}"
                else:
                    po_dict['tracking_url'] = None
            else:
                po_dict['tracking_url'] = None
            pos_with_shipments_enhanced.append(po_dict)
        
        # Get pending shipments (delivered but not yet received) for receiving tab
        pending_shipments = conn.execute('''
            SELECT s.*, po.po_number
            FROM shipments s
            JOIN purchase_orders po ON s.po_id = po.id
            LEFT JOIN receiving r ON s.id = r.shipment_id
            WHERE s.tracking_status = 'Delivered' AND r.id IS NULL
            ORDER BY s.delivered_at DESC, s.created_at DESC
        ''').fetchall()
        
        # Get recent receiving history
        recent_receives = conn.execute('''
            SELECT r.*, po.po_number,
                   COUNT(sb.id) as total_boxes,
                   SUM(sb.total_bags) as total_bags
            FROM receiving r
            JOIN purchase_orders po ON r.po_id = po.id
            LEFT JOIN small_boxes sb ON r.id = sb.receiving_id
            GROUP BY r.id
            ORDER BY r.received_date DESC
            LIMIT 10
        ''').fetchall()
        
        conn.close()
        
        return render_template('shipping_unified.html', 
                             pos_with_shipments=pos_with_shipments_enhanced,
                             pending_shipments=pending_shipments,
                             recent_receives=recent_receives)
                             
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        app.logger.error(f"Error in shipping_unified: {str(e)}\n{error_details}")
        return render_template('error.html', 
                             error_message=f"Error loading shipping page: {str(e)}\n\nFull traceback:\n{error_details}"), 500

@app.route('/api/shipments/<int:shipment_id>/refresh', methods=['POST'])
def refresh_shipment(shipment_id: int):
    """Manually refresh a single shipment's tracking status."""
    try:
        conn = get_db()
        result = refresh_shipment_row(conn, shipment_id)
        conn.close()
        if result.get('success'):
            return jsonify(result)
        return jsonify(result), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/shipment/<int:shipment_id>', methods=['GET'])
def get_shipment(shipment_id: int):
    try:
        conn = get_db()
        row = conn.execute('''
            SELECT id, po_id, tracking_number, carrier, shipped_date, estimated_delivery, actual_delivery, notes
            FROM shipments WHERE id = ?
        ''', (shipment_id,)).fetchone()
        conn.close()
        if not row:
            return jsonify({'success': False, 'error': 'Not found'}), 404
        return jsonify({'success': True, 'shipment': dict(row)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/shipment/<int:shipment_id>', methods=['DELETE'])
def delete_shipment(shipment_id: int):
    try:
        conn = get_db()
        conn.execute('DELETE FROM shipments WHERE id = ?', (shipment_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/save_shipment', methods=['POST'])
def save_shipment():
    """Save shipment information (supports multiple shipments per PO)"""
    try:
        data = request.get_json()
        conn = get_db()
        
        # For multiple shipments per PO, always create new unless we're editing a specific shipment
        shipment_id = data.get('shipment_id')
        
        if shipment_id:
            # Update existing specific shipment
            conn.execute('''
                UPDATE shipments 
                SET tracking_number = ?, carrier = ?, shipped_date = ?,
                    estimated_delivery = ?, actual_delivery = ?, notes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (data.get('tracking_number'), data.get('carrier'), data.get('shipped_date'),
                  data.get('estimated_delivery'), data.get('actual_delivery'), 
                  data.get('notes'), shipment_id))
        else:
            # Create new shipment (allows multiple shipments per PO)
            conn.execute('''
                INSERT INTO shipments (po_id, tracking_number, carrier, shipped_date,
                                     estimated_delivery, actual_delivery, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (data['po_id'], data.get('tracking_number'), data.get('carrier'), 
                  data.get('shipped_date'), data.get('estimated_delivery'), 
                  data.get('actual_delivery'), data.get('notes')))
            # set carrier_code based on carrier
            conn.execute('UPDATE shipments SET carrier_code = LOWER(?) WHERE rowid = last_insert_rowid()', (data.get('carrier'),))
        
        # Auto-progress PO to "Shipped" status when tracking info is added
        if data.get('tracking_number'):
            current_status = conn.execute(
                'SELECT internal_status FROM purchase_orders WHERE id = ?',
                (data['po_id'],)
            ).fetchone()
            
            if current_status and current_status['internal_status'] in ['Draft', 'Issued']:
                conn.execute('''
                    UPDATE purchase_orders 
                    SET internal_status = 'Shipped', updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (data['po_id'],))
                print(f"Auto-progressed PO {data['po_id']} to Shipped (tracking added)")
        
        conn.commit()

        # Trigger immediate UPS refresh when applicable
        if data.get('tracking_number') and (data.get('carrier', '').lower() in ('ups','fedex','fed ex')):
            sh = conn.execute('''
                SELECT id FROM shipments WHERE po_id = ? AND tracking_number = ?
                ORDER BY updated_at DESC LIMIT 1
            ''', (data['po_id'], data.get('tracking_number'))).fetchone()
            if sh:
                try:
                    result = refresh_shipment_row(conn, sh['id'])
                    print('UPS refresh result:', result)
                except Exception as exc:
                    print('UPS refresh error:', exc)

        conn.close()
        return jsonify({'success': True, 'message': 'Shipment saved; tracking refreshed if supported'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/update_tablet_type_inventory', methods=['POST'])
def update_tablet_type_inventory():
    """Update a tablet type's inventory item ID"""
    try:
        data = request.get_json()
        tablet_type_id = data.get('tablet_type_id')
        inventory_item_id = data.get('inventory_item_id', '').strip()
        
        conn = get_db()
        
        # Clear the inventory_item_id if empty
        if not inventory_item_id:
            conn.execute('''
                UPDATE tablet_types 
                SET inventory_item_id = NULL
                WHERE id = ?
            ''', (tablet_type_id,))
        else:
            # Check if this inventory_item_id is already used
            existing = conn.execute('''
                SELECT tablet_type_name FROM tablet_types 
                WHERE inventory_item_id = ? AND id != ?
            ''', (inventory_item_id, tablet_type_id)).fetchone()
            
            if existing:
                return jsonify({
                    'success': False, 
                    'error': f'Inventory ID already used by {existing["tablet_type_name"]}'
                })
            
            conn.execute('''
                UPDATE tablet_types 
                SET inventory_item_id = ?
                WHERE id = ?
            ''', (inventory_item_id, tablet_type_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Tablet type updated successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin')
def admin_panel():
    """Admin panel with quick actions and product management"""
    # Check for admin session
    if not session.get('admin_authenticated'):
        return render_template('admin_login.html')
    return render_template('admin_panel.html')

@app.route('/admin/login', methods=['POST'])
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
        app.permanent_session_lifetime = timedelta(hours=8)  # 8 hour timeout
        
        return redirect('/admin') if request.form else jsonify({'success': True})
    else:
        # Log failed login attempt
        print(f"Failed admin login attempt from {request.remote_addr} at {datetime.now()}")
        
        if request.form:
            flash('Invalid password', 'error')
            return render_template('admin_login.html')
        else:
            return jsonify({'success': False, 'error': 'Invalid password'})

@app.route('/admin/logout')
def admin_logout():
    """Logout admin - redirect to unified logout"""
    return redirect(url_for('logout'))

@app.route('/login')
def employee_login():
    """Employee login page"""
    return render_template('employee_login.html')

@app.route('/login', methods=['POST'])
def employee_login_post():
    """Handle employee login"""
    username = request.form.get('username') or request.json.get('username')
    password = request.form.get('password') or request.json.get('password')
    
    if not username or not password:
        if request.form:
            flash('Username and password required', 'error')
            return render_template('employee_login.html')
        else:
            return jsonify({'success': False, 'error': 'Username and password required'})
    
    conn = get_db()
    employee = conn.execute('''
        SELECT id, username, full_name, password_hash, role, is_active 
        FROM employees 
        WHERE username = ? AND is_active = TRUE
    ''', (username,)).fetchone()
    
    conn.close()
    
    if employee and verify_password(password, employee['password_hash']):
        session['employee_authenticated'] = True
        session['employee_id'] = employee['id']
        session['employee_name'] = employee['full_name']
        session['employee_username'] = employee['username']
        session['employee_role'] = employee['role'] if employee['role'] else 'warehouse_staff'
        session.permanent = True
        app.permanent_session_lifetime = timedelta(hours=8)
        
        return redirect(url_for('warehouse_form')) if request.form else jsonify({'success': True})
    else:
        # Log failed login attempt
        print(f"Failed employee login attempt for {username} from {request.remote_addr} at {datetime.now()}")
        
        if request.form:
            flash('Invalid username or password', 'error')
            return render_template('employee_login.html')
        else:
            return jsonify({'success': False, 'error': 'Invalid username or password'})

@app.route('/logout')
def logout():
    """Unified logout for both employees and admin"""
    # Clear all session data
    session.pop('admin_authenticated', None)
    session.pop('employee_authenticated', None)
    session.pop('employee_id', None)
    session.pop('employee_name', None)
    session.pop('employee_username', None)
    session.pop('employee_role', None)
    session.pop('login_time', None)
    
    flash('You have been logged out successfully', 'success')
    return redirect(url_for('index'))

@app.route('/count')
@employee_required
def count_form():
    """Manual count form for end-of-period PO close-outs"""
    conn = get_db()
    
    # Get all tablet types for dropdown
    tablet_types = conn.execute('''
        SELECT * FROM tablet_types 
        ORDER BY tablet_type_name
    ''').fetchall()
    
    conn.close()
    
    # Get today's date for the date picker
    today_date = datetime.now().date().isoformat()
    
    return render_template('count_form.html', tablet_types=tablet_types, today_date=today_date)

@app.route('/submit_count', methods=['POST'])
def submit_count():
    """Process manual count submission for PO close-outs"""
    try:
        data = request.get_json() if request.is_json else request.form
        
        conn = get_db()
        
        # Get tablet type details
        tablet_type = conn.execute('''
            SELECT * FROM tablet_types
            WHERE tablet_type_name = ?
        ''', (data['tablet_type'],)).fetchone()
        
        if not tablet_type:
            return jsonify({'error': 'Tablet type not found'}), 400
        
        actual_count = int(data.get('actual_count', 0))
        bag_label_count = int(data.get('bag_label_count', 0))
        
        # Get submission_date (defaults to today if not provided)
        submission_date = data.get('submission_date', datetime.now().date().isoformat())
        
        # Insert count record
        conn.execute('''
            INSERT INTO warehouse_submissions 
            (employee_name, product_name, box_number, bag_number, bag_label_count,
             displays_made, packs_remaining, loose_tablets, damaged_tablets, submission_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (data['employee_name'], data['tablet_type'], data.get('box_number'),
              data.get('bag_number'), bag_label_count, 0, 0, actual_count, 0, submission_date))
        
        # Find open PO lines for this inventory item
        # Order by PO number (oldest PO numbers first) since they represent issue order
        # Exclude Draft POs - only assign to Issued/Active POs
        po_lines = conn.execute('''
            SELECT pl.*, po.closed
            FROM po_lines pl
            JOIN purchase_orders po ON pl.po_id = po.id
            WHERE pl.inventory_item_id = ? AND po.closed = FALSE
            AND COALESCE(po.internal_status, '') != 'Draft'
            AND (pl.quantity_ordered - pl.good_count - pl.damaged_count) > 0
            ORDER BY po.po_number ASC
        ''', (tablet_type['inventory_item_id'],)).fetchall()
        
        if not po_lines:
            conn.commit()
            conn.close()
            return jsonify({'warning': 'No open PO found for this tablet type', 'submission_saved': True})
        
        # Get the PO we'll assign to (first available line's PO)
        assigned_po_id = po_lines[0]['po_id'] if po_lines else None
        
        # Update submission with assigned PO
        if assigned_po_id:
            conn.execute('''
                UPDATE warehouse_submissions 
                SET assigned_po_id = ?
                WHERE rowid = last_insert_rowid()
            ''', (assigned_po_id,))
        
        # Allocate count to first available PO line
        remaining_count = actual_count
        
        for line in po_lines:
            if remaining_count <= 0:
                break
                
            available = line['quantity_ordered'] - line['good_count'] - line['damaged_count']
            if available <= 0:
                continue
            
            # Apply count as good tablets
            apply_count = min(remaining_count, available)
            remaining_count -= apply_count
            
            # Update the line
            conn.execute('''
                UPDATE po_lines 
                SET good_count = good_count + ?
                WHERE id = ?
            ''', (apply_count, line['id']))
            
            print(f"Manual count - Updated PO line {line['id']}: +{apply_count} tablets")
            
            if remaining_count <= 0:
                break
        
        # Update PO header totals
        updated_pos = set()
        for line in po_lines:
            if line['po_id'] not in updated_pos:
                po_id = line['po_id']
                totals = conn.execute('''
                    SELECT 
                        COALESCE(SUM(quantity_ordered), 0) as total_ordered,
                        COALESCE(SUM(good_count), 0) as total_good,
                        COALESCE(SUM(damaged_count), 0) as total_damaged
                    FROM po_lines 
                    WHERE po_id = ?
                ''', (po_id,)).fetchone()
                
                remaining = totals['total_ordered'] - totals['total_good'] - totals['total_damaged']
                print(f"Manual count - PO {po_id}: Ordered={totals['total_ordered']}, Good={totals['total_good']}, Damaged={totals['total_damaged']}, Remaining={remaining}")
                
                conn.execute('''
                    UPDATE purchase_orders 
                    SET ordered_quantity = ?, current_good_count = ?, 
                        current_damaged_count = ?, remaining_quantity = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (totals['total_ordered'], totals['total_good'], 
                      totals['total_damaged'], remaining, po_id))
                
                updated_pos.add(po_id)
        
        conn.commit()
        conn.close()
        
        message = f'Count submitted successfully! Applied {actual_count - remaining_count} tablets to PO'
        if remaining_count > 0:
            message += f' ({remaining_count} tablets could not be allocated)'
        
        return jsonify({'success': True, 'message': message})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/save_product', methods=['POST'])
@admin_required
def save_product():
    """Save or update a product configuration"""
    try:
        data = request.get_json()
        conn = get_db()
        
        if data.get('id'):
            # Update existing product
            conn.execute('''
                UPDATE product_details 
                SET product_name = ?, tablet_type_id = ?, packages_per_display = ?, tablets_per_package = ?
                WHERE id = ?
            ''', (data['product_name'], data['tablet_type_id'], data['packages_per_display'], 
                  data['tablets_per_package'], data['id']))
            message = f"Updated {data['product_name']}"
        else:
            # Create new product
            conn.execute('''
                INSERT INTO product_details (product_name, tablet_type_id, packages_per_display, tablets_per_package)
                VALUES (?, ?, ?, ?)
            ''', (data['product_name'], data['tablet_type_id'], data['packages_per_display'], data['tablets_per_package']))
            message = f"Created {data['product_name']}"
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': message})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/delete_product/<int:product_id>', methods=['DELETE'])
def delete_product(product_id):
    """Delete a product configuration"""
    try:
        conn = get_db()
        
        # Get product name first
        product = conn.execute('SELECT product_name FROM product_details WHERE id = ?', (product_id,)).fetchone()
        if not product:
            return jsonify({'success': False, 'error': 'Product not found'}), 404
        
        conn.execute('DELETE FROM product_details WHERE id = ?', (product_id,))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f"Deleted {product['product_name']}"})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/get_or_create_tablet_type', methods=['POST'])
def get_or_create_tablet_type():
    """Get existing tablet type by name or create new one"""
    try:
        data = request.get_json()
        tablet_type_name = data.get('tablet_type_name', '').strip()
        
        if not tablet_type_name:
            return jsonify({'success': False, 'error': 'Tablet type name required'}), 400
        
        conn = get_db()
        
        # Check if exists
        existing = conn.execute(
            'SELECT id FROM tablet_types WHERE tablet_type_name = ?', 
            (tablet_type_name,)
        ).fetchone()
        
        if existing:
            tablet_type_id = existing['id']
        else:
            # Create new
            cursor = conn.execute(
                'INSERT INTO tablet_types (tablet_type_name) VALUES (?)',
                (tablet_type_name,)
            )
            tablet_type_id = cursor.lastrowid
            conn.commit()
        
        conn.close()
        return jsonify({'success': True, 'tablet_type_id': tablet_type_id})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/update_tablet_inventory_ids', methods=['POST'])
def update_tablet_inventory_ids():
    """Update tablet types with inventory item IDs from PO line items"""
    try:
        conn = get_db()
        
        # Get all tablet types without inventory_item_id
        tablet_types = conn.execute('''
            SELECT id, tablet_type_name 
            FROM tablet_types 
            WHERE inventory_item_id IS NULL OR inventory_item_id = ''
        ''').fetchall()
        
        updated_count = 0
        
        for tablet_type in tablet_types:
            print(f"Processing tablet type: {tablet_type['tablet_type_name']}")
            
            # Look for PO lines that contain this tablet type name
            matching_lines = conn.execute('''
                SELECT DISTINCT inventory_item_id, line_item_name
                FROM po_lines 
                WHERE line_item_name LIKE ? OR line_item_name LIKE ?
                LIMIT 1
            ''', (f'%{tablet_type["tablet_type_name"]}%', 
                  f'%{tablet_type["tablet_type_name"].replace(" ", "%")}%')).fetchone()
            
            if matching_lines:
                print(f"Found matching line: {matching_lines['line_item_name']} -> {matching_lines['inventory_item_id']}")
                
                # Check if this inventory_item_id is already used by another tablet type
                existing = conn.execute('''
                    SELECT tablet_type_name FROM tablet_types 
                    WHERE inventory_item_id = ? AND id != ?
                ''', (matching_lines['inventory_item_id'], tablet_type['id'])).fetchone()
                
                if existing:
                    print(f"Inventory ID {matching_lines['inventory_item_id']} already used by {existing['tablet_type_name']}, skipping {tablet_type['tablet_type_name']}")
                else:
                    conn.execute('''
                        UPDATE tablet_types 
                        SET inventory_item_id = ?
                        WHERE id = ?
                    ''', (matching_lines['inventory_item_id'], tablet_type['id']))
                    updated_count += 1
            else:
                print(f"No matching line found for: {tablet_type['tablet_type_name']}")
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': f'Updated {updated_count} tablet types with inventory item IDs'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/add_tablet_type', methods=['POST'])
def add_tablet_type():
    """Add a new tablet type"""
    try:
        data = request.get_json()
        tablet_type_name = data.get('tablet_type_name', '').strip()
        inventory_item_id = data.get('inventory_item_id', '').strip()
        
        if not tablet_type_name:
            return jsonify({'success': False, 'error': 'Tablet type name required'}), 400
            
        conn = get_db()
        
        # Check if tablet type already exists
        existing = conn.execute(
            'SELECT id FROM tablet_types WHERE tablet_type_name = ?', 
            (tablet_type_name,)
        ).fetchone()
        
        if existing:
            return jsonify({'success': False, 'error': 'Tablet type already exists'}), 400
        
        # Check if inventory_item_id is already used (if provided)
        if inventory_item_id:
            existing_id = conn.execute(
                'SELECT tablet_type_name FROM tablet_types WHERE inventory_item_id = ?',
                (inventory_item_id,)
            ).fetchone()
            
            if existing_id:
                return jsonify({
                    'success': False, 
                    'error': f'Inventory ID already used by {existing_id["tablet_type_name"]}'
                }), 400
        
        # Insert new tablet type
        conn.execute('''
            INSERT INTO tablet_types (tablet_type_name, inventory_item_id)
            VALUES (?, ?)
        ''', (tablet_type_name, inventory_item_id if inventory_item_id else None))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f'Added tablet type: {tablet_type_name}'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/delete_tablet_type/<int:tablet_type_id>', methods=['DELETE'])
def delete_tablet_type(tablet_type_id):
    """Delete a tablet type and its associated products"""
    try:
        conn = get_db()
        
        # Get tablet type name first
        tablet_type = conn.execute(
            'SELECT tablet_type_name FROM tablet_types WHERE id = ?', 
            (tablet_type_id,)
        ).fetchone()
        
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

# Employee Management Routes for Admin
@app.route('/admin/employees')
@admin_required
def manage_employees():
    """Employee management page"""
    conn = get_db()
    employees = conn.execute('''
        SELECT id, username, full_name, role, is_active, created_at
        FROM employees 
        ORDER BY role, full_name
    ''').fetchall()
    
    conn.close()
    return render_template('employee_management.html', employees=employees)

@app.route('/api/add_employee', methods=['POST'])
def add_employee():
    """Add a new employee"""
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        full_name = data.get('full_name', '').strip()
        password = data.get('password', '').strip()
        role = data.get('role', 'warehouse_staff').strip()
        
        if not username or not full_name or not password:
            return jsonify({'success': False, 'error': 'Username, full name, and password required'}), 400
            
        # Validate role
        valid_roles = ['warehouse_staff', 'manager', 'admin']
        if role not in valid_roles:
            return jsonify({'success': False, 'error': 'Invalid role specified'}), 400
            
        conn = get_db()
        
        # Check if username already exists
        existing = conn.execute(
            'SELECT id FROM employees WHERE username = ?', 
            (username,)
        ).fetchone()
        
        if existing:
            return jsonify({'success': False, 'error': 'Username already exists'}), 400
        
        # Hash password and insert employee
        password_hash = hash_password(password)
        conn.execute('''
            INSERT INTO employees (username, full_name, password_hash, role)
            VALUES (?, ?, ?, ?)
        ''', (username, full_name, password_hash, role))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f'Added employee: {full_name}'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/update_employee_role/<int:employee_id>', methods=['POST'])
@admin_required
def update_employee_role(employee_id):
    """Update an employee's role"""
    try:
        data = request.get_json()
        new_role = data.get('role', '').strip()
        
        # Validate role
        valid_roles = ['warehouse_staff', 'manager', 'admin']
        if new_role not in valid_roles:
            return jsonify({'success': False, 'error': 'Invalid role specified'}), 400
            
        conn = get_db()
        
        # Check if employee exists
        employee = conn.execute(
            'SELECT id, username, full_name FROM employees WHERE id = ?', 
            (employee_id,)
        ).fetchone()
        
        if not employee:
            return jsonify({'success': False, 'error': 'Employee not found'}), 404
            
        # Update employee role
        conn.execute('''
            UPDATE employees 
            SET role = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (new_role, employee_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': f'Updated {employee["full_name"]} role to {new_role.replace("_", " ").title()}'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/toggle_employee/<int:employee_id>', methods=['POST'])
def toggle_employee(employee_id):
    """Toggle employee active status"""
    try:
        conn = get_db()
        
        # Get current status
        employee = conn.execute(
            'SELECT full_name, is_active FROM employees WHERE id = ?', 
            (employee_id,)
        ).fetchone()
        
        if not employee:
            return jsonify({'success': False, 'error': 'Employee not found'}), 404
        
        # Toggle status
        new_status = not employee['is_active']
        conn.execute('''
            UPDATE employees 
            SET is_active = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (new_status, employee_id))
        
        conn.commit()
        conn.close()
        
        status_text = 'activated' if new_status else 'deactivated'
        return jsonify({'success': True, 'message': f'{employee["full_name"]} {status_text}'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/delete_employee/<int:employee_id>', methods=['DELETE'])
def delete_employee(employee_id):
    """Delete an employee"""
    try:
        conn = get_db()
        
        # Get employee name first
        employee = conn.execute(
            'SELECT full_name FROM employees WHERE id = ?', 
            (employee_id,)
        ).fetchone()
        
        if not employee:
            return jsonify({'success': False, 'error': 'Employee not found'}), 404
        
        # Delete employee
        conn.execute('DELETE FROM employees WHERE id = ?', (employee_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f'Deleted employee: {employee["full_name"]}'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/set-language', methods=['POST'])
def set_language():
    """Set language preference for current session and save to employee profile"""
    try:
        data = request.get_json()
        language = data.get('language', '').strip()
        
        # Validate language
        if language not in app.config['LANGUAGES']:
            return jsonify({'success': False, 'error': 'Invalid language'}), 400
        
        # Set session language with manual override flag
        session['language'] = language
        session['manual_language_override'] = True
        session.permanent = True
        
        # Save to employee profile if authenticated
        if session.get('employee_authenticated') and session.get('employee_id'):
            try:
                conn = get_db()
                conn.execute('''
                    UPDATE employees 
                    SET preferred_language = ? 
                    WHERE id = ?
                ''', (language, session.get('employee_id')))
                conn.commit()
                conn.close()
                app.logger.info(f"Language preference saved to database: {language} for employee {session.get('employee_id')}")
            except Exception as e:
                app.logger.error(f"Failed to save language preference to database: {str(e)}")
                # Continue without database save - session is still set
        
        app.logger.info(f"Language manually set to {language} for session")
        
        return jsonify({'success': True, 'message': f'Language set to {language}'})
        
    except Exception as e:
        app.logger.error(f"Language setting error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/refresh_products', methods=['POST'])
def refresh_products():
    """Clear and rebuild products with updated configuration"""
    try:
        from setup_db import setup_sample_data
        
        conn = get_db()
        
        # Clear existing data
        conn.execute('DELETE FROM warehouse_submissions')
        conn.execute('DELETE FROM product_details')
        conn.execute('DELETE FROM tablet_types')
        conn.commit()
        conn.close()
        
        # Rebuild with new data
        setup_sample_data()
        
        return jsonify({
            'success': True, 
            'message': 'Products refreshed with updated configuration'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/po_tracking/<int:po_id>')
def get_po_tracking(po_id):
    """Get all tracking information for a PO (supports multiple shipments)"""
    try:
        conn = get_db()
        
        # Get all shipments for this PO
        shipments = conn.execute('''
            SELECT id, tracking_number, carrier, shipped_date, estimated_delivery, actual_delivery, notes, created_at
            FROM shipments 
            WHERE po_id = ?
            ORDER BY created_at DESC
        ''', (po_id,)).fetchall()
        
        conn.close()
        
        if shipments:
            # Return all shipments
            shipments_list = []
            for shipment in shipments:
                shipments_list.append({
                    'id': shipment['id'],
                    'tracking_number': shipment['tracking_number'],
                    'carrier': shipment['carrier'],
                    'shipped_date': shipment['shipped_date'],
                    'estimated_delivery': shipment['estimated_delivery'],
                    'actual_delivery': shipment['actual_delivery'],
                    'notes': shipment['notes']
                })
            
            return jsonify({
                'shipments': shipments_list,
                'has_tracking': True
            })
        else:
            return jsonify({
                'shipments': [],
                'has_tracking': False
            })
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/find_org_id')
def find_organization_id():
    """Help find the correct Zoho Organization ID"""
    try:
        # Get token first
        token = zoho_api.get_access_token()
        if not token:
            return jsonify({
                'success': False,
                'error': 'Failed to get access token. Check your credentials.'
            })
        
        # Try to get organizations
        url = 'https://www.zohoapis.com/inventory/v1/organizations'
        headers = {'Authorization': f'Zoho-oauthtoken {token}'}
        
        response = requests.get(url, headers=headers)
        print(f"Organizations API - Status: {response.status_code}")
        print(f"Organizations API - Response: {response.text}")
        
        if response.status_code == 200:
            data = response.json()
            orgs = data.get('organizations', [])
            return jsonify({
                'success': True,
                'organizations': orgs,
                'message': f'Found {len(orgs)} organizations. Use the organization_id from the one you want.'
            })
        else:
            return jsonify({
                'success': False,
                'error': f'Failed to get organizations: {response.status_code} - {response.text}'
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Error finding organizations: {str(e)}'
        })

@app.route('/api/test_zoho_connection')
def test_zoho_connection():
    """Test if Zoho API credentials are working"""
    try:
        # Try to get an access token
        token = zoho_api.get_access_token()
        if not token:
            return jsonify({
                'success': False,
                'error': 'Failed to get access token. Check your CLIENT_ID, CLIENT_SECRET, and REFRESH_TOKEN in .env file'
            })
        
        # Try to make a simple API call
        result = zoho_api.make_request('items', method='GET', extra_params={'per_page': 10})
        if result:
            item_count = len(result.get('items', []))
            return jsonify({
                'success': True,
                'message': f'✅ Connected to Zoho! Found {item_count} inventory items.',
                'organization_id': zoho_api.organization_id
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Got access token but API call failed. Check your ORGANIZATION_ID or check the terminal for detailed error info.'
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Connection test failed: {str(e)}'
        })

@app.route('/api/clear_po_data', methods=['POST'])
@admin_required
def clear_po_data():
    """Clear all PO data for fresh sync testing"""
    try:
        conn = get_db()
        
        # Clear all PO-related data
        conn.execute('DELETE FROM po_lines')
        conn.execute('DELETE FROM purchase_orders WHERE zoho_po_id IS NOT NULL')  # Keep sample test POs
        conn.execute('DELETE FROM warehouse_submissions')
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': '✅ Cleared all synced PO data. Ready for fresh sync!'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Clear failed: {str(e)}'
        }), 500

# ===== PRODUCTION REPORT ENDPOINTS =====

@app.route('/api/reports/production', methods=['POST'])
@admin_required
def generate_production_report():
    """Generate comprehensive production report PDF"""
    try:
        data = request.get_json() or {}
        
        start_date = data.get('start_date')
        end_date = data.get('end_date') 
        po_numbers = data.get('po_numbers', [])
        
        # Validate date formats if provided
        if start_date:
            try:
                datetime.strptime(start_date, '%Y-%m-%d')
            except ValueError:
                return jsonify({'error': 'Invalid start_date format. Use YYYY-MM-DD'}), 400
        
        if end_date:
            try:
                datetime.strptime(end_date, '%Y-%m-%d')
            except ValueError:
                return jsonify({'error': 'Invalid end_date format. Use YYYY-MM-DD'}), 400
        
        # Generate report
        generator = ProductionReportGenerator()
        pdf_content = generator.generate_production_report(
            start_date=start_date,
            end_date=end_date,
            po_numbers=po_numbers if po_numbers else None
        )
        
        # Create filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'production_report_{timestamp}.pdf'
        
        # Return PDF as download
        from flask import make_response
        response = make_response(pdf_content)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response
        
    except Exception as e:
        print(f"Report generation error: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Report generation failed: {str(e)}'
        }), 500

@app.route('/api/reports/po-summary')
@admin_required 
def get_po_summary_for_reports():
    """Get summary of POs available for reporting"""
    try:
        conn = get_db()
        
        # Get PO summary with date ranges
        pos = conn.execute('''
            SELECT 
                po.po_number,
                po.tablet_type,
                po.internal_status,
                po.ordered_quantity,
                po.current_good_count,
                po.current_damaged_count,
                po.created_at,
                po.updated_at,
                COUNT(DISTINCT ws.id) as submission_count,
                MIN(ws.created_at) as first_submission,
                MAX(ws.created_at) as last_submission,
                s.actual_delivery,
                s.delivered_at,
                s.tracking_status
            FROM purchase_orders po
            LEFT JOIN warehouse_submissions ws ON po.id = ws.assigned_po_id
            LEFT JOIN shipments s ON po.id = s.po_id
            GROUP BY po.id
            ORDER BY po.created_at DESC
            LIMIT 100
        ''').fetchall()
        
        po_list = []
        for po in pos:
            # Calculate pack time if possible
            pack_time = None
            delivery_date = None
            completion_date = None
            
            if po['actual_delivery']:
                delivery_date = po['actual_delivery']
            elif po['delivered_at']:
                delivery_date = po['delivered_at']
            
            if po['last_submission']:
                completion_date = po['last_submission'][:10]
            elif po['internal_status'] == 'Complete':
                completion_date = po['updated_at'][:10]
            
            if delivery_date and completion_date:
                try:
                    del_dt = datetime.strptime(delivery_date[:10], '%Y-%m-%d')
                    comp_dt = datetime.strptime(completion_date, '%Y-%m-%d')
                    pack_time = (comp_dt - del_dt).days
                except:
                    pack_time = None
            
            po_list.append({
                'po_number': po['po_number'],
                'tablet_type': po['tablet_type'],
                'status': po['internal_status'],
                'ordered': po['ordered_quantity'] or 0,
                'produced': po['current_good_count'] or 0,
                'damaged': po['current_damaged_count'] or 0,
                'created_date': po['created_at'][:10] if po['created_at'] else None,
                'submissions': po['submission_count'],
                'pack_time_days': pack_time,
                'tracking_status': po['tracking_status']
            })
        
        conn.close()
        
        return jsonify({
            'success': True,
            'pos': po_list,
            'total_count': len(po_list)
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to get PO summary: {str(e)}'
        }), 500

# ===== RECEIVING MANAGEMENT ROUTES =====

# Temporarily removed force-reload route due to import issues

@app.route('/debug/server-info')
def server_debug_info():
    """Debug route to check server state - no auth required"""
    import os
    import time
    import sqlite3
    
    try:
        # Check file timestamps
        app_py_time = os.path.getmtime('app.py')
        version_time = os.path.getmtime('__version__.py')
        
        # Check if we can read version
        try:
            from __version__ import __version__, __title__
            version_info = f"{__title__} v{__version__}"
        except:
            version_info = "Version import failed"
        
        # Check current working directory
        cwd = os.getcwd()
        
        # Check if template exists
        template_exists = os.path.exists('templates/receiving_management.html')
        
        # Find database path and check what tables exist
        db_path = 'tablettracker.db'
        db_full_path = os.path.abspath(db_path)
        db_exists = os.path.exists(db_path)
        
        # Check what tables actually exist in this database
        tables_info = "Database not accessible"
        if db_exists:
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cursor.fetchall()]
                tables_info = f"Tables: {tables}"
                conn.close()
            except Exception as e:
                tables_info = f"Database error: {e}"
        
        return f"""
        <h2>Server Debug Info</h2>
        <p><strong>Version:</strong> {version_info}</p>
        <p><strong>Working Directory:</strong> {cwd}</p>
        <p><strong>App.py Modified:</strong> {time.ctime(app_py_time)}</p>
        <p><strong>Version.py Modified:</strong> {time.ctime(version_time)}</p>
        <p><strong>Receiving Template Exists:</strong> {template_exists}</p>
        <p><strong>Python Path:</strong> {os.sys.path[0]}</p>
        <hr>
        <p><strong>Database Path:</strong> {db_full_path}</p>
        <p><strong>Database Exists:</strong> {db_exists}</p>
        <p><strong>{tables_info}</strong></p>
        <hr>
        <p><a href="/receiving">Test Receiving Route</a></p>
        <p><a href="/receiving/debug">Test Debug Route</a></p>
        """
        
    except Exception as e:
        return f"<h2>Server Debug Error</h2><p>{str(e)}</p>"

@app.route('/receiving/debug')
@admin_required
def receiving_debug():
    """Debug route to test receiving functionality"""
    try:
        conn = get_db()
        
        # Test database connections
        po_count = conn.execute('SELECT COUNT(*) as count FROM purchase_orders').fetchone()
        shipment_count = conn.execute('SELECT COUNT(*) as count FROM shipments').fetchone()
        receiving_count = conn.execute('SELECT COUNT(*) as count FROM receiving').fetchone()
        
        # Test the actual query
        pending_shipments = conn.execute('''
            SELECT s.*, po.po_number
            FROM shipments s
            JOIN purchase_orders po ON s.po_id = po.id
            LEFT JOIN receiving r ON s.id = r.shipment_id
            WHERE s.tracking_status = 'Delivered' AND r.id IS NULL
            ORDER BY s.delivered_at DESC, s.created_at DESC
        ''').fetchall()
        
        conn.close()
        
        debug_info = {
            'status': 'success',
            'database_counts': {
                'purchase_orders': po_count['count'] if po_count else 0,
                'shipments': shipment_count['count'] if shipment_count else 0,
                'receiving': receiving_count['count'] if receiving_count else 0
            },
            'pending_shipments': len(pending_shipments),
            'template_exists': 'receiving_management.html exists',
            'version': '1.7.1'
        }
        
        return f"""
        <h2>Receiving Debug Info (v1.7.1)</h2>
        <pre>{debug_info}</pre>
        <p><a href="/receiving">Go to actual receiving page</a></p>
        """
        
    except Exception as e:
        return f"""
        <h2>Receiving Debug Error</h2>
        <p>Error: {str(e)}</p>
        <p><a href="/receiving">Try receiving page anyway</a></p>
        """

@app.route('/receiving')
@admin_required  
def receiving_management_v2():
    """Receiving management page - REBUILT VERSION"""
    try:
        conn = get_db()
        
        # Simple query first - just check if we can access receiving table
        try:
            test_query = conn.execute('SELECT COUNT(*) as count FROM receiving').fetchone()
            receiving_count = test_query['count'] if test_query else 0
        except Exception as e:
            conn.close()
            return f"""
            <h2>Database Error (v1.7.6 REBUILT)</h2>
            <p>Cannot access receiving table: {str(e)}</p>
            <p><a href="/debug/server-info">Check Database</a></p>
            """
        
        # Get pending shipments (delivered but not yet received)
        pending_shipments = conn.execute('''
            SELECT s.*, po.po_number
            FROM shipments s
            JOIN purchase_orders po ON s.po_id = po.id
            LEFT JOIN receiving r ON s.id = r.shipment_id
            WHERE s.tracking_status = 'Delivered' AND r.id IS NULL
            ORDER BY s.delivered_at DESC, s.created_at DESC
        ''').fetchall()
        
        # Get recent receiving history
        recent_receiving = conn.execute('''
            SELECT r.*, po.po_number,
                   COUNT(sb.id) as total_boxes,
                   SUM(sb.total_bags) as total_bags
            FROM receiving r
            JOIN purchase_orders po ON r.po_id = po.id
            LEFT JOIN small_boxes sb ON r.id = sb.receiving_id
            GROUP BY r.id
            ORDER BY r.received_date DESC
            LIMIT 20
        ''').fetchall()
        
        conn.close()
        
        return render_template('receiving_management.html', 
                             pending_shipments=pending_shipments,
                             recent_receiving=recent_receiving)
                             
    except Exception as e:
        # If template fails, return simple HTML with version
        return f"""
        <h2>Receiving Page Error (v1.7.6 REBUILT)</h2>
        <p>Template error: {str(e)}</p>
        <p><a href="/receiving/debug">View debug info</a></p>
        <p><a href="/debug/server-info">Check Server Info</a></p>
        <p><a href="/admin">Back to admin</a></p>
        """

@app.route('/receiving/<int:receiving_id>')
@admin_required
def receiving_details(receiving_id):
    """View detailed information about a specific receiving record"""
    try:
        conn = get_db()
        
        # Get receiving record with PO and shipment info
        receiving = conn.execute('''
            SELECT r.*, po.po_number, s.tracking_number, s.carrier
            FROM receiving r
            JOIN purchase_orders po ON r.po_id = po.id
            LEFT JOIN shipments s ON r.shipment_id = s.id
            WHERE r.id = ?
        ''', (receiving_id,)).fetchone()
        
        if not receiving:
            flash('Receiving record not found', 'error')
            return redirect(url_for('receiving_management_v2'))
        
        # Get box and bag details
        boxes = conn.execute('''
            SELECT sb.*, 
                   GROUP_CONCAT(b.bag_number) as bag_numbers, 
                   COUNT(b.id) as bag_count,
                   GROUP_CONCAT('Bag ' || b.bag_number || ': ' || COALESCE(b.pill_count, 'N/A') || ' pills') as pill_counts
            FROM small_boxes sb
            LEFT JOIN bags b ON sb.id = b.small_box_id
            WHERE sb.receiving_id = ?
            GROUP BY sb.id
            ORDER BY sb.box_number
        ''', (receiving_id,)).fetchall()
        
        conn.close()
        
        return render_template('receiving_details.html', 
                             receiving=dict(receiving),
                             boxes=[dict(box) for box in boxes])
                             
    except Exception as e:
        flash(f'Error loading receiving details: {str(e)}', 'error')
        return redirect(url_for('receiving_management_v2'))

@app.route('/api/receiving/<int:receiving_id>', methods=['DELETE'])
@admin_required
def delete_receiving(receiving_id):
    """Delete a receiving record with confirmation"""
    try:
        # Get confirmation password/name from request
        data = request.get_json() or {}
        confirmation = data.get('confirmation', '').strip().lower()
        
        # Require exact match of "delete" as confirmation
        if confirmation != 'delete':
            return jsonify({'error': 'Confirmation required. Type "delete" to confirm.'}), 400
        
        conn = get_db()
        
        # Check if receiving record exists and get info
        receiving = conn.execute('''
            SELECT r.id, po.po_number 
            FROM receiving r
            JOIN purchase_orders po ON r.po_id = po.id
            WHERE r.id = ?
        ''', (receiving_id,)).fetchone()
        
        if not receiving:
            conn.close()
            return jsonify({'error': 'Receiving record not found'}), 404
        
        # Delete in correct order due to foreign key constraints
        # 1. Delete bags first
        conn.execute('DELETE FROM bags WHERE small_box_id IN (SELECT id FROM small_boxes WHERE receiving_id = ?)', (receiving_id,))
        
        # 2. Delete small_boxes
        conn.execute('DELETE FROM small_boxes WHERE receiving_id = ?', (receiving_id,))
        
        # 3. Delete receiving record
        conn.execute('DELETE FROM receiving WHERE id = ?', (receiving_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'Successfully deleted receiving record for PO {receiving["po_number"]}'
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to delete receiving record: {str(e)}'}), 500

@app.route('/api/process_receiving', methods=['POST'])
@admin_required
def process_receiving():
    """Process a new shipment receiving with photos and box/bag tracking"""
    try:
        conn = get_db()
        
        # Get form data
        shipment_id = request.form.get('shipment_id')
        total_small_boxes = int(request.form.get('total_small_boxes', 0))
        received_by = request.form.get('received_by')
        notes = request.form.get('notes', '')
        
        # Get shipment and PO info
        shipment = conn.execute('''
            SELECT s.*, po.po_number, po.id as po_id
            FROM shipments s
            JOIN purchase_orders po ON s.po_id = po.id
            WHERE s.id = ?
        ''', (shipment_id,)).fetchone()
        
        if not shipment:
            return jsonify({'error': 'Shipment not found'}), 404
        
        # Handle photo upload
        delivery_photo = request.files.get('delivery_photo')
        photo_path = None
        zoho_photo_id = None
        
        if delivery_photo and delivery_photo.filename:
            # Save photo locally
            import os
            from werkzeug.utils import secure_filename
            
            # Create uploads directory if it doesn't exist
            upload_dir = 'static/uploads/receiving'
            os.makedirs(upload_dir, exist_ok=True)
            
            # Generate unique filename
            filename = f"shipment_{shipment_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            photo_path = os.path.join(upload_dir, filename)
            delivery_photo.save(photo_path)
            
            # TODO: Upload to Zoho (implement after basic workflow is working)
        
        # Create receiving record
        receiving_cursor = conn.execute('''
            INSERT INTO receiving (po_id, shipment_id, total_small_boxes, received_by, notes, delivery_photo_path, delivery_photo_zoho_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (shipment['po_id'], shipment_id, total_small_boxes, received_by, notes, photo_path, zoho_photo_id))
        
        receiving_id = receiving_cursor.lastrowid
        
        # Process box details with sequential bag numbering
        total_bags = 0
        all_bag_data = {}
        
        # First, collect all bag data from the form
        for key in request.form.keys():
            if key.startswith('bag_') and key.endswith('_pill_count'):
                # Extract bag number from key like 'bag_3_pill_count'
                bag_num = int(key.split('_')[1])
                if bag_num not in all_bag_data:
                    all_bag_data[bag_num] = {}
                all_bag_data[bag_num]['pill_count'] = int(request.form[key])
                all_bag_data[bag_num]['box'] = int(request.form.get(f'bag_{bag_num}_box', 0))
                all_bag_data[bag_num]['notes'] = request.form.get(f'bag_{bag_num}_notes', '')
        
        # Process boxes and their bags with sequential numbering
        for box_num in range(1, total_small_boxes + 1):
            bags_in_box = int(request.form.get(f'box_{box_num}_bags', 0))
            box_notes = request.form.get(f'box_{box_num}_notes', '')
            
            # Create small box record
            box_cursor = conn.execute('''
                INSERT INTO small_boxes (receiving_id, box_number, total_bags, notes)
                VALUES (?, ?, ?, ?)
            ''', (receiving_id, box_num, bags_in_box, box_notes))
            
            small_box_id = box_cursor.lastrowid
            
            # Create bag records for this box using sequential numbering
            for bag_data_key, bag_data in all_bag_data.items():
                if bag_data['box'] == box_num:
                    conn.execute('''
                        INSERT INTO bags (small_box_id, bag_number, pill_count, status)
                        VALUES (?, ?, ?, 'Available')
                    ''', (small_box_id, bag_data_key, bag_data['pill_count']))
                    total_bags += 1
        
        # Update shipment status to indicate it's been received
        conn.execute('''
            UPDATE shipments SET actual_delivery = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (shipment_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'Successfully received shipment for PO {shipment["po_number"]}. Processed {total_small_boxes} boxes with {total_bags} total bags.',
            'receiving_id': receiving_id
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to process receiving: {str(e)}'}), 500

@app.route('/api/available_boxes_bags/<int:po_id>')
@employee_required
def get_available_boxes_bags(po_id):
    """Get available boxes and bags for a PO (for warehouse form dropdowns)"""
    conn = get_db()
    
    # Get all receiving records for this PO with available bags
    receiving_data = conn.execute('''
        SELECT r.id as receiving_id, sb.box_number, b.bag_number, b.id as bag_id, b.bag_label_count
        FROM receiving r
        JOIN small_boxes sb ON r.id = sb.receiving_id
        JOIN bags b ON sb.id = b.small_box_id
        WHERE r.po_id = ? AND b.status = 'Available'
        ORDER BY sb.box_number, b.bag_number
    ''', (po_id,)).fetchall()
    
    conn.close()
    
    # Structure data for frontend
    boxes = {}
    for row in receiving_data:
        box_num = row['box_number']
        if box_num not in boxes:
            boxes[box_num] = []
        boxes[box_num].append({
            'bag_number': row['bag_number'],
            'bag_id': row['bag_id'],
            'bag_label_count': row['bag_label_count']
        })
    
    return jsonify({'boxes': boxes})


@app.route('/api/create_sample_receiving_data', methods=['POST'])
@admin_required  
def create_sample_receiving_data():
    """Create sample PO and shipment data for testing receiving workflow"""
    try:
        from datetime import datetime
        import random
        
        conn = get_db()
        
        # Generate unique PO number
        timestamp = datetime.now().strftime('%m%d-%H%M')
        po_number = f'TEST-{timestamp}'
        
        # Generate unique tracking number
        tracking_suffix = random.randint(100000, 999999)
        tracking_number = f'1Z999AA{tracking_suffix}'
        
        # Create sample PO
        po_cursor = conn.execute('''
            INSERT INTO purchase_orders (po_number, tablet_type, zoho_status, ordered_quantity, internal_status)
            VALUES (?, ?, ?, ?, ?)
        ''', (po_number, 'Test Tablets', 'confirmed', 1000, 'Active'))
        
        po_id = po_cursor.lastrowid
        
        # Create sample shipment with delivered status
        shipment_cursor = conn.execute('''
            INSERT INTO shipments (po_id, tracking_number, carrier, tracking_status, delivered_at, created_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ''', (po_id, tracking_number, 'UPS', 'Delivered'))
        
        shipment_id = shipment_cursor.lastrowid
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'Created sample PO {po_number} with delivered UPS shipment. Ready for receiving!',
            'po_id': po_id,
            'shipment_id': shipment_id
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to create sample data: {str(e)}'}), 500

@app.route('/api/update_submission_date', methods=['POST'])
@admin_required
def update_submission_date():
    """Update the submission date for an existing submission"""
    try:
        data = request.get_json()
        submission_id = data.get('submission_id')
        submission_date = data.get('submission_date')
        
        if not submission_id or not submission_date:
            return jsonify({'error': 'Missing submission_id or submission_date'}), 400
        
        conn = get_db()
        
        # Update the submission date
        conn.execute('''
            UPDATE warehouse_submissions 
            SET submission_date = ?
            WHERE id = ?
        ''', (submission_date, submission_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'Submission date updated to {submission_date}'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/reassign_all_submissions', methods=['POST'])
@admin_required
def reassign_all_submissions():
    """Reassign ALL submissions to POs using correct PO order (by PO number, not created_at)"""
    try:
        conn = get_db()
        
        # Step 1: Clear all PO assignments and counts
        print("Clearing all PO assignments and counts...")
        conn.execute('UPDATE warehouse_submissions SET assigned_po_id = NULL')
        conn.execute('UPDATE po_lines SET good_count = 0, damaged_count = 0')
        conn.execute('UPDATE purchase_orders SET current_good_count = 0, current_damaged_count = 0, remaining_quantity = ordered_quantity')
        conn.commit()
        
        # Step 2: Get all submissions in order with their creation timestamp
        all_submissions_rows = conn.execute('''
            SELECT ws.id, ws.product_name, ws.displays_made, 
                   ws.packs_remaining, ws.loose_tablets, ws.damaged_tablets, ws.created_at
            FROM warehouse_submissions ws
            ORDER BY ws.created_at ASC
        ''').fetchall()
        
        all_submissions = [dict(row) for row in all_submissions_rows]
        
        if not all_submissions:
            conn.close()
            return jsonify({'success': True, 'message': 'No submissions found'})
        
        matched_count = 0
        updated_pos = set()
        
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
                
                # Find ALL PO lines (open or closed) - ORDER BY PO NUMBER
                # This allows historical submissions to be assigned to their correct POs even if now closed
                # Exclude Draft POs - only assign to Issued/Active POs
                po_lines_rows = conn.execute('''
                    SELECT pl.*, po.closed
                    FROM po_lines pl
                    JOIN purchase_orders po ON pl.po_id = po.id
                    WHERE pl.inventory_item_id = ?
                    AND COALESCE(po.internal_status, '') != 'Draft'
                    AND (pl.quantity_ordered - pl.good_count - pl.damaged_count) > 0
                    ORDER BY po.po_number ASC
                ''', (inventory_item_id,)).fetchall()
                
                po_lines = [dict(row) for row in po_lines_rows]
                
                if not po_lines:
                    continue
                
                # Calculate good and damaged counts
                packages_per_display = product.get('packages_per_display') or 0
                tablets_per_package = product.get('tablets_per_package') or 0
                
                good_tablets = (submission.get('displays_made', 0) * packages_per_display * tablets_per_package + 
                              submission.get('packs_remaining', 0) * tablets_per_package + 
                              submission.get('loose_tablets', 0))
                damaged_tablets = submission.get('damaged_tablets', 0)
                
                # Assign to first available PO
                assigned_po_id = po_lines[0]['po_id']
                conn.execute('''
                    UPDATE warehouse_submissions 
                    SET assigned_po_id = ?
                    WHERE id = ?
                ''', (assigned_po_id, submission['id']))
                
                # Allocate counts to PO lines
                remaining_good = good_tablets
                remaining_damaged = damaged_tablets
                
                for line in po_lines:
                    if remaining_good <= 0 and remaining_damaged <= 0:
                        break
                        
                    available = line['quantity_ordered'] - line['good_count'] - line['damaged_count']
                    if available <= 0:
                        continue
                    
                    # Apply good count
                    if remaining_good > 0:
                        apply_good = min(remaining_good, available)
                        remaining_good -= apply_good
                        conn.execute('''
                            UPDATE po_lines 
                            SET good_count = good_count + ?
                            WHERE id = ?
                        ''', (apply_good, line['id']))
                        available -= apply_good
                    
                    # Apply damaged count
                    if remaining_damaged > 0 and available > 0:
                        apply_damaged = min(remaining_damaged, available)
                        remaining_damaged -= apply_damaged
                        conn.execute('''
                            UPDATE po_lines 
                            SET damaged_count = damaged_count + ?
                            WHERE id = ?
                        ''', (apply_damaged, line['id']))
                    
                    updated_pos.add(line['po_id'])
                
                matched_count += 1
            except Exception as e:
                print(f"Error processing submission {submission.get('id')}: {e}")
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
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': f'✅ Reassigned all {matched_count} submissions to POs using correct order (by PO number)',
            'matched': matched_count,
            'total_submissions': len(all_submissions)
        })
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌❌❌ REASSIGN ERROR: {str(e)}")
        print(error_trace)
        return jsonify({'error': str(e), 'trace': error_trace}), 500

@app.route('/api/resync_unassigned_submissions', methods=['POST'])
@admin_required
def resync_unassigned_submissions():
    """Resync unassigned submissions to try matching them with POs based on updated item IDs"""
    try:
        conn = get_db()
        
        # Get all unassigned submissions - convert to dicts immediately
        # Note: Use 'id' instead of 'rowid' for better compatibility
        unassigned_rows = conn.execute('''
            SELECT ws.id, ws.product_name, ws.displays_made, 
                   ws.packs_remaining, ws.loose_tablets, ws.damaged_tablets
            FROM warehouse_submissions ws
            WHERE ws.assigned_po_id IS NULL
            ORDER BY ws.created_at DESC
        ''').fetchall()
        
        # Convert Row objects to dicts to avoid key access issues
        unassigned = [dict(row) for row in unassigned_rows]
        
        if not unassigned:
            conn.close()
            return jsonify({'success': True, 'message': 'No unassigned submissions found'})
        
        matched_count = 0
        updated_pos = set()
        
        for submission in unassigned:
            try:
                # Get the product's details including inventory_item_id
                # submission['product_name'] matches product_details.product_name
                # then join to tablet_types to get inventory_item_id
                product_row = conn.execute('''
                    SELECT tt.inventory_item_id, pd.packages_per_display, pd.tablets_per_package
                    FROM product_details pd
                    JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                    WHERE pd.product_name = ?
                ''', (submission['product_name'],)).fetchone()
                
                if not product_row:
                    # Try direct tablet_type match if no product_details entry
                    product_row = conn.execute('''
                        SELECT inventory_item_id, 0 as packages_per_display, 0 as tablets_per_package
                        FROM tablet_types
                        WHERE tablet_type_name = ?
                    ''', (submission['product_name'],)).fetchone()
                
                if not product_row:
                    print(f"⚠️  No product config found for: {submission['product_name']}")
                    continue
                
                # Convert to dict for safe access
                product = dict(product_row)
                inventory_item_id = product.get('inventory_item_id')
                
                if not inventory_item_id:
                    print(f"⚠️  No inventory_item_id for: {submission['product_name']}")
                    continue
            except Exception as e:
                print(f"❌ Error processing submission {submission.get('id', 'unknown')}: {e}")
                continue
            
            # Find open PO lines for this inventory item
            # Order by PO number (oldest PO numbers first) since they represent issue order
            # Exclude Draft POs - only assign to Issued/Active POs
            po_lines_rows = conn.execute('''
                SELECT pl.*, po.closed
                FROM po_lines pl
                JOIN purchase_orders po ON pl.po_id = po.id
                WHERE pl.inventory_item_id = ? AND po.closed = FALSE
                AND COALESCE(po.internal_status, '') != 'Draft'
                AND (pl.quantity_ordered - pl.good_count - pl.damaged_count) > 0
                ORDER BY po.po_number ASC
            ''', (inventory_item_id,)).fetchall()
            
            # Convert to dicts
            po_lines = [dict(row) for row in po_lines_rows]
            
            if not po_lines:
                continue
            
            # Calculate good and damaged counts
            packages_per_display = product.get('packages_per_display') or 0
            tablets_per_package = product.get('tablets_per_package') or 0
            
            good_tablets = (submission.get('displays_made', 0) * packages_per_display * tablets_per_package + 
                          submission.get('packs_remaining', 0) * tablets_per_package + 
                          submission.get('loose_tablets', 0))
            damaged_tablets = submission.get('damaged_tablets', 0)
            
            # Assign to first available PO
            assigned_po_id = po_lines[0]['po_id']
            conn.execute('''
                UPDATE warehouse_submissions 
                SET assigned_po_id = ?
                WHERE id = ?
            ''', (assigned_po_id, submission['id']))
            
            # Allocate counts to PO lines
            remaining_good = good_tablets
            remaining_damaged = damaged_tablets
            
            for line in po_lines:
                if remaining_good <= 0 and remaining_damaged <= 0:
                    break
                    
                available = line['quantity_ordered'] - line['good_count'] - line['damaged_count']
                if available <= 0:
                    continue
                
                # Apply good count
                if remaining_good > 0:
                    apply_good = min(remaining_good, available)
                    remaining_good -= apply_good
                    conn.execute('''
                        UPDATE po_lines 
                        SET good_count = good_count + ?
                        WHERE id = ?
                    ''', (apply_good, line['id']))
                    available -= apply_good
                
                # Apply damaged count
                if remaining_damaged > 0 and available > 0:
                    apply_damaged = min(remaining_damaged, available)
                    remaining_damaged -= apply_damaged
                    conn.execute('''
                        UPDATE po_lines 
                        SET damaged_count = damaged_count + ?
                        WHERE id = ?
                    ''', (apply_damaged, line['id']))
                
                updated_pos.add(line['po_id'])
            
            matched_count += 1
        
        # Update PO header totals for all affected POs
        for po_id in updated_pos:
            totals_row = conn.execute('''
                SELECT 
                    COALESCE(SUM(quantity_ordered), 0) as total_ordered,
                    COALESCE(SUM(good_count), 0) as total_good,
                    COALESCE(SUM(damaged_count), 0) as total_damaged
                FROM po_lines 
                WHERE po_id = ?
            ''', (po_id,)).fetchone()
            
            # Convert to dict
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
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': f'Successfully matched {matched_count} of {len(unassigned)} unassigned submissions to POs',
            'matched': matched_count,
            'total_unassigned': len(unassigned)
        })
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌❌❌ RESYNC ERROR: {str(e)}")
        print(error_trace)
        return jsonify({'error': str(e), 'trace': error_trace}), 500

@app.route('/api/po/<int:po_id>/submissions', methods=['GET'])
@admin_required
def get_po_submissions(po_id):
    """Get all submissions assigned to a specific PO"""
    try:
        conn = get_db()
        
        # Get PO details
        po = conn.execute('''
            SELECT po_number, tablet_type, ordered_quantity, 
                   current_good_count, current_damaged_count, remaining_quantity
            FROM purchase_orders
            WHERE id = ?
        ''', (po_id,)).fetchone()
        
        if not po:
            conn.close()
            return jsonify({'error': 'PO not found'}), 404
        
        # Get all submissions for this PO
        submissions = conn.execute('''
            SELECT 
                ws.id,
                ws.product_name,
                ws.displays_made,
                ws.packs_remaining,
                ws.loose_tablets,
                ws.damaged_tablets,
                ws.created_at,
                ws.submission_date,
                e.name as employee_name
            FROM warehouse_submissions ws
            LEFT JOIN employees e ON ws.employee_id = e.id
            WHERE ws.assigned_po_id = ?
            ORDER BY ws.created_at DESC
        ''', (po_id,)).fetchall()
        
        conn.close()
        
        return jsonify({
            'success': True,
            'po': dict(po),
            'submissions': [dict(s) for s in submissions],
            'count': len(submissions)
        })
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ Error fetching PO submissions: {str(e)}")
        print(error_trace)
        return jsonify({'error': str(e)}), 500

# ===== TEMPLATE CONTEXT PROCESSORS =====

@app.context_processor
def inject_version():
    """Make version information available to all templates"""
    return {
        'version': lambda: __version__,
        'app_title': __title__,
        'app_description': __description__,
        'current_language': get_locale(),
        'languages': app.config['LANGUAGES'],
        'gettext': gettext,
        'ngettext': ngettext
    }

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5002)
