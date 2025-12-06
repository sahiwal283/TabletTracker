#!/usr/bin/env python3
"""
Simple script to run database migrations manually
Safe to run multiple times - migrations are idempotent
"""
import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def run_migration():
    """Run database initialization and migrations"""
    try:
        print("🔄 Running database initialization and migrations...")
        print("=" * 60)
        
        # Import and run init_db
        from app.models.database import init_db
        init_db()
        
        print("=" * 60)
        print("✅ Database initialization completed successfully!")
        print("\nAll tables and columns have been created/updated.")
        print("The database is now ready to use.")
        
        return True
        
    except Exception as e:
        print("=" * 60)
        print(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = run_migration()
    sys.exit(0 if success else 1)

