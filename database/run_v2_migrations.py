#!/usr/bin/env python3
"""
Run v2.0 migrations on production database
"""
import sys
import os
import sqlite3

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def run_migrations():
    print("=" * 80)
    print("RUNNING V2.0 MIGRATIONS")
    print("=" * 80)
    print()
    
    try:
        # Import the migration system
        from app.models.migrations import MigrationRunner
        from config import Config
        
        print("STEP 1: Initializing database connection...")
        print("-" * 80)
        
        # Get database path from config
        db_path = Config.DATABASE_PATH
        print(f"Database path: {db_path}")
        
        if not os.path.exists(db_path):
            print(f"❌ Database not found at: {db_path}")
            return False
        
        # Connect to database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print("✓ Database connection established")
        print()
        
        print("STEP 2: Running migrations...")
        print("-" * 80)
        
        # Run migrations
        migration_runner = MigrationRunner(cursor)
        migration_runner.run_all()  # Note: method is run_all(), not run_all_migrations()
        
        print()
        print("STEP 3: Committing changes...")
        print("-" * 80)
        
        conn.commit()
        conn.close()
        
        print("✓ Migrations committed successfully")
        print()
        
        print("=" * 80)
        print("✅ MIGRATIONS COMPLETE")
        print("=" * 80)
        print()
        print("Next steps:")
        print("1. Verify schema: python3 database/diagnose_v2_schema.py")
        print("2. Clear Python cache: find . -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true")
        print("3. Reload web app")
        print("=" * 80)
        
        return True
        
    except Exception as e:
        print()
        print("=" * 80)
        print("❌ MIGRATION FAILED")
        print("=" * 80)
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = run_migrations()
    sys.exit(0 if success else 1)

