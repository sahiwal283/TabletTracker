#!/usr/bin/env python3
"""
Add 'closed' column to receiving table for PythonAnywhere deployment
Run this on PythonAnywhere after pulling the latest code
"""
import sqlite3
import sys

def add_closed_column():
    """Add closed column to receiving table if it doesn't exist"""
    try:
        # Connect to database
        conn = sqlite3.connect('database/tablet_counter.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        print("=" * 60)
        print("Adding 'closed' column to receiving table")
        print("=" * 60)
        
        # Check if column already exists
        cursor.execute("PRAGMA table_info(receiving)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'closed' in columns:
            print("✅ 'closed' column already exists in receiving table!")
            print("No action needed.")
            conn.close()
            return True
        
        # Add the column
        print("\n📝 Adding 'closed' column to receiving table...")
        cursor.execute('ALTER TABLE receiving ADD COLUMN closed BOOLEAN DEFAULT 0')
        
        # Verify it was added
        cursor.execute("PRAGMA table_info(receiving)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'closed' in columns:
            conn.commit()
            print("✅ Successfully added 'closed' column!")
            print("✅ Default value: FALSE (0)")
            print("✅ All existing receives are now marked as open (closed=0)")
            
            # Show count of receives
            cursor.execute("SELECT COUNT(*) as count FROM receiving")
            count = cursor.fetchone()[0]
            print(f"\n📊 Updated {count} receiving record(s)")
            
            conn.close()
            return True
        else:
            print("❌ Failed to add column")
            conn.rollback()
            conn.close()
            return False
            
    except Exception as e:
        print(f"\n❌ Error: {e}")
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        return False

if __name__ == '__main__':
    print("\n🚀 Starting database migration...")
    success = add_closed_column()
    
    if success:
        print("\n" + "=" * 60)
        print("✅ MIGRATION COMPLETE!")
        print("=" * 60)
        print("\nYou can now use the close/reopen feature for receives.")
        print("Reload your web app on PythonAnywhere to apply changes.")
        sys.exit(0)
    else:
        print("\n" + "=" * 60)
        print("❌ MIGRATION FAILED")
        print("=" * 60)
        print("\nPlease check the error above and try again.")
        sys.exit(1)

