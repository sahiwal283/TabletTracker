#!/usr/bin/env python3
"""
Check categories in both tables and compare
"""
import sqlite3

def check_categories():
    conn = sqlite3.connect('tablet_counter.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("=" * 80)
    print("CATEGORIES DATA CHECK")
    print("=" * 80)
    print()
    
    # Query 1: Categories table
    print("QUERY 1: SELECT * FROM categories WHERE is_active = TRUE ORDER BY display_order;")
    print("-" * 80)
    
    cursor.execute("SELECT * FROM categories WHERE is_active = TRUE ORDER BY display_order")
    categories_table = cursor.fetchall()
    
    if categories_table:
        print(f"Found {len(categories_table)} active categories:")
        print()
        print(f"{'ID':<5} {'Category Name':<20} {'Display Order':<15} {'Active':<10} {'Created At'}")
        print("-" * 80)
        for cat in categories_table:
            print(f"{cat['id']:<5} {cat['category_name']:<20} {cat['display_order']:<15} {cat['is_active']:<10} {cat['created_at']}")
    else:
        print("⚠️  No active categories found in categories table!")
    
    print()
    print("=" * 80)
    print()
    
    # Query 2: Distinct categories from tablet_types
    print("QUERY 2: SELECT DISTINCT category FROM tablet_types WHERE category IS NOT NULL AND category != '' ORDER BY category;")
    print("-" * 80)
    
    cursor.execute("SELECT DISTINCT category FROM tablet_types WHERE category IS NOT NULL AND category != '' ORDER BY category")
    tablet_types_categories = cursor.fetchall()
    
    if tablet_types_categories:
        print(f"Found {len(tablet_types_categories)} distinct categories in tablet_types:")
        print()
        for cat in tablet_types_categories:
            print(f"  • {cat['category']}")
    else:
        print("⚠️  No categories found in tablet_types table!")
    
    print()
    print("=" * 80)
    print()
    
    # Comparison
    print("COMPARISON:")
    print("-" * 80)
    
    categories_set = {cat['category_name'] for cat in categories_table}
    tablet_types_set = {cat['category'] for cat in tablet_types_categories}
    
    print(f"\nCategories in 'categories' table: {len(categories_set)}")
    for cat in sorted(categories_set):
        print(f"  • {cat}")
    
    print(f"\nCategories in 'tablet_types' table: {len(tablet_types_set)}")
    for cat in sorted(tablet_types_set):
        print(f"  • {cat}")
    
    # Find missing categories
    missing_from_categories_table = tablet_types_set - categories_set
    extra_in_categories_table = categories_set - tablet_types_set
    
    print()
    if missing_from_categories_table:
        print(f"⚠️  MISSING from categories table (but exist in tablet_types):")
        for cat in sorted(missing_from_categories_table):
            print(f"  ✗ {cat}")
    else:
        print("✓ All tablet_types categories are in categories table")
    
    print()
    if extra_in_categories_table:
        print(f"ℹ️  EXTRA in categories table (not in tablet_types):")
        for cat in sorted(extra_in_categories_table):
            print(f"  + {cat}")
    
    print()
    print("=" * 80)
    print()
    
    # Check specific categories mentioned
    print("SPECIFIC CHECKS:")
    print("-" * 80)
    
    check_list = ['MIT A', '18mg', 'FIX Energy', 'FIX Focus', 'FIX Relax', 'FIX MAX', 'Hyroxi XL', 'Hyroxi Regular']
    
    for cat_name in check_list:
        cursor.execute("SELECT * FROM categories WHERE category_name = ?", (cat_name,))
        result = cursor.fetchone()
        
        if result:
            status = "ACTIVE" if result['is_active'] else "INACTIVE"
            print(f"  ✓ '{cat_name}': {status} (order: {result['display_order']})")
        else:
            print(f"  ✗ '{cat_name}': NOT FOUND in categories table")
    
    print()
    print("=" * 80)
    
    conn.close()

if __name__ == '__main__':
    check_categories()

