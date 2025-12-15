#!/usr/bin/env python3
"""
Add tablets_pressed_into_cards column to warehouse_submissions table

This migration adds a properly named column for machine count submissions.
Previously, the value was stored in loose_tablets which was misleading since
these tablets are pressed into cards, not loose.

For machine submissions:
- tablets_pressed_into_cards = turns × cards_per_turn × tablets_per_package
- This replaces the misleading use of loose_tablets for machine submissions
"""

import sqlite3
import os
import sys

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

def add_tablets_pressed_column():
    """Add tablets_pressed_into_cards column and backfill data"""
    
    # Use the same database path logic as the app
    db_path = DB_PATH
    
    if not os.path.exists(db_path):
        print(f"❌ Database not found at: {db_path}")
        return False
    
    print("=" * 80)
    print("ADDING tablets_pressed_into_cards COLUMN")
    print("=" * 80)
    print(f"Database: {db_path}")
    print()
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    try:
        # Check if column already exists
        c.execute("PRAGMA table_info(warehouse_submissions)")
        existing_cols = [row[1] for row in c.fetchall()]
        
        if 'tablets_pressed_into_cards' in existing_cols:
            print("✓ Column 'tablets_pressed_into_cards' already exists")
            
            # Check if backfill is needed
            c.execute('''
                SELECT COUNT(*) as count
                FROM warehouse_submissions
                WHERE submission_type = 'machine'
                AND tablets_pressed_into_cards IS NULL
                AND loose_tablets IS NOT NULL
                AND loose_tablets > 0
            ''')
            needs_backfill = c.fetchone()['count']
            
            if needs_backfill > 0:
                print(f"⚠️  Found {needs_backfill} machine submissions that need backfill")
                print("Running backfill...")
            else:
                print("✓ All machine submissions already have tablets_pressed_into_cards")
                conn.close()
                return True
        else:
            print("➕ Adding column 'tablets_pressed_into_cards'...")
            c.execute('ALTER TABLE warehouse_submissions ADD COLUMN tablets_pressed_into_cards INTEGER DEFAULT 0')
            print("✓ Column added")
        
        # Backfill existing machine submissions
        print()
        print("📋 Backfilling existing machine submissions...")
        c.execute('''
            SELECT COUNT(*) as count
            FROM warehouse_submissions
            WHERE submission_type = 'machine'
            AND loose_tablets IS NOT NULL
            AND loose_tablets > 0
        ''')
        machine_submissions = c.fetchone()['count']
        
        if machine_submissions > 0:
            c.execute('''
                UPDATE warehouse_submissions 
                SET tablets_pressed_into_cards = loose_tablets
                WHERE submission_type = 'machine' 
                AND (tablets_pressed_into_cards IS NULL OR tablets_pressed_into_cards = 0)
                AND loose_tablets IS NOT NULL 
                AND loose_tablets > 0
            ''')
            updated = c.rowcount
            print(f"✓ Backfilled {updated} machine submission(s)")
        else:
            print("ℹ️  No machine submissions found to backfill")
        
        conn.commit()
        
        # Verify
        print()
        print("=" * 80)
        print("VERIFICATION")
        print("=" * 80)
        c.execute('''
            SELECT 
                COUNT(*) as total_machine,
                COUNT(CASE WHEN tablets_pressed_into_cards IS NOT NULL AND tablets_pressed_into_cards > 0 THEN 1 END) as with_value
            FROM warehouse_submissions
            WHERE submission_type = 'machine'
        ''')
        result = c.fetchone()
        total = result['total_machine']
        with_value = result['with_value']
        
        print(f"Total machine submissions: {total}")
        print(f"With tablets_pressed_into_cards: {with_value}")
        
        if total > 0 and with_value == total:
            print("✅ All machine submissions have tablets_pressed_into_cards")
        elif total > 0:
            print(f"⚠️  {total - with_value} machine submission(s) still missing value")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        conn.close()
        return False

if __name__ == '__main__':
    success = add_tablets_pressed_column()
    if success:
        print()
        print("=" * 80)
        print("✅ MIGRATION COMPLETE")
        print("=" * 80)
    else:
        print()
        print("=" * 80)
        print("❌ MIGRATION FAILED")
        print("=" * 80)
        exit(1)

