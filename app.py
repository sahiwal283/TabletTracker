from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session, make_response
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import sqlite3
import json
import os
import requests
import hashlib
import re
import traceback
import csv
import io
from functools import wraps
from config import Config
from app.services.zoho_service import zoho_api
from __version__ import __version__, __title__, __description__
from app.services.tracking_service import refresh_shipment_row
from app.services.report_service import ProductionReportGenerator
from flask_babel import Babel, gettext, ngettext, lazy_gettext, get_locale

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY

# Helper function to get current time in EST
def get_est_timestamp():
    """Get current timestamp in Eastern Time (EST/EDT)"""
    return datetime.now(ZoneInfo('America/New_York')).strftime('%Y-%m-%d %H:%M:%S')

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
        conn = None
        try:
            conn = get_db()
            employee = conn.execute('''
                SELECT preferred_language FROM employees WHERE id = ?
            ''', (session.get('employee_id'),)).fetchone()
            if employee and employee['preferred_language'] and employee['preferred_language'] in app.config['LANGUAGES']:
                session['language'] = employee['preferred_language']
                return employee['preferred_language']
        except Exception as e:
            # Continue to fallback if database query fails
            pass
        finally:
            if conn:
                try:
                    conn.close()
                except:
                    pass
    
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
    conn = sqlite3.connect(Config.DATABASE_PATH)
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
    
    # Add parent_po_number column for tracking overs POs linked to parent POs
    try:
        c.execute('ALTER TABLE purchase_orders ADD COLUMN parent_po_number TEXT')
    except:
        pass  # Column already exists
    
    # Add machine count columns to purchase_orders for separate tracking
    try:
        c.execute('ALTER TABLE purchase_orders ADD COLUMN machine_good_count INTEGER DEFAULT 0')
    except:
        pass
    try:
        c.execute('ALTER TABLE purchase_orders ADD COLUMN machine_damaged_count INTEGER DEFAULT 0')
    except:
        pass
    
    # Add machine count columns to po_lines for separate tracking
    c.execute('PRAGMA table_info(po_lines)')
    existing_po_lines_cols = [row[1] for row in c.fetchall()]
    if 'machine_good_count' not in existing_po_lines_cols:
        try:
            c.execute('ALTER TABLE po_lines ADD COLUMN machine_good_count INTEGER DEFAULT 0')
        except:
            pass
    if 'machine_damaged_count' not in existing_po_lines_cols:
        try:
            c.execute('ALTER TABLE po_lines ADD COLUMN machine_damaged_count INTEGER DEFAULT 0')
        except:
            pass
    
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
        inventory_item_id TEXT UNIQUE,
        category TEXT
    )''')
    
    # Add category column if it doesn't exist (for existing databases)
    try:
        c.execute('ALTER TABLE tablet_types ADD COLUMN category TEXT')
    except:
        pass  # Column already exists
    
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
    
    # Add po_assignment_verified column to warehouse_submissions for approval workflow
    if 'po_assignment_verified' not in existing_ws_cols:
        try:
            c.execute('ALTER TABLE warehouse_submissions ADD COLUMN po_assignment_verified BOOLEAN DEFAULT FALSE')
            # All existing submissions default to unverified (need manager approval)
            print("Added po_assignment_verified column to warehouse_submissions table")
        except Exception:
            pass
    
    # Add inventory_item_id column to warehouse_submissions for reliable product matching
    if 'inventory_item_id' not in existing_ws_cols:
        try:
            c.execute('ALTER TABLE warehouse_submissions ADD COLUMN inventory_item_id TEXT')
            # Backfill existing submissions with inventory_item_id from product_details
            c.execute('''
                UPDATE warehouse_submissions 
                SET inventory_item_id = (
                    SELECT tt.inventory_item_id 
                    FROM product_details pd
                    JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                    WHERE pd.product_name = warehouse_submissions.product_name
                )
                WHERE inventory_item_id IS NULL
            ''')
            rows_updated = c.execute('SELECT changes()').fetchone()[0]
            print(f"Added inventory_item_id column to warehouse_submissions and backfilled {rows_updated} existing records")
        except Exception as e:
            print(f"Note: inventory_item_id column migration: {e}")
    
    # Add admin_notes column to warehouse_submissions for admin-only notes
    if 'admin_notes' not in existing_ws_cols:
        try:
            c.execute('ALTER TABLE warehouse_submissions ADD COLUMN admin_notes TEXT')
            print("Added admin_notes column to warehouse_submissions table")
        except Exception as e:
            print(f"Note: admin_notes column migration: {e}")
    
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
    c.execute('PRAGMA table_info(bags)')
    existing_bags_cols = [row[1] for row in c.fetchall()]
    if 'pill_count' not in existing_bags_cols:
        try:
            c.execute('ALTER TABLE bags ADD COLUMN pill_count INTEGER')
            print("Added pill_count column to bags table")
        except Exception as e:
            print(f"Note: pill_count column migration: {e}")
    
    # Add tablet_type_id column to bags table if it doesn't exist
    if 'tablet_type_id' not in existing_bags_cols:
        try:
            c.execute('ALTER TABLE bags ADD COLUMN tablet_type_id INTEGER')
            print("Added tablet_type_id column to bags table")
        except Exception as e:
            print(f"Note: tablet_type_id column migration: {e}")
    
    # Add submission_type column to warehouse_submissions if it doesn't exist
    c.execute('PRAGMA table_info(warehouse_submissions)')
    existing_ws_cols = [row[1] for row in c.fetchall()]
    if 'submission_type' not in existing_ws_cols:
        try:
            c.execute('ALTER TABLE warehouse_submissions ADD COLUMN submission_type TEXT DEFAULT "packaged"')
            # Backfill existing records
            c.execute('UPDATE warehouse_submissions SET submission_type = "packaged" WHERE submission_type IS NULL')
            print("Added submission_type column to warehouse_submissions table")
        except Exception as e:
            print(f"Note: submission_type column migration: {e}")
    
    # Add bag_id column to warehouse_submissions (links to receives)
    if 'bag_id' not in existing_ws_cols:
        try:
            c.execute('ALTER TABLE warehouse_submissions ADD COLUMN bag_id INTEGER REFERENCES bags(id)')
            print("Added bag_id column to warehouse_submissions table")
        except Exception as e:
            print(f"Note: bag_id column migration: {e}")
    
    # Add needs_review flag to warehouse_submissions
    if 'needs_review' not in existing_ws_cols:
        try:
            c.execute('ALTER TABLE warehouse_submissions ADD COLUMN needs_review BOOLEAN DEFAULT FALSE')
            print("Added needs_review column to warehouse_submissions table")
        except Exception as e:
            print(f"Note: needs_review column migration: {e}")
    
    # Migrate existing data: lock in soft assignments and flag unassigned
    try:
        # Lock in soft assignments (po_assignment_verified = 0 → 1)
        c.execute('''
            UPDATE warehouse_submissions 
            SET po_assignment_verified = 1 
            WHERE assigned_po_id IS NOT NULL 
            AND COALESCE(po_assignment_verified, 0) = 0
        ''')
        
        # Flag unassigned submissions for manual review
        c.execute('''
            UPDATE warehouse_submissions 
            SET needs_review = 1 
            WHERE assigned_po_id IS NULL
            AND bag_id IS NULL
        ''')
        print("Migrated existing submission data: locked soft assignments, flagged unassigned")
    except Exception as e:
        print(f"Note: existing data migration: {e}")
    
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
                    tablet_type_id INTEGER,
                    status TEXT DEFAULT 'Available',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (small_box_id) REFERENCES small_boxes (id)
                )''')
    
    # Machine counts table - tracks machine counter readings by flavor/tablet type
    c.execute('''CREATE TABLE IF NOT EXISTS machine_counts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tablet_type_id INTEGER,
        machine_count INTEGER NOT NULL,
        employee_name TEXT NOT NULL,
        count_date DATE NOT NULL,
        box_number TEXT,
        bag_number TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (tablet_type_id) REFERENCES tablet_types (id)
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
    
    # App Settings table for system-wide configuration
    c.execute('''CREATE TABLE IF NOT EXISTS app_settings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        setting_key TEXT UNIQUE NOT NULL,
        setting_value TEXT NOT NULL,
        description TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Initialize default settings if they don't exist
    default_settings = [
        ('cards_per_turn', '1', 'Number of cards produced in one turn of the machine (LEGACY - use machines table)')
    ]
    for key, value, description in default_settings:
        existing = c.execute('SELECT id FROM app_settings WHERE setting_key = ?', (key,)).fetchone()
        if not existing:
            c.execute('''
                INSERT INTO app_settings (setting_key, setting_value, description)
                VALUES (?, ?, ?)
            ''', (key, value, description))
    
    # Machines table - configurable production machines
    c.execute('''CREATE TABLE IF NOT EXISTS machines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        machine_name TEXT UNIQUE NOT NULL,
        cards_per_turn INTEGER NOT NULL DEFAULT 1,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Initialize default machines if none exist
    existing_machines = c.execute('SELECT COUNT(*) as count FROM machines').fetchone()
    if existing_machines['count'] == 0:
        default_machines = [
            ('Machine 1', 1),
            ('Machine 2', 1)
        ]
        for machine_name, cards_per_turn in default_machines:
            c.execute('''
                INSERT INTO machines (machine_name, cards_per_turn, is_active)
                VALUES (?, ?, TRUE)
            ''', (machine_name, cards_per_turn))
        print("Initialized default machines: Machine 1 and Machine 2")
    
    # Add machine_id column to machine_counts table if it doesn't exist
    c.execute('PRAGMA table_info(machine_counts)')
    machine_counts_cols = [row[1] for row in c.fetchall()]
    if 'machine_id' not in machine_counts_cols:
        try:
            c.execute('ALTER TABLE machine_counts ADD COLUMN machine_id INTEGER REFERENCES machines(id)')
            print("Added machine_id column to machine_counts table")
        except Exception as e:
            print(f"Note: machine_id column migration: {e}")
    
    # Categories table - proper category management (no more hardcoded lists!)
    c.execute('''CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category_name TEXT UNIQUE NOT NULL,
        display_order INTEGER DEFAULT 999,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Migrate/seed categories
    existing_categories_count = c.execute('SELECT COUNT(*) as count FROM categories WHERE is_active = TRUE').fetchone()['count']
    if existing_categories_count == 0:
        # Get existing categories from tablet_types
        existing_from_tablet_types = c.execute('''
            SELECT DISTINCT category 
            FROM tablet_types 
            WHERE category IS NOT NULL AND category != ''
        ''').fetchall()
        
        # Default categories with display order
        default_categories = [
            ('FIX Energy', 1),
            ('FIX Focus', 2),
            ('FIX Relax', 3),
            ('FIX MAX', 4),
            ('18mg', 5),
            ('Hyroxi XL', 6),
            ('Hyroxi Regular', 7),
            ('Other', 999)
        ]
        
        # Combine existing and defaults (avoid duplicates)
        all_categories = set()
        for cat in existing_from_tablet_types:
            if cat['category']:
                all_categories.add(cat['category'])
        
        # Add defaults
        for cat_name, order in default_categories:
            all_categories.add(cat_name)
        
        # Insert all categories
        for idx, cat_name in enumerate(sorted(all_categories)):
            # Use default order if available, otherwise use index
            order = next((order for name, order in default_categories if name == cat_name), idx + 100)
            c.execute('''
                INSERT INTO categories (category_name, display_order, is_active)
                VALUES (?, ?, TRUE)
            ''', (cat_name, order))
        
        print(f"Initialized {len(all_categories)} categories")
    
    # Commit and close with error handling
    try:
        conn.commit()
    except Exception as e:
        print(f"❌ Database commit error during initialization: {str(e)}")
        try:
            conn.rollback()
        except:
            pass
        raise  # Re-raise to ensure init failures are visible
    finally:
        try:
            conn.close()
        except:
            pass

def get_db():
    conn = sqlite3.connect(Config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def auto_sync_categories(conn):
    """
    Auto-sync categories from tablet_types to categories table.
    This ensures all categories in use appear in dropdowns.
    Called automatically when categories are accessed.
    """
    try:
        # Get all unique categories from tablet_types
        categories_in_use = conn.execute('''
            SELECT DISTINCT category 
            FROM tablet_types 
            WHERE category IS NOT NULL AND category != ''
        ''').fetchall()
        
        app.logger.debug(f"Auto-sync: Found {len(categories_in_use)} categories in tablet_types: {[c['category'] for c in categories_in_use]}")
        
        for cat_row in categories_in_use:
            category_name = cat_row['category']
            
            # Check if category exists in categories table
            existing = conn.execute('''
                SELECT id FROM categories WHERE category_name = ?
            ''', (category_name,)).fetchone()
            
            if not existing:
                # Get max display_order
                max_order = conn.execute('SELECT MAX(display_order) as max FROM categories').fetchone()['max']
                new_order = (max_order or 0) + 1
                
                # Insert new category
                conn.execute('''
                    INSERT INTO categories (category_name, display_order, is_active)
                    VALUES (?, ?, TRUE)
                ''', (category_name, new_order))
                app.logger.info(f"Auto-sync: Added new category '{category_name}' with display_order {new_order}")
        
        conn.commit()
        app.logger.debug("Auto-sync: Categories synced successfully")
    except Exception as e:
        app.logger.error(f"Auto-sync categories failed: {e}")
        import traceback
        app.logger.error(traceback.format_exc())
        # Don't raise - this is a background sync, shouldn't break main functionality

def find_bag_for_submission(conn, tablet_type_id, box_number, bag_number):
    """
    Find matching bag in receives by tablet_type_id, box_number, bag_number.
    
    If exactly 1 match: Returns bag, assigns automatically
    If 2+ matches: Returns None for bag, flags for manual review
    If 0 matches: Returns error
    
    Returns: (bag_row or None, needs_review_flag, error_message)
    """
    # Check for duplicates FIRST (same tablet_type + box + bag in multiple receives)
    matching_bags = conn.execute('''
        SELECT b.*, sb.box_number, sb.receiving_id, r.po_id, r.received_date
        FROM bags b
        JOIN small_boxes sb ON b.small_box_id = sb.id
        JOIN receiving r ON sb.receiving_id = r.id
        WHERE b.tablet_type_id = ? 
        AND sb.box_number = ? 
        AND b.bag_number = ?
        ORDER BY r.received_date DESC
    ''', (tablet_type_id, box_number, bag_number)).fetchall()
    
    if not matching_bags:
        return None, False, f'No receive found for this product, Box #{box_number}, Bag #{bag_number}. Please check receiving records or contact your manager.'
    
    # If exactly 1 match: auto-assign
    if len(matching_bags) == 1:
        return matching_bags[0], False, None
    
    # If 2+ matches: needs manual review, don't auto-assign
    return None, True, None

# Helper function to require login for admin views
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Allow if admin authenticated OR if employee authenticated with admin role
        if not (session.get('admin_authenticated') or 
                (session.get('employee_authenticated') and session.get('employee_role') == 'admin')):
            # Check if this is an API request (starts with /api/)
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': 'Access denied. Admin authentication required.'}), 403
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
    conn = None
    try:
        conn = get_db()
        result = conn.execute(
            'SELECT role FROM employees WHERE username = ? AND is_active = 1',
            (username,)
        ).fetchone()
        return result['role'] if result else None
    except Exception as e:
        return None
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

def has_permission(username, required_permission):
    """Check if an employee has a specific permission"""
    role = get_employee_role(username)
    if not role:
        return False
    
    permissions = ROLE_PERMISSIONS.get(role, [])
    return 'all' in permissions or required_permission in permissions

def ensure_app_settings_table():
    """Ensure app_settings table exists, create if missing"""
    conn = None
    try:
        conn = get_db()
        # Check if table exists
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='app_settings'")
        if not c.fetchone():
            # Create the table
            c.execute('''CREATE TABLE IF NOT EXISTS app_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                setting_key TEXT UNIQUE NOT NULL,
                setting_value TEXT NOT NULL,
                description TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            # Initialize default settings
            default_settings = [
                ('cards_per_turn', '1', 'Number of cards produced in one turn of the machine')
            ]
            for key, value, description in default_settings:
                c.execute('''
                    INSERT INTO app_settings (setting_key, setting_value, description)
                    VALUES (?, ?, ?)
                ''', (key, value, description))
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error ensuring app_settings table: {e}")
        import traceback
        traceback.print_exc()
        if conn:
            try:
                conn.close()
            except:
                pass

def ensure_submission_type_column():
    """Ensure submission_type column exists in warehouse_submissions table"""
    conn = None
    try:
        conn = get_db()
        c = conn.cursor()
        # Check if column exists
        c.execute('PRAGMA table_info(warehouse_submissions)')
        existing_cols = [row[1] for row in c.fetchall()]
        if 'submission_type' not in existing_cols:
            # Add the column
            c.execute('ALTER TABLE warehouse_submissions ADD COLUMN submission_type TEXT DEFAULT "packaged"')
            # Backfill existing records
            c.execute('UPDATE warehouse_submissions SET submission_type = "packaged" WHERE submission_type IS NULL')
            conn.commit()
            print("Added submission_type column to warehouse_submissions table")
        conn.close()
    except Exception as e:
        print(f"Error ensuring submission_type column: {e}")
        import traceback
        traceback.print_exc()
        if conn:
            try:
                conn.close()
            except:
                pass

def ensure_machine_counts_table():
    """Ensure machine_counts table exists, create if missing"""
    conn = None
    try:
        conn = get_db()
        c = conn.cursor()
        # Check if table exists
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='machine_counts'")
        if not c.fetchone():
            # Create the table
            c.execute('''CREATE TABLE IF NOT EXISTS machine_counts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tablet_type_id INTEGER,
                machine_count INTEGER NOT NULL,
                employee_name TEXT NOT NULL,
                count_date DATE NOT NULL,
                box_number TEXT,
                bag_number TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (tablet_type_id) REFERENCES tablet_types (id)
            )''')
            conn.commit()
            print("Created machine_counts table")
        conn.close()
    except Exception as e:
        print(f"Error ensuring machine_counts table: {e}")
        import traceback
        traceback.print_exc()
        if conn:
            try:
                conn.close()
            except:
                pass

def ensure_machine_count_columns():
    """Ensure machine_good_count and machine_damaged_count columns exist in purchase_orders and po_lines tables, and box_number/bag_number in machine_counts"""
    conn = None
    try:
        conn = get_db()
        c = conn.cursor()
        
        # Check and add columns to purchase_orders table
        c.execute('PRAGMA table_info(purchase_orders)')
        po_cols = [row[1] for row in c.fetchall()]
        
        if 'machine_good_count' not in po_cols:
            try:
                c.execute('ALTER TABLE purchase_orders ADD COLUMN machine_good_count INTEGER DEFAULT 0')
                print("Added machine_good_count column to purchase_orders table")
            except Exception as e:
                print(f"Note: machine_good_count column migration: {e}")
        
        if 'machine_damaged_count' not in po_cols:
            try:
                c.execute('ALTER TABLE purchase_orders ADD COLUMN machine_damaged_count INTEGER DEFAULT 0')
                print("Added machine_damaged_count column to purchase_orders table")
            except Exception as e:
                print(f"Note: machine_damaged_count column migration: {e}")
        
        # Check and add columns to po_lines table
        c.execute('PRAGMA table_info(po_lines)')
        po_lines_cols = [row[1] for row in c.fetchall()]
        
        if 'machine_good_count' not in po_lines_cols:
            try:
                c.execute('ALTER TABLE po_lines ADD COLUMN machine_good_count INTEGER DEFAULT 0')
                print("Added machine_good_count column to po_lines table")
            except Exception as e:
                print(f"Note: machine_good_count column migration: {e}")
        
        if 'machine_damaged_count' not in po_lines_cols:
            try:
                c.execute('ALTER TABLE po_lines ADD COLUMN machine_damaged_count INTEGER DEFAULT 0')
                print("Added machine_damaged_count column to po_lines table")
            except Exception as e:
                print(f"Note: machine_damaged_count column migration: {e}")
        
        # Check and add columns to machine_counts table
        c.execute('PRAGMA table_info(machine_counts)')
        machine_counts_cols = [row[1] for row in c.fetchall()]
        
        if 'box_number' not in machine_counts_cols:
            try:
                c.execute('ALTER TABLE machine_counts ADD COLUMN box_number TEXT')
                print("Added box_number column to machine_counts table")
            except Exception as e:
                print(f"Note: box_number column migration: {e}")
        
        if 'bag_number' not in machine_counts_cols:
            try:
                c.execute('ALTER TABLE machine_counts ADD COLUMN bag_number TEXT')
                print("Added bag_number column to machine_counts table")
            except Exception as e:
                print(f"Note: bag_number column migration: {e}")
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error ensuring machine count columns: {e}")
        import traceback
        traceback.print_exc()
        if conn:
            try:
                conn.close()
            except:
                pass

def get_setting(setting_key, default_value=None):
    """Get a setting value from app_settings table"""
    conn = None
    try:
        ensure_app_settings_table()  # Ensure table exists
        conn = get_db()
        setting = conn.execute(
            'SELECT setting_value FROM app_settings WHERE setting_key = ?',
            (setting_key,)
        ).fetchone()
        if setting:
            return setting['setting_value']
        return default_value
    except Exception as e:
        print(f"Error getting setting {setting_key}: {e}")
        return default_value
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

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
            conn = None
            try:
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
            except Exception as e:
                if conn:
                    try:
                        conn.close()
                    except:
                        pass
                print(f"Login error in index(): {str(e)}")
                flash('An error occurred during login', 'error')
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

@app.route('/production')
@employee_required
def production_form():
    """Combined production submission and bag count form"""
    conn = None
    try:
        conn = get_db()
        
        # Auto-sync categories from tablet_types to categories table
        auto_sync_categories(conn)
        
        # Get product list for dropdown
        products = conn.execute('''
            SELECT pd.product_name, tt.tablet_type_name, pd.packages_per_display, pd.tablets_per_package
            FROM product_details pd
            JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            ORDER BY pd.product_name
        ''').fetchall()
        
        # Get all tablet types for bag count dropdown
        tablet_types = conn.execute('''
            SELECT * FROM tablet_types 
            ORDER BY tablet_type_name
        ''').fetchall()
        
        # Get employee info for display (handle admin users)
        employee = None
        if session.get('admin_authenticated'):
            # Create a mock employee object for admin
            class MockEmployee:
                full_name = 'Admin'
            employee = MockEmployee()
        elif session.get('employee_id'):
            employee = conn.execute('''
                SELECT full_name FROM employees WHERE id = ?
            ''', (session.get('employee_id'),)).fetchone()
        
        conn.close()
        
        # Get today's date for the date picker
        today_date = datetime.now().date().isoformat()
        
        # Check if user is admin or manager (for admin notes access)
        is_admin = session.get('admin_authenticated') or session.get('employee_role') in ['admin', 'manager']
        
        return render_template('production.html', products=products, tablet_types=tablet_types, employee=employee, today_date=today_date, is_admin=is_admin)
    except Exception as e:
        if conn:
            try:
                conn.close()
            except:
                pass
        # Log error and re-raise to let Flask handle it
        print(f"Error in production_form(): {str(e)}")
        raise

@app.route('/warehouse')
@employee_required
def warehouse_form():
    """Legacy route - redirects to production page"""
    return redirect(url_for('production_form'))

@app.route('/submit_warehouse', methods=['POST'])
@employee_required
def submit_warehouse():
    """Process warehouse submission and update PO counts"""
    conn = None
    try:
        data = request.get_json() if request.is_json else request.form
        
        # Validate required fields
        if not data.get('product_name'):
            return jsonify({'error': 'product_name is required'}), 400
        
        # Ensure submission_type column exists
        ensure_submission_type_column()
        
        # Get employee name from session
        conn = get_db()
        
        # Handle admin users (they don't have employee_id in session)
        if session.get('admin_authenticated'):
            employee_name = 'Admin'
        else:
            employee = conn.execute('''
                SELECT full_name FROM employees WHERE id = ?
            ''', (session.get('employee_id'),)).fetchone()
            
            if not employee:
                return jsonify({'error': 'Employee not found'}), 400
            
            employee_name = employee['full_name']
        
        # Get product details
        product = conn.execute('''
            SELECT pd.*, tt.inventory_item_id, tt.tablet_type_name
            FROM product_details pd
            JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            WHERE pd.product_name = ?
        ''', (data.get('product_name'),)).fetchone()
        
        if not product:
            return jsonify({'error': 'Product not found'}), 400
        
        # Convert Row to dict for safe access
        product = dict(product)
        
        # Validate product configuration
        packages_per_display = product.get('packages_per_display')
        tablets_per_package = product.get('tablets_per_package')
        
        if packages_per_display is None or tablets_per_package is None or packages_per_display == 0 or tablets_per_package == 0:
            return jsonify({'error': 'Product configuration incomplete: packages_per_display and tablets_per_package are required and must be greater than 0'}), 400
        
        # Convert to int after validation
        try:
            packages_per_display = int(packages_per_display)
            tablets_per_package = int(tablets_per_package)
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid numeric values for product configuration'}), 400
        
        # Calculate tablet counts with safe type conversion
        try:
            displays_made = int(data.get('displays_made', 0) or 0)
            packs_remaining = int(data.get('packs_remaining', 0) or 0)
            loose_tablets = 0  # No longer collected from form
            damaged_tablets = 0  # No longer collected from form
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid numeric values for counts'}), 400
        
        good_tablets = (displays_made * packages_per_display * tablets_per_package + 
                       packs_remaining * tablets_per_package)
        
        # Get submission_date (defaults to today if not provided)
        submission_date = data.get('submission_date', datetime.now().date().isoformat())
        
        # Get admin_notes if user is admin or manager
        admin_notes = data.get('admin_notes', '') if (session.get('admin_authenticated') or session.get('employee_role') in ['admin', 'manager']) else None
        
        # Get inventory_item_id and tablet_type_id from product
        inventory_item_id = product.get('inventory_item_id')
        tablet_type_id = product.get('tablet_type_id')
        if not inventory_item_id:
            return jsonify({'error': 'Product inventory_item_id not found'}), 400
        if not tablet_type_id:
            return jsonify({'error': 'Product tablet_type_id not found'}), 400
        
        # Find matching bag in receives
        bag, needs_review, error = find_bag_for_submission(
            conn, tablet_type_id, data.get('box_number'), data.get('bag_number')
        )
        
        if error:
            return jsonify({'error': error}), 404
        
        # If needs_review, bag will be None (ambiguous submission)
        bag_id = bag['id'] if bag else None
        po_id = bag['po_id'] if bag else None
        
        # Insert submission record with bag_id (or NULL if needs review)
        conn.execute('''
            INSERT INTO warehouse_submissions 
            (employee_name, product_name, inventory_item_id, box_number, bag_number, 
             bag_id, assigned_po_id, needs_review, displays_made, packs_remaining, 
             loose_tablets, damaged_tablets, submission_date, admin_notes, submission_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'packaged')
        ''', (employee_name, data.get('product_name'), inventory_item_id, data.get('box_number'),
              data.get('bag_number'), bag_id, po_id, needs_review,
              displays_made, packs_remaining, 0, 0, submission_date, admin_notes))
        
        conn.commit()
        
        message = 'Submission flagged for manager review - multiple matching receives found.' if needs_review else 'Submission processed successfully'
        
        return jsonify({
            'success': True, 
            'message': message,
            'bag_id': bag_id,
            'po_number': po_id,
            'needs_review': needs_review
        })
        
    except Exception as e:
        print(f"Error in submit_warehouse: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/dashboard')
@role_required('dashboard')
def admin_dashboard():
    """Desktop dashboard for managers/admins"""
    conn = None
    try:
        conn = get_db()
        
        # Get active receives that have submissions assigned (last 10)
        active_receives_query = '''
            SELECT r.*,
                   po.po_number,
                   po.id as po_id,
                   -- Calculate receive number (which shipment # for this PO)
                   (
                       SELECT COUNT(*) + 1
                       FROM receiving r2
                       WHERE r2.po_id = r.po_id
                       AND (r2.received_date < r.received_date 
                            OR (r2.received_date = r.received_date AND r2.id < r.id))
                   ) as receive_number,
                   COUNT(DISTINCT b.id) as bag_count,
                   COALESCE(SUM(b.bag_label_count), 0) as total_received,
                   COUNT(DISTINCT ws.id) as submission_count,
                   -- Calculate good count from submissions
                   COALESCE((
                       SELECT SUM(
                           (COALESCE(ws2.displays_made, 0) * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0)) +
                           (COALESCE(ws2.packs_remaining, 0) * COALESCE(pd.tablets_per_package, 0)) +
                           COALESCE(ws2.loose_tablets, 0)
                       )
                       FROM warehouse_submissions ws2
                       LEFT JOIN product_details pd ON ws2.product_name = pd.product_name
                       LEFT JOIN bags b2 ON ws2.bag_id = b2.id
                       LEFT JOIN small_boxes sb2 ON b2.small_box_id = sb2.id
                       WHERE sb2.receiving_id = r.id
                   ), 0) as current_good_count,
                   -- Calculate damaged count
                   COALESCE((
                       SELECT SUM(COALESCE(ws2.damaged_tablets, 0))
                       FROM warehouse_submissions ws2
                       LEFT JOIN bags b2 ON ws2.bag_id = b2.id
                       LEFT JOIN small_boxes sb2 ON b2.small_box_id = sb2.id
                       WHERE sb2.receiving_id = r.id
                   ), 0) as current_damaged_count,
                   -- Get primary tablet type (most common in this receive)
                   (
                       SELECT tt.tablet_type_name
                       FROM bags b3
                       JOIN small_boxes sb3 ON b3.small_box_id = sb3.id
                       JOIN tablet_types tt ON b3.tablet_type_id = tt.id
                       WHERE sb3.receiving_id = r.id
                       GROUP BY tt.tablet_type_name
                       ORDER BY COUNT(*) DESC
                       LIMIT 1
                   ) as tablet_type
            FROM receiving r
            LEFT JOIN purchase_orders po ON r.po_id = po.id
            LEFT JOIN small_boxes sb ON sb.receiving_id = r.id
            LEFT JOIN bags b ON b.small_box_id = sb.id
            LEFT JOIN warehouse_submissions ws ON ws.bag_id = b.id
            WHERE r.received_date IS NOT NULL
            AND r.id IS NOT NULL
            GROUP BY r.id
            HAVING submission_count > 0
            ORDER BY r.received_date DESC
            LIMIT 10
        '''
        print("📊 Executing active receives query...")
        active_pos = conn.execute(active_receives_query).fetchall()
        print(f"✅ Found {len(active_pos)} active receives")
        
        # Get closed POs for historical reference (removed from dashboard)
        closed_pos = []
        
        # Get tablet types for report filters
        tablet_types = conn.execute('SELECT id, tablet_type_name FROM tablet_types ORDER BY tablet_type_name').fetchall()
        
        # Get recent submissions with bag relationship and separate machine/packaged totals
        submissions_query = '''
            SELECT ws.*, 
                   po.po_number, 
                   po.closed as po_closed,
                   pd.packages_per_display, 
                   pd.tablets_per_package,
                   b.bag_label_count as receive_bag_count,
                   r.id as receiving_id,
                   ws.needs_review,
                   ws.admin_notes,
                   -- SEPARATE machine count total for this bag
                   (SELECT SUM(ws2.loose_tablets)
                    FROM warehouse_submissions ws2
                    WHERE ws2.bag_id = ws.bag_id 
                    AND ws2.submission_type = 'machine') as machine_count_total,
                   -- SEPARATE packaged/bag count total for this bag
                   (SELECT SUM(
                       CASE ws2.submission_type
                           WHEN 'packaged' THEN (ws2.displays_made * pd2.packages_per_display * pd2.tablets_per_package + 
                                                ws2.packs_remaining * pd2.tablets_per_package)
                           WHEN 'bag' THEN ws2.loose_tablets
                           ELSE 0 END)
                   FROM warehouse_submissions ws2
                   LEFT JOIN product_details pd2 ON ws2.product_name = pd2.product_name
                   WHERE ws2.bag_id = ws.bag_id 
                   AND ws2.submission_type IN ('packaged', 'bag')) as packaged_count_total,
                   -- Individual submission count
                   (
                       CASE ws.submission_type
                           WHEN 'packaged' THEN (ws.displays_made * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0) + 
                                                ws.packs_remaining * COALESCE(pd.tablets_per_package, 0))
                           WHEN 'bag' THEN ws.loose_tablets
                           WHEN 'machine' THEN ws.loose_tablets
                           ELSE ws.loose_tablets + ws.damaged_tablets
                       END
                   ) as calculated_total
            FROM warehouse_submissions ws
            LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
            LEFT JOIN bags b ON ws.bag_id = b.id
            LEFT JOIN small_boxes sb ON b.small_box_id = sb.id
            LEFT JOIN receiving r ON sb.receiving_id = r.id
            ORDER BY ws.created_at DESC
            LIMIT 50
        '''
        submissions_raw = conn.execute(submissions_query).fetchall()
        
        # Calculate running totals by bag using bag_id (with legacy fallback)
        # Track machine and packaged totals separately
        bag_running_totals_machine = {}  # Key: bag_id or (po_id, product_name, "box/bag")
        bag_running_totals_packaged = {}  # Key: bag_id or (po_id, product_name, "box/bag")
        submissions_processed = []
        
        for sub in submissions_raw:
            sub_dict = dict(sub)
            
            # Use bag_id as primary key, fallback to legacy key for old submissions
            bag_id = sub_dict.get('bag_id')
            if bag_id:
                bag_key = bag_id
            else:
                # Legacy fallback: use (po_id, product_name, "box/bag") tuple
                bag_identifier = f"{sub_dict.get('box_number', '')}/{sub_dict.get('bag_number', '')}"
                bag_key = (sub_dict.get('assigned_po_id'), sub_dict.get('product_name'), bag_identifier)
            
            # Individual calculation for this submission
            individual_calc = sub_dict.get('calculated_total', 0) or 0
            submission_type = sub_dict.get('submission_type', 'packaged')
            
            # Initialize running totals for this bag if not exists
            if bag_key not in bag_running_totals_machine:
                bag_running_totals_machine[bag_key] = 0
            if bag_key not in bag_running_totals_packaged:
                bag_running_totals_packaged[bag_key] = 0
            
            # Update appropriate running total based on submission type
            if submission_type == 'machine':
                bag_running_totals_machine[bag_key] += individual_calc
            else:  # 'packaged' or 'bag'
                bag_running_totals_packaged[bag_key] += individual_calc
            
            # Calculate totals
            machine_running_total = bag_running_totals_machine[bag_key]
            packaged_running_total = bag_running_totals_packaged[bag_key]
            total_running_total = machine_running_total + packaged_running_total
            
            # Add running total fields
            sub_dict['individual_calc'] = individual_calc
            sub_dict['machine_running_total'] = machine_running_total
            sub_dict['packaged_running_total'] = packaged_running_total
            sub_dict['running_total'] = total_running_total
            
            # Compare running total to bag label count (exact match, no tolerance)
            # Use receive_bag_count from bags table (more reliable than submission field)
            bag_count = sub_dict.get('receive_bag_count', 0) or sub_dict.get('bag_label_count', 0) or 0
            
            # Determine status with exact match logic
            if bag_count == 0:
                sub_dict['count_status'] = 'no_bag'
            elif total_running_total == bag_count:
                sub_dict['count_status'] = 'match'
            elif total_running_total < bag_count:
                sub_dict['count_status'] = 'under'
            else:
                sub_dict['count_status'] = 'over'
            
            # Calculate tablet difference for display
            sub_dict['tablet_difference'] = total_running_total - bag_count if bag_count > 0 else 0
            sub_dict['has_discrepancy'] = 1 if sub_dict['count_status'] != 'match' and bag_count > 0 else 0
            
            submissions_processed.append(sub_dict)
        
        # Show only first 10 most recent submissions on dashboard (query already orders DESC)
        submissions = submissions_processed[:10]  # First 10, already newest first from DESC query
        
        # Get summary stats using closed field (boolean) and internal status (only count synced POs, not test data)
        stats = conn.execute('''
            SELECT 
                COUNT(CASE WHEN closed = FALSE AND zoho_po_id IS NOT NULL THEN 1 END) as open_pos,
                COUNT(CASE WHEN closed = TRUE AND zoho_po_id IS NOT NULL THEN 1 END) as closed_pos,
                COUNT(CASE WHEN internal_status = 'Draft' AND zoho_po_id IS NOT NULL THEN 1 END) as draft_pos,
                COALESCE(SUM(CASE WHEN closed = FALSE AND zoho_po_id IS NOT NULL THEN 
                    (ordered_quantity - current_good_count - current_damaged_count) END), 0) as total_remaining
            FROM purchase_orders
        ''').fetchone()
        
        # Find submissions that need review (ambiguous submissions)
        # These are submissions where flavor + box + bag match multiple receives
        # They have needs_review=TRUE and bag_id=NULL (not yet assigned)
        submissions_needing_review = conn.execute('''
            SELECT ws.*, 
                   tt.tablet_type_name,
                   (
                       CASE ws.submission_type
                           WHEN 'packaged' THEN (ws.displays_made * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0) + 
                                                ws.packs_remaining * COALESCE(pd.tablets_per_package, 0))
                           WHEN 'bag' THEN ws.loose_tablets
                           WHEN 'machine' THEN ws.loose_tablets
                           ELSE ws.loose_tablets + ws.damaged_tablets
                       END
                   ) as calculated_total
            FROM warehouse_submissions ws
            LEFT JOIN tablet_types tt ON ws.inventory_item_id = tt.inventory_item_id
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
            WHERE ws.needs_review = TRUE
            ORDER BY ws.created_at DESC
        ''').fetchall()
        
        # Convert to list of dicts
        review_submissions = [dict(row) for row in submissions_needing_review]
        
        return render_template('dashboard.html', active_pos=active_pos, closed_pos=closed_pos, submissions=submissions, stats=stats, tablet_types=tablet_types, submissions_needing_review=review_submissions)
    except Exception as e:
        print(f"Error in admin_dashboard: {e}")
        traceback.print_exc()
        flash('An error occurred while loading the dashboard. Please try again.', 'error')
        # Create default stats dict to match expected structure (SQLite Row-like object)
        default_stats = type('obj', (object,), {
            'open_pos': 0,
            'closed_pos': 0,
            'draft_pos': 0,
            'total_remaining': 0
        })()
        return render_template('dashboard.html', active_pos=[], closed_pos=[], submissions=[], stats=default_stats, tablet_types=[], submissions_needing_review=[])
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/submissions')
@role_required('dashboard')
def all_submissions():
    """Full submissions page showing all submissions"""
    conn = None
    try:
        conn = get_db()
        
        # Get filter parameters from query string
        filter_po_id = request.args.get('po_id', type=int)
        filter_item_id = request.args.get('item_id', type=str)
        filter_date_from = request.args.get('date_from', type=str)
        filter_date_to = request.args.get('date_to', type=str)
        filter_tablet_type_id = request.args.get('tablet_type_id', type=int)
        filter_submission_type = request.args.get('submission_type', type=str)
        
        # Build query with optional filters
        query = '''
            SELECT ws.*, po.po_number, po.closed as po_closed, po.id as po_id_for_filter,
                   pd.packages_per_display, pd.tablets_per_package,
                   tt.inventory_item_id, tt.id as tablet_type_id, tt.tablet_type_name,
                   COALESCE(ws.po_assignment_verified, 0) as po_verified,
                   ws.admin_notes,
                   COALESCE(ws.submission_type, 'packaged') as submission_type,
                   COALESCE(ws.submission_date, DATE(ws.created_at)) as filter_date,
                   b.bag_label_count as receive_bag_count,
                   (
                       (ws.displays_made * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0)) +
                       (ws.packs_remaining * COALESCE(pd.tablets_per_package, 0)) + 
                       ws.loose_tablets + ws.damaged_tablets
                   ) as calculated_total
            FROM warehouse_submissions ws
            LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
            LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            LEFT JOIN bags b ON ws.bag_id = b.id
            WHERE 1=1
        '''
        
        params = []
        
        # Apply PO filter if provided
        if filter_po_id:
            query += ' AND ws.assigned_po_id = ?'
            params.append(filter_po_id)
        
        # Apply item filter if provided
        if filter_item_id:
            query += ' AND tt.inventory_item_id = ?'
            params.append(filter_item_id)
        
        # Apply date range filters
        if filter_date_from:
            query += ' AND COALESCE(ws.submission_date, DATE(ws.created_at)) >= ?'
            params.append(filter_date_from)
        
        if filter_date_to:
            query += ' AND COALESCE(ws.submission_date, DATE(ws.created_at)) <= ?'
            params.append(filter_date_to)
        
        # Apply tablet type filter if provided
        if filter_tablet_type_id:
            query += ' AND tt.id = ?'
            params.append(filter_tablet_type_id)
        
        # Apply submission type filter if provided
        if filter_submission_type:
            query += ' AND COALESCE(ws.submission_type, \'packaged\') = ?'
            params.append(filter_submission_type)
        
        query += ' ORDER BY ws.created_at DESC'
        
        submissions_raw = conn.execute(query, params).fetchall()
        
        # Calculate running totals by bag using bag_id (with legacy fallback)
        # Track machine and packaged totals separately
        bag_running_totals_machine = {}  # Key: bag_id or (po_id, product_name, "box/bag")
        bag_running_totals_packaged = {}  # Key: bag_id or (po_id, product_name, "box/bag")
        submissions_processed = []
        
        for sub in submissions_raw:
            sub_dict = dict(sub)
            
            # Use bag_id as primary key, fallback to legacy key for old submissions
            bag_id = sub_dict.get('bag_id')
            if bag_id:
                bag_key = bag_id
            else:
                # Legacy fallback: use (po_id, product_name, "box/bag") tuple
                bag_identifier = f"{sub_dict.get('box_number', '')}/{sub_dict.get('bag_number', '')}"
                bag_key = (sub_dict.get('po_id_for_filter'), sub_dict.get('product_name'), bag_identifier)
            
            # Individual calculation for this submission
            individual_calc = sub_dict.get('calculated_total', 0) or 0
            submission_type = sub_dict.get('submission_type', 'packaged')
            
            # Initialize running totals for this bag if not exists
            if bag_key not in bag_running_totals_machine:
                bag_running_totals_machine[bag_key] = 0
            if bag_key not in bag_running_totals_packaged:
                bag_running_totals_packaged[bag_key] = 0
            
            # Update appropriate running total based on submission type
            if submission_type == 'machine':
                bag_running_totals_machine[bag_key] += individual_calc
            else:  # 'packaged' or 'bag'
                bag_running_totals_packaged[bag_key] += individual_calc
            
            # Calculate totals
            machine_running_total = bag_running_totals_machine[bag_key]
            packaged_running_total = bag_running_totals_packaged[bag_key]
            total_running_total = machine_running_total + packaged_running_total
            
            # Add running total fields
            sub_dict['individual_calc'] = individual_calc
            sub_dict['machine_running_total'] = machine_running_total
            sub_dict['packaged_running_total'] = packaged_running_total
            sub_dict['running_total'] = total_running_total
            
            # Compare running total to bag label count (exact match, no tolerance)
            bag_count = sub_dict.get('bag_label_count', 0) or 0
            
            # Determine status with exact match logic
            if bag_count == 0:
                sub_dict['count_status'] = 'no_bag'
            elif total_running_total == bag_count:
                sub_dict['count_status'] = 'match'
            elif total_running_total < bag_count:
                sub_dict['count_status'] = 'under'
            else:
                sub_dict['count_status'] = 'over'
            
            # Calculate tablet difference for display
            sub_dict['tablet_difference'] = total_running_total - bag_count if bag_count > 0 else 0
            sub_dict['has_discrepancy'] = 1 if sub_dict['count_status'] != 'match' and bag_count > 0 else 0
            
            submissions_processed.append(sub_dict)
        
        # Query already orders by DESC (newest first), so use as-is
        all_submissions = submissions_processed  # All submissions, newest first
        
        # Pagination
        page = request.args.get('page', 1, type=int)
        per_page = 15
        total_submissions = len(all_submissions)
        total_pages = (total_submissions + per_page - 1) // per_page  # Ceiling division
        
        # Calculate start and end indices
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        
        # Get submissions for current page
        submissions = all_submissions[start_idx:end_idx]
        
        # Verification workflow removed - using receive-based tracking
        
        # Pagination info
        pagination = {
            'page': page,
            'per_page': per_page,
            'total': total_submissions,
            'total_pages': total_pages,
            'has_prev': page > 1,
            'has_next': page < total_pages,
            'prev_page': page - 1 if page > 1 else None,
            'next_page': page + 1 if page < total_pages else None
        }
        
        # Get filter info for display
        filter_info = {}
        if filter_po_id:
            po_info = conn.execute('SELECT po_number FROM purchase_orders WHERE id = ?', (filter_po_id,)).fetchone()
            if po_info:
                filter_info['po_number'] = po_info['po_number']
                filter_info['po_id'] = filter_po_id
        
        if filter_item_id:
            item_info = conn.execute('SELECT line_item_name FROM po_lines WHERE inventory_item_id = ? LIMIT 1', (filter_item_id,)).fetchone()
            if item_info:
                filter_info['item_name'] = item_info['line_item_name']
                filter_info['item_id'] = filter_item_id
        
        if filter_date_from:
            filter_info['date_from'] = filter_date_from
        if filter_date_to:
            filter_info['date_to'] = filter_date_to
        if filter_tablet_type_id:
            tablet_type_info = conn.execute('SELECT tablet_type_name FROM tablet_types WHERE id = ?', (filter_tablet_type_id,)).fetchone()
            if tablet_type_info:
                filter_info['tablet_type_name'] = tablet_type_info['tablet_type_name']
                filter_info['tablet_type_id'] = filter_tablet_type_id
        
        if filter_submission_type:
            filter_info['submission_type'] = filter_submission_type
        
        # Get all tablet types for the filter dropdown
        tablet_types = conn.execute('SELECT id, tablet_type_name FROM tablet_types ORDER BY tablet_type_name').fetchall()
        
        return render_template('submissions.html', submissions=submissions, pagination=pagination, filter_info=filter_info, tablet_types=tablet_types, 
                             filter_date_from=filter_date_from, filter_date_to=filter_date_to, filter_tablet_type_id=filter_tablet_type_id, filter_submission_type=filter_submission_type)
    except Exception as e:
        print(f"Error in all_submissions: {e}")
        traceback.print_exc()
        flash('An error occurred while loading submissions. Please try again.', 'error')
        return render_template('submissions.html', submissions=[], pagination={'page': 1, 'per_page': 15, 'total': 0, 'total_pages': 0, 'has_prev': False, 'has_next': False}, filter_info={})
    finally:
        if conn:
            conn.close()

@app.route('/submissions/flagged')
@role_required('dashboard')
def flagged_submissions():
    """View submissions that need review (duplicates, unassigned legacy data)"""
    conn = None
    try:
        conn = get_db()
        
        # Get all submissions flagged for review
        query = '''
            SELECT ws.*, 
                   po.po_number, 
                   pd.packages_per_display, 
                   pd.tablets_per_package,
                   tt.tablet_type_name,
                   b.bag_label_count as receive_bag_count,
                   b.bag_number,
                   sb.box_number,
                   r.id as receiving_id,
                   r.received_date,
                   CASE 
                       WHEN ws.bag_id IS NULL AND ws.assigned_po_id IS NULL THEN 'Unassigned Legacy'
                       WHEN ws.bag_id IS NOT NULL THEN 'Duplicate Bag'
                       ELSE 'Other'
                   END as flag_reason,
                   (
                       CASE ws.submission_type
                           WHEN 'packaged' THEN (ws.displays_made * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0) + 
                                                ws.packs_remaining * COALESCE(pd.tablets_per_package, 0))
                           WHEN 'bag' THEN ws.loose_tablets
                           WHEN 'machine' THEN ws.loose_tablets
                           ELSE ws.loose_tablets
                       END
                   ) as calculated_total
            FROM warehouse_submissions ws
            LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
            LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            LEFT JOIN bags b ON ws.bag_id = b.id
            LEFT JOIN small_boxes sb ON b.small_box_id = sb.id
            LEFT JOIN receiving r ON sb.receiving_id = r.id
            WHERE ws.needs_review = 1
            ORDER BY ws.created_at DESC
        '''
        
        flagged = conn.execute(query).fetchall()
        flagged_list = [dict(row) for row in flagged]
        
        # Get counts by flag reason
        stats = {
            'total': len(flagged_list),
            'unassigned_legacy': sum(1 for f in flagged_list if f['flag_reason'] == 'Unassigned Legacy'),
            'duplicate_bags': sum(1 for f in flagged_list if f['flag_reason'] == 'Duplicate Bag'),
            'other': sum(1 for f in flagged_list if f['flag_reason'] == 'Other')
        }
        
        return render_template('flagged_submissions.html', flagged=flagged_list, stats=stats)
        
    except Exception as e:
        print(f"Error in flagged_submissions: {e}")
        traceback.print_exc()
        flash('An error occurred while loading flagged submissions.', 'error')
        return render_template('flagged_submissions.html', flagged=[], stats={'total': 0, 'unassigned_legacy': 0, 'duplicate_bags': 0, 'other': 0})
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/submissions/export')
@role_required('dashboard')
def export_submissions_csv():
    """Export submissions to CSV with all active filters applied"""
    conn = None
    try:
        conn = get_db()
        
        # Get filter parameters from query string (same as all_submissions)
        filter_po_id = request.args.get('po_id', type=int)
        filter_item_id = request.args.get('item_id', type=str)
        filter_date_from = request.args.get('date_from', type=str)
        filter_date_to = request.args.get('date_to', type=str)
        filter_tablet_type_id = request.args.get('tablet_type_id', type=int)
        
        # Build query with optional filters (same logic as all_submissions)
        query = '''
            SELECT ws.*, po.po_number, po.closed as po_closed,
                   pd.packages_per_display, pd.tablets_per_package,
                   tt.inventory_item_id, tt.tablet_type_name,
                   COALESCE(ws.po_assignment_verified, 0) as po_verified,
                   ws.admin_notes,
                   COALESCE(ws.submission_date, DATE(ws.created_at)) as filter_date,
                   (
                       (ws.displays_made * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0)) +
                       (ws.packs_remaining * COALESCE(pd.tablets_per_package, 0)) + 
                       ws.loose_tablets + ws.damaged_tablets
                   ) as calculated_total
            FROM warehouse_submissions ws
            LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
            LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            WHERE 1=1
        '''
        
        params = []
        
        # Apply PO filter if provided
        if filter_po_id:
            query += ' AND ws.assigned_po_id = ?'
            params.append(filter_po_id)
        
        # Apply item filter if provided
        if filter_item_id:
            query += ' AND tt.inventory_item_id = ?'
            params.append(filter_item_id)
        
        # Apply date range filters
        if filter_date_from:
            query += ' AND COALESCE(ws.submission_date, DATE(ws.created_at)) >= ?'
            params.append(filter_date_from)
        
        if filter_date_to:
            query += ' AND COALESCE(ws.submission_date, DATE(ws.created_at)) <= ?'
            params.append(filter_date_to)
        
        # Apply tablet type filter if provided
        if filter_tablet_type_id:
            query += ' AND tt.id = ?'
            params.append(filter_tablet_type_id)
        
        query += ' ORDER BY ws.created_at ASC'
        
        submissions_raw = conn.execute(query, params).fetchall()
        
        # Calculate running totals by bag PER PO (same logic as all_submissions)
        bag_running_totals = {}
        submissions_processed = []
        
        for sub in submissions_raw:
            sub_dict = dict(sub)
            bag_identifier = f"{sub_dict.get('box_number', '')}/{sub_dict.get('bag_number', '')}"
            bag_key = (sub_dict.get('assigned_po_id'), sub_dict.get('product_name'), bag_identifier)
            
            individual_calc = sub_dict.get('calculated_total', 0) or 0
            
            if bag_key not in bag_running_totals:
                bag_running_totals[bag_key] = 0
            bag_running_totals[bag_key] += individual_calc
            
            sub_dict['individual_calc'] = individual_calc
            sub_dict['running_total'] = bag_running_totals[bag_key]
            
            bag_count = sub_dict.get('bag_label_count', 0) or 0
            running_total = bag_running_totals[bag_key]
            
            if bag_count == 0:
                sub_dict['count_status'] = 'No Bag Label'
            elif abs(running_total - bag_count) <= 5:
                sub_dict['count_status'] = 'Match'
            elif running_total < bag_count:
                sub_dict['count_status'] = 'Under'
            else:
                sub_dict['count_status'] = 'Over'
            
            submissions_processed.append(sub_dict)
        
        # Create CSV in memory
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header row
        writer.writerow([
            'Submission Date',
            'Created At',
            'Employee Name',
            'Product Name',
            'Tablet Type',
            'PO Number',
            'Box Number',
            'Bag Number',
            'Displays Made',
            'Packs Remaining',
            'Loose Tablets',
            'Damaged Tablets',
            'Total Tablets (Individual)',
            'Running Total (Bag)',
            'Bag Label Count',
            'Count Status',
            'PO Assignment Verified',
            'Admin Notes'
        ])
        
        # Write data rows (oldest first for CSV)
        for sub in submissions_processed:
            submission_date = sub.get('submission_date') or sub.get('filter_date') or ''
            created_at = sub.get('created_at', '')
            if created_at:
                try:
                    # Format datetime for CSV
                    if isinstance(created_at, str):
                        created_at = created_at[:19]  # Truncate to seconds
                except:
                    pass
            
            writer.writerow([
                submission_date,
                created_at,
                sub.get('employee_name', ''),
                sub.get('product_name', ''),
                sub.get('tablet_type_name', ''),
                sub.get('po_number', ''),
                sub.get('box_number', ''),
                sub.get('bag_number', ''),
                sub.get('displays_made', 0),
                sub.get('packs_remaining', 0),
                sub.get('loose_tablets', 0),
                sub.get('damaged_tablets', 0),
                sub.get('individual_calc', 0),
                sub.get('running_total', 0),
                sub.get('bag_label_count', 0),
                sub.get('count_status', ''),
                'Yes' if sub.get('po_verified', 0) else 'No',
                sub.get('admin_notes', '')
            ])
        
        # Generate filename with date range if applicable
        filename_parts = ['submissions']
        if filter_date_from:
            filename_parts.append(f'from_{filter_date_from}')
        if filter_date_to:
            filename_parts.append(f'to_{filter_date_to}')
        if filter_tablet_type_id:
            filename_parts.append(f'type_{submissions_processed[0].get("tablet_type_name", "unknown") if submissions_processed else "unknown"}')
        if filter_po_id:
            po_info = conn.execute('SELECT po_number FROM purchase_orders WHERE id = ?', (filter_po_id,)).fetchone()
            if po_info:
                filename_parts.append(f'po_{po_info["po_number"]}')
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{'_'.join(filename_parts)}_{timestamp}.csv"
        
        # Create response
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv; charset=utf-8'
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response
        
    except Exception as e:
        print(f"Error exporting submissions CSV: {e}")
        traceback.print_exc()
        flash('An error occurred while exporting submissions. Please try again.', 'error')
        return redirect(url_for('all_submissions'))
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/purchase_orders')
@role_required('dashboard')
def all_purchase_orders():
    """Full purchase orders page showing all POs with filtering"""
    conn = None
    try:
        conn = get_db()
        
        # Get ALL POs with line counts and submission counts
        all_pos = conn.execute('''
            SELECT po.*, 
                   COUNT(DISTINCT pl.id) as line_count,
                   COALESCE(SUM(pl.quantity_ordered), 0) as total_ordered,
                   COALESCE(po.internal_status, 'Active') as status_display,
                   (SELECT COUNT(DISTINCT ws.id) 
                    FROM warehouse_submissions ws 
                    WHERE ws.assigned_po_id = po.id) as submission_count
            FROM purchase_orders po
            LEFT JOIN po_lines pl ON po.id = pl.po_id
            GROUP BY po.id
            ORDER BY po.po_number DESC
        ''').fetchall()
        
        # Organize POs: group overs POs under their parents
        organized_pos = []
        overs_pos = {}  # Key: parent_po_number, Value: list of overs POs
        
        # First pass: separate overs POs
        for po in all_pos:
            po_dict = dict(po)
            if po_dict.get('parent_po_number'):
                # This is an overs PO
                parent_num = po_dict['parent_po_number']
                if parent_num not in overs_pos:
                    overs_pos[parent_num] = []
                overs_pos[parent_num].append(po_dict)
            else:
                # Regular PO - will be added in second pass
                pass
        
        # Second pass: add parent POs and their overs
        for po in all_pos:
            po_dict = dict(po)
            if not po_dict.get('parent_po_number'):
                # Add parent PO
                po_dict['is_overs'] = False
                organized_pos.append(po_dict)
                
                # Add any overs POs for this parent
                if po_dict['po_number'] in overs_pos:
                    for overs_po in overs_pos[po_dict['po_number']]:
                        overs_po['is_overs'] = True
                        organized_pos.append(overs_po)
        
        return render_template('purchase_orders.html', purchase_orders=organized_pos)
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ ALL PURCHASE ORDERS ERROR: {str(e)}")
        print(error_trace)
        flash(f'Error loading purchase orders: {str(e)}', 'error')
        return render_template('purchase_orders.html', purchase_orders=[])
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/shipments')
def public_shipments():
    """Read-only shipment status page for staff (no login required)."""
    conn = None
    try:
        conn = get_db()
        rows = conn.execute('''
            SELECT po.po_number, s.id as shipment_id, s.tracking_number, s.carrier, s.tracking_status,
                   s.estimated_delivery, s.last_checkpoint, s.actual_delivery, s.updated_at
            FROM shipments s
            JOIN purchase_orders po ON po.id = s.po_id
            ORDER BY s.updated_at DESC
            LIMIT 200
        ''').fetchall()
        return render_template('shipments_public.html', shipments=rows)
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ Error loading public shipments: {str(e)}")
        print(f"Traceback: {error_trace}")
        flash('Failed to load shipments. Please try again later.', 'error')
        return render_template('shipments_public.html', shipments=[])
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/sync_zoho_pos', methods=['GET', 'POST'])
@role_required('dashboard')
def sync_zoho_pos():
    """Sync Purchase Orders from Zoho Inventory"""
    conn = None
    try:
        print("🔄 Starting Zoho PO sync...")
        conn = get_db()
        print("✅ Database connection established")
        
        print("📡 Calling Zoho API sync function...")
        success, message = zoho_api.sync_tablet_pos_to_db(conn)
        print(f"✅ Sync completed. Success: {success}, Message: {message}")
        
        if success:
            return jsonify({'message': message, 'success': True})
        else:
            return jsonify({'error': message, 'success': False}), 400
            
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ Sync Zoho POs error: {str(e)}")
        print(f"Traceback: {error_trace}")
        return jsonify({'error': f'Sync failed: {str(e)}', 'success': False}), 500
    finally:
        if conn:
            try:
                conn.close()
                print("✅ Database connection closed")
            except:
                pass

@app.route('/api/create_overs_po/<int:po_id>', methods=['POST'])
@role_required('dashboard')
def create_overs_po(po_id):
    """Create an overs PO in Zoho for a parent PO"""
    conn = None
    try:
        conn = get_db()
        
        # Get parent PO details
        parent_po = conn.execute('''
            SELECT po_number, tablet_type, ordered_quantity, current_good_count, 
                   current_damaged_count, remaining_quantity, zoho_po_id
            FROM purchase_orders
            WHERE id = ?
        ''', (po_id,)).fetchone()
        
        if not parent_po:
            return jsonify({'error': 'Parent PO not found'}), 404
        
        # Calculate overs (negative remaining_quantity means overs)
        overs_quantity = abs(min(0, parent_po['remaining_quantity']))
        
        if overs_quantity == 0:
            return jsonify({'error': 'No overs found for this PO'}), 400
        
        # Get line items with overs (negative remaining means overs)
        lines_with_overs = conn.execute('''
            SELECT pl.*, 
                   (pl.quantity_ordered - pl.good_count - pl.damaged_count) as line_remaining
            FROM po_lines pl
            WHERE pl.po_id = ? 
            AND (pl.quantity_ordered - pl.good_count - pl.damaged_count) < 0
        ''', (po_id,)).fetchall()
        
        if not lines_with_overs:
            return jsonify({'error': 'No line items with overs found'}), 400
        
        # Generate overs PO number
        overs_po_number = f"{parent_po['po_number']}-OVERS"
        
        # Get parent PO details from Zoho to use as template
        parent_zoho_po = None
        if parent_po['zoho_po_id']:
            parent_zoho_po = zoho_api.get_purchase_order_details(parent_po['zoho_po_id'])
        
        # Build line items for overs PO
        line_items = []
        for line in lines_with_overs:
            line_overs = abs(line['line_remaining'])
            line_items.append({
                'item_id': line['inventory_item_id'],
                'name': line['line_item_name'],
                'quantity': line_overs,
                'rate': 0  # Free/overs items typically have $0 rate
            })
        
        # Build PO data for Zoho
        po_data = {
            'purchaseorder_number': overs_po_number,
            'date': datetime.now().date().isoformat(),
            'line_items': line_items,
            'cf_tablets': True,  # Mark as tablet PO
            'notes': f'Overs PO for {parent_po["po_number"]} - {overs_quantity:,} tablets',
            'status': 'draft'  # Create as draft so it can be reviewed
        }
        
        # Copy vendor and other details from parent PO if available
        if parent_zoho_po and 'purchaseorder' in parent_zoho_po:
            parent_data = parent_zoho_po['purchaseorder']
            if 'vendor_id' in parent_data:
                po_data['vendor_id'] = parent_data['vendor_id']
            if 'vendor_name' in parent_data:
                po_data['vendor_name'] = parent_data['vendor_name']
            if 'currency_code' in parent_data:
                po_data['currency_code'] = parent_data['currency_code']
        
        # Create PO in Zoho
        result = zoho_api.create_purchase_order(po_data)
        
        if result and 'purchaseorder' in result:
            created_po = result['purchaseorder']
            return jsonify({
                'success': True,
                'message': f'Overs PO "{overs_po_number}" created successfully in Zoho!',
                'overs_po_number': overs_po_number,
                'zoho_po_id': created_po.get('purchaseorder_id'),
                'total_overs': overs_quantity,
                'instructions': 'The overs PO has been created in Zoho. You can now sync POs to import it into the app.'
            })
        else:
            error_msg = result.get('message', 'Unknown error') if result else 'No response from Zoho API'
            return jsonify({
                'success': False,
                'error': f'Failed to create PO in Zoho: {error_msg}'
            }), 500
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/create_overs_po_info/<int:po_id>')
@role_required('dashboard')
def get_overs_po_info(po_id):
    """Get information needed to create an overs PO for a parent PO (for preview)"""
    conn = None
    try:
        conn = get_db()
        
        # Get parent PO details
        parent_po = conn.execute('''
            SELECT po_number, tablet_type, ordered_quantity, current_good_count, 
                   current_damaged_count, remaining_quantity
            FROM purchase_orders
            WHERE id = ?
        ''', (po_id,)).fetchone()
        
        if not parent_po:
            return jsonify({'error': 'Parent PO not found'}), 404
        
        # Calculate overs (negative remaining_quantity means overs)
        overs_quantity = abs(min(0, parent_po['remaining_quantity']))
        
        # Get line items with overs (negative remaining means overs)
        lines_with_overs = conn.execute('''
            SELECT pl.*, 
                   (pl.quantity_ordered - pl.good_count - pl.damaged_count) as line_remaining
            FROM po_lines pl
            WHERE pl.po_id = ? 
            AND (pl.quantity_ordered - pl.good_count - pl.damaged_count) < 0
        ''', (po_id,)).fetchall()
        
        # Generate overs PO number
        overs_po_number = f"{parent_po['po_number']}-OVERS"
        
        # Prepare line items for overs PO
        overs_line_items = []
        total_overs = 0
        for line in lines_with_overs:
            line_overs = abs(line['line_remaining'])
            total_overs += line_overs
            overs_line_items.append({
                'inventory_item_id': line['inventory_item_id'],
                'line_item_name': line['line_item_name'],
                'overs_quantity': line_overs,
                'original_ordered': line['quantity_ordered']
            })
        
        return jsonify({
            'success': True,
            'parent_po_number': parent_po['po_number'],
            'overs_po_number': overs_po_number,
            'tablet_type': parent_po['tablet_type'],
            'total_overs': overs_quantity,
            'line_items': overs_line_items,
            'instructions': f'Click "Create in Zoho" to automatically create this overs PO in Zoho, or copy details to create manually.'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/po_lines/<int:po_id>')
def get_po_lines(po_id):
    """Get line items for a specific PO"""
    conn = None
    try:
        conn = get_db()
        lines = conn.execute('''
            SELECT * FROM po_lines WHERE po_id = ? ORDER BY line_item_name
        ''', (po_id,)).fetchall()
        
        # Verification workflow removed - all submissions now link to receives
        
        # Get current PO details including status and parent
        current_po = conn.execute('''
            SELECT po_number, closed, internal_status, zoho_status, parent_po_number
            FROM purchase_orders WHERE id = ?
        ''', (po_id,)).fetchone()
        current_po_number = current_po['po_number'] if current_po else None
        po_status = None
        if current_po:
            # Determine status: cancelled takes priority, then closed, then internal_status, then zoho_status
            if current_po['internal_status'] == 'Cancelled':
                po_status = 'Cancelled'
            elif current_po['closed']:
                po_status = 'Closed'
            elif current_po['internal_status']:
                po_status = current_po['internal_status']
            elif current_po['zoho_status']:
                po_status = current_po['zoho_status']
            else:
                po_status = 'Open'
        
        # Check if there's an overs PO linked to this parent PO
        overs_po = None
        if current_po_number:
            overs_po_record = conn.execute('''
                SELECT id, po_number 
                FROM purchase_orders 
                WHERE parent_po_number = ?
            ''', (current_po_number,)).fetchone()
            if overs_po_record:
                overs_po = {
                    'id': overs_po_record['id'],
                    'po_number': overs_po_record['po_number']
                }
        
        # Check if this is an overs PO (has a parent)
        parent_po = None
        if current_po and current_po['parent_po_number']:
            parent_po_record = conn.execute('''
                SELECT id, po_number 
                FROM purchase_orders 
                WHERE po_number = ?
            ''', (current_po['parent_po_number'],)).fetchone()
            if parent_po_record:
                parent_po = {
                    'id': parent_po_record['id'],
                    'po_number': parent_po_record['po_number']
                }
        
        # Calculate round numbers and received counts for each line item
        lines_with_rounds = []
        for line in lines:
            line_dict = dict(line)
            round_number = None
            
            if line_dict.get('inventory_item_id') and current_po_number:
                # Find all POs containing this inventory_item_id, ordered by PO number (oldest first)
                pos_with_item = conn.execute('''
                    SELECT DISTINCT po.po_number, po.id
                    FROM purchase_orders po
                    JOIN po_lines pl ON po.id = pl.po_id
                    WHERE pl.inventory_item_id = ?
                    ORDER BY po.po_number ASC
                ''', (line_dict['inventory_item_id'],)).fetchall()
                
                # Find the position of current PO in this list (1-indexed = round number)
                for idx, po_row in enumerate(pos_with_item, start=1):
                    if po_row['po_number'] == current_po_number:
                        round_number = idx
                        break
            
            line_dict['round_number'] = round_number
            
            # Get received count from bags (bag_label_count sum for this PO and inventory_item_id)
            received_count = conn.execute('''
                SELECT COALESCE(SUM(b.bag_label_count), 0) as total_received
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN receiving r ON sb.receiving_id = r.id
                JOIN tablet_types tt ON b.tablet_type_id = tt.id
                WHERE r.po_id = ? AND tt.inventory_item_id = ?
            ''', (po_id, line_dict.get('inventory_item_id'))).fetchone()
            
            line_dict['received_count'] = received_count['total_received'] if received_count else 0
            
            # Get machine count (from machine_counts table via warehouse_submissions)
            # Calculate total tablets: (displays_made * packages_per_display * tablets_per_package) + (packs_remaining * tablets_per_package) + loose_tablets
            machine_count = conn.execute('''
                SELECT COALESCE(SUM(
                    (COALESCE(ws.displays_made, 0) * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0)) +
                    (COALESCE(ws.packs_remaining, 0) * COALESCE(pd.tablets_per_package, 0)) +
                    COALESCE(ws.loose_tablets, 0)
                ), 0) as total_machine
                FROM warehouse_submissions ws
                LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                WHERE ws.assigned_po_id = ? 
                AND ws.inventory_item_id = ? 
                AND ws.submission_type = 'machine'
            ''', (po_id, line_dict.get('inventory_item_id'))).fetchone()
            
            line_dict['machine_count'] = machine_count['total_machine'] if machine_count else 0
            
            # Get packaged count (from packaged and bag count submissions)
            # Calculate total tablets: (displays_made * packages_per_display * tablets_per_package) + (packs_remaining * tablets_per_package) + loose_tablets
            packaged_count = conn.execute('''
                SELECT COALESCE(SUM(
                    (COALESCE(ws.displays_made, 0) * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0)) +
                    (COALESCE(ws.packs_remaining, 0) * COALESCE(pd.tablets_per_package, 0)) +
                    COALESCE(ws.loose_tablets, 0)
                ), 0) as total_packaged
                FROM warehouse_submissions ws
                LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                WHERE ws.assigned_po_id = ? 
                AND ws.inventory_item_id = ? 
                AND ws.submission_type IN ('packaged', 'bag')
            ''', (po_id, line_dict.get('inventory_item_id'))).fetchone()
            
            line_dict['packaged_count'] = packaged_count['total_packaged'] if packaged_count else 0
            
            lines_with_rounds.append(line_dict)
        
        result = {
            'lines': lines_with_rounds,
            'po_status': po_status,
            'overs_po': overs_po,
            'parent_po': parent_po
        }
        
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': f'Failed to get PO lines: {str(e)}'}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/admin/products')
@admin_required
def product_mapping():
    """Show product → tablet mapping and calculation examples"""
    conn = None
    try:
        conn = get_db()
        
        # Get all products with their tablet type and calculation details
        products = conn.execute('''
            SELECT pd.*, tt.tablet_type_name, tt.inventory_item_id, tt.category
            FROM product_details pd
            JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            ORDER BY tt.category, tt.tablet_type_name, pd.product_name
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
                print(f"Warning: Could not add category column: {e}")
        
        # Get tablet types for dropdown
        if has_category_column:
            tablet_types = conn.execute('SELECT * FROM tablet_types ORDER BY tablet_type_name').fetchall()
            # Get unique categories (including those with tablet types assigned)
            categories = conn.execute('SELECT DISTINCT category FROM tablet_types WHERE category IS NOT NULL AND category != "" ORDER BY category').fetchall()
            category_list = [cat['category'] for cat in categories] if categories else []
        else:
            # Fallback: get tablet types without category column
            tablet_types_raw = conn.execute('SELECT id, tablet_type_name, inventory_item_id FROM tablet_types ORDER BY tablet_type_name').fetchall()
            # Convert to dict format with None category
            tablet_types = [dict(row) for row in tablet_types_raw]
            for tt in tablet_types:
                tt['category'] = None
            category_list = []
        
        # Auto-sync categories from tablet_types to categories table
        auto_sync_categories(conn)
        
        # Get all active categories from database (no more hardcoded lists!)
        categories_from_db = conn.execute('''
            SELECT category_name 
            FROM categories 
            WHERE is_active = TRUE 
            ORDER BY display_order, category_name
        ''').fetchall()
        all_categories = [cat['category_name'] for cat in categories_from_db]
        
        return render_template('product_mapping.html', products=products, tablet_types=tablet_types, categories=all_categories)
    except Exception as e:
        flash(f'Error loading product mapping: {str(e)}', 'error')
        return render_template('product_mapping.html', products=[], tablet_types=[])
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/admin/tablet_types')
@admin_required
def tablet_types_config():
    """Configuration page for tablet types and their inventory item IDs"""
    conn = None
    try:
        conn = get_db()
        
        # Get all tablet types with their current inventory item IDs
        tablet_types = conn.execute('''
            SELECT * FROM tablet_types 
            ORDER BY tablet_type_name
        ''').fetchall()
        
        return render_template('tablet_types_config.html', tablet_types=tablet_types)
    except Exception as e:
        flash(f'Error loading tablet types: {str(e)}', 'error')
        return render_template('tablet_types_config.html', tablet_types=[])
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/shipping')
@role_required('shipping')
def shipping_unified():
    """Shipments Received page - record shipments that arrive"""
    conn = None
    try:
        conn = get_db()
        
        # Auto-sync categories from tablet_types to categories table
        auto_sync_categories(conn)
        
        # Get all tablet types for the form dropdown (with category)
        tablet_types_raw = conn.execute('''
            SELECT id, tablet_type_name, category 
            FROM tablet_types 
            ORDER BY category, tablet_type_name
        ''').fetchall()
        # Convert Row objects to dicts for JSON serialization
        tablet_types = [dict(tt) for tt in tablet_types_raw]
        
        # Get all active categories from database
        categories = conn.execute('''
            SELECT category_name 
            FROM categories 
            WHERE is_active = TRUE 
            ORDER BY display_order, category_name
        ''').fetchall()
        all_categories = [cat['category_name'] for cat in categories]
        
        # Get all OPEN POs for managers/admin to assign (closed POs can't receive new shipments)
        purchase_orders = []
        if session.get('employee_role') in ['manager', 'admin'] or session.get('admin_authenticated'):
            purchase_orders = conn.execute('''
                SELECT id, po_number, closed, internal_status, zoho_status
                FROM purchase_orders
                WHERE closed = FALSE
                AND COALESCE(internal_status, '') != 'Cancelled'
                ORDER BY po_number DESC
            ''').fetchall()
        
        # Get all receiving records with their boxes and bags
        receiving_records = conn.execute('''
            SELECT r.*, 
                   COUNT(DISTINCT sb.id) as box_count,
                   COUNT(DISTINCT b.id) as total_bags,
                   po.po_number
            FROM receiving r
            LEFT JOIN small_boxes sb ON r.id = sb.receiving_id
            LEFT JOIN bags b ON sb.id = b.small_box_id
            LEFT JOIN purchase_orders po ON r.po_id = po.id
            GROUP BY r.id
            ORDER BY r.received_date DESC
        ''').fetchall()
        
        # Calculate shipment numbers for each PO (numbered sequentially by received_date)
        # Group shipments by PO and assign numbers
        po_shipment_counts = {}
        for rec in receiving_records:
            po_id = rec['po_id']
            if po_id:
                if po_id not in po_shipment_counts:
                    # Get all shipments for this PO ordered by received_date
                    po_shipments = conn.execute('''
                        SELECT id, received_date
                        FROM receiving
                        WHERE po_id = ?
                        ORDER BY received_date ASC, id ASC
                    ''', (po_id,)).fetchall()
                    po_shipment_counts[po_id] = {
                        shipment['id']: idx + 1 
                        for idx, shipment in enumerate(po_shipments)
                    }
        
        # For each receiving record, get its boxes and bags
        shipments = []
        for rec in receiving_records:
            # Add shipment number if PO is assigned
            rec_dict = dict(rec)
            if rec['po_id'] and rec['po_id'] in po_shipment_counts:
                rec_dict['shipment_number'] = po_shipment_counts[rec['po_id']].get(rec['id'], 1)
            else:
                rec_dict['shipment_number'] = None
            boxes = conn.execute('''
                SELECT sb.*, COUNT(b.id) as bag_count
                FROM small_boxes sb
                LEFT JOIN bags b ON sb.id = b.small_box_id
                WHERE sb.receiving_id = ?
                GROUP BY sb.id
                ORDER BY sb.box_number
            ''', (rec['id'],)).fetchall()
            
            # Get bags for each box with tablet type info
            boxes_with_bags = []
            for box in boxes:
                bags = conn.execute('''
                    SELECT b.*, tt.tablet_type_name
                    FROM bags b
                    LEFT JOIN tablet_types tt ON b.tablet_type_id = tt.id
                    WHERE b.small_box_id = ?
                    ORDER BY b.bag_number
                ''', (box['id'],)).fetchall()
                boxes_with_bags.append({
                    'box': dict(box),
                    'bags': [dict(bag) for bag in bags]
                })
            
            shipments.append({
                'receiving': rec_dict,
                'boxes': boxes_with_bags
            })
        
        return render_template('shipping_unified.html', 
                             tablet_types=tablet_types,
                             categories=all_categories,
                             purchase_orders=purchase_orders,
                             shipments=shipments,
                             user_role=session.get('employee_role'))
                             
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        app.logger.error(f"Error in shipping_unified: {str(e)}\n{error_details}")
        return render_template('error.html', 
                             error_message=f"Error loading shipping page: {str(e)}\n\nFull traceback:\n{error_details}"), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/shipments/<int:shipment_id>/refresh', methods=['POST'])
def refresh_shipment(shipment_id: int):
    """Manually refresh a single shipment's tracking status."""
    conn = None
    try:
        conn = get_db()
        result = refresh_shipment_row(conn, shipment_id)
        if result.get('success'):
            return jsonify(result)
        return jsonify(result), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

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
    conn = None
    try:
        conn = get_db()
        conn.execute('DELETE FROM shipments WHERE id = ?', (shipment_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        if conn:
            try:
                conn.close()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/save_shipment', methods=['POST'])
def save_shipment():
    """Save shipment information (supports multiple shipments per PO)"""
    conn = None
    try:
        data = request.get_json()
        
        # Validate required fields
        if not data.get('po_id'):
            return jsonify({'success': False, 'error': 'po_id is required'}), 400
        
        # Validate po_id is numeric
        try:
            po_id = int(data['po_id'])
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid po_id'}), 400
        
        conn = get_db()
        
        # For multiple shipments per PO, always create new unless we're editing a specific shipment
        shipment_id = data.get('shipment_id')
        
        if shipment_id:
            # Validate shipment_id is numeric
            try:
                shipment_id = int(shipment_id)
            except (ValueError, TypeError):
                conn.close()
                return jsonify({'success': False, 'error': 'Invalid shipment_id'}), 400
                
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
            ''', (po_id, data.get('tracking_number'), data.get('carrier'), 
                  data.get('shipped_date'), data.get('estimated_delivery'), 
                  data.get('actual_delivery'), data.get('notes')))
            # set carrier_code based on carrier
            conn.execute('UPDATE shipments SET carrier_code = LOWER(?) WHERE rowid = last_insert_rowid()', (data.get('carrier'),))
        
        # Auto-progress PO to "Shipped" status when tracking info is added
        if data.get('tracking_number'):
            current_status = conn.execute(
                'SELECT internal_status FROM purchase_orders WHERE id = ?',
                (po_id,)
            ).fetchone()
            
            if current_status and current_status['internal_status'] in ['Draft', 'Issued']:
                conn.execute('''
                    UPDATE purchase_orders 
                    SET internal_status = 'Shipped', updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (po_id,))
                print(f"Auto-progressed PO {po_id} to Shipped (tracking added)")
        
        conn.commit()

        # Trigger immediate UPS refresh when applicable
        if data.get('tracking_number') and (data.get('carrier', '').lower() in ('ups','fedex','fed ex')):
            sh = conn.execute('''
                SELECT id FROM shipments WHERE po_id = ? AND tracking_number = ?
                ORDER BY updated_at DESC LIMIT 1
            ''', (po_id, data.get('tracking_number'))).fetchone()
            if sh:
                try:
                    result = refresh_shipment_row(conn, sh['id'])
                    print('UPS refresh result:', result)
                except Exception as exc:
                    print('UPS refresh error:', exc)

        conn.close()
        return jsonify({'success': True, 'message': 'Shipment saved; tracking refreshed if supported'})
        
    except Exception as e:
        if conn:
            try:
                conn.close()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/update_tablet_type_inventory', methods=['POST'])
def update_tablet_type_inventory():
    """Update a tablet type's inventory item ID"""
    conn = None
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
                conn.close()
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
        if conn:
            try:
                conn.close()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/settings/cards_per_turn', methods=['GET', 'POST'])
@admin_required
def manage_cards_per_turn():
    """Get or update cards per turn setting"""
    conn = None
    try:
        ensure_app_settings_table()  # Ensure table exists
        conn = get_db()
        
        if request.method == 'GET':
            setting = conn.execute(
                'SELECT setting_value, description FROM app_settings WHERE setting_key = ?',
                ('cards_per_turn',)
            ).fetchone()
            if setting:
                return jsonify({
                    'success': True,
                    'value': int(setting['setting_value']),
                    'description': setting['description']
                })
            else:
                return jsonify({'success': False, 'error': 'Setting not found'}), 404
        
        elif request.method == 'POST':
            data = request.get_json()
            if not data:
                return jsonify({'success': False, 'error': 'No data provided'}), 400
            
            cards_per_turn = data.get('cards_per_turn')
            
            if cards_per_turn is None:
                return jsonify({'success': False, 'error': 'cards_per_turn is required'}), 400
            
            try:
                cards_per_turn = int(cards_per_turn)
                if cards_per_turn < 1:
                    return jsonify({'success': False, 'error': 'cards_per_turn must be at least 1'}), 400
            except (ValueError, TypeError):
                return jsonify({'success': False, 'error': 'Invalid cards_per_turn value'}), 400
            
            # Update or insert setting
            existing = conn.execute(
                'SELECT id FROM app_settings WHERE setting_key = ?',
                ('cards_per_turn',)
            ).fetchone()
            
            if existing:
                conn.execute('''
                    UPDATE app_settings 
                    SET setting_value = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE setting_key = ?
                ''', (str(cards_per_turn), 'cards_per_turn'))
            else:
                conn.execute('''
                    INSERT INTO app_settings (setting_key, setting_value, description)
                    VALUES (?, ?, ?)
                ''', ('cards_per_turn', str(cards_per_turn), 'Number of cards produced in one turn of the machine'))
            
            conn.commit()
            return jsonify({
                'success': True,
                'message': f'Cards per turn updated to {cards_per_turn}'
            })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/machines', methods=['GET'])
@employee_required  # Changed from @admin_required - employees need to see machines to submit counts
def get_machines():
    """Get all machines"""
    conn = None
    try:
        conn = get_db()
        machines = conn.execute('''
            SELECT * FROM machines 
            WHERE is_active = TRUE
            ORDER BY machine_name
        ''').fetchall()
        
        machines_list = [dict(m) for m in machines]
        app.logger.info(f"🔧 GET /api/machines - Found {len(machines_list)} active machines")
        for m in machines_list:
            app.logger.info(f"   Machine: {m.get('machine_name')} (ID: {m.get('id')}, cards_per_turn: {m.get('cards_per_turn')})")
        return jsonify({'success': True, 'machines': machines_list})
    except Exception as e:
        app.logger.error(f"❌ GET /api/machines error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/machines', methods=['POST'])
@admin_required
def create_machine():
    """Create a new machine"""
    conn = None
    try:
        data = request.get_json()
        machine_name = data.get('machine_name', '').strip()
        cards_per_turn = data.get('cards_per_turn')
        
        if not machine_name:
            return jsonify({'success': False, 'error': 'Machine name is required'}), 400
        
        try:
            cards_per_turn = int(cards_per_turn)
            if cards_per_turn < 1:
                return jsonify({'success': False, 'error': 'Cards per turn must be at least 1'}), 400
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid cards per turn value'}), 400
        
        conn = get_db()
        
        # Check if machine name already exists
        existing = conn.execute('SELECT id FROM machines WHERE machine_name = ?', (machine_name,)).fetchone()
        if existing:
            return jsonify({'success': False, 'error': 'Machine name already exists'}), 400
        
        # Create machine
        conn.execute('''
            INSERT INTO machines (machine_name, cards_per_turn, is_active)
            VALUES (?, ?, TRUE)
        ''', (machine_name, cards_per_turn))
        
        conn.commit()
        return jsonify({'success': True, 'message': f'Machine "{machine_name}" created successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/machines/<int:machine_id>', methods=['PUT'])
@admin_required
def update_machine(machine_id):
    """Update a machine's configuration"""
    conn = None
    try:
        data = request.get_json()
        machine_name = data.get('machine_name', '').strip()
        cards_per_turn = data.get('cards_per_turn')
        
        if not machine_name:
            return jsonify({'success': False, 'error': 'Machine name is required'}), 400
        
        try:
            cards_per_turn = int(cards_per_turn)
            if cards_per_turn < 1:
                return jsonify({'success': False, 'error': 'Cards per turn must be at least 1'}), 400
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid cards per turn value'}), 400
        
        conn = get_db()
        
        # Check if machine exists
        machine = conn.execute('SELECT id FROM machines WHERE id = ?', (machine_id,)).fetchone()
        if not machine:
            return jsonify({'success': False, 'error': 'Machine not found'}), 404
        
        # Check if new name conflicts with another machine
        existing = conn.execute('SELECT id FROM machines WHERE machine_name = ? AND id != ?', (machine_name, machine_id)).fetchone()
        if existing:
            return jsonify({'success': False, 'error': 'Machine name already exists'}), 400
        
        # Update machine
        conn.execute('''
            UPDATE machines 
            SET machine_name = ?, cards_per_turn = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (machine_name, cards_per_turn, machine_id))
        
        conn.commit()
        return jsonify({'success': True, 'message': f'Machine "{machine_name}" updated successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/machines/<int:machine_id>', methods=['DELETE'])
@admin_required
def delete_machine(machine_id):
    """Soft delete a machine (set is_active = FALSE)"""
    conn = None
    try:
        conn = get_db()
        
        # Check if machine exists
        machine = conn.execute('SELECT machine_name FROM machines WHERE id = ?', (machine_id,)).fetchone()
        if not machine:
            return jsonify({'success': False, 'error': 'Machine not found'}), 404
        
        # Soft delete (don't actually delete - just mark inactive)
        conn.execute('''
            UPDATE machines 
            SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (machine_id,))
        
        conn.commit()
        return jsonify({'success': True, 'message': f'Machine "{machine["machine_name"]}" deleted successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/admin')
def admin_panel():
    """Admin panel with quick actions and product management"""
    # Check for admin session
    if not session.get('admin_authenticated'):
        return render_template('admin_login.html')
    
    conn = None
    try:
        ensure_app_settings_table()  # Ensure table exists
        conn = get_db()
        # Get current settings
        cards_per_turn = conn.execute(
            'SELECT setting_value FROM app_settings WHERE setting_key = ?',
            ('cards_per_turn',)
        ).fetchone()
        cards_per_turn_value = int(cards_per_turn['setting_value']) if cards_per_turn else 1
        conn.close()
        return render_template('admin_panel.html', cards_per_turn=cards_per_turn_value)
    except Exception as e:
        import traceback
        traceback.print_exc()
        if conn:
            try:
                conn.close()
            except:
                pass
        return render_template('admin_panel.html', cards_per_turn=1)

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
    conn = None
    try:
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
    except Exception as e:
        if conn:
            try:
                conn.close()
            except:
                pass
        # Log error but don't expose details to user
        print(f"Login error: {str(e)}")
        if request.form:
            flash('An error occurred during login', 'error')
            return render_template('employee_login.html')
        else:
            return jsonify({'success': False, 'error': 'An error occurred during login'}), 500

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
    """Legacy route - redirects to production page"""
    return redirect(url_for('production_form'))

@app.route('/submit_count', methods=['POST'])
def submit_count():
    """Process manual count submission for PO close-outs"""
    conn = None
    try:
        data = request.get_json() if request.is_json else request.form
        
        # Ensure submission_type column exists
        ensure_submission_type_column()
        
        # Validate required fields
        if not data.get('tablet_type'):
            return jsonify({'error': 'tablet_type is required'}), 400
        
        conn = get_db()
        
        # Get employee name from session (logged-in user)
        if session.get('admin_authenticated'):
            employee_name = 'Admin'
        else:
            employee = conn.execute('''
                SELECT full_name FROM employees WHERE id = ?
            ''', (session.get('employee_id'),)).fetchone()
            
            if not employee:
                return jsonify({'error': 'Employee not found'}), 400
            
            employee_name = employee['full_name']
        
        # Get tablet type details
        tablet_type = conn.execute('''
            SELECT * FROM tablet_types
            WHERE tablet_type_name = ?
        ''', (data.get('tablet_type'),)).fetchone()
        
        if not tablet_type:
            return jsonify({'error': 'Tablet type not found'}), 400
        
        # Convert Row to dict for safe access
        tablet_type = dict(tablet_type)
        
        # Safe type conversion
        try:
            actual_count = int(data.get('actual_count', 0) or 0)
            bag_label_count = 0  # No longer collected from form
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid numeric values for counts'}), 400
        
        # Get submission_date (defaults to today if not provided)
        submission_date = data.get('submission_date', datetime.now().date().isoformat())
        
        # Get admin_notes if user is admin or manager
        admin_notes = data.get('admin_notes', '') if (session.get('admin_authenticated') or session.get('employee_role') in ['admin', 'manager']) else None
        
        # Get inventory_item_id and tablet_type_id
        inventory_item_id = tablet_type.get('inventory_item_id')
        tablet_type_id = tablet_type.get('id')
        if not inventory_item_id:
            return jsonify({'error': 'Tablet type inventory_item_id not found'}), 400
        if not tablet_type_id:
            return jsonify({'error': 'Tablet type_id not found'}), 400
        
        # Find matching bag in receives
        bag, needs_review, error = find_bag_for_submission(
            conn, tablet_type_id, data.get('box_number'), data.get('bag_number')
        )
        
        if error:
            return jsonify({'error': error}), 404
        
        # If needs_review, bag will be None (ambiguous submission)
        bag_id = bag['id'] if bag else None
        po_id = bag['po_id'] if bag else None
        
        # Insert count record with bag_id (or NULL if needs review)
        conn.execute('''
            INSERT INTO warehouse_submissions 
            (employee_name, product_name, inventory_item_id, box_number, bag_number, 
             bag_id, assigned_po_id, needs_review, loose_tablets, 
             submission_date, admin_notes, submission_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'bag')
        ''', (employee_name, data.get('tablet_type'), inventory_item_id, data.get('box_number'),
              data.get('bag_number'), bag_id, po_id, needs_review,
              actual_count, submission_date, admin_notes))
        
        conn.commit()
        
        message = 'Count flagged for manager review - multiple matching receives found.' if needs_review else 'Count submitted successfully!'
        
        return jsonify({
            'success': True,
            'message': message,
            'bag_id': bag_id,
            'needs_review': needs_review
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/submit_machine_count', methods=['POST'])
@employee_required
def submit_machine_count():
    """Submit machine count reading and create warehouse submission"""
    conn = None
    try:
        data = request.get_json()
        
        # Ensure required tables/columns exist
        ensure_submission_type_column()
        ensure_machine_counts_table()
        ensure_machine_count_columns()
        
        tablet_type_id = data.get('tablet_type_id')
        machine_id = data.get('machine_id')
        machine_count = data.get('machine_count')
        box_number = data.get('box_number', '')
        bag_number = data.get('bag_number', '')
        admin_notes = data.get('admin_notes', '').strip() or None  # Convert empty string to NULL
        
        # Automatically set date to current EST date
        count_date = datetime.now(ZoneInfo('America/New_York')).strftime('%Y-%m-%d')
        
        # Validation
        if not tablet_type_id:
            return jsonify({'error': 'Tablet type is required'}), 400
        if not machine_id:
            return jsonify({'error': 'Machine is required'}), 400
        if machine_count is None or machine_count < 0:
            return jsonify({'error': 'Valid machine count is required'}), 400
        if not box_number:
            return jsonify({'error': 'Box number is required'}), 400
        if not bag_number:
            return jsonify({'error': 'Bag number is required'}), 400
        
        conn = get_db()
        
        # Get employee name from session (logged-in user)
        if session.get('admin_authenticated'):
            employee_name = 'Admin'
        else:
            employee = conn.execute('''
                SELECT full_name FROM employees WHERE id = ?
            ''', (session.get('employee_id'),)).fetchone()
            
            if not employee:
                return jsonify({'error': 'Employee not found'}), 400
            
            employee_name = employee['full_name']
        
        # Verify tablet type exists and get its info
        tablet_type = conn.execute('''
            SELECT id, tablet_type_name, inventory_item_id 
            FROM tablet_types 
            WHERE id = ?
        ''', (tablet_type_id,)).fetchone()
        if not tablet_type:
            return jsonify({'error': 'Invalid tablet type'}), 400
        
        tablet_type = dict(tablet_type)
        
        # Get a product for this tablet type to get tablets_per_package
        product = conn.execute('''
            SELECT product_name, tablets_per_package 
            FROM product_details 
            WHERE tablet_type_id = ? 
            LIMIT 1
        ''', (tablet_type_id,)).fetchone()
        
        if not product:
            return jsonify({'error': 'No product found for this tablet type. Please configure a product first.'}), 400
        
        product = dict(product)
        tablets_per_package = product.get('tablets_per_package', 0)
        
        if tablets_per_package == 0:
            return jsonify({'error': 'Product configuration incomplete: tablets_per_package must be greater than 0'}), 400
        
        # Get machine configuration
        machine = conn.execute('''
            SELECT machine_name, cards_per_turn 
            FROM machines 
            WHERE id = ? AND is_active = TRUE
        ''', (machine_id,)).fetchone()
        
        if not machine:
            return jsonify({'error': 'Machine not found or inactive'}), 400
        
        machine = dict(machine)
        cards_per_turn = machine.get('cards_per_turn', 1)
        
        # Calculate total tablets: machine_count (turns) × cards_per_turn × tablets_per_package
        try:
            machine_count_int = int(machine_count)
            total_tablets = machine_count_int * cards_per_turn * tablets_per_package
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid machine count value'}), 400
        
        # Insert machine count record (for historical tracking)
        conn.execute('''
            INSERT INTO machine_counts (tablet_type_id, machine_id, machine_count, employee_name, count_date, box_number, bag_number)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (tablet_type_id, machine_id, machine_count_int, employee_name, count_date, box_number, bag_number))
        
        # Get inventory_item_id
        inventory_item_id = tablet_type.get('inventory_item_id')
        if not inventory_item_id:
            conn.commit()
            return jsonify({'warning': 'Tablet type inventory_item_id not found. Machine count saved but not linked to receive.', 'submission_saved': True})
        
        # Find matching bag in receives
        bag, needs_review, error = find_bag_for_submission(
            conn, tablet_type_id, box_number, bag_number
        )
        
        if error:
            # Save machine_counts record even if no bag found
            conn.commit()
            return jsonify({
                'warning': error,
                'submission_saved': True,
                'message': f'Machine count recorded ({total_tablets} tablets) but not linked to receive: {error}'
            })
        
        # If needs_review, bag will be None (ambiguous submission)
        bag_id = bag['id'] if bag else None
        po_id = bag['po_id'] if bag else None
        
        # Create warehouse submission with submission_type='machine' and bag_id (or NULL if needs review)
        conn.execute('''
            INSERT INTO warehouse_submissions 
            (employee_name, product_name, inventory_item_id, box_number, bag_number,
             bag_id, assigned_po_id, needs_review, loose_tablets, submission_date, admin_notes, submission_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'machine')
        ''', (employee_name, product['product_name'], inventory_item_id, box_number, bag_number,
              bag_id, po_id, needs_review, total_tablets, count_date, admin_notes))
        
        conn.commit()
        
        base_message = f'Machine count submitted ({machine["machine_name"]}): {total_tablets} tablets ({machine_count_int} turns × {cards_per_turn} cards × {tablets_per_package} tablets/card)'
        if needs_review:
            base_message += ' - Flagged for manager review (multiple matching receives found)'
        
        return jsonify({
            'success': True, 
            'message': base_message,
            'bag_id': bag_id,
            'needs_review': needs_review
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/save_product', methods=['POST'])
@admin_required
def save_product():
    """Save or update a product configuration"""
    conn = None
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['product_name', 'tablet_type_id', 'packages_per_display', 'tablets_per_package']
        for field in required_fields:
            if field not in data or data[field] is None:
                return jsonify({'success': False, 'error': f'{field} is required'}), 400
        
        # Validate numeric fields
        try:
            tablet_type_id = int(data['tablet_type_id'])
            packages_per_display = int(data['packages_per_display'])
            tablets_per_package = int(data['tablets_per_package'])
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid numeric values for tablet_type_id, packages_per_display, or tablets_per_package'}), 400
        
        conn = get_db()
        
        product_name = data.get('product_name')
        
        if data.get('id'):
            # Update existing product
            try:
                product_id = int(data['id'])
            except (ValueError, TypeError):
                conn.close()
                return jsonify({'success': False, 'error': 'Invalid product ID'}), 400
                
            conn.execute('''
                UPDATE product_details 
                SET product_name = ?, tablet_type_id = ?, packages_per_display = ?, tablets_per_package = ?
                WHERE id = ?
            ''', (product_name, tablet_type_id, packages_per_display, tablets_per_package, product_id))
            message = f"Updated {product_name}"
        else:
            # Create new product
            conn.execute('''
                INSERT INTO product_details (product_name, tablet_type_id, packages_per_display, tablets_per_package)
                VALUES (?, ?, ?, ?)
            ''', (product_name, tablet_type_id, packages_per_display, tablets_per_package))
            message = f"Created {product_name}"
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': message})
        
    except Exception as e:
        if conn:
            try:
                conn.close()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/delete_product/<int:product_id>', methods=['DELETE'])
def delete_product(product_id):
    """Delete a product configuration"""
    conn = None
    try:
        conn = get_db()
        
        # Get product name first
        product = conn.execute('SELECT product_name FROM product_details WHERE id = ?', (product_id,)).fetchone()
        if not product:
            conn.close()
            return jsonify({'success': False, 'error': 'Product not found'}), 404
        
        conn.execute('DELETE FROM product_details WHERE id = ?', (product_id,))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f"Deleted {product['product_name']}"})
        
    except Exception as e:
        if conn:
            try:
                conn.close()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/get_or_create_tablet_type', methods=['POST'])
def get_or_create_tablet_type():
    """Get existing tablet type by name or create new one"""
    conn = None
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
        if conn:
            try:
                conn.close()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/update_tablet_inventory_ids', methods=['POST'])
def update_tablet_inventory_ids():
    """Update tablet types with inventory item IDs from PO line items"""
    conn = None
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
        if conn:
            try:
                conn.close()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/tablet_types/categories', methods=['GET'])
def get_tablet_type_categories():
    """Get all tablet types grouped by their configured categories"""
    conn = None
    try:
        conn = get_db()
        conn.row_factory = sqlite3.Row
        
        # Get all tablet types with their categories
        tablet_types = conn.execute('''
            SELECT id, tablet_type_name, category 
            FROM tablet_types 
            ORDER BY tablet_type_name
        ''').fetchall()
        
        # Group by category
        categories = {}
        unassigned = []
        
        for tt in tablet_types:
            category = tt['category'] if tt['category'] else None
            if not category:
                unassigned.append({
                    'id': tt['id'],
                    'name': tt['tablet_type_name']
                })
            else:
                if category not in categories:
                    categories[category] = []
                categories[category].append({
                    'id': tt['id'],
                    'name': tt['tablet_type_name']
                })
        
        # Add unassigned to Other if it exists
        if unassigned:
            if 'Other' not in categories:
                categories['Other'] = []
            categories['Other'].extend(unassigned)
        
        # Get category order from categories table (dynamic, not hardcoded!)
        category_rows = conn.execute('''
            SELECT category_name FROM categories 
            WHERE is_active = TRUE 
            ORDER BY display_order, category_name
        ''').fetchall()
        category_order = [row['category_name'] for row in category_rows]
        
        return jsonify({
            'success': True,
            'categories': categories,
            'category_order': category_order
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/tablet_type/category', methods=['POST'])
@admin_required
def update_tablet_type_category():
    """Update category for a tablet type"""
    conn = None
    try:
        data = request.get_json()
        tablet_type_id = data.get('tablet_type_id')
        category = data.get('category')  # Can be None to remove category
        
        if not tablet_type_id:
            return jsonify({'success': False, 'error': 'Tablet type ID required'}), 400
        
        conn = get_db()
        
        # Ensure category exists in categories table if not None
        if category:
            # Check if category exists
            existing_cat = conn.execute('''
                SELECT id FROM categories WHERE category_name = ?
            ''', (category,)).fetchone()
            
            if not existing_cat:
                # Get max display_order and add new category at the end
                max_order = conn.execute('SELECT MAX(display_order) as max FROM categories').fetchone()['max']
                new_order = (max_order or 0) + 1
                
                # Insert new category
                conn.execute('''
                    INSERT INTO categories (category_name, display_order, is_active)
                    VALUES (?, ?, TRUE)
                ''', (category, new_order))
        
        # Update category in tablet_types
        conn.execute('''
            UPDATE tablet_types 
            SET category = ?
            WHERE id = ?
        ''', (category, tablet_type_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Category updated successfully'})
    except Exception as e:
        if conn:
            try:
                conn.close()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/debug/tablet_types', methods=['GET'])
@admin_required
def debug_tablet_types():
    """Debug endpoint to see tablet types with categories"""
    conn = None
    try:
        conn = get_db()
        
        # Get all tablet types with their categories
        tablet_types = conn.execute('''
            SELECT id, tablet_type_name, category 
            FROM tablet_types 
            ORDER BY category, tablet_type_name
        ''').fetchall()
        
        conn.close()
        
        return jsonify({
            'success': True,
            'tablet_types': [dict(tt) for tt in tablet_types],
            'count': len(tablet_types)
        })
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/debug/categories', methods=['GET'])
@admin_required
def debug_categories():
    """Debug endpoint to see category data"""
    conn = None
    try:
        conn = get_db()
        
        # Get categories from categories table
        categories_table = conn.execute('''
            SELECT * FROM categories WHERE is_active = TRUE ORDER BY display_order
        ''').fetchall()
        
        # Get categories from tablet_types
        categories_in_use = conn.execute('''
            SELECT DISTINCT category FROM tablet_types WHERE category IS NOT NULL AND category != ''
        ''').fetchall()
        
        conn.close()
        
        return jsonify({
            'success': True,
            'categories_table': [dict(c) for c in categories_table],
            'categories_in_tablet_types': [c['category'] for c in categories_in_use],
            'count_in_table': len(categories_table),
            'count_in_tablet_types': len(categories_in_use)
        })
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/categories', methods=['GET'])
@admin_required
def get_categories():
    """Get all unique categories"""
    conn = None
    try:
        conn = get_db()
        
        # Get unique categories from tablet_types
        categories = conn.execute('''
            SELECT DISTINCT category 
            FROM tablet_types 
            WHERE category IS NOT NULL AND category != ''
            ORDER BY category
        ''').fetchall()
        
        # Get all active categories from database (no more hardcoded lists!)
        all_categories_from_db = conn.execute('''
            SELECT category_name 
            FROM categories 
            WHERE is_active = TRUE 
            ORDER BY display_order, category_name
        ''').fetchall()
        all_categories = [cat['category_name'] for cat in all_categories_from_db]
        
        conn.close()
        return jsonify({'success': True, 'categories': all_categories})
    except Exception as e:
        if conn:
            try:
                conn.close()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/categories', methods=['POST'])
@admin_required
def add_category():
    """Add a new category to the categories table"""
    conn = None
    try:
        data = request.get_json()
        category_name = data.get('category_name', '').strip()
        
        if not category_name:
            return jsonify({'success': False, 'error': 'Category name required'}), 400
        
        conn = get_db()
        conn.row_factory = sqlite3.Row
        
        # Check if category already exists (including inactive ones)
        existing = conn.execute('''
            SELECT id, is_active FROM categories WHERE category_name = ?
        ''', (category_name,)).fetchone()
        
        if existing:
            if existing['is_active']:
                return jsonify({'success': False, 'error': 'Category already exists'}), 400
            else:
                # Reactivate inactive category
                conn.execute('''
                    UPDATE categories 
                    SET is_active = TRUE, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (existing['id'],))
                conn.commit()
                return jsonify({
                    'success': True, 
                    'message': f'Category "{category_name}" reactivated successfully!'
                })
        
        # Get max display_order and add new category at the end
        max_order = conn.execute('SELECT MAX(display_order) as max FROM categories').fetchone()['max']
        new_order = (max_order or 0) + 1
        
        # Insert new category
        conn.execute('''
            INSERT INTO categories (category_name, display_order, is_active)
            VALUES (?, ?, TRUE)
        ''', (category_name, new_order))
        
        conn.commit()
        
        return jsonify({
            'success': True, 
            'message': f'Category "{category_name}" added successfully!'
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/categories/rename', methods=['POST'])
@admin_required
def rename_category():
    """Rename a category in the categories table (also updates tablet_types)"""
    conn = None
    try:
        data = request.get_json()
        old_name = data.get('old_name', '').strip()
        new_name = data.get('new_name', '').strip()
        
        if not old_name or not new_name:
            return jsonify({'success': False, 'error': 'Both old and new category names required'}), 400
        
        if old_name == new_name:
            return jsonify({'success': False, 'error': 'New name must be different from old name'}), 400
        
        conn = get_db()
        conn.row_factory = sqlite3.Row
        
        # Check if old category exists in categories table
        old_exists = conn.execute('''
            SELECT id FROM categories WHERE category_name = ?
        ''', (old_name,)).fetchone()
        
        if not old_exists:
            return jsonify({'success': False, 'error': f'Category "{old_name}" not found'}), 404
        
        # Check if new name already exists
        new_exists = conn.execute('''
            SELECT id FROM categories WHERE category_name = ?
        ''', (new_name,)).fetchone()
        
        if new_exists:
            return jsonify({'success': False, 'error': 'Category name already exists'}), 400
        
        # Update the category name in categories table
        conn.execute('''
            UPDATE categories 
            SET category_name = ?, updated_at = CURRENT_TIMESTAMP
            WHERE category_name = ?
        ''', (new_name, old_name))
        
        # Also update all tablet types with the old category name
        cursor = conn.execute('''
            UPDATE tablet_types 
            SET category = ?
            WHERE category = ?
        ''', (new_name, old_name))
        
        tablet_types_updated = cursor.rowcount
        
        conn.commit()
        
        return jsonify({
            'success': True, 
            'message': f'✅ Category renamed from "{old_name}" to "{new_name}" ({tablet_types_updated} tablet types updated)'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/categories/delete', methods=['POST'])
@admin_required
def delete_category():
    """Soft delete a category (marks as inactive, removes from tablet types)"""
    conn = None
    try:
        data = request.get_json()
        category_name = data.get('category_name', '').strip()
        
        if not category_name:
            return jsonify({'success': False, 'error': 'Category name required'}), 400
        
        conn = get_db()
        conn.row_factory = sqlite3.Row
        
        # Check if category exists in categories table
        category = conn.execute('''
            SELECT id, is_active FROM categories WHERE category_name = ?
        ''', (category_name,)).fetchone()
        
        if not category:
            return jsonify({'success': False, 'error': f'Category "{category_name}" not found'}), 404
        
        if not category['is_active']:
            return jsonify({'success': False, 'error': 'Category already deleted'}), 400
        
        # Soft delete category (mark as inactive)
        conn.execute('''
            UPDATE categories 
            SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (category['id'],))
        
        # Remove category from all tablet types (set to NULL)
        cursor = conn.execute('''
            UPDATE tablet_types 
            SET category = NULL
            WHERE category = ?
        ''', (category_name,))
        
        tablet_types_updated = cursor.rowcount
        
        conn.commit()
        
        return jsonify({
            'success': True, 
            'message': f'✅ Category "{category_name}" deleted. {tablet_types_updated} tablet type(s) unassigned.'
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

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
    conn = None
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
        return jsonify({'success': True, 'message': f'Added employee: {full_name}'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/update_employee_role/<int:employee_id>', methods=['POST'])
@admin_required
def update_employee_role(employee_id):
    """Update an employee's role"""
    conn = None
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
        
        return jsonify({
            'success': True, 
            'message': f'Updated {employee["full_name"]} role to {new_role.replace("_", " ").title()}'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/toggle_employee/<int:employee_id>', methods=['POST'])
def toggle_employee(employee_id):
    """Toggle employee active status"""
    conn = None
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
        
        status_text = 'activated' if new_status else 'deactivated'
        return jsonify({'success': True, 'message': f'{employee["full_name"]} {status_text}'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/delete_employee/<int:employee_id>', methods=['DELETE'])
def delete_employee(employee_id):
    """Delete an employee"""
    conn = None
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
        
        return jsonify({'success': True, 'message': f'Deleted employee: {employee["full_name"]}'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

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
    conn = None
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
        if conn:
            try:
                conn.close()
            except:
                pass
        return jsonify({
            'success': False,
            'error': f'Clear failed: {str(e)}'
        }), 500

# ===== PRODUCTION REPORT ENDPOINTS =====

@app.route('/api/reports/production', methods=['POST'])
@role_required('dashboard')
def generate_production_report():
    """Generate comprehensive production report PDF"""
    try:
        data = request.get_json() or {}
        
        start_date = data.get('start_date')
        end_date = data.get('end_date') 
        po_numbers = data.get('po_numbers', [])
        tablet_type_id = data.get('tablet_type_id')
        receive_id = data.get('receive_id')
        report_type = data.get('report_type', 'production')  # 'production', 'vendor', or 'receive'
        
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
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        if report_type == 'vendor':
            pdf_content = generator.generate_vendor_report(
                start_date=start_date,
                end_date=end_date,
                po_numbers=po_numbers if po_numbers else None,
                tablet_type_id=tablet_type_id
            )
            filename = f'vendor_report_{timestamp}.pdf'
        elif report_type == 'receive':
            if not receive_id:
                return jsonify({'error': 'Receive ID is required for receive reports'}), 400
            pdf_content = generator.generate_receive_report(receive_id=receive_id)
            filename = f'receive_report_{timestamp}.pdf'
        else:
            pdf_content = generator.generate_production_report(
                start_date=start_date,
                end_date=end_date,
                po_numbers=po_numbers if po_numbers else None,
                tablet_type_id=tablet_type_id
            )
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
@role_required('dashboard')
def get_po_summary_for_reports():
    """Get summary of POs available for reporting"""
    conn = None
    try:
        conn = get_db()
        
        # First, verify the table exists and has data
        po_count_row = conn.execute('SELECT COUNT(*) as count FROM purchase_orders').fetchone()
        po_count = dict(po_count_row) if po_count_row else {'count': 0}
        if not po_count or po_count.get('count', 0) == 0:
            conn.close()
            return jsonify({
                'success': True,
                'pos': [],
                'total_count': 0,
                'message': 'No purchase orders found'
            })
        
        # Simplified query for dropdown - use subqueries instead of GROUP BY with JOINs
        # This avoids expensive JOIN operations and is much faster
        query = '''
            SELECT 
                po.id,
                po.po_number,
                po.tablet_type,
                COALESCE(po.internal_status, 'Active') as internal_status,
                COALESCE(po.ordered_quantity, 0) as ordered_quantity,
                COALESCE(po.current_good_count, 0) as current_good_count,
                COALESCE(po.current_damaged_count, 0) as current_damaged_count,
                po.created_at,
                po.updated_at,
                (SELECT COUNT(*) FROM warehouse_submissions WHERE assigned_po_id = po.id) as submission_count,
                (SELECT MAX(created_at) FROM warehouse_submissions WHERE assigned_po_id = po.id) as last_submission,
                (SELECT MAX(actual_delivery) FROM shipments WHERE po_id = po.id) as actual_delivery,
                (SELECT MAX(delivered_at) FROM shipments WHERE po_id = po.id) as delivered_at,
                (SELECT MAX(tracking_status) FROM shipments WHERE po_id = po.id) as tracking_status
            FROM purchase_orders po
            WHERE po.po_number IS NOT NULL
            ORDER BY po.created_at DESC
            LIMIT 100
        '''
        pos = conn.execute(query).fetchall()
        
        # Convert to list of dicts efficiently - calculate pack_time only if dates exist
        po_list = []
        for po_row in pos:
            po = dict(po_row)
            
            # Calculate pack time if both dates exist (simplified)
            pack_time = None
            delivery_date = po.get('actual_delivery') or po.get('delivered_at')
            completion_date = po.get('last_submission') or (po.get('updated_at')[:10] if po.get('internal_status') == 'Complete' and po.get('updated_at') else None)
            
            if delivery_date and completion_date:
                try:
                    del_dt = datetime.strptime(str(delivery_date)[:10], '%Y-%m-%d')
                    comp_dt = datetime.strptime(str(completion_date)[:10], '%Y-%m-%d')
                    pack_time = (comp_dt - del_dt).days
                except (ValueError, TypeError):
                    pack_time = None
            
            po_list.append({
                'po_number': po.get('po_number') or 'N/A',
                'tablet_type': po.get('tablet_type') or 'N/A',
                'status': po.get('internal_status') or 'Active',
                'ordered': int(po.get('ordered_quantity') or 0),
                'produced': int(po.get('current_good_count') or 0),
                'damaged': int(po.get('current_damaged_count') or 0),
                'created_date': str(po['created_at'])[:10] if po.get('created_at') else None,
                'submissions': int(po.get('submission_count') or 0),
                'pack_time_days': pack_time,
                'tracking_status': po.get('tracking_status')
            })
        
        conn.close()
        
        return jsonify({
            'success': True,
            'pos': po_list,
            'total_count': len(po_list)
        })
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error in get_po_summary_for_reports: {e}")
        print(error_trace)
        if conn:
            try:
                conn.close()
            except:
                pass
        return jsonify({
            'success': False,
            'error': f'Failed to get PO summary: {str(e)}',
            'trace': error_trace
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
    conn = None
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
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/receiving')
@admin_required  
def receiving_management_v2():
    """Receiving management page - REBUILT VERSION"""
    conn = None
    try:
        conn = get_db()
        
        # Simple query first - just check if we can access receiving table
        try:
            test_query = conn.execute('SELECT COUNT(*) as count FROM receiving').fetchone()
            receiving_count = test_query['count'] if test_query else 0
        except Exception as e:
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
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/receiving/<int:receiving_id>')
@admin_required
def receiving_details(receiving_id):
    """View detailed information about a specific receiving record"""
    conn = None
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
        
        return render_template('receiving_details.html', 
                             receiving=dict(receiving),
                             boxes=[dict(box) for box in boxes])
                             
    except Exception as e:
        flash(f'Error loading receiving details: {str(e)}', 'error')
        return redirect(url_for('receiving_management_v2'))
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/receiving/<int:receiving_id>', methods=['DELETE'])
@role_required('shipping')
def delete_receiving(receiving_id):
    """Delete a receiving record with verification"""
    conn = None
    try:
        # Check if user is manager or admin
        user_role = session.get('employee_role')
        if user_role not in ['manager', 'admin']:
            return jsonify({'success': False, 'error': 'Only managers and admins can delete shipments'}), 403
        
        conn = get_db()
        
        # Check if receiving record exists and get info
        receiving = conn.execute('''
            SELECT r.id, r.po_id, po.po_number, r.received_date, r.received_by
            FROM receiving r
            LEFT JOIN purchase_orders po ON r.po_id = po.id
            WHERE r.id = ?
        ''', (receiving_id,)).fetchone()
        
        if not receiving:
            return jsonify({'success': False, 'error': 'Receiving record not found'}), 404
        
        # Delete in correct order due to foreign key constraints
        # 1. Delete bags first
        conn.execute('DELETE FROM bags WHERE small_box_id IN (SELECT id FROM small_boxes WHERE receiving_id = ?)', (receiving_id,))
        
        # 2. Delete small_boxes
        conn.execute('DELETE FROM small_boxes WHERE receiving_id = ?', (receiving_id,))
        
        # 3. Delete receiving record
        conn.execute('DELETE FROM receiving WHERE id = ?', (receiving_id,))
        
        conn.commit()
        
        po_info = receiving['po_number'] if receiving['po_number'] else 'No PO'
        return jsonify({
            'success': True,
            'message': f'Successfully deleted shipment (PO: {po_info})'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'Failed to delete receiving record: {str(e)}'}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/process_receiving', methods=['POST'])
@admin_required
def process_receiving():
    """Process a new shipment receiving with photos and box/bag tracking"""
    conn = None
    try:
        conn = get_db()
        
        # Get form data with safe type conversion
        shipment_id = request.form.get('shipment_id')
        if not shipment_id:
            return jsonify({'error': 'Shipment ID required'}), 400
        
        # Safe type conversion for total_small_boxes
        try:
            total_small_boxes = int(request.form.get('total_small_boxes', 0))
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid total_small_boxes value'}), 400
        
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
            # Create uploads directory if it doesn't exist
            upload_dir = 'static/uploads/receiving'
            os.makedirs(upload_dir, exist_ok=True)
            
            # Generate unique filename
            filename = f"shipment_{shipment_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            photo_path = os.path.join(upload_dir, filename)
            delivery_photo.save(photo_path)
            
            # TODO: Upload to Zoho (implement after basic workflow is working)
        
        # Create receiving record with EST timestamp
        est_timestamp = get_est_timestamp()
        receiving_cursor = conn.execute('''
            INSERT INTO receiving (po_id, shipment_id, total_small_boxes, received_by, notes, delivery_photo_path, delivery_photo_zoho_id, received_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (shipment['po_id'], shipment_id, total_small_boxes, received_by, notes, photo_path, zoho_photo_id, est_timestamp))
        
        receiving_id = receiving_cursor.lastrowid
        
        # Process box details with sequential bag numbering
        total_bags = 0
        all_bag_data = {}
        
        # First, collect all bag data from the form with safe type conversion
        for key in request.form.keys():
            if key.startswith('bag_') and key.endswith('_pill_count'):
                try:
                    # Extract bag number from key like 'bag_3_pill_count'
                    key_parts = key.split('_')
                    if len(key_parts) < 2:
                        continue
                    bag_num = int(key_parts[1])
                    if bag_num not in all_bag_data:
                        all_bag_data[bag_num] = {}
                    
                    # Safe type conversion for pill_count
                    try:
                        all_bag_data[bag_num]['pill_count'] = int(request.form[key])
                    except (ValueError, TypeError):
                        all_bag_data[bag_num]['pill_count'] = 0
                    
                    # Safe type conversion for box number
                    try:
                        all_bag_data[bag_num]['box'] = int(request.form.get(f'bag_{bag_num}_box', 0))
                    except (ValueError, TypeError):
                        all_bag_data[bag_num]['box'] = 0
                    
                    all_bag_data[bag_num]['notes'] = request.form.get(f'bag_{bag_num}_notes', '')
                except (ValueError, TypeError, IndexError):
                    # Skip invalid bag entries
                    continue
        
        # Process boxes and their bags with sequential numbering
        for box_num in range(1, total_small_boxes + 1):
            # Safe type conversion for bags_in_box
            try:
                bags_in_box = int(request.form.get(f'box_{box_num}_bags', 0))
            except (ValueError, TypeError):
                bags_in_box = 0
            
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
        
        return jsonify({
            'success': True,
            'message': f'Successfully received shipment for PO {shipment["po_number"]}. Processed {total_small_boxes} boxes with {total_bags} total bags.',
            'receiving_id': receiving_id
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to process receiving: {str(e)}'}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/save_receives', methods=['POST'])
@role_required('shipping')
def save_receives():
    """Save received shipment data (boxes and bags)"""
    conn = None
    try:
        data = request.get_json()
        boxes_data = data.get('boxes', [])
        po_id = data.get('po_id')  # Required PO assignment
        
        if not boxes_data:
            return jsonify({'success': False, 'error': 'No boxes data provided'}), 400
        
        # PO is now required for all receives (source of truth for submissions)
        if not po_id:
            return jsonify({'success': False, 'error': 'PO is required when creating a receive'}), 400
        
        # Only managers and admins can assign POs
        user_role = session.get('employee_role')
        if user_role not in ['manager', 'admin'] and not session.get('admin_authenticated'):
            return jsonify({'success': False, 'error': 'Only managers and admins can create receives'}), 403
        
        conn = get_db()
        
        # Ensure tablet_type_id column exists in bags table
        c = conn.cursor()
        c.execute('PRAGMA table_info(bags)')
        existing_bags_cols = [row[1] for row in c.fetchall()]
        if 'tablet_type_id' not in existing_bags_cols:
            try:
                conn.execute('ALTER TABLE bags ADD COLUMN tablet_type_id INTEGER')
                conn.commit()
            except Exception as e:
                print(f"Warning: Could not add tablet_type_id column: {e}")
        
        # Get current user name
        received_by = 'Unknown'
        if session.get('employee_id'):
            employee = conn.execute('SELECT full_name FROM employees WHERE id = ?', (session.get('employee_id'),)).fetchone()
            if employee:
                received_by = employee['full_name']
        elif session.get('admin_authenticated'):
            received_by = 'Admin'
        
        # Create receiving record (with optional PO assignment) with EST timestamp
        est_timestamp = get_est_timestamp()
        receiving_cursor = conn.execute('''
            INSERT INTO receiving (po_id, received_by, received_date, total_small_boxes, notes)
            VALUES (?, ?, ?, ?, ?)
        ''', (po_id if po_id else None, received_by, est_timestamp, len(boxes_data), f'Recorded {len(boxes_data)} box(es)'))
        
        receiving_id = receiving_cursor.lastrowid
        total_bags = 0
        
        # Process each box
        for box_data in boxes_data:
            box_number = box_data.get('box_number')
            bags = box_data.get('bags', [])
            
            if not bags:
                continue
            
            # Create small box record
            box_cursor = conn.execute('''
                INSERT INTO small_boxes (receiving_id, box_number, total_bags)
                VALUES (?, ?, ?)
            ''', (receiving_id, box_number, len(bags)))
            
            small_box_id = box_cursor.lastrowid
            
            # Create bag records
            for bag_idx, bag in enumerate(bags, start=1):
                tablet_type_id = bag.get('tablet_type_id')
                bag_count = bag.get('bag_count', 0)
                
                if not tablet_type_id:
                    continue
                
                conn.execute('''
                    INSERT INTO bags (small_box_id, bag_number, bag_label_count, tablet_type_id, status)
                    VALUES (?, ?, ?, ?, 'Available')
                ''', (small_box_id, bag_idx, bag_count, tablet_type_id))
                total_bags += 1
        
        # Update receiving record with total bags
        conn.execute('''
            UPDATE receiving SET total_small_boxes = ?
            WHERE id = ?
        ''', (len(boxes_data), receiving_id))
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': f'Successfully recorded {len(boxes_data)} box(es) with {total_bags} bag(s)',
            'receiving_id': receiving_id
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/receiving/<int:receiving_id>/assign_po', methods=['POST'])
@role_required('shipping')
def assign_po_to_receiving(receiving_id):
    """Update PO assignment for a receiving record (managers and admins only)"""
    conn = None
    try:
        user_role = session.get('employee_role')
        if user_role not in ['manager', 'admin']:
            return jsonify({'success': False, 'error': 'Only managers and admins can assign POs'}), 403
        
        data = request.get_json()
        po_id = data.get('po_id')  # Can be None to unassign
        
        conn = get_db()
        
        # Verify receiving record exists
        receiving = conn.execute('SELECT id FROM receiving WHERE id = ?', (receiving_id,)).fetchone()
        if not receiving:
            return jsonify({'success': False, 'error': 'Receiving record not found'}), 404
        
        # Update PO assignment
        conn.execute('''
            UPDATE receiving SET po_id = ?
            WHERE id = ?
        ''', (po_id if po_id else None, receiving_id))
        
        conn.commit()
        
        # Get PO number for response
        po_number = None
        if po_id:
            po = conn.execute('SELECT po_number FROM purchase_orders WHERE id = ?', (po_id,)).fetchone()
            if po:
                po_number = po['po_number']
        
        return jsonify({
            'success': True,
            'message': f'PO assignment updated successfully',
            'po_number': po_number
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/available_boxes_bags/<int:po_id>')
@employee_required
def get_available_boxes_bags(po_id):
    """Get available boxes and bags for a PO (for warehouse form dropdowns)"""
    conn = None
    try:
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
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


@app.route('/api/create_sample_receiving_data', methods=['POST'])
@admin_required  
def create_sample_receiving_data():
    """Create sample PO and shipment data for testing receiving workflow"""
    conn = None
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
        # Ensure connection is closed even on error
        if conn:
            try:
                conn.close()
            except:
                pass
        return jsonify({'error': f'Failed to create sample data: {str(e)}'}), 500

@app.route('/api/update_submission_date', methods=['POST'])
@role_required('dashboard')
def update_submission_date():
    """Update the submission date for an existing submission"""
    conn = None
    try:
        data = request.get_json()
        submission_id = data.get('submission_id')
        submission_date = data.get('submission_date')
        
        if not submission_id or not submission_date:
            return jsonify({'error': 'Missing submission_id or submission_date'}), 400
        
        # Validate submission_id is numeric
        try:
            submission_id = int(submission_id)
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid submission_id - must be numeric'}), 400
        
        conn = get_db()
        
        # Update the submission date
        conn.execute('''
            UPDATE warehouse_submissions 
            SET submission_date = ?
            WHERE id = ?
        ''', (submission_date, submission_id))
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': f'Submission date updated to {submission_date}'
        })
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/submission/<int:submission_id>/available_pos', methods=['GET'])
@role_required('dashboard')
def get_available_pos_for_submission(submission_id):
    """Get list of POs that can accept this submission (filtered by product/inventory_item_id)"""
    conn = None
    try:
        conn = get_db()
        
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
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/submission/<int:submission_id>/approve', methods=['POST'])
@role_required('dashboard')
def approve_submission_assignment(submission_id):
    """Approve and lock the current PO assignment for a submission"""
    conn = None
    try:
        conn = get_db()
        
        # Check if submission exists and isn't already verified
        submission = conn.execute('''
            SELECT id, assigned_po_id, po_assignment_verified
            FROM warehouse_submissions
            WHERE id = ?
        ''', (submission_id,)).fetchone()
        
        if not submission:
            return jsonify({'error': 'Submission not found'}), 404
        
        if submission['po_assignment_verified']:
            return jsonify({'error': 'Submission already verified and locked'}), 400
        
        if not submission['assigned_po_id']:
            return jsonify({'error': 'Cannot approve unassigned submission'}), 400
        
        # Mark as verified/locked
        conn.execute('''
            UPDATE warehouse_submissions 
            SET po_assignment_verified = TRUE
            WHERE id = ?
        ''', (submission_id,))
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': 'PO assignment approved and locked'
        })
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@app.route('/api/receives/list', methods=['GET'])
@role_required('dashboard')
def get_receives_list():
    """Get list of all receives for reporting"""
    conn = None
    try:
        conn = get_db()
        
        receives = conn.execute('''
            SELECT r.id, 
                   r.received_date,
                   po.po_number,
                   r.po_id,
                   (SELECT COUNT(*) + 1
                    FROM receiving r2
                    WHERE r2.po_id = r.po_id
                    AND (r2.received_date < r.received_date 
                         OR (r2.received_date = r.received_date AND r2.id < r.id))
                   ) as receive_number
            FROM receiving r
            LEFT JOIN purchase_orders po ON r.po_id = po.id
            WHERE r.received_date IS NOT NULL
            ORDER BY r.received_date DESC, r.id DESC
            LIMIT 100
        ''').fetchall()
        
        receives_list = []
        for r in receives:
            receive_dict = dict(r)
            # Create receive name like "PO-00164-1"
            receive_dict['receive_name'] = f"{receive_dict['po_number']}-{receive_dict['receive_number']}"
            receives_list.append(receive_dict)
        
        return jsonify({
            'success': True,
            'receives': receives_list
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/bag/<int:bag_id>/submissions', methods=['GET'])
@role_required('dashboard')
def get_bag_submissions(bag_id):
    """Get all submissions for a specific bag (for duplicate review)"""
    conn = None
    try:
        conn = get_db()
        
        submissions = conn.execute('''
            SELECT ws.*, 
                   (
                       CASE ws.submission_type
                           WHEN 'packaged' THEN (ws.displays_made * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0) + 
                                                ws.packs_remaining * COALESCE(pd.tablets_per_package, 0))
                           WHEN 'bag' THEN ws.loose_tablets
                           WHEN 'machine' THEN ws.loose_tablets
                           ELSE ws.loose_tablets + ws.damaged_tablets
                       END
                   ) as total_tablets
            FROM warehouse_submissions ws
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
            WHERE ws.bag_id = ?
            ORDER BY ws.created_at DESC
        ''', (bag_id,)).fetchall()
        
        return jsonify({
            'success': True,
            'submissions': [dict(row) for row in submissions]
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/submission/<int:submission_id>', methods=['DELETE'])
@role_required('dashboard')
def delete_submission(submission_id):
    """Delete a submission (for removing duplicates)"""
    conn = None
    try:
        conn = get_db()
        
        # Check if submission exists
        submission = conn.execute('''
            SELECT id FROM warehouse_submissions WHERE id = ?
        ''', (submission_id,)).fetchone()
        
        if not submission:
            return jsonify({'success': False, 'error': 'Submission not found'}), 404
        
        # Delete the submission
        conn.execute('DELETE FROM warehouse_submissions WHERE id = ?', (submission_id,))
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': 'Submission deleted successfully'
        })
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/submission/<int:submission_id>/details', methods=['GET'])
@admin_required
def get_submission_details(submission_id):
    # Allow managers to view submission details (especially admin notes)
    if not (session.get('admin_authenticated') or 
            (session.get('employee_authenticated') and session.get('employee_role') in ['admin', 'manager'])):
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    """Get full details of a submission for editing (Admin only)"""
    conn = None
    try:
        conn = get_db()
        
        submission = conn.execute('''
            SELECT ws.*, po.po_number, po.closed as po_closed,
                   COALESCE(ws.po_assignment_verified, 0) as po_verified
            FROM warehouse_submissions ws
            LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
            WHERE ws.id = ?
        ''', (submission_id,)).fetchone()
        
        if not submission:
            return jsonify({'success': False, 'error': 'Submission not found'}), 404
        
        return jsonify({
            'success': True,
            'submission': dict(submission)
        })
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ GET SUBMISSION ERROR: {str(e)}")
        print(error_trace)
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/submission/<int:submission_id>/edit', methods=['POST'])
@admin_required
def edit_submission(submission_id):
    """Edit a submission and recalculate PO counts (Admin and Manager only)"""
    # Allow managers to edit submissions (especially admin notes)
    if not (session.get('admin_authenticated') or 
            (session.get('employee_authenticated') and session.get('employee_role') in ['admin', 'manager'])):
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    conn = None
    try:
        data = request.get_json()
        conn = get_db()
        
        # Get the submission's current PO assignment
        submission = conn.execute('''
            SELECT assigned_po_id, product_name, displays_made, packs_remaining, 
                   loose_tablets, damaged_tablets, inventory_item_id
            FROM warehouse_submissions
            WHERE id = ?
        ''', (submission_id,)).fetchone()
        
        if not submission:
            return jsonify({'success': False, 'error': 'Submission not found'}), 404
        
        old_po_id = submission['assigned_po_id']
        inventory_item_id = submission['inventory_item_id']
        
        # Get product details for calculations
        product = conn.execute('''
            SELECT pd.packages_per_display, pd.tablets_per_package
            FROM product_details pd
            JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            WHERE pd.product_name = ?
        ''', (submission['product_name'],)).fetchone()
        
        if not product:
            return jsonify({'success': False, 'error': 'Product configuration not found'}), 400
        
        # Convert Row to dict for safe access
        product = dict(product)
        
        # Validate product configuration values
        packages_per_display = product.get('packages_per_display')
        tablets_per_package = product.get('tablets_per_package')
        
        if packages_per_display is None or tablets_per_package is None or packages_per_display == 0 or tablets_per_package == 0:
            return jsonify({'success': False, 'error': 'Product configuration incomplete: packages_per_display and tablets_per_package are required and must be greater than 0'}), 400
        
        # Convert to int after validation
        try:
            packages_per_display = int(packages_per_display)
            tablets_per_package = int(tablets_per_package)
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid numeric values for product configuration'}), 400
        
        # Calculate old totals to subtract
        old_good = (submission['displays_made'] * packages_per_display * tablets_per_package +
                   submission['packs_remaining'] * tablets_per_package +
                   submission['loose_tablets'])
        old_damaged = submission['damaged_tablets']
        
        # Validate and convert input data
        try:
            displays_made = int(data.get('displays_made', 0) or 0)
            packs_remaining = int(data.get('packs_remaining', 0) or 0)
            loose_tablets = int(data.get('loose_tablets', 0) or 0)
            damaged_tablets = int(data.get('damaged_tablets', 0) or 0)
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid numeric values for counts'}), 400
        
        # Calculate new totals
        new_good = (displays_made * packages_per_display * tablets_per_package +
                   packs_remaining * tablets_per_package +
                   loose_tablets)
        new_damaged = damaged_tablets
        
        # Update the submission
        submission_date = data.get('submission_date', datetime.now().date().isoformat())
        conn.execute('''
            UPDATE warehouse_submissions
            SET displays_made = ?, packs_remaining = ?, loose_tablets = ?, 
                damaged_tablets = ?, box_number = ?, bag_number = ?, bag_label_count = ?,
                submission_date = ?, admin_notes = ?
            WHERE id = ?
        ''', (displays_made, packs_remaining, loose_tablets,
              damaged_tablets, data.get('box_number'), data.get('bag_number'),
              data.get('bag_label_count'), submission_date, data.get('admin_notes'), submission_id))
        
        # Update PO line counts if assigned to a PO
        if old_po_id and inventory_item_id:
            # Find the PO line
            po_line = conn.execute('''
                SELECT id FROM po_lines
                WHERE po_id = ? AND inventory_item_id = ?
                LIMIT 1
            ''', (old_po_id, inventory_item_id)).fetchone()
            
            if po_line:
                # Calculate the difference and update
                good_diff = new_good - old_good
                damaged_diff = new_damaged - old_damaged
                
                conn.execute('''
                    UPDATE po_lines
                    SET good_count = good_count + ?, damaged_count = damaged_count + ?
                    WHERE id = ?
                ''', (good_diff, damaged_diff, po_line['id']))
                
                # Update PO header totals
                totals = conn.execute('''
                    SELECT 
                        COALESCE(SUM(quantity_ordered), 0) as total_ordered,
                        COALESCE(SUM(good_count), 0) as total_good,
                        COALESCE(SUM(damaged_count), 0) as total_damaged
                    FROM po_lines 
                    WHERE po_id = ?
                ''', (old_po_id,)).fetchone()
                
                remaining = totals['total_ordered'] - totals['total_good'] - totals['total_damaged']
                conn.execute('''
                    UPDATE purchase_orders 
                    SET ordered_quantity = ?, current_good_count = ?, 
                        current_damaged_count = ?, remaining_quantity = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (totals['total_ordered'], totals['total_good'], 
                      totals['total_damaged'], remaining, old_po_id))
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': 'Submission updated successfully'
        })
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ EDIT SUBMISSION ERROR: {str(e)}")
        print(error_trace)
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/submission/<int:submission_id>/delete', methods=['POST'])
@admin_required
def delete_submission_admin(submission_id):
    """Delete a submission and remove its counts from PO (Admin only)"""
    conn = None
    try:
        conn = get_db()
        
        # Get the submission details
        submission = conn.execute('''
            SELECT assigned_po_id, product_name, displays_made, packs_remaining, 
                   loose_tablets, damaged_tablets, inventory_item_id
            FROM warehouse_submissions
            WHERE id = ?
        ''', (submission_id,)).fetchone()
        
        if not submission:
            return jsonify({'success': False, 'error': 'Submission not found'}), 404
        
        old_po_id = submission['assigned_po_id']
        inventory_item_id = submission['inventory_item_id']
        
        # Get product details for calculations
        product = conn.execute('''
            SELECT pd.packages_per_display, pd.tablets_per_package
            FROM product_details pd
            JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            WHERE pd.product_name = ?
        ''', (submission['product_name'],)).fetchone()
        
        if not product:
            return jsonify({'success': False, 'error': 'Product configuration not found'}), 400
        
        # Calculate counts to remove
        good_tablets = (submission['displays_made'] * product['packages_per_display'] * product['tablets_per_package'] +
                       submission['packs_remaining'] * product['tablets_per_package'] +
                       submission['loose_tablets'])
        damaged_tablets = submission['damaged_tablets']
        
        # Remove counts from PO line if assigned
        if old_po_id and inventory_item_id:
            # Find the PO line
            po_line = conn.execute('''
                SELECT id FROM po_lines
                WHERE po_id = ? AND inventory_item_id = ?
                LIMIT 1
            ''', (old_po_id, inventory_item_id)).fetchone()
            
            if po_line:
                # Get current counts first to calculate new values
                current_line = conn.execute('''
                    SELECT good_count, damaged_count FROM po_lines WHERE id = ?
                ''', (po_line['id'],)).fetchone()
                
                new_good = max(0, (current_line['good_count'] or 0) - good_tablets)
                new_damaged = max(0, (current_line['damaged_count'] or 0) - damaged_tablets)
                
                # Remove counts from PO line
                conn.execute('''
                    UPDATE po_lines
                    SET good_count = ?, 
                        damaged_count = ?
                    WHERE id = ?
                ''', (new_good, new_damaged, po_line['id']))
                
                # Update PO header totals
                totals = conn.execute('''
                    SELECT 
                        COALESCE(SUM(quantity_ordered), 0) as total_ordered,
                        COALESCE(SUM(good_count), 0) as total_good,
                        COALESCE(SUM(damaged_count), 0) as total_damaged
                    FROM po_lines 
                    WHERE po_id = ?
                ''', (old_po_id,)).fetchone()
                
                remaining = totals['total_ordered'] - totals['total_good'] - totals['total_damaged']
                conn.execute('''
                    UPDATE purchase_orders 
                    SET ordered_quantity = ?, current_good_count = ?, 
                        current_damaged_count = ?, remaining_quantity = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (totals['total_ordered'], totals['total_good'], 
                      totals['total_damaged'], remaining, old_po_id))
        
        # Delete the submission
        conn.execute('DELETE FROM warehouse_submissions WHERE id = ?', (submission_id,))
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': 'Submission deleted successfully'
        })
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ DELETE SUBMISSION ERROR: {str(e)}")
        print(error_trace)
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/submission/<int:submission_id>/possible-receives', methods=['GET'])
@role_required('dashboard')
def get_possible_receives(submission_id):
    """Get all possible receives that match a submission's flavor, box, bag"""
    conn = None
    try:
        conn = get_db()
        
        # Get submission details
        submission = conn.execute('''
            SELECT ws.*, tt.id as tablet_type_id, tt.tablet_type_name
            FROM warehouse_submissions ws
            LEFT JOIN tablet_types tt ON ws.inventory_item_id = tt.inventory_item_id
            WHERE ws.id = ?
        ''', (submission_id,)).fetchone()
        
        if not submission:
            return jsonify({'success': False, 'error': 'Submission not found'}), 404
        
        # Debug logging
        print(f"🔍 Finding possible receives for submission {submission_id}")
        print(f"   tablet_type_id: {submission['tablet_type_id']}")
        print(f"   box_number: {submission['box_number']}")
        print(f"   bag_number: {submission['bag_number']}")
        print(f"   inventory_item_id: {submission['inventory_item_id']}")
        
        # Find all matching bags (flavor + box + bag)
        # Must match the exact same logic as find_bag_for_submission
        matching_bags = conn.execute('''
            SELECT b.id as bag_id, 
                   sb.box_number, 
                   b.bag_number, 
                   b.bag_label_count,
                   r.id as receive_id,
                   r.received_date,
                   po.po_number,
                   po.id as po_id,
                   tt.tablet_type_name
            FROM bags b
            JOIN small_boxes sb ON b.small_box_id = sb.id
            JOIN receiving r ON sb.receiving_id = r.id
            JOIN purchase_orders po ON r.po_id = po.id
            JOIN tablet_types tt ON b.tablet_type_id = tt.id
            WHERE b.tablet_type_id = ? 
            AND sb.box_number = ? 
            AND b.bag_number = ?
            ORDER BY r.received_date DESC
        ''', (submission['tablet_type_id'], submission['box_number'], submission['bag_number'])).fetchall()
        
        print(f"   Found {len(matching_bags)} matching bags")
        
        # Calculate receive_number for each
        receives = []
        for bag in matching_bags:
            # Calculate which receive # this is for the PO
            receive_number = conn.execute('''
                SELECT COUNT(*) + 1
                FROM receiving r2
                WHERE r2.po_id = ?
                AND (r2.received_date < (SELECT received_date FROM receiving WHERE id = ?)
                     OR (r2.received_date = (SELECT received_date FROM receiving WHERE id = ?) 
                         AND r2.id < ?))
            ''', (bag['po_id'], bag['receive_id'], bag['receive_id'], bag['receive_id'])).fetchone()[0]
            
            receives.append({
                'bag_id': bag['bag_id'],
                'receive_id': bag['receive_id'],
                'receive_name': f"{bag['po_number']}-{receive_number}",
                'po_number': bag['po_number'],
                'received_date': bag['received_date'],
                'box_number': bag['box_number'],
                'bag_number': bag['bag_number'],
                'bag_label_count': bag['bag_label_count'],
                'tablet_type_name': bag['tablet_type_name']
            })
        
        return jsonify({
            'success': True,
            'submission': dict(submission),
            'possible_receives': receives
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/submission/<int:submission_id>/assign-receive', methods=['POST'])
@role_required('dashboard')
def assign_submission_to_receive(submission_id):
    """Assign a submission to a specific receive bag"""
    conn = None
    try:
        conn = get_db()
        data = request.get_json()
        bag_id = data.get('bag_id')
        
        if not bag_id:
            return jsonify({'success': False, 'error': 'bag_id is required'}), 400
        
        # Get bag details
        bag = conn.execute('''
            SELECT b.*, r.po_id
            FROM bags b
            JOIN small_boxes sb ON b.small_box_id = sb.id
            JOIN receiving r ON sb.receiving_id = r.id
            WHERE b.id = ?
        ''', (bag_id,)).fetchone()
        
        if not bag:
            return jsonify({'success': False, 'error': 'Bag not found'}), 404
        
        # Update submission
        conn.execute('''
            UPDATE warehouse_submissions
            SET bag_id = ?, assigned_po_id = ?, needs_review = FALSE
            WHERE id = ?
        ''', (bag_id, bag['po_id'], submission_id))
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': 'Submission assigned successfully'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/po/<int:po_id>/delete', methods=['POST'])
@admin_required
def delete_po(po_id):
    """Delete a PO and all its related data (Admin only)"""
    conn = None
    try:
        conn = get_db()
        
        # Get PO details first
        po = conn.execute('SELECT po_number FROM purchase_orders WHERE id = ?', (po_id,)).fetchone()
        
        if not po:
            return jsonify({'success': False, 'error': 'PO not found'}), 404
        
        # Delete related data
        # 1. Unassign all submissions (don't delete submissions, just unassign them)
        conn.execute('UPDATE warehouse_submissions SET assigned_po_id = NULL WHERE assigned_po_id = ?', (po_id,))
        
        # 2. Delete shipments
        conn.execute('DELETE FROM shipments WHERE po_id = ?', (po_id,))
        
        # 3. Delete PO lines
        conn.execute('DELETE FROM po_lines WHERE po_id = ?', (po_id,))
        
        # 4. Delete the PO itself
        conn.execute('DELETE FROM purchase_orders WHERE id = ?', (po_id,))
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': f'Successfully deleted {po["po_number"]} and all related data'
        })
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ DELETE PO ERROR: {str(e)}")
        print(error_trace)
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/resync_unassigned_submissions', methods=['POST'])
@admin_required
def resync_unassigned_submissions():
    """Resync unassigned submissions to try matching them with POs based on updated item IDs"""
    conn = None
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
            # Note: We do NOT filter by available quantity - POs can receive more than ordered
            po_lines_rows = conn.execute('''
                SELECT pl.*, po.closed
                FROM po_lines pl
                JOIN purchase_orders po ON pl.po_id = po.id
                WHERE pl.inventory_item_id = ? AND po.closed = FALSE
                AND COALESCE(po.internal_status, '') != 'Draft'
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
            # Note: We do NOT cap at ordered quantity - actual production may exceed the PO
            line = po_lines[0]
            
            # Apply all counts to the first line
            conn.execute('''
                UPDATE po_lines 
                SET good_count = good_count + ?, damaged_count = damaged_count + ?
                WHERE id = ?
            ''', (good_tablets, damaged_tablets, line['id']))
            
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
        if conn:
            try:
                conn.close()
            except:
                pass
        return jsonify({'error': str(e), 'trace': error_trace}), 500

@app.route('/api/po/<int:po_id>/receives', methods=['GET'])
@role_required('dashboard')
def get_po_receives(po_id):
    """Get all receives (shipments received) for a specific PO"""
    conn = None
    try:
        conn = get_db()
        
        # Get PO details
        po = conn.execute('''
            SELECT po_number
            FROM purchase_orders
            WHERE id = ?
        ''', (po_id,)).fetchone()
        
        if not po:
            return jsonify({'error': 'PO not found'}), 404
        
        # Get all receiving records for this PO with their boxes and bags
        receiving_records = conn.execute('''
            SELECT r.*, 
                   COUNT(DISTINCT sb.id) as box_count,
                   COUNT(DISTINCT b.id) as total_bags
            FROM receiving r
            LEFT JOIN small_boxes sb ON r.id = sb.receiving_id
            LEFT JOIN bags b ON sb.id = b.small_box_id
            WHERE r.po_id = ?
            GROUP BY r.id
            ORDER BY r.received_date DESC
        ''', (po_id,)).fetchall()
        
        # For each receiving record, get its boxes and bags
        receives = []
        for rec in receiving_records:
            boxes = conn.execute('''
                SELECT sb.*, COUNT(b.id) as bag_count
                FROM small_boxes sb
                LEFT JOIN bags b ON sb.id = b.small_box_id
                WHERE sb.receiving_id = ?
                GROUP BY sb.id
                ORDER BY sb.box_number
            ''', (rec['id'],)).fetchall()
            
            # Get bags for each box with tablet type info
            boxes_with_bags = []
            for box in boxes:
                bags = conn.execute('''
                    SELECT b.*, tt.tablet_type_name
                    FROM bags b
                    LEFT JOIN tablet_types tt ON b.tablet_type_id = tt.id
                    WHERE b.small_box_id = ?
                    ORDER BY b.bag_number
                ''', (box['id'],)).fetchall()
                boxes_with_bags.append({
                    'box': dict(box),
                    'bags': [dict(bag) for bag in bags]
                })
            
            receives.append({
                'receiving': dict(rec),
                'boxes': boxes_with_bags
            })
        
        return jsonify({
            'success': True,
            'po': dict(po),
            'receives': receives
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/receive/<int:receive_id>/details', methods=['GET'])
@role_required('shipping')
def get_receive_details(receive_id):
    """Get receive details with submission counts (similar to PO details modal)"""
    conn = None
    try:
        conn = get_db()
        
        # Get receive details with PO info
        receive = conn.execute('''
            SELECT r.*, po.po_number, po.id as po_id
            FROM receiving r
            LEFT JOIN purchase_orders po ON r.po_id = po.id
            WHERE r.id = ?
        ''', (receive_id,)).fetchone()
        
        if not receive:
            return jsonify({'error': 'Receive not found'}), 404
        
        receive_dict = dict(receive)
        
        # Get all bags in this receive with their counts and tablet types
        bags = conn.execute('''
            SELECT b.*, tt.tablet_type_name, tt.inventory_item_id, sb.box_number
            FROM bags b
            JOIN small_boxes sb ON b.small_box_id = sb.id
            JOIN tablet_types tt ON b.tablet_type_id = tt.id
            WHERE sb.receiving_id = ?
            ORDER BY sb.box_number, b.bag_number
        ''', (receive_id,)).fetchall()
        
        # Group by product -> box -> bag
        products = {}
        for bag in bags:
            inventory_item_id = bag['inventory_item_id']
            tablet_type_name = bag['tablet_type_name']
            box_number = bag['box_number']
            bag_number = bag['bag_number']
            bag_label_count = bag['bag_label_count'] or 0
            
            if inventory_item_id not in products:
                products[inventory_item_id] = {
                    'tablet_type_name': tablet_type_name,
                    'inventory_item_id': inventory_item_id,
                    'boxes': {}
                }
            
            if box_number not in products[inventory_item_id]['boxes']:
                products[inventory_item_id]['boxes'][box_number] = {}
            
            # Get submission counts for this specific bag
            # Match by bag_id first (most accurate), fall back to box/bag/po for older submissions
            machine_count = conn.execute('''
                SELECT COALESCE(SUM(
                    (COALESCE(ws.displays_made, 0) * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0)) +
                    (COALESCE(ws.packs_remaining, 0) * COALESCE(pd.tablets_per_package, 0)) +
                    COALESCE(ws.loose_tablets, 0)
                ), 0) as total_machine
                FROM warehouse_submissions ws
                LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                WHERE ws.submission_type = 'machine'
                AND (
                    ws.bag_id = ?
                    OR (
                        ws.bag_id IS NULL
                        AND ws.inventory_item_id = ?
                        AND ws.box_number = ?
                        AND ws.bag_number = ?
                        AND ws.assigned_po_id = ?
                    )
                )
            ''', (bag['id'], inventory_item_id, box_number, bag_number, receive_dict['po_id'])).fetchone()
            
            packaged_count = conn.execute('''
                SELECT COALESCE(SUM(
                    (COALESCE(ws.displays_made, 0) * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0)) +
                    (COALESCE(ws.packs_remaining, 0) * COALESCE(pd.tablets_per_package, 0)) +
                    COALESCE(ws.loose_tablets, 0)
                ), 0) as total_packaged
                FROM warehouse_submissions ws
                LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                WHERE ws.submission_type IN ('packaged', 'bag')
                AND (
                    ws.bag_id = ?
                    OR (
                        ws.bag_id IS NULL
                        AND ws.inventory_item_id = ?
                        AND ws.box_number = ?
                        AND ws.bag_number = ?
                        AND ws.assigned_po_id = ?
                    )
                )
            ''', (bag['id'], inventory_item_id, box_number, bag_number, receive_dict['po_id'])).fetchone()
            
            products[inventory_item_id]['boxes'][box_number][bag_number] = {
                'bag_id': bag['id'],
                'received_count': bag_label_count,
                'machine_count': machine_count['total_machine'] if machine_count else 0,
                'packaged_count': packaged_count['total_packaged'] if packaged_count else 0
            }
        
        # Convert nested dict to list format for easier frontend handling
        products_list = []
        for inventory_item_id, product_data in products.items():
            product_entry = {
                'tablet_type_name': product_data['tablet_type_name'],
                'inventory_item_id': inventory_item_id,
                'boxes': []
            }
            for box_number, bags_in_box in sorted(product_data['boxes'].items()):
                box_entry = {
                    'box_number': box_number,
                    'bags': []
                }
                for bag_number, bag_data in sorted(bags_in_box.items()):
                    box_entry['bags'].append({
                        'bag_number': bag_number,
                        **bag_data
                    })
                product_entry['boxes'].append(box_entry)
            products_list.append(product_entry)
        
        return jsonify({
            'success': True,
            'receive': receive_dict,
            'products': products_list
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@app.route('/api/po/<int:po_id>/submissions', methods=['GET'])
@role_required('dashboard')
def get_po_submissions(po_id):
    """Get all submissions assigned to a specific PO"""
    conn = None
    try:
        conn = get_db()
        
        # Get PO details including machine counts and closed status
        po = conn.execute('''
            SELECT po_number, tablet_type, ordered_quantity, 
                   current_good_count, current_damaged_count, remaining_quantity,
                   machine_good_count, machine_damaged_count,
                   parent_po_number, closed
            FROM purchase_orders
            WHERE id = ?
        ''', (po_id,)).fetchone()
        
        if not po:
            return jsonify({'error': 'PO not found'}), 404
        
        # Check if submission_date and submission_type columns exist
        has_submission_date = False
        has_submission_type = False
        try:
            conn.execute('SELECT submission_date FROM warehouse_submissions LIMIT 1')
            has_submission_date = True
        except:
            pass
        try:
            conn.execute('SELECT submission_type FROM warehouse_submissions LIMIT 1')
            has_submission_type = True
        except:
            pass
        
        # For PO-specific views, show ALL submissions for auditing purposes
        
        # Determine which PO IDs to query:
        # 1. If this is a parent PO, also include submissions from related OVERS POs
        # 2. If this is an OVERS PO, also include submissions from the parent PO
        po_ids_to_query = [po_id]
        po_number = po['po_number']
        
        # Check if this is a parent PO - find related OVERS POs
        overs_pos = conn.execute('''
            SELECT id FROM purchase_orders 
            WHERE parent_po_number = ?
        ''', (po_number,)).fetchall()
        for overs_po in overs_pos:
            po_ids_to_query.append(overs_po['id'])
        
        # Check if this is an OVERS PO - find parent PO
        if po['parent_po_number']:
            parent_po = conn.execute('''
                SELECT id FROM purchase_orders 
                WHERE po_number = ?
            ''', (po['parent_po_number'],)).fetchone()
            if parent_po and parent_po['id'] not in po_ids_to_query:
                po_ids_to_query.append(parent_po['id'])
        
        # Build WHERE clause for multiple PO IDs
        po_ids_placeholders = ','.join(['?'] * len(po_ids_to_query))
        
        # Get all submissions for this PO (and related OVERS/parent POs) with product details
        # Include inventory_item_id for matching with PO line items
        submission_type_select = ', ws.submission_type' if has_submission_type else ", 'packaged' as submission_type"
        po_verified_select = ', COALESCE(ws.po_assignment_verified, 0) as po_verified' if has_submission_type else ", 0 as po_verified"
        if has_submission_date:
            submissions_query = f'''
                SELECT 
                    ws.id,
                    ws.product_name,
                    ws.employee_name,
                    ws.displays_made,
                    ws.packs_remaining,
                    ws.loose_tablets,
                    ws.damaged_tablets,
                    ws.created_at,
                    ws.submission_date,
                    ws.box_number,
                    ws.bag_number,
                    ws.bag_id,
                    ws.bag_label_count,
                    ws.admin_notes,
                    pd.packages_per_display,
                    pd.tablets_per_package,
                    tt.inventory_item_id,
                    ws.assigned_po_id,
                    po.po_number,
                    po.closed as po_closed
                    {submission_type_select}
                    {po_verified_select}
                FROM warehouse_submissions ws
                LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
                WHERE ws.assigned_po_id IN ({po_ids_placeholders})
                ORDER BY ws.created_at ASC
            '''
        else:
            submissions_query = f'''
                SELECT 
                    ws.id,
                    ws.product_name,
                    ws.employee_name,
                    ws.displays_made,
                    ws.packs_remaining,
                    ws.loose_tablets,
                    ws.damaged_tablets,
                    ws.created_at,
                    ws.created_at as submission_date,
                    ws.box_number,
                    ws.bag_number,
                    ws.bag_id,
                    ws.bag_label_count,
                    ws.admin_notes,
                    pd.packages_per_display,
                    pd.tablets_per_package,
                    tt.inventory_item_id,
                    ws.assigned_po_id,
                    po.po_number,
                    po.closed as po_closed
                    {submission_type_select}
                    {po_verified_select}
                FROM warehouse_submissions ws
                LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
                WHERE ws.assigned_po_id IN ({po_ids_placeholders})
                ORDER BY ws.created_at ASC
            '''
        
        submissions_raw = conn.execute(submissions_query, tuple(po_ids_to_query)).fetchall()
        print(f"🔍 get_po_submissions: Found {len(submissions_raw)} submissions for PO {po_id} ({po_number}) including related POs: {po_ids_to_query}")
        
        # Calculate total tablets and running bag totals for each submission
        # Also calculate separate totals for machine vs packaged+bag counts
        bag_running_totals = {}
        submissions = []
        machine_total = 0
        packaged_bag_total = 0
        
        for sub in submissions_raw:
            sub_dict = dict(sub)
            submission_type = sub_dict.get('submission_type', 'packaged')
            
            # Calculate total tablets for this submission
            displays_tablets = (sub_dict.get('displays_made', 0) or 0) * (sub_dict.get('packages_per_display', 0) or 0) * (sub_dict.get('tablets_per_package', 0) or 0)
            package_tablets = (sub_dict.get('packs_remaining', 0) or 0) * (sub_dict.get('tablets_per_package', 0) or 0)
            loose_tablets = sub_dict.get('loose_tablets', 0) or 0
            damaged_tablets = sub_dict.get('damaged_tablets', 0) or 0
            total_tablets = displays_tablets + package_tablets + loose_tablets + damaged_tablets
            sub_dict['total_tablets'] = total_tablets
            
            # Track totals separately by submission type
            if submission_type == 'machine':
                machine_total += total_tablets
            else:  # 'packaged' or 'bag'
                packaged_bag_total += total_tablets
            
            # Calculate running total by bag PER PO (only for packaged/bag submissions)
            if submission_type != 'machine':
                bag_identifier = f"{sub_dict.get('box_number', '')}/{sub_dict.get('bag_number', '')}"
                # Key includes PO ID so each PO tracks its own bag totals independently
                bag_key = (po_id, sub_dict.get('product_name', ''), bag_identifier)
                if bag_key not in bag_running_totals:
                    bag_running_totals[bag_key] = 0
                bag_running_totals[bag_key] += total_tablets
                sub_dict['running_total'] = bag_running_totals[bag_key]
                
                # Determine count status (only for packaged/bag submissions)
                bag_count = sub_dict.get('bag_label_count', 0) or 0
                if bag_count == 0:
                    sub_dict['count_status'] = 'no_bag'
                elif abs(bag_running_totals[bag_key] - bag_count) <= 5:
                    sub_dict['count_status'] = 'match'
                elif bag_running_totals[bag_key] < bag_count:
                    sub_dict['count_status'] = 'under'
                else:
                    sub_dict['count_status'] = 'over'
            else:
                # Machine counts don't have bag running totals
                sub_dict['running_total'] = total_tablets
                sub_dict['count_status'] = None
            
            submissions.append(sub_dict)
        
        # Reverse to show newest first in modal
        submissions.reverse()
        
        return jsonify({
            'success': True,
            'po': dict(po),
            'submissions': submissions,
            'count': len(submissions),
            'totals': {
                'machine': machine_total,
                'packaged_bag': packaged_bag_total,
                'total': machine_total + packaged_bag_total
            }
        })
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ Error fetching PO submissions: {str(e)}")
        print(error_trace)
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

# ===== TEMPLATE CONTEXT PROCESSORS =====

@app.template_filter('to_est')
def to_est_filter(dt_string):
    """Convert UTC datetime string to Eastern Time (EST/EDT)"""
    if not dt_string:
        return 'N/A'
    try:
        # Parse the datetime string (assumes UTC)
        if isinstance(dt_string, str):
            # Handle date-only strings (YYYY-MM-DD)
            if re.match(r'^\d{4}-\d{2}-\d{2}$', dt_string):
                return dt_string  # Return date-only as-is
            
            # Handle different datetime formats
            if '.' in dt_string:
                dt = datetime.strptime(dt_string.split('.')[0], '%Y-%m-%d %H:%M:%S')
            else:
                dt = datetime.strptime(dt_string, '%Y-%m-%d %H:%M:%S')
            # Assume UTC if no timezone info in string
            utc_dt = dt.replace(tzinfo=ZoneInfo('UTC'))
        else:
            # Already a datetime object
            dt = dt_string
            if dt.tzinfo is None:
                # Naive datetime - assume UTC (from database)
                utc_dt = dt.replace(tzinfo=ZoneInfo('UTC'))
            else:
                # Already has timezone - convert to UTC first if needed
                utc_dt = dt.astimezone(ZoneInfo('UTC'))
        
        # Convert from UTC to Eastern
        est_dt = utc_dt.astimezone(ZoneInfo('America/New_York'))
        
        # Format as YYYY-MM-DD HH:MM:SS
        return est_dt.strftime('%Y-%m-%d %H:%M:%S')
    except Exception as e:
        print(f"Error converting datetime to EST: {e}")
        return dt_string if isinstance(dt_string, str) else 'N/A'

@app.template_filter('to_est_time')
def to_est_time_filter(dt_string):
    """Convert UTC datetime string to Eastern Time, showing only time portion"""
    if not dt_string:
        return 'N/A'
    try:
        # Parse the datetime string (assumes UTC)
        if isinstance(dt_string, str):
            # Handle date-only strings (YYYY-MM-DD) - return N/A for time-only display
            if re.match(r'^\d{4}-\d{2}-\d{2}$', dt_string):
                return 'N/A'  # No time component for date-only strings
            
            # Handle different datetime formats
            if '.' in dt_string:
                dt = datetime.strptime(dt_string.split('.')[0], '%Y-%m-%d %H:%M:%S')
            else:
                dt = datetime.strptime(dt_string, '%Y-%m-%d %H:%M:%S')
            # Assume UTC if no timezone info in string
            utc_dt = dt.replace(tzinfo=ZoneInfo('UTC'))
        else:
            # Already a datetime object
            dt = dt_string
            if dt.tzinfo is None:
                # Naive datetime - assume UTC (from database)
                utc_dt = dt.replace(tzinfo=ZoneInfo('UTC'))
            else:
                # Already has timezone - convert to UTC first if needed
                utc_dt = dt.astimezone(ZoneInfo('UTC'))
        
        # Convert from UTC to Eastern
        est_dt = utc_dt.astimezone(ZoneInfo('America/New_York'))
        
        # Format as HH:MM:SS
        return est_dt.strftime('%H:%M:%S')
    except Exception as e:
        print(f"Error converting datetime to EST: {e}")
        if isinstance(dt_string, str):
            # Fallback: try to extract time portion
            parts = dt_string.split(' ')
            if len(parts) > 1:
                return parts[1].split('.')[0] if '.' in parts[1] else parts[1]
        return 'N/A'

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
