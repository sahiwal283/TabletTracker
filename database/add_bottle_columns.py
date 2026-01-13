#!/usr/bin/env python3
"""
Add bottle production columns to database.
Run this script directly on PythonAnywhere to add missing columns.

Usage: python database/add_bottle_columns.py
"""
import sqlite3
import os
import sys

# Determine database path
if os.path.exists('database/tablet_counter.db'):
    DB_PATH = 'database/tablet_counter.db'
elif os.path.exists('tablet_counter.db'):
    DB_PATH = 'tablet_counter.db'
else:
    print("ERROR: Could not find database file")
    sys.exit(1)

print(f"Using database: {DB_PATH}")

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

def column_exists(table, column):
    cursor.execute(f"PRAGMA table_info({table})")
    return column in [row[1] for row in cursor.fetchall()]

def add_column(table, column, definition):
    if column_exists(table, column):
        print(f"  ✓ {table}.{column} already exists")
        return False
    try:
        cursor.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
        print(f"  ✓ Added {table}.{column}")
        return True
    except Exception as e:
        print(f"  ✗ Failed to add {table}.{column}: {e}")
        return False

print("\n=== Adding Bottle Production Columns ===\n")

# tablet_types columns
print("tablet_types table:")
add_column('tablet_types', 'is_bottle_only', 'BOOLEAN DEFAULT 0')
add_column('tablet_types', 'is_variety_pack', 'BOOLEAN DEFAULT 0')
add_column('tablet_types', 'tablets_per_bottle', 'INTEGER')
add_column('tablet_types', 'bottles_per_pack', 'INTEGER')
add_column('tablet_types', 'variety_pack_contents', 'TEXT')

# bags columns
print("\nbags table:")
add_column('bags', 'reserved_for_bottles', 'BOOLEAN DEFAULT 0')

# warehouse_submissions columns
print("\nwarehouse_submissions table:")
add_column('warehouse_submissions', 'bottles_made', 'INTEGER DEFAULT 0')

conn.commit()
conn.close()

print("\n=== Migration Complete ===\n")

