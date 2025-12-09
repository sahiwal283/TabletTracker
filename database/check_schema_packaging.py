#!/usr/bin/env python3
"""
Check schema for tablet_types and product_details to find packaging information
"""
import sqlite3

def check_schema():
    conn = sqlite3.connect('tablet_counter.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("=" * 80)
    print("DATABASE SCHEMA CHECK - PACKAGING INFORMATION")
    print("=" * 80)
    print()
    
    # Check tablet_types schema
    print("TABLET_TYPES TABLE SCHEMA:")
    print("-" * 80)
    cursor.execute("PRAGMA table_info(tablet_types)")
    tt_cols = cursor.fetchall()
    
    for col in tt_cols:
        print(f"  • {col['name']:<30} {col['type']:<15} {'NOT NULL' if col['notnull'] else ''}")
    
    print()
    
    # Check if packaging columns exist in tablet_types
    tt_col_names = [col['name'] for col in tt_cols]
    print("PACKAGING COLUMNS IN tablet_types:")
    for col in ['tablets_per_package', 'packages_per_display']:
        status = "✓ EXISTS" if col in tt_col_names else "✗ MISSING"
        print(f"  {status}: {col}")
    
    print()
    print("=" * 80)
    print()
    
    # Check product_details schema
    print("PRODUCT_DETAILS TABLE SCHEMA:")
    print("-" * 80)
    cursor.execute("PRAGMA table_info(product_details)")
    pd_cols = cursor.fetchall()
    
    for col in pd_cols:
        print(f"  • {col['name']:<30} {col['type']:<15} {'NOT NULL' if col['notnull'] else ''}")
    
    print()
    
    # Check if packaging columns exist in product_details
    pd_col_names = [col['name'] for col in pd_cols]
    print("PACKAGING COLUMNS IN product_details:")
    for col in ['tablets_per_package', 'packages_per_display']:
        status = "✓ EXISTS" if col in pd_col_names else "✗ MISSING"
        print(f"  {status}: {col}")
    
    print()
    print("=" * 80)
    print()
    
    # Show sample data
    print("SAMPLE DATA FROM product_details:")
    print("-" * 80)
    cursor.execute("""
        SELECT pd.product_name, pd.packages_per_display, pd.tablets_per_package, 
               tt.tablet_type_name, tt.inventory_item_id
        FROM product_details pd
        LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
        LIMIT 5
    """)
    samples = cursor.fetchall()
    
    if samples:
        print(f"{'Product Name':<30} {'Pkgs/Display':<15} {'Tabs/Pkg':<12} {'Tablet Type':<20} {'Item ID'}")
        print("-" * 80)
        for row in samples:
            print(f"{row['product_name']:<30} {row['packages_per_display']:<15} {row['tablets_per_package']:<12} {row['tablet_type_name']:<20} {row['inventory_item_id']}")
    else:
        print("  No data found")
    
    print()
    print("=" * 80)
    print()
    
    # Check warehouse_submissions columns
    print("WAREHOUSE_SUBMISSIONS TABLE SCHEMA:")
    print("-" * 80)
    cursor.execute("PRAGMA table_info(warehouse_submissions)")
    ws_cols = cursor.fetchall()
    
    relevant_cols = ['inventory_item_id', 'product_name', 'displays_made', 'packs_remaining', 'loose_tablets']
    for col in ws_cols:
        if col['name'] in relevant_cols:
            print(f"  • {col['name']:<30} {col['type']:<15}")
    
    print()
    print("=" * 80)
    print()
    
    # Show the relationship
    print("RELATIONSHIP STRUCTURE:")
    print("-" * 80)
    print("""
    warehouse_submissions
        └─ inventory_item_id (links to tablet_types)
        └─ product_name (links to product_details)
        
    tablet_types
        ├─ inventory_item_id (unique identifier)
        └─ id (primary key)
            └─ product_details.tablet_type_id (foreign key)
                ├─ packages_per_display ← PACKAGING INFO HERE
                └─ tablets_per_package  ← PACKAGING INFO HERE
    """)
    
    print("=" * 80)
    print()
    
    # Provide corrected query pattern
    print("CORRECTED QUERY PATTERN:")
    print("-" * 80)
    print("""
-- WRONG (current broken query):
SELECT ... 
FROM warehouse_submissions ws
LEFT JOIN tablet_types tt ON ws.inventory_item_id = tt.inventory_item_id
WHERE tt.tablets_per_package ...  ← ERROR: column doesn't exist!

-- CORRECT (fixed query):
SELECT 
    COALESCE(SUM(
        (COALESCE(ws.displays_made, 0) * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0)) +
        (COALESCE(ws.packs_remaining, 0) * COALESCE(pd.tablets_per_package, 0)) +
        COALESCE(ws.loose_tablets, 0)
    ), 0) as total_tablets
FROM warehouse_submissions ws
LEFT JOIN product_details pd ON ws.product_name = pd.product_name
WHERE ...

-- OR if using tablet_types link:
SELECT 
    COALESCE(SUM(
        (COALESCE(ws.displays_made, 0) * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0)) +
        (COALESCE(ws.packs_remaining, 0) * COALESCE(pd.tablets_per_package, 0)) +
        COALESCE(ws.loose_tablets, 0)
    ), 0) as total_tablets
FROM warehouse_submissions ws
LEFT JOIN tablet_types tt ON ws.inventory_item_id = tt.inventory_item_id
LEFT JOIN product_details pd ON pd.tablet_type_id = tt.id
WHERE ...
    """)
    
    print("=" * 80)
    
    conn.close()

if __name__ == '__main__':
    check_schema()

