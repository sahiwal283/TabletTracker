#!/usr/bin/env python3
"""
Backfill archived status for submissions belonging to closed POs.

This script updates the archived column in warehouse_submissions table
to mark submissions as archived if they belong to a closed purchase order.

Run this script after deploying the submissions page overhaul to ensure
existing closed PO submissions are properly archived.
"""

import sqlite3
import sys
import os

# Add parent directory to path to import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def backfill_archive_submissions(db_path='tablet_counter.db'):
    """
    Backfill archived status for submissions from closed POs.
    
    Args:
        db_path: Path to the SQLite database file
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Check if archived column exists
        try:
            cursor.execute('SELECT archived FROM warehouse_submissions LIMIT 1')
            print("✅ archived column exists")
        except sqlite3.OperationalError:
            print("❌ archived column does NOT exist - adding it...")
            cursor.execute('ALTER TABLE warehouse_submissions ADD COLUMN archived BOOLEAN DEFAULT FALSE')
            conn.commit()
            print("✅ Added archived column")
        
        # Count submissions from closed POs
        count_query = '''
            SELECT COUNT(*) as count
            FROM warehouse_submissions ws
            LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
            WHERE po.closed = TRUE
        '''
        total_count = cursor.execute(count_query).fetchone()['count']
        
        print(f"\n📊 Found {total_count} submissions from closed POs")
        
        if total_count == 0:
            print("✅ No submissions to archive")
            conn.close()
            return
        
        # Update archived status for submissions from closed POs
        update_query = '''
            UPDATE warehouse_submissions
            SET archived = TRUE
            WHERE assigned_po_id IN (
                SELECT id FROM purchase_orders WHERE closed = TRUE
            )
            AND COALESCE(archived, FALSE) = FALSE
        '''
        
        cursor.execute(update_query)
        rows_updated = cursor.rowcount
        conn.commit()
        
        print(f"✅ Archived {rows_updated} submissions from closed POs")
        
        # Verify the update
        archived_count = cursor.execute('''
            SELECT COUNT(*) as count
            FROM warehouse_submissions ws
            LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
            WHERE po.closed = TRUE AND COALESCE(ws.archived, FALSE) = TRUE
        ''').fetchone()['count']
        
        print(f"✅ Verified: {archived_count} submissions are now archived")
        
        # Show breakdown by PO
        po_breakdown = cursor.execute('''
            SELECT po.po_number, po.closed, COUNT(ws.id) as submission_count
            FROM purchase_orders po
            LEFT JOIN warehouse_submissions ws ON po.id = ws.assigned_po_id
            WHERE po.closed = TRUE
            GROUP BY po.id, po.po_number, po.closed
            ORDER BY po.po_number DESC
            LIMIT 10
        ''').fetchall()
        
        if po_breakdown:
            print("\n📦 Sample of closed POs with submissions:")
            for row in po_breakdown:
                print(f"  - {row['po_number']}: {row['submission_count']} submissions")
        
        conn.close()
        print("\n✅ Backfill complete!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    # Allow database path to be passed as argument
    db_path = sys.argv[1] if len(sys.argv) > 1 else 'tablet_counter.db'
    backfill_archive_submissions(db_path)
