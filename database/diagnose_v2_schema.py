#!/usr/bin/env python3
"""
Diagnose production database schema for v2.0 compatibility
"""
import sqlite3
import os
import sys

def diagnose_schema():
    db_path = 'database/tablet_counter.db'
    
    if not os.path.exists(db_path):
        print(f"❌ Database not found: {db_path}")
        return False
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("=" * 80)
    print("V2.0 SCHEMA DIAGNOSIS")
    print("=" * 80)
    print(f"Database: {db_path}")
    print()
    
    # Check tablet_types table
    print("TABLET_TYPES TABLE:")
    print("-" * 80)
    cursor.execute("PRAGMA table_info(tablet_types)")
    tt_cols = cursor.fetchall()
    tt_col_names = [col['name'] for col in tt_cols]
    
    print("Current columns:")
    for col in tt_cols:
        print(f"  • {col['name']:<30} {col['type']:<15}")
    
    print()
    print("Expected columns (v2.0):")
    expected_tt = ['id', 'tablet_type_name', 'inventory_item_id', 'category', 'category_id']
    for col in expected_tt:
        status = "✓" if col in tt_col_names else "✗"
        print(f"  {status} {col}")
    
    # Check for columns that shouldn't exist
    invalid_tt = ['tablets_per_package', 'packages_per_display']
    print()
    print("Invalid columns (should NOT exist):")
    for col in invalid_tt:
        status = "✗ FOUND (SHOULD BE REMOVED)" if col in tt_col_names else "✓ Not present"
        print(f"  {status}: {col}")
    
    print()
    print("=" * 80)
    print()
    
    # Check product_details table
    print("PRODUCT_DETAILS TABLE:")
    print("-" * 80)
    cursor.execute("PRAGMA table_info(product_details)")
    pd_cols = cursor.fetchall()
    pd_col_names = [col['name'] for col in pd_cols]
    
    print("Current columns:")
    for col in pd_cols:
        print(f"  • {col['name']:<30} {col['type']:<15}")
    
    print()
    print("Expected columns (v2.0):")
    expected_pd = ['id', 'product_name', 'tablet_type_id', 'packages_per_display', 'tablets_per_package']
    for col in expected_pd:
        status = "✓" if col in pd_col_names else "✗"
        print(f"  {status} {col}")
    
    print()
    print("=" * 80)
    print()
    
    # Check warehouse_submissions table
    print("WAREHOUSE_SUBMISSIONS TABLE:")
    print("-" * 80)
    cursor.execute("PRAGMA table_info(warehouse_submissions)")
    ws_cols = cursor.fetchall()
    ws_col_names = [col['name'] for col in ws_cols]
    
    print("Current columns:")
    for col in ws_cols:
        print(f"  • {col['name']:<30} {col['type']:<15}")
    
    print()
    print("Expected columns (v2.0):")
    expected_ws = [
        'id', 'employee_name', 'product_name', 'box_number', 'bag_number',
        'bag_label_count', 'displays_made', 'packs_remaining', 'loose_tablets',
        'damaged_tablets', 'discrepancy_flag', 'assigned_po_id', 'created_at',
        'submission_date', 'po_assignment_verified', 'inventory_item_id', 'admin_notes',
        'category', 'submission_type', 'machine_good_count', 'tablet_type_id',
        'bag_id', 'needs_review'
    ]
    for col in expected_ws:
        status = "✓" if col in ws_col_names else "✗"
        print(f"  {status} {col}")
    
    # Check for invalid columns
    invalid_ws = ['tablets_per_package']
    print()
    print("Invalid columns (should NOT exist):")
    for col in invalid_ws:
        status = "✗ FOUND (SHOULD BE REMOVED)" if col in ws_col_names else "✓ Not present"
        print(f"  {status}: {col}")
    
    print()
    print("=" * 80)
    print()
    
    # Check receiving table
    print("RECEIVING TABLE:")
    print("-" * 80)
    cursor.execute("PRAGMA table_info(receiving)")
    rec_cols = cursor.fetchall()
    rec_col_names = [col['name'] for col in rec_cols]
    
    print("Current columns:")
    for col in rec_cols:
        print(f"  • {col['name']:<30} {col['type']:<15}")
    
    print()
    print("Expected columns (v2.0):")
    expected_rec = [
        'id', 'po_id', 'shipment_id', 'received_date', 'delivery_photo_path',
        'delivery_photo_zoho_id', 'total_small_boxes', 'received_by', 'notes', 'created_at'
    ]
    for col in expected_rec:
        status = "✓" if col in rec_col_names else "✗"
        print(f"  {status} {col}")
    
    # Check for invalid columns
    invalid_rec = ['received']
    print()
    print("Invalid columns (should NOT exist):")
    for col in invalid_rec:
        status = "✗ FOUND (SHOULD BE REMOVED)" if col in rec_col_names else "✓ Not present"
        print(f"  {status}: {col}")
    
    print()
    print("=" * 80)
    print()
    
    # Summary
    print("SUMMARY:")
    print("-" * 80)
    
    missing_cols = []
    invalid_cols = []
    
    # Check missing columns
    for col in expected_tt:
        if col not in tt_col_names:
            missing_cols.append(f"tablet_types.{col}")
    
    for col in expected_pd:
        if col not in pd_col_names:
            missing_cols.append(f"product_details.{col}")
    
    for col in expected_ws:
        if col not in ws_col_names:
            missing_cols.append(f"warehouse_submissions.{col}")
    
    for col in expected_rec:
        if col not in rec_col_names:
            missing_cols.append(f"receiving.{col}")
    
    # Check invalid columns
    for col in invalid_tt:
        if col in tt_col_names:
            invalid_cols.append(f"tablet_types.{col}")
    
    for col in invalid_ws:
        if col in ws_col_names:
            invalid_cols.append(f"warehouse_submissions.{col}")
    
    for col in invalid_rec:
        if col in rec_col_names:
            invalid_cols.append(f"receiving.{col}")
    
    if missing_cols:
        print(f"⚠️  Missing columns ({len(missing_cols)}):")
        for col in missing_cols:
            print(f"  • {col}")
    else:
        print("✅ No missing columns")
    
    print()
    
    if invalid_cols:
        print(f"⚠️  Invalid columns found ({len(invalid_cols)}):")
        for col in invalid_cols:
            print(f"  • {col}")
        print("  Note: These may cause errors but won't block migrations")
    else:
        print("✅ No invalid columns found")
    
    print()
    print("=" * 80)
    print()
    
    conn.close()
    
    return len(missing_cols) > 0

if __name__ == '__main__':
    needs_migration = diagnose_schema()
    if needs_migration:
        print("⚠️  Database needs migration - run migrations next")
        sys.exit(1)
    else:
        print("✅ Schema looks good!")
        sys.exit(0)

