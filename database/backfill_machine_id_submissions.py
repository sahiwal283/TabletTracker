#!/usr/bin/env python3
"""
Backfill machine_id for existing machine submissions

This script matches existing machine submissions to machine_counts records
and populates the machine_id column in warehouse_submissions.
"""
import sqlite3
import sys
import os
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config

def backfill_machine_id_submissions(db_path=None):
    """Backfill machine_id for machine submissions"""
    
    if db_path is None:
        db_path = Config.DATABASE_PATH
    
    print("=" * 80)
    print("BACKFILL MACHINE_ID FOR MACHINE SUBMISSIONS")
    print("=" * 80)
    print(f"Database: {db_path}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    try:
        # Check if machine_id column exists in warehouse_submissions
        c.execute("PRAGMA table_info(warehouse_submissions)")
        ws_cols = [row[1] for row in c.fetchall()]
        
        if 'machine_id' not in ws_cols:
            print("⚠️  machine_id column does not exist in warehouse_submissions")
            print("   Please run migrations first to add the column.")
            return False
        
        # Check if machine_id column exists in machine_counts
        c.execute("PRAGMA table_info(machine_counts)")
        mc_cols = [row[1] for row in c.fetchall()]
        
        if 'machine_id' not in mc_cols:
            print("⚠️  machine_id column does not exist in machine_counts")
            print("   Please run migrations first to add the column.")
            return False
        
        # Get all machine submissions without machine_id
        c.execute('''
            SELECT ws.id, ws.employee_name, ws.product_name, ws.inventory_item_id,
                   ws.displays_made, ws.submission_date, ws.created_at,
                   ws.box_number, ws.bag_number
            FROM warehouse_submissions ws
            WHERE ws.submission_type = 'machine'
            AND ws.machine_id IS NULL
            ORDER BY ws.created_at
        ''')
        
        submissions = c.fetchall()
        
        print(f"Found {len(submissions)} machine submissions without machine_id")
        print()
        
        if not submissions:
            print("✅ All machine submissions already have machine_id")
            return True
        
        # Statistics
        matched_count = 0
        unmatched_count = 0
        multiple_matches = 0
        
        print("Processing submissions...")
        print("-" * 80)
        
        for sub in submissions:
            sub_id = sub['id']
            employee_name = sub['employee_name']
            product_name = sub['product_name']
            inventory_item_id = sub['inventory_item_id']
            displays_made = sub['displays_made']
            submission_date = sub['submission_date'] or sub['created_at']
            box_number = sub['box_number']
            bag_number = sub['bag_number']
            
            # Get tablet_type_id from inventory_item_id
            tablet_type_id = None
            if inventory_item_id:
                tablet_type_row = c.execute('''
                    SELECT id FROM tablet_types WHERE inventory_item_id = ?
                ''', (inventory_item_id,)).fetchone()
                if tablet_type_row:
                    tablet_type_id = tablet_type_row['id']
            
            # If we don't have tablet_type_id, try to get it from product_name
            if not tablet_type_id:
                product_row = c.execute('''
                    SELECT tablet_type_id FROM product_details WHERE product_name = ?
                ''', (product_name,)).fetchone()
                if product_row:
                    tablet_type_id = product_row['tablet_type_id']
            
            if not tablet_type_id:
                print(f"  ⚠️  Submission {sub_id}: Could not determine tablet_type_id")
                unmatched_count += 1
                continue
            
            # Try to find matching machine_counts record
            # Match on: tablet_type_id, machine_count (displays_made), employee_name, count_date
            # Also try to match on box_number and bag_number if available
            query = '''
                SELECT mc.id, mc.machine_id, mc.machine_count, mc.employee_name, mc.count_date,
                       mc.box_number, mc.bag_number
                FROM machine_counts mc
                WHERE mc.tablet_type_id = ?
                AND mc.machine_count = ?
                AND mc.employee_name = ?
                AND DATE(mc.count_date) = DATE(?)
            '''
            params = [tablet_type_id, displays_made, employee_name, submission_date]
            
            # If box_number and bag_number are available, try to match on those too
            if box_number and bag_number:
                query += ' AND (mc.box_number = ? OR mc.box_number IS NULL)'
                query += ' AND (mc.bag_number = ? OR mc.bag_number IS NULL)'
                params.extend([box_number, bag_number])
            
            query += ' ORDER BY mc.created_at DESC'
            
            matches = c.execute(query, params).fetchall()
            
            if not matches:
                # Try without date match (in case of timezone issues)
                query_no_date = '''
                    SELECT mc.id, mc.machine_id, mc.machine_count, mc.employee_name, mc.count_date,
                           mc.box_number, mc.bag_number
                    FROM machine_counts mc
                    WHERE mc.tablet_type_id = ?
                    AND mc.machine_count = ?
                    AND mc.employee_name = ?
                '''
                params_no_date = [tablet_type_id, displays_made, employee_name]
                
                if box_number and bag_number:
                    query_no_date += ' AND (mc.box_number = ? OR mc.box_number IS NULL)'
                    query_no_date += ' AND (mc.bag_number = ? OR mc.bag_number IS NULL)'
                    params_no_date.extend([box_number, bag_number])
                
                query_no_date += ' ORDER BY mc.created_at DESC LIMIT 1'
                matches = c.execute(query_no_date, params_no_date).fetchall()
            
            if len(matches) == 1:
                match = matches[0]
                machine_id = match['machine_id']
                
                if machine_id:
                    # Update the submission with machine_id
                    c.execute('''
                        UPDATE warehouse_submissions
                        SET machine_id = ?
                        WHERE id = ?
                    ''', (machine_id, sub_id))
                    
                    matched_count += 1
                    print(f"  ✓ Submission {sub_id}: Matched to machine_id {machine_id}")
                else:
                    print(f"  ⚠️  Submission {sub_id}: Matched machine_counts record but it has no machine_id")
                    unmatched_count += 1
            elif len(matches) > 1:
                # Multiple matches - use the most recent one with a machine_id
                machine_id = None
                for match in matches:
                    if match['machine_id']:
                        machine_id = match['machine_id']
                        break
                
                if machine_id:
                    c.execute('''
                        UPDATE warehouse_submissions
                        SET machine_id = ?
                        WHERE id = ?
                    ''', (machine_id, sub_id))
                    
                    matched_count += 1
                    multiple_matches += 1
                    print(f"  ⚠️  Submission {sub_id}: Multiple matches, used most recent machine_id {machine_id}")
                else:
                    print(f"  ⚠️  Submission {sub_id}: Multiple matches but none have machine_id")
                    unmatched_count += 1
            else:
                print(f"  ✗ Submission {sub_id}: No matching machine_counts record found")
                unmatched_count += 1
        
        conn.commit()
        
        print()
        print("=" * 80)
        print("BACKFILL SUMMARY")
        print("=" * 80)
        print(f"Total submissions processed: {len(submissions)}")
        print(f"  ✓ Successfully matched: {matched_count}")
        print(f"  ✗ Unmatched: {unmatched_count}")
        if multiple_matches > 0:
            print(f"  ⚠️  Multiple matches resolved: {multiple_matches}")
        print()
        
        # If there are unmatched submissions, try to assign a default machine
        if unmatched_count > 0:
            print()
            print("Attempting to assign default machine to unmatched submissions...")
            print("-" * 80)
            
            # Get the first active machine as default
            default_machine = c.execute('''
                SELECT id, machine_name FROM machines WHERE is_active = TRUE ORDER BY id LIMIT 1
            ''').fetchone()
            
            if default_machine:
                default_machine_id = default_machine['id']
                default_machine_name = default_machine['machine_name']
                print(f"Using default machine: {default_machine_name} (ID: {default_machine_id})")
                print()
                
                # Get the unmatched submissions again
                c.execute('''
                    SELECT ws.id, ws.employee_name, ws.product_name, ws.inventory_item_id,
                           ws.displays_made, ws.submission_date, ws.created_at,
                           ws.box_number, ws.bag_number
                    FROM warehouse_submissions ws
                    WHERE ws.submission_type = 'machine'
                    AND ws.machine_id IS NULL
                    ORDER BY ws.created_at
                ''')
                
                unmatched_subs = c.fetchall()
                default_assigned = 0
                
                for sub in unmatched_subs:
                    sub_id = sub['id']
                    
                    # Update warehouse_submissions with default machine
                    c.execute('''
                        UPDATE warehouse_submissions
                        SET machine_id = ?
                        WHERE id = ?
                    ''', (default_machine_id, sub_id))
                    
                    # Also try to update the corresponding machine_counts record if it exists
                    tablet_type_id = None
                    if sub['inventory_item_id']:
                        tablet_type_row = c.execute('''
                            SELECT id FROM tablet_types WHERE inventory_item_id = ?
                        ''', (sub['inventory_item_id'],)).fetchone()
                        if tablet_type_row:
                            tablet_type_id = tablet_type_row['id']
                    
                    if not tablet_type_id:
                        product_row = c.execute('''
                            SELECT tablet_type_id FROM product_details WHERE product_name = ?
                        ''', (sub['product_name'],)).fetchone()
                        if product_row:
                            tablet_type_id = product_row['tablet_type_id']
                    
                    if tablet_type_id:
                        # Update machine_counts if a matching record exists
                        submission_date = sub['submission_date'] or sub['created_at']
                        c.execute('''
                            UPDATE machine_counts
                            SET machine_id = ?
                            WHERE tablet_type_id = ?
                            AND machine_count = ?
                            AND employee_name = ?
                            AND DATE(count_date) = DATE(?)
                            AND machine_id IS NULL
                        ''', (default_machine_id, tablet_type_id, sub['displays_made'], 
                              sub['employee_name'], submission_date))
                    
                    default_assigned += 1
                    print(f"  ✓ Submission {sub_id}: Assigned default machine {default_machine_name}")
                
                if default_assigned > 0:
                    conn.commit()
                    matched_count += default_assigned
                    unmatched_count -= default_assigned
                    print()
                    print(f"✓ Assigned default machine to {default_assigned} submissions")
            
            print()
            print("=" * 80)
            print("FINAL BACKFILL SUMMARY")
            print("=" * 80)
            print(f"Total submissions processed: {len(submissions)}")
            print(f"  ✓ Successfully matched: {matched_count}")
            if unmatched_count > 0:
                print(f"  ✗ Unmatched: {unmatched_count}")
                print()
                print("⚠️  Some submissions could not be matched.")
                print("   This may be because:")
                print("   - No corresponding machine_counts record exists")
                print("   - Data mismatch (employee name, date, or count)")
            else:
                print("✅ All submissions successfully matched!")
        else:
            print("✅ All submissions successfully matched!")
        
        return True
        
    except Exception as e:
        print()
        print("=" * 80)
        print("❌ BACKFILL FAILED")
        print("=" * 80)
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        return False
        
    finally:
        conn.close()


if __name__ == '__main__':
    db_path = sys.argv[1] if len(sys.argv) > 1 else None
    success = backfill_machine_id_submissions(db_path)
    sys.exit(0 if success else 1)












