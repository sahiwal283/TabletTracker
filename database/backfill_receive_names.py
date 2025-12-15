#!/usr/bin/env python3
"""
Backfill receive_name for existing receiving records

Receive name format: PO-{po_number}-{receive_number}
where receive_number is sequential per PO (1, 2, 3, etc.)
"""
import sqlite3
import sys
import os

# Add parent directory to path to import config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config import Config
    DB_PATH = Config.DATABASE_PATH
except ImportError:
    # Fallback if config not available
    if os.path.exists('database/tablet_counter.db'):
        DB_PATH = 'database/tablet_counter.db'
    elif os.path.exists('tablet_counter.db'):
        DB_PATH = 'tablet_counter.db'
    else:
        print("❌ Error: Could not find database file")
        sys.exit(1)


def backfill_receive_names():
    """Backfill receive_name for all receiving records"""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        # Check if receive_name column exists
        c.execute("PRAGMA table_info(receiving)")
        columns = [row[1] for row in c.fetchall()]
        
        if 'receive_name' not in columns:
            print("➕ Adding receive_name column to receiving table...")
            c.execute('ALTER TABLE receiving ADD COLUMN receive_name TEXT')
            conn.commit()
            print("✓ Column added")
        else:
            print("✓ receive_name column already exists")
        
        # Get all receiving records with their PO info
        c.execute('''
            SELECT r.id, r.po_id, r.received_date, po.po_number
            FROM receiving r
            LEFT JOIN purchase_orders po ON r.po_id = po.id
            ORDER BY r.po_id, r.received_date, r.id
        ''')
        
        receiving_records = c.fetchall()
        
        if not receiving_records:
            print("ℹ️  No receiving records found to backfill")
            return
        
        print(f"\n📋 Found {len(receiving_records)} receiving record(s) to process")
        
        # Track receive numbers per PO
        po_receive_counts = {}
        updated_count = 0
        
        for rec in receiving_records:
            rec_id = rec['id']
            po_id = rec['po_id']
            po_number = rec['po_number']
            received_date = rec['received_date']
            
            # Skip if no PO assigned
            if not po_id or not po_number:
                print(f"⚠️  Skipping receiving ID {rec_id} - no PO assigned")
                continue
            
            # Calculate receive number for this PO
            if po_id not in po_receive_counts:
                po_receive_counts[po_id] = 0
            
            po_receive_counts[po_id] += 1
            receive_number = po_receive_counts[po_id]
            
            # Build receive name: PO-{po_number}-{receive_number}
            receive_name = f"{po_number}-{receive_number}"
            
            # Update the record
            c.execute('''
                UPDATE receiving
                SET receive_name = ?
                WHERE id = ?
            ''', (receive_name, rec_id))
            
            updated_count += 1
            print(f"  ✓ ID {rec_id}: {receive_name}")
        
        conn.commit()
        
        print(f"\n✅ Successfully backfilled {updated_count} receive_name(s)")
        
        # Verify
        c.execute('SELECT COUNT(*) FROM receiving WHERE receive_name IS NOT NULL')
        count_with_name = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM receiving')
        total_count = c.fetchone()[0]
        
        print(f"📊 Verification: {count_with_name}/{total_count} records have receive_name")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        if conn:
            conn.close()


if __name__ == '__main__':
    print("=" * 70)
    print("Backfill Receive Names")
    print("=" * 70)
    print(f"Database: {DB_PATH}\n")
    
    backfill_receive_names()
    
    print("\n" + "=" * 70)
    print("✅ Backfill complete!")
    print("=" * 70)




