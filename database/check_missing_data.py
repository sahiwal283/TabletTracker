#!/usr/bin/env python3
"""
Check for missing bag_id and inventory_item_id in warehouse_submissions
"""
import sqlite3
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config

def check_missing_data():
    db_path = Config.DATABASE_PATH
    
    print("=" * 80)
    print("CHECKING MISSING DATA IN WAREHOUSE_SUBMISSIONS")
    print("=" * 80)
    print(f"Database: {db_path}")
    print()
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Check total submissions
    cursor.execute("SELECT COUNT(*) FROM warehouse_submissions")
    total = cursor.fetchone()[0]
    print(f"Total submissions: {total}")
    print()
    
    # Check missing bag_id
    print("MISSING bag_id:")
    print("-" * 80)
    cursor.execute("""
        SELECT COUNT(*) 
        FROM warehouse_submissions 
        WHERE bag_id IS NULL
    """)
    missing_bag_id = cursor.fetchone()[0]
    print(f"Submissions missing bag_id: {missing_bag_id}")
    
    if missing_bag_id > 0:
        print("\nExamples of submissions missing bag_id:")
        cursor.execute("""
            SELECT id, employee_name, product_name, created_at, bag_id, bag_number
            FROM warehouse_submissions 
            WHERE bag_id IS NULL
            ORDER BY created_at DESC
            LIMIT 5
        """)
        for row in cursor.fetchall():
            print(f"  • ID {row['id']}: {row['product_name']} by {row['employee_name']}")
            print(f"    Created: {row['created_at']}, Bag #: {row['bag_number']}, bag_id: {row['bag_id']}")
    
    print()
    
    # Check missing inventory_item_id
    print("MISSING inventory_item_id:")
    print("-" * 80)
    cursor.execute("""
        SELECT COUNT(*) 
        FROM warehouse_submissions 
        WHERE inventory_item_id IS NULL OR inventory_item_id = ''
    """)
    missing_inv_id = cursor.fetchone()[0]
    print(f"Submissions missing inventory_item_id: {missing_inv_id}")
    
    if missing_inv_id > 0:
        print("\nExamples of submissions missing inventory_item_id:")
        cursor.execute("""
            SELECT id, employee_name, product_name, created_at, inventory_item_id
            FROM warehouse_submissions 
            WHERE inventory_item_id IS NULL OR inventory_item_id = ''
            ORDER BY created_at DESC
            LIMIT 5
        """)
        for row in cursor.fetchall():
            print(f"  • ID {row['id']}: {row['product_name']} by {row['employee_name']}")
            print(f"    Created: {row['created_at']}, inventory_item_id: {row['inventory_item_id']}")
    
    print()
    print("=" * 80)
    print()
    
    # Summary
    print("SUMMARY:")
    print("-" * 80)
    print(f"Total submissions: {total}")
    print(f"Missing bag_id: {missing_bag_id}")
    print(f"Missing inventory_item_id: {missing_inv_id}")
    
    if missing_bag_id == 0 and missing_inv_id == 0:
        print("\n✅ All submissions have required data!")
    else:
        print(f"\n⚠️  {missing_bag_id + missing_inv_id} submission(s) need backfilling")
    
    print("=" * 80)
    
    conn.close()
    
    return missing_bag_id, missing_inv_id

if __name__ == '__main__':
    check_missing_data()

