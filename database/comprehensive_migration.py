#!/usr/bin/env python3
"""
Comprehensive Database Migration Script
Adds all missing tables and columns to production database
"""
import sqlite3
import sys
from datetime import datetime

def run_comprehensive_migration(db_path='tablet_counter.db'):
    """Run all necessary migrations"""
    
    print("=" * 80)
    print("COMPREHENSIVE DATABASE MIGRATION")
    print("=" * 80)
    print(f"Database: {db_path}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    migration_log = []
    
    try:
        # ========== STEP 1: CHECK EXISTING TABLES ==========
        print("STEP 1: Checking existing tables...")
        print("-" * 80)
        
        c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        existing_tables = [row[0] for row in c.fetchall()]
        print(f"Found {len(existing_tables)} tables:")
        for table in existing_tables:
            print(f"  ✓ {table}")
        print()
        
        # ========== STEP 2: CREATE MISSING TABLES ==========
        print("STEP 2: Creating missing tables...")
        print("-" * 80)
        
        # Machines table
        if 'machines' not in existing_tables:
            c.execute('''CREATE TABLE IF NOT EXISTS machines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                machine_name TEXT UNIQUE NOT NULL,
                cards_per_turn INTEGER NOT NULL DEFAULT 1,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            print("✓ Created machines table")
            migration_log.append("Created machines table")
        else:
            print("  ℹ machines table already exists")
        
        # Categories table
        if 'categories' not in existing_tables:
            c.execute('''CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_name TEXT UNIQUE NOT NULL,
                display_order INTEGER DEFAULT 999,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            print("✓ Created categories table")
            migration_log.append("Created categories table")
        else:
            print("  ℹ categories table already exists")
        
        # Machine counts table
        if 'machine_counts' not in existing_tables:
            c.execute('''CREATE TABLE IF NOT EXISTS machine_counts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tablet_type_id INTEGER,
                machine_count INTEGER NOT NULL,
                employee_name TEXT NOT NULL,
                count_date DATE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (tablet_type_id) REFERENCES tablet_types (id)
            )''')
            print("✓ Created machine_counts table")
            migration_log.append("Created machine_counts table")
        else:
            print("  ℹ machine_counts table already exists")
        
        conn.commit()
        print()
        
        # ========== STEP 3: ADD MISSING COLUMNS ==========
        print("STEP 3: Adding missing columns...")
        print("-" * 80)
        
        # Check warehouse_submissions columns
        c.execute("PRAGMA table_info(warehouse_submissions)")
        ws_cols = [row[1] for row in c.fetchall()]
        
        # Add bag_id column
        if 'bag_id' not in ws_cols:
            try:
                c.execute('ALTER TABLE warehouse_submissions ADD COLUMN bag_id INTEGER REFERENCES bags(id)')
                print("✓ Added warehouse_submissions.bag_id")
                migration_log.append("Added warehouse_submissions.bag_id")
            except Exception as e:
                print(f"  ⚠ Error adding bag_id: {e}")
        else:
            print("  ℹ warehouse_submissions.bag_id already exists")
        
        # Add needs_review column
        if 'needs_review' not in ws_cols:
            try:
                c.execute('ALTER TABLE warehouse_submissions ADD COLUMN needs_review BOOLEAN DEFAULT FALSE')
                print("✓ Added warehouse_submissions.needs_review")
                migration_log.append("Added warehouse_submissions.needs_review")
            except Exception as e:
                print(f"  ⚠ Error adding needs_review: {e}")
        else:
            print("  ℹ warehouse_submissions.needs_review already exists")
        
        # Check machine_counts columns
        c.execute("PRAGMA table_info(machine_counts)")
        mc_cols = [row[1] for row in c.fetchall()]
        
        # Add machine_id column
        if 'machine_id' not in mc_cols:
            try:
                c.execute('ALTER TABLE machine_counts ADD COLUMN machine_id INTEGER REFERENCES machines(id)')
                print("✓ Added machine_counts.machine_id")
                migration_log.append("Added machine_counts.machine_id")
            except Exception as e:
                print(f"  ⚠ Error adding machine_id: {e}")
        else:
            print("  ℹ machine_counts.machine_id already exists")
        
        # Add box_number and bag_number to machine_counts if missing
        if 'box_number' not in mc_cols:
            try:
                c.execute('ALTER TABLE machine_counts ADD COLUMN box_number TEXT')
                print("✓ Added machine_counts.box_number")
                migration_log.append("Added machine_counts.box_number")
            except Exception as e:
                print(f"  ℹ box_number: {e}")
        else:
            print("  ℹ machine_counts.box_number already exists")
        
        if 'bag_number' not in mc_cols:
            try:
                c.execute('ALTER TABLE machine_counts ADD COLUMN bag_number TEXT')
                print("✓ Added machine_counts.bag_number")
                migration_log.append("Added machine_counts.bag_number")
            except Exception as e:
                print(f"  ℹ bag_number: {e}")
        else:
            print("  ℹ machine_counts.bag_number already exists")
        
        conn.commit()
        print()
        
        # ========== STEP 4: SEED MACHINES TABLE ==========
        print("STEP 4: Seeding machines table...")
        print("-" * 80)
        
        c.execute('SELECT COUNT(*) as count FROM machines')
        machine_count = c.fetchone()[0]
        
        if machine_count == 0:
            machines = [
                ('Machine 1', 6),  # User wants 6 cards per turn
                ('Machine 2', 6)
            ]
            for machine_name, cards_per_turn in machines:
                c.execute('''
                    INSERT INTO machines (machine_name, cards_per_turn, is_active)
                    VALUES (?, ?, TRUE)
                ''', (machine_name, cards_per_turn))
                print(f"✓ Added {machine_name} (cards_per_turn: {cards_per_turn})")
                migration_log.append(f"Added {machine_name}")
            conn.commit()
        else:
            print(f"  ℹ Machines table already has {machine_count} machines")
            # Show existing machines
            c.execute('SELECT machine_name, cards_per_turn, is_active FROM machines')
            for row in c.fetchall():
                status = "active" if row[2] else "inactive"
                print(f"    • {row[0]}: {row[1]} cards/turn ({status})")
        
        print()
        
        # ========== STEP 5: SEED CATEGORIES TABLE ==========
        print("STEP 5: Seeding categories table...")
        print("-" * 80)
        
        c.execute('SELECT COUNT(*) as count FROM categories WHERE is_active = TRUE')
        category_count = c.fetchone()[0]
        
        if category_count == 0:
            # Get existing categories from tablet_types
            c.execute('''
                SELECT DISTINCT category 
                FROM tablet_types 
                WHERE category IS NOT NULL AND category != ''
            ''')
            existing_cats = {row[0] for row in c.fetchall() if row[0]}
            
            # Default categories with display order
            default_categories = [
                ('FIX Energy', 1),
                ('FIX Focus', 2),
                ('FIX Relax', 3),
                ('FIX MAX', 4),
                ('18mg', 5),
                ('Hyroxi XL', 6),
                ('Hyroxi Regular', 7),
                ('Other', 999)
            ]
            
            # Combine existing and defaults
            all_categories = {}
            for cat_name, order in default_categories:
                all_categories[cat_name] = order
            
            # Add any existing categories not in defaults
            for cat in existing_cats:
                if cat not in all_categories:
                    all_categories[cat] = 100  # Lower priority
            
            # Insert all categories
            for cat_name, order in sorted(all_categories.items(), key=lambda x: x[1]):
                try:
                    c.execute('''
                        INSERT INTO categories (category_name, display_order, is_active)
                        VALUES (?, ?, TRUE)
                    ''', (cat_name, order))
                    print(f"✓ Added category: {cat_name} (order: {order})")
                except sqlite3.IntegrityError:
                    print(f"  ℹ Category already exists: {cat_name}")
            
            migration_log.append(f"Seeded {len(all_categories)} categories")
            conn.commit()
        else:
            print(f"  ℹ Categories table already has {category_count} active categories")
            # Show existing categories
            c.execute('SELECT category_name, display_order FROM categories WHERE is_active = TRUE ORDER BY display_order')
            for row in c.fetchall():
                print(f"    • {row[0]} (order: {row[1]})")
        
        print()
        
        # ========== STEP 6: DATA MIGRATIONS ==========
        print("STEP 6: Running data migrations...")
        print("-" * 80)
        
        # Lock in soft PO assignments
        c.execute('''
            UPDATE warehouse_submissions 
            SET po_assignment_verified = 1 
            WHERE assigned_po_id IS NOT NULL 
            AND COALESCE(po_assignment_verified, 0) = 0
        ''')
        updated = c.rowcount
        if updated > 0:
            print(f"✓ Locked {updated} soft PO assignments")
            migration_log.append(f"Locked {updated} soft PO assignments")
        
        # Flag unassigned submissions for review
        c.execute('''
            UPDATE warehouse_submissions 
            SET needs_review = 1 
            WHERE assigned_po_id IS NULL
            AND bag_id IS NULL
            AND COALESCE(needs_review, 0) = 0
        ''')
        flagged = c.rowcount
        if flagged > 0:
            print(f"✓ Flagged {flagged} unassigned submissions for review")
            migration_log.append(f"Flagged {flagged} submissions for review")
        
        if updated == 0 and flagged == 0:
            print("  ℹ No data migrations needed")
        
        conn.commit()
        print()
        
        # ========== FINAL VERIFICATION ==========
        print("=" * 80)
        print("FINAL VERIFICATION")
        print("=" * 80)
        
        # Check all required tables exist
        required_tables = ['machines', 'categories', 'machine_counts', 'warehouse_submissions']
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        all_tables = {row[0] for row in c.fetchall()}
        
        print("\nRequired Tables:")
        all_present = True
        for table in required_tables:
            if table in all_tables:
                print(f"  ✓ {table}")
            else:
                print(f"  ✗ {table} - MISSING!")
                all_present = False
        
        # Check required columns
        print("\nRequired Columns:")
        
        # warehouse_submissions
        c.execute("PRAGMA table_info(warehouse_submissions)")
        ws_cols = {row[1] for row in c.fetchall()}
        for col in ['bag_id', 'needs_review']:
            status = "✓" if col in ws_cols else "✗"
            print(f"  {status} warehouse_submissions.{col}")
            if col not in ws_cols:
                all_present = False
        
        # machine_counts
        c.execute("PRAGMA table_info(machine_counts)")
        mc_cols = {row[1] for row in c.fetchall()}
        for col in ['machine_id', 'box_number', 'bag_number']:
            status = "✓" if col in mc_cols else "✗"
            print(f"  {status} machine_counts.{col}")
            if col not in mc_cols:
                all_present = False
        
        # Data counts
        print("\nData Summary:")
        c.execute('SELECT COUNT(*) FROM warehouse_submissions')
        print(f"  • Submissions: {c.fetchone()[0]}")
        
        c.execute('SELECT COUNT(*) FROM purchase_orders')
        print(f"  • Purchase Orders: {c.fetchone()[0]}")
        
        c.execute('SELECT COUNT(*) FROM machines')
        print(f"  • Machines: {c.fetchone()[0]}")
        
        c.execute('SELECT COUNT(*) FROM categories WHERE is_active = TRUE')
        print(f"  • Active Categories: {c.fetchone()[0]}")
        
        print()
        print("=" * 80)
        if all_present and migration_log:
            print("✅ MIGRATION COMPLETE - ALL CHANGES APPLIED")
        elif all_present:
            print("✅ VERIFICATION COMPLETE - NO CHANGES NEEDED")
        else:
            print("⚠️  MIGRATION COMPLETE - SOME ISSUES REMAIN")
        print("=" * 80)
        
        if migration_log:
            print("\nChanges Applied:")
            for item in migration_log:
                print(f"  • {item}")
        
        return True
        
    except Exception as e:
        print()
        print("=" * 80)
        print("❌ MIGRATION FAILED")
        print("=" * 80)
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        return False
        
    finally:
        conn.close()


if __name__ == '__main__':
    db_path = sys.argv[1] if len(sys.argv) > 1 else 'tablet_counter.db'
    success = run_comprehensive_migration(db_path)
    sys.exit(0 if success else 1)

