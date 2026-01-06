#!/usr/bin/env python3
"""
Check if Spearmint (or any product) has inventory_item_id configured.
Run this to diagnose the inventory_item_id error.
"""

import sqlite3
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config

def check_product_config(product_name=None):
    """Check product configuration for inventory_item_id"""
    
    db_path = Config.DATABASE_PATH
    print(f"📊 Connecting to database: {db_path}\n")
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        if product_name:
            # Check specific product
            print(f"🔍 Checking configuration for: {product_name}\n")
            
            product = cursor.execute('''
                SELECT pd.*, tt.inventory_item_id, tt.tablet_type_name, tt.id as tablet_type_id
                FROM product_details pd
                JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                WHERE pd.product_name = ?
            ''', (product_name,)).fetchone()
            
            if not product:
                print(f"❌ Product '{product_name}' not found in product_details table")
                return False
            
            print(f"✅ Product found:")
            print(f"   Product Name: {product['product_name']}")
            print(f"   Tablet Type: {product['tablet_type_name']}")
            print(f"   Tablet Type ID: {product['tablet_type_id']}")
            print(f"   Inventory Item ID: {product['inventory_item_id'] or '❌ MISSING'}")
            print(f"   Packages per Display: {product.get('packages_per_display', 'N/A')}")
            print(f"   Tablets per Package: {product.get('tablets_per_package', 'N/A')}")
            
            if not product['inventory_item_id']:
                print(f"\n⚠️  PROBLEM: {product_name} is missing inventory_item_id!")
                print(f"   This needs to be set in the tablet_types table.")
                print(f"   Tablet Type: {product['tablet_type_name']} (ID: {product['tablet_type_id']})")
                return False
            else:
                print(f"\n✅ {product_name} is properly configured!")
                return True
        else:
            # List all products and their inventory_item_id status
            print("📋 All Products Configuration:\n")
            
            products = cursor.execute('''
                SELECT pd.product_name, tt.tablet_type_name, tt.inventory_item_id, 
                       pd.packages_per_display, pd.tablets_per_package
                FROM product_details pd
                JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                ORDER BY pd.product_name
            ''').fetchall()
            
            missing = []
            configured = []
            
            for product in products:
                if not product['inventory_item_id']:
                    missing.append(product)
                else:
                    configured.append(product)
            
            print(f"✅ Configured ({len(configured)}):")
            for p in configured:
                print(f"   {p['product_name']:30} -> {p['inventory_item_id']}")
            
            if missing:
                print(f"\n❌ Missing inventory_item_id ({len(missing)}):")
                for p in missing:
                    print(f"   {p['product_name']:30} (Tablet Type: {p['tablet_type_name']})")
                print(f"\n⚠️  These products will fail when submitting!")
            
            return len(missing) == 0
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        conn.close()

if __name__ == '__main__':
    import sys
    product_name = sys.argv[1] if len(sys.argv) > 1 else None
    check_product_config(product_name)

