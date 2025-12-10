#!/usr/bin/env python3
"""
Backfill missing bag_id and inventory_item_id for legacy warehouse_submissions
This is a safe, idempotent script that can be run multiple times
"""
import sqlite3
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config

def backfill_missing_data():
    db_path = Config.DATABASE_PATH
    
    print("=" * 80)
    print("BACKFILL MISSING DATA IN WAREHOUSE_SUBMISSIONS")
    print("=" * 80)
    print(f"Database: {db_path}")
    print()
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Check what needs fixing
    cursor.execute("SELECT COUNT(*) FROM warehouse_submissions WHERE bag_id IS NULL")
    missing_bag_id = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM warehouse_submissions WHERE inventory_item_id IS NULL OR inventory_item_id = ''")
    missing_inv_id = cursor.fetchone()[0]
    
    print("BEFORE BACKFILL:")
    print("-" * 80)
    print(f"Submissions missing bag_id: {missing_bag_id}")
    print(f"Submissions missing inventory_item_id: {missing_inv_id}")
    print()
    
    if missing_bag_id == 0 and missing_inv_id == 0:
        print("✅ No data needs backfilling!")
        conn.close()
        return True
    
    # Backfill inventory_item_id
    if missing_inv_id > 0:
        print("BACKFILLING inventory_item_id...")
        print("-" * 80)
        try:
            cursor.execute('''
                UPDATE warehouse_submissions 
                SET inventory_item_id = (
                    SELECT tt.inventory_item_id 
                    FROM product_details pd
                    JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                    WHERE pd.product_name = warehouse_submissions.product_name
                    LIMIT 1
                )
                WHERE (inventory_item_id IS NULL OR inventory_item_id = '')
                AND product_name IS NOT NULL
                AND product_name != ''
            ''')
            updated_inv = cursor.rowcount
            conn.commit()
            print(f"✓ Backfilled {updated_inv} missing inventory_item_id values")
        except Exception as e:
            print(f"⚠️  Error backfilling inventory_item_id: {e}")
            conn.rollback()
    
    print()
    
    # Backfill bag_id
    if missing_bag_id > 0:
        print("BACKFILLING bag_id...")
        print("-" * 80)
        try:
            # Try to match by bag_number and PO relationship
            cursor.execute('''
                UPDATE warehouse_submissions 
                SET bag_id = (
                    SELECT b.id
                    FROM bags b
                    JOIN small_boxes sb ON b.small_box_id = sb.id
                    JOIN receiving r ON sb.receiving_id = r.id
                    WHERE b.bag_number = warehouse_submissions.bag_number
                    AND r.po_id = warehouse_submissions.assigned_po_id
                    LIMIT 1
                )
                WHERE bag_id IS NULL
                AND bag_number IS NOT NULL
                AND assigned_po_id IS NOT NULL
            ''')
            updated_bag = cursor.rowcount
            conn.commit()
            print(f"✓ Backfilled {updated_bag} missing bag_id values")
            
            # Check if any remain
            cursor.execute("SELECT COUNT(*) FROM warehouse_submissions WHERE bag_id IS NULL")
            remaining = cursor.fetchone()[0]
            if remaining > 0:
                print(f"  ℹ {remaining} submissions still missing bag_id (may not have matching bags in receiving)")
        except Exception as e:
            print(f"⚠️  Error backfilling bag_id: {e}")
            conn.rollback()
    
    print()
    
    # Verify results
    print("AFTER BACKFILL:")
    print("-" * 80)
    cursor.execute("SELECT COUNT(*) FROM warehouse_submissions WHERE bag_id IS NULL")
    remaining_bag_id = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM warehouse_submissions WHERE inventory_item_id IS NULL OR inventory_item_id = ''")
    remaining_inv_id = cursor.fetchone()[0]
    
    print(f"Submissions still missing bag_id: {remaining_bag_id}")
    print(f"Submissions still missing inventory_item_id: {remaining_inv_id}")
    print()
    
    if remaining_bag_id == 0 and remaining_inv_id == 0:
        print("✅ All data backfilled successfully!")
    elif remaining_bag_id > 0 or remaining_inv_id > 0:
        print("⚠️  Some data could not be backfilled:")
        if remaining_bag_id > 0:
            print(f"  • {remaining_bag_id} submissions missing bag_id (may not have matching bags)")
        if remaining_inv_id > 0:
            print(f"  • {remaining_inv_id} submissions missing inventory_item_id (product_name may not match)")
    
    print()
    print("=" * 80)
    
    conn.close()
    return True

if __name__ == '__main__':
    backfill_missing_data()

