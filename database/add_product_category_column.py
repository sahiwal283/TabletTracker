"""
Add category column to product_details table

This migration adds an independent category field to products,
allowing products to have different categories than their underlying tablet types.
"""
import sqlite3
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config

def add_product_category_column():
    """Add category column to product_details table"""
    db_path = Config.DATABASE_PATH
    
    print(f"Connecting to database: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        # Check if column already exists
        cursor.execute("PRAGMA table_info(product_details)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'category' in columns:
            print("✓ Category column already exists in product_details table")
            return
        
        # Add category column
        print("Adding category column to product_details table...")
        cursor.execute('''
            ALTER TABLE product_details 
            ADD COLUMN category TEXT
        ''')
        
        conn.commit()
        print("✓ Successfully added category column to product_details table")
        
        # Show table structure
        cursor.execute("PRAGMA table_info(product_details)")
        print("\nProduct_details table structure:")
        for col in cursor.fetchall():
            print(f"  - {col[1]} ({col[2]})")
        
    except Exception as e:
        print(f"✗ Error: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == '__main__':
    add_product_category_column()
