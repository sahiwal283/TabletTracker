#!/usr/bin/env python3
"""
Deployment verification script for PythonAnywhere
Run this script to verify the deployment setup and run migrations
"""
import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def check_deployment():
    """Check deployment setup and run migrations"""
    print("=" * 70)
    print("TabletTracker Deployment Verification")
    print("=" * 70)
    print()
    
    # Check 1: Verify app package structure
    print("1. Checking app package structure...")
    try:
        from app import create_app
        print("   ✅ app.create_app() imported successfully")
    except ImportError as e:
        print(f"   ❌ Failed to import create_app: {e}")
        return False
    except Exception as e:
        print(f"   ❌ Unexpected error importing create_app: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Check 2: Verify database initialization
    print("\n2. Checking database initialization...")
    try:
        from app.models.database import init_db
        print("   ✅ init_db() imported successfully")
        
        # Try to run init_db
        print("   🔄 Running database initialization...")
        init_db()
        print("   ✅ Database initialization completed successfully")
    except Exception as e:
        print(f"   ❌ Database initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Check 3: Verify Flask app creation
    print("\n3. Checking Flask app creation...")
    try:
        app = create_app()
        print("   ✅ Flask app created successfully")
        print(f"   ✅ App name: {app.name}")
        print(f"   ✅ Registered blueprints: {len(app.blueprints)}")
        for bp_name in app.blueprints.keys():
            print(f"      - {bp_name}")
    except Exception as e:
        print(f"   ❌ Failed to create Flask app: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Check 4: Verify database tables exist
    print("\n4. Checking database tables...")
    try:
        from app.utils.db_utils import get_db
        conn = get_db()
        cursor = conn.cursor()
        
        required_tables = [
            'purchase_orders', 'po_lines', 'tablet_types', 'product_details',
            'warehouse_submissions', 'shipments', 'receiving', 'small_boxes',
            'bags', 'machine_counts', 'employees', 'app_settings',
            'tablet_type_categories', 'roles'
        ]
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing_tables = [row[0] for row in cursor.fetchall()]
        
        missing_tables = []
        for table in required_tables:
            if table in existing_tables:
                print(f"   ✅ Table '{table}' exists")
            else:
                print(f"   ❌ Table '{table}' is missing")
                missing_tables.append(table)
        
        conn.close()
        
        if missing_tables:
            print(f"\n   ⚠️  Missing tables: {', '.join(missing_tables)}")
            print("   🔄 Re-running database initialization...")
            init_db()
            print("   ✅ Re-initialization complete")
        else:
            print("\n   ✅ All required tables exist")
            
    except Exception as e:
        print(f"   ❌ Error checking database tables: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print("\n" + "=" * 70)
    print("✅ Deployment verification completed successfully!")
    print("=" * 70)
    print("\nNext steps:")
    print("1. Ensure WSGI file is configured correctly (see DEPLOYMENT.md)")
    print("2. Reload the web app in PythonAnywhere dashboard")
    print("3. Test the application at your domain")
    
    return True

if __name__ == '__main__':
    success = check_deployment()
    sys.exit(0 if success else 1)

