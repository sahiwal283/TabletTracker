#!/usr/bin/env python3
"""
Verify which submissions should have bag_id vs which correctly have NULL
"""
import sqlite3
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config

def verify_bag_assignments():
    db_path = Config.DATABASE_PATH
    
    print("=" * 80)
    print("VERIFYING BAG_ID ASSIGNMENTS")
    print("=" * 80)
    print(f"Database: {db_path}")
    print()
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get all bags with their relationships
    print("EXISTING BAGS IN DATABASE:")
    print("-" * 80)
    cursor.execute("""
        SELECT b.id as bag_id, b.bag_number, b.status,
               sb.box_number as box_num, sb.id as box_id,
               r.po_id, r.received_date
        FROM bags b
        JOIN small_boxes sb ON b.small_box_id = sb.id
        JOIN receiving r ON sb.receiving_id = r.id
        ORDER BY r.po_id, sb.box_number, b.bag_number
    """)
    bags = cursor.fetchall()
    
    if bags:
        print(f"Found {len(bags)} bags:")
        for bag in bags:
            print(f"  Bag ID {bag['bag_id']}: Bag #{bag['bag_number']} in Box {bag['box_num']}")
            print(f"    PO: {bag['po_id']}, Received: {bag['received_date']}, Status: {bag['status']}")
            
            # Check if any submissions should link to this bag
            cursor.execute("""
                SELECT id, product_name, employee_name, created_at, bag_id
                FROM warehouse_submissions
                WHERE assigned_po_id = ? 
                AND bag_number = ?
                AND box_number = ?
            """, (bag['po_id'], bag['bag_number'], bag['box_num']))
            matching_subs = cursor.fetchall()
            
            if matching_subs:
                print(f"    Matching submissions:")
                for sub in matching_subs:
                    has_bag = "✓" if sub['bag_id'] == bag['bag_id'] else "✗ MISSING"
                    print(f"      {has_bag} Submission {sub['id']}: {sub['product_name']} (bag_id: {sub['bag_id']})")
            else:
                print(f"    No matching submissions found")
            print()
    else:
        print("No bags found in database")
    
    print("=" * 80)
    print()
    
    # Check submissions that should have bags (those with matching PO, box, bag numbers)
    print("SUBMISSIONS THAT SHOULD HAVE BAGS:")
    print("-" * 80)
    
    if bags:
        for bag in bags:
            cursor.execute("""
                SELECT id, product_name, employee_name, created_at, bag_id,
                       assigned_po_id, box_number, bag_number
                FROM warehouse_submissions
                WHERE assigned_po_id = ? 
                AND bag_number = ?
                AND box_number = ?
            """, (bag['po_id'], bag['bag_number'], bag['box_num']))
            should_have_bag = cursor.fetchall()
            
            if should_have_bag:
                for sub in should_have_bag:
                    if sub['bag_id'] == bag['bag_id']:
                        print(f"  ✓ Submission {sub['id']}: Has correct bag_id {sub['bag_id']}")
                    else:
                        print(f"  ✗ Submission {sub['id']}: Missing bag_id (should be {bag['bag_id']})")
                        print(f"      Product: {sub['product_name']}")
                        print(f"      PO: {sub['assigned_po_id']}, Box: {sub['box_number']}, Bag: {sub['bag_number']}")
    else:
        print("  No bags exist - no submissions should have bag_id")
    
    print()
    print("=" * 80)
    print()
    
    # Summary
    print("SUMMARY:")
    print("-" * 80)
    
    cursor.execute("SELECT COUNT(*) FROM bags")
    total_bags = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM warehouse_submissions WHERE bag_id IS NOT NULL")
    subs_with_bag = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM warehouse_submissions WHERE bag_id IS NULL")
    subs_without_bag = cursor.fetchone()[0]
    
    print(f"Total bags in database: {total_bags}")
    print(f"Submissions with bag_id: {subs_with_bag}")
    print(f"Submissions without bag_id: {subs_without_bag}")
    print()
    
    if total_bags == 0:
        print("✅ All submissions correctly have bag_id = NULL (no bags exist)")
    elif subs_without_bag == 0:
        print("✅ All submissions that should have bag_id have it")
    else:
        print("⚠️  Some submissions may need bag_id assignment")
        print("   Run the fix script to assign bag_id where matches exist")
    
    print("=" * 80)
    
    conn.close()

if __name__ == '__main__':
    verify_bag_assignments()

