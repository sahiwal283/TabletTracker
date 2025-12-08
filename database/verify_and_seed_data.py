#!/usr/bin/env python3
"""
Verify and seed machines and categories tables
"""
import sqlite3

def verify_and_seed():
    conn = sqlite3.connect('tablet_counter.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("=" * 80)
    print("DATABASE DATA VERIFICATION & SEEDING")
    print("=" * 80)
    print()
    
    # ========== CHECK MACHINES TABLE ==========
    print("MACHINES TABLE:")
    print("-" * 80)
    
    cursor.execute("SELECT * FROM machines ORDER BY id")
    machines = cursor.fetchall()
    
    if machines:
        print(f"Found {len(machines)} machines:")
        for machine in machines:
            status = "ACTIVE" if machine['is_active'] else "INACTIVE"
            print(f"  • {machine['machine_name']}: {machine['cards_per_turn']} cards/turn ({status})")
    else:
        print("⚠️  Machines table is EMPTY! Seeding...")
        cursor.execute('''
            INSERT INTO machines (machine_name, cards_per_turn, is_active)
            VALUES ('Machine 1', 6, TRUE), ('Machine 2', 6, TRUE)
        ''')
        print("✓ Added Machine 1 (6 cards/turn)")
        print("✓ Added Machine 2 (6 cards/turn)")
        conn.commit()
    
    print()
    
    # ========== CHECK CATEGORIES TABLE ==========
    print("CATEGORIES TABLE:")
    print("-" * 80)
    
    cursor.execute("SELECT * FROM categories WHERE is_active = TRUE ORDER BY display_order")
    categories = cursor.fetchall()
    
    if categories:
        print(f"Found {len(categories)} active categories:")
        for cat in categories:
            print(f"  • {cat['category_name']} (order: {cat['display_order']})")
    else:
        print("⚠️  Categories table is EMPTY!")
    
    print()
    
    # Check for MIT A specifically
    cursor.execute("SELECT * FROM categories WHERE category_name = 'MIT A'")
    mit_a = cursor.fetchone()
    
    if not mit_a:
        print("⚠️  'MIT A' category is MISSING! Adding it...")
        
        # Get all unique categories from tablet_types
        cursor.execute('''
            SELECT DISTINCT category 
            FROM tablet_types 
            WHERE category IS NOT NULL AND category != ''
        ''')
        existing_from_tablet_types = {row['category'] for row in cursor.fetchall()}
        
        # Define all categories with proper ordering
        all_categories = {
            'FIX Energy': 1,
            'FIX Focus': 2,
            'FIX Relax': 3,
            'FIX MAX': 4,
            '18mg': 5,
            'Hyroxi XL': 6,
            'Hyroxi Regular': 7,
            'MIT A': 8,
            'Other': 999
        }
        
        # Add any categories from tablet_types that aren't in our list
        for cat in existing_from_tablet_types:
            if cat not in all_categories:
                all_categories[cat] = 100  # Lower priority
        
        # Insert or update all categories
        added = 0
        updated = 0
        for cat_name, order in all_categories.items():
            cursor.execute('SELECT id FROM categories WHERE category_name = ?', (cat_name,))
            existing = cursor.fetchone()
            
            if existing:
                # Update display order if needed
                cursor.execute('''
                    UPDATE categories 
                    SET display_order = ?, is_active = TRUE
                    WHERE category_name = ?
                ''', (order, cat_name))
                if cursor.rowcount > 0:
                    updated += 1
            else:
                # Insert new category
                cursor.execute('''
                    INSERT INTO categories (category_name, display_order, is_active)
                    VALUES (?, ?, TRUE)
                ''', (cat_name, order))
                print(f"  ✓ Added: {cat_name} (order: {order})")
                added += 1
        
        conn.commit()
        
        if added > 0:
            print(f"\n✓ Added {added} new categories")
        if updated > 0:
            print(f"✓ Updated {updated} existing categories")
    else:
        print("✓ 'MIT A' category exists")
    
    print()
    
    # ========== FINAL VERIFICATION ==========
    print("=" * 80)
    print("FINAL STATE")
    print("=" * 80)
    print()
    
    # Show all machines
    cursor.execute("SELECT * FROM machines ORDER BY id")
    machines = cursor.fetchall()
    print(f"MACHINES ({len(machines)}):")
    for machine in machines:
        status = "✓" if machine['is_active'] else "✗"
        print(f"  {status} {machine['machine_name']}: {machine['cards_per_turn']} cards/turn")
    
    print()
    
    # Show all active categories
    cursor.execute("SELECT * FROM categories WHERE is_active = TRUE ORDER BY display_order")
    categories = cursor.fetchall()
    print(f"ACTIVE CATEGORIES ({len(categories)}):")
    for cat in categories:
        print(f"  • {cat['category_name']} (order: {cat['display_order']})")
    
    print()
    print("=" * 80)
    print("✅ VERIFICATION COMPLETE")
    print("=" * 80)
    
    conn.close()

if __name__ == '__main__':
    verify_and_seed()

