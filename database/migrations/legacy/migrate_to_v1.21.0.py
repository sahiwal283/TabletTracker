#!/usr/bin/env python3
"""
Production Migration Script for TabletTracker v1.21.0
Safe to run multiple times (idempotent)

This script applies all necessary database schema changes for v1.21.0:
1. Adds submission_date column to warehouse_submissions
2. Backfills submission_date from created_at
3. Verifies all required columns exist

Run this on PythonAnywhere before deploying the new code:
    python3 migrate_to_v1.21.0.py
"""

import sqlite3
from datetime import datetime

def migrate_database():
    """Apply all migrations for v1.21.0"""
    print("=" * 60)
    print("TabletTracker Migration to v1.21.0")
    print("=" * 60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    try:
        # Connect to database
        conn = sqlite3.connect('tablet_counter.db')
        c = conn.cursor()
        
        # MIGRATION 1: Add submission_date column to warehouse_submissions
        print("Checking warehouse_submissions table...")
        c.execute('PRAGMA table_info(warehouse_submissions)')
        existing_ws_cols = [row[1] for row in c.fetchall()]
        
        if 'submission_date' not in existing_ws_cols:
            print("  ➜ Adding submission_date column...")
            c.execute('ALTER TABLE warehouse_submissions ADD COLUMN submission_date DATE')
            
            # Backfill existing records with date from created_at
            print("  ➜ Backfilling submission_date from created_at...")
            c.execute('UPDATE warehouse_submissions SET submission_date = DATE(created_at) WHERE submission_date IS NULL')
            
            rows_updated = c.rowcount
            print(f"  ✓ Added submission_date column and backfilled {rows_updated} rows")
        else:
            print("  ✓ submission_date column already exists")
            
            # Ensure any NULL values are backfilled
            c.execute('SELECT COUNT(*) FROM warehouse_submissions WHERE submission_date IS NULL')
            null_count = c.fetchone()[0]
            if null_count > 0:
                print(f"  ➜ Backfilling {null_count} NULL submission_date values...")
                c.execute('UPDATE warehouse_submissions SET submission_date = DATE(created_at) WHERE submission_date IS NULL')
                print(f"  ✓ Backfilled {null_count} rows")
        
        print()
        
        # MIGRATION 2: Verify purchase_orders has required columns
        print("Checking purchase_orders table...")
        c.execute('PRAGMA table_info(purchase_orders)')
        po_cols = [row[1] for row in c.fetchall()]
        
        required_po_cols = {
            'zoho_status': 'TEXT',
            'internal_status': 'TEXT DEFAULT "Active"'
        }
        
        for col, col_type in required_po_cols.items():
            if col not in po_cols:
                print(f"  ➜ Adding {col} column...")
                c.execute(f'ALTER TABLE purchase_orders ADD COLUMN {col} {col_type}')
                print(f"  ✓ Added {col} column")
            else:
                print(f"  ✓ {col} column already exists")
        
        print()
        
        # MIGRATION 3: Verify shipments has tracking columns
        print("Checking shipments table...")
        c.execute('PRAGMA table_info(shipments)')
        shipment_cols = [row[1] for row in c.fetchall()]
        
        required_shipment_cols = {
            'carrier_code': 'TEXT',
            'tracking_status': 'TEXT',
            'last_checkpoint': 'TEXT',
            'updated_at': 'TIMESTAMP'
        }
        
        for col, col_type in required_shipment_cols.items():
            if col not in shipment_cols:
                print(f"  ➜ Adding {col} column...")
                c.execute(f'ALTER TABLE shipments ADD COLUMN {col} {col_type}')
                print(f"  ✓ Added {col} column")
            else:
                print(f"  ✓ {col} column already exists")
        
        print()
        
        # Commit all changes
        conn.commit()
        
        # Summary
        print("=" * 60)
        print("✅ Migration completed successfully!")
        print("=" * 60)
        print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        print("Next steps:")
        print("1. Deploy the new code (v1.21.0)")
        print("2. Reload the web app on PythonAnywhere")
        print("3. Verify the dashboard loads correctly")
        print()
        
        conn.close()
        return True
        
    except Exception as e:
        print()
        print("=" * 60)
        print("❌ Migration failed!")
        print("=" * 60)
        print(f"Error: {e}")
        print()
        print("Please check the error and try again.")
        print("If the error persists, contact support.")
        return False

if __name__ == '__main__':
    migrate_database()

