#!/usr/bin/env python3
"""
Backfill inventory_item_id for warehouse_submissions that are missing it.

This handles legacy submissions created before inventory_item_id tracking was added.
The field can be derived from product_name -> product_details -> tablet_types.
"""

import sqlite3
import sys
import os

# Add parent directory to path to import config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config


def backfill_inventory_item_ids():
    """Backfill missing inventory_item_id values in warehouse_submissions"""
    
    db_path = Config.DATABASE_PATH
    print(f"📊 Connecting to database: {db_path}")
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    try:
        # Check how many submissions are missing inventory_item_id
        missing_count = conn.execute('''
            SELECT COUNT(*) as count
            FROM warehouse_submissions
            WHERE inventory_item_id IS NULL
        ''').fetchone()['count']
        
        print(f"📋 Found {missing_count} submissions missing inventory_item_id")
        
        if missing_count == 0:
            print("✅ All submissions already have inventory_item_id - nothing to do!")
            return
        
        # Show some examples of what will be updated
        examples = conn.execute('''
            SELECT ws.id, ws.product_name, tt.inventory_item_id, tt.tablet_type_name
            FROM warehouse_submissions ws
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
            LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            WHERE ws.inventory_item_id IS NULL
            LIMIT 5
        ''').fetchall()
        
        print("\n📝 Example mappings:")
        for ex in examples:
            print(f"   Submission {ex['id']}: '{ex['product_name']}' -> '{ex['inventory_item_id']}' ({ex['tablet_type_name']})")
        
        # Perform the backfill
        print(f"\n🔄 Backfilling inventory_item_id...")
        
        result = conn.execute('''
            UPDATE warehouse_submissions 
            SET inventory_item_id = (
                SELECT tt.inventory_item_id 
                FROM product_details pd
                JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                WHERE pd.product_name = warehouse_submissions.product_name
                LIMIT 1
            )
            WHERE inventory_item_id IS NULL
            AND EXISTS (
                SELECT 1 
                FROM product_details pd
                JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                WHERE pd.product_name = warehouse_submissions.product_name
            )
        ''')
        
        conn.commit()
        updated_count = result.rowcount
        
        print(f"✅ Successfully backfilled {updated_count} submissions")
        
        # Check if any are still missing
        still_missing = conn.execute('''
            SELECT COUNT(*) as count
            FROM warehouse_submissions
            WHERE inventory_item_id IS NULL
        ''').fetchone()['count']
        
        if still_missing > 0:
            print(f"\n⚠️  Warning: {still_missing} submissions still missing inventory_item_id")
            print("   These likely have product_name values that don't match product_details.")
            
            orphans = conn.execute('''
                SELECT DISTINCT ws.product_name, COUNT(*) as count
                FROM warehouse_submissions ws
                WHERE ws.inventory_item_id IS NULL
                GROUP BY ws.product_name
            ''').fetchall()
            
            print("\n   Orphaned product names:")
            for orphan in orphans:
                print(f"      '{orphan['product_name']}' ({orphan['count']} submissions)")
        else:
            print("\n🎉 All submissions now have inventory_item_id!")
        
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        return 1
    finally:
        conn.close()
    
    return 0


if __name__ == '__main__':
    exit(backfill_inventory_item_ids())

