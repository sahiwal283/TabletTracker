#!/usr/bin/env python3
"""
Fix bag_id assignments for submissions that have matching bags
This only assigns bag_id where there's an actual match - doesn't force it
"""
import sqlite3
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config

def fix_bag_assignments():
    db_path = Config.DATABASE_PATH
    
    print("=" * 80)
    print("FIXING BAG_ID ASSIGNMENTS")
    print("=" * 80)
    print(f"Database: {db_path}")
    print()
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Check before
    cursor.execute("SELECT COUNT(*) FROM warehouse_submissions WHERE bag_id IS NULL")
    before_count = cursor.fetchone()[0]
    
    print("BEFORE:")
    print("-" * 80)
    print(f"Submissions missing bag_id: {before_count}")
    print()
    
    # Fix bag_id assignments where there's a clear match
    print("FIXING bag_id assignments...")
    print("-" * 80)
    
    # Match by: PO + Box + Bag number
    cursor.execute("""
        UPDATE warehouse_submissions
        SET bag_id = (
            SELECT b.id
            FROM bags b
            JOIN small_boxes sb ON b.small_box_id = sb.id
            JOIN receiving r ON sb.receiving_id = r.id
            WHERE r.po_id = warehouse_submissions.assigned_po_id
            AND sb.box_number = warehouse_submissions.box_number
            AND b.bag_number = warehouse_submissions.bag_number
            LIMIT 1
        )
        WHERE bag_id IS NULL
        AND assigned_po_id IS NOT NULL
        AND box_number IS NOT NULL
        AND bag_number IS NOT NULL
        AND EXISTS (
            SELECT 1
            FROM bags b
            JOIN small_boxes sb ON b.small_box_id = sb.id
            JOIN receiving r ON sb.receiving_id = r.id
            WHERE r.po_id = warehouse_submissions.assigned_po_id
            AND sb.box_number = warehouse_submissions.box_number
            AND b.bag_number = warehouse_submissions.bag_number
        )
    """)
    
    updated = cursor.rowcount
    conn.commit()
    
    print(f"✓ Updated {updated} submission(s) with bag_id")
    print()
    
    # Check after
    cursor.execute("SELECT COUNT(*) FROM warehouse_submissions WHERE bag_id IS NULL")
    after_count = cursor.fetchone()[0]
    
    print("AFTER:")
    print("-" * 80)
    print(f"Submissions missing bag_id: {after_count}")
    print(f"Fixed: {before_count - after_count}")
    print()
    
    if after_count < before_count:
        print("✅ Successfully assigned bag_id where matches exist")
    else:
        print("ℹ️  No matches found - submissions correctly have bag_id = NULL")
        print("   (These submissions predate the receiving/bags system)")
    
    print("=" * 80)
    
    conn.close()
    return True

if __name__ == '__main__':
    fix_bag_assignments()

