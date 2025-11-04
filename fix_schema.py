#!/usr/bin/env python3
"""
Complete database schema fix for restored backup
Adds all missing columns from recent migrations
Run this on PythonAnywhere to fix the schema mismatch
"""
import sqlite3
import sys

def fix_schema():
    """Add all missing columns that were added in recent versions"""
    try:
        conn = sqlite3.connect('tablet_counter.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        print("=" * 60)
        print("Database Schema Migration")
        print("=" * 60)
        
        # Check warehouse_submissions columns
        print("\n1. Checking warehouse_submissions table...")
        cursor.execute("PRAGMA table_info(warehouse_submissions)")
        ws_columns = [col[1] for col in cursor.fetchall()]
        
        # Add submission_date column
        if 'submission_date' not in ws_columns:
            print("  ➜ Adding submission_date column...")
            cursor.execute('ALTER TABLE warehouse_submissions ADD COLUMN submission_date DATE')
            # Backfill existing records
            cursor.execute('UPDATE warehouse_submissions SET submission_date = DATE(created_at) WHERE submission_date IS NULL')
            conn.commit()
            print("  ✓ Added submission_date and backfilled from created_at")
        else:
            print("  ✓ submission_date already exists")
        
        # Add po_assignment_verified column
        if 'po_assignment_verified' not in ws_columns:
            print("  ➜ Adding po_assignment_verified column...")
            cursor.execute('ALTER TABLE warehouse_submissions ADD COLUMN po_assignment_verified INTEGER DEFAULT 0')
            conn.commit()
            print("  ✓ Added po_assignment_verified (default: unverified)")
        else:
            print("  ✓ po_assignment_verified already exists")
        
        # Add inventory_item_id column
        if 'inventory_item_id' not in ws_columns:
            print("  ➜ Adding inventory_item_id column...")
            cursor.execute('ALTER TABLE warehouse_submissions ADD COLUMN inventory_item_id TEXT')
            # Backfill from product_details/tablet_types
            cursor.execute('''
                UPDATE warehouse_submissions 
                SET inventory_item_id = (
                    SELECT tt.inventory_item_id 
                    FROM product_details pd
                    JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                    WHERE pd.product_name = warehouse_submissions.product_name
                )
                WHERE inventory_item_id IS NULL
            ''')
            conn.commit()
            rows_updated = cursor.rowcount
            print(f"  ✓ Added inventory_item_id and backfilled {rows_updated} records")
        else:
            print("  ✓ inventory_item_id already exists")
        
        # Check purchase_orders columns
        print("\n2. Checking purchase_orders table...")
        cursor.execute("PRAGMA table_info(purchase_orders)")
        po_columns = [col[1] for col in cursor.fetchall()]
        
        # Add parent_po_number column for overs PO tracking
        if 'parent_po_number' not in po_columns:
            print("  ➜ Adding parent_po_number column...")
            cursor.execute('ALTER TABLE purchase_orders ADD COLUMN parent_po_number TEXT')
            conn.commit()
            print("  ✓ Added parent_po_number for overs PO linking")
        else:
            print("  ✓ parent_po_number already exists")
        
        # Final verification
        print("\n3. Verifying database integrity...")
        cursor.execute("SELECT COUNT(*) FROM warehouse_submissions")
        submission_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM purchase_orders")
        po_count = cursor.fetchone()[0]
        
        print(f"  ✓ Found {submission_count} submissions")
        print(f"  ✓ Found {po_count} purchase orders")
        
        print("\n" + "=" * 60)
        print("✓ Migration completed successfully!")
        print("=" * 60)
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = fix_schema()
    sys.exit(0 if success else 1)

