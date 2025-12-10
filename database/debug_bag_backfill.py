#!/usr/bin/env python3
"""
Debug why bag_id backfill isn't working - check actual data relationships
"""
import sqlite3
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config

def debug_bag_backfill():
    db_path = Config.DATABASE_PATH
    
    print("=" * 80)
    print("DEBUGGING BAG_ID BACKFILL")
    print("=" * 80)
    print(f"Database: {db_path}")
    print()
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get a sample submission that's missing bag_id
    print("SAMPLE SUBMISSION MISSING bag_id:")
    print("-" * 80)
    cursor.execute("""
        SELECT id, employee_name, product_name, bag_number, assigned_po_id, 
               box_number, created_at, bag_id
        FROM warehouse_submissions 
        WHERE bag_id IS NULL
        LIMIT 3
    """)
    samples = cursor.fetchall()
    
    for sample in samples:
        print(f"\nSubmission ID {sample['id']}:")
        print(f"  Product: {sample['product_name']}")
        print(f"  PO: {sample['assigned_po_id']}")
        print(f"  Box: {sample['box_number']}, Bag: {sample['bag_number']}")
        print(f"  Created: {sample['created_at']}")
        print(f"  Current bag_id: {sample['bag_id']}")
        
        # Check if there are any bags for this PO
        if sample['assigned_po_id']:
            print(f"\n  Checking for bags with PO {sample['assigned_po_id']}, Bag #{sample['bag_number']}:")
            
            # Check receiving records for this PO
            cursor.execute("""
                SELECT id, po_id, received_date, total_small_boxes
                FROM receiving
                WHERE po_id = ?
            """, (sample['assigned_po_id'],))
            receiving_recs = cursor.fetchall()
            
            if receiving_recs:
                print(f"    ✓ Found {len(receiving_recs)} receiving record(s)")
                for rec in receiving_recs:
                    print(f"      Receiving ID {rec['id']}: {rec['total_small_boxes']} boxes, {rec['received_date']}")
                    
                    # Check small boxes
                    cursor.execute("""
                        SELECT id, box_number, total_bags
                        FROM small_boxes
                        WHERE receiving_id = ?
                    """, (rec['id'],))
                    boxes = cursor.fetchall()
                    
                    if boxes:
                        print(f"        Found {len(boxes)} small box(es):")
                        for box in boxes:
                            print(f"          Box {box['box_number']}: {box['total_bags']} bags")
                            
                            # Check bags in this box
                            cursor.execute("""
                                SELECT id, bag_number, bag_label_count, status
                                FROM bags
                                WHERE small_box_id = ?
                            """, (box['id'],))
                            bags = cursor.fetchall()
                            
                            if bags:
                                print(f"            Found {len(bags)} bag(s):")
                                for bag in bags:
                                    match = "✓ MATCHES!" if bag['bag_number'] == sample['bag_number'] else ""
                                    print(f"              Bag #{bag['bag_number']} (ID: {bag['id']}) {match}")
                            else:
                                print(f"            No bags found in box {box['box_number']}")
                    else:
                        print(f"        No small boxes found")
            else:
                print(f"    ✗ No receiving records found for PO {sample['assigned_po_id']}")
    
    print()
    print("=" * 80)
    print()
    
    # Try the actual backfill query to see what happens
    print("TESTING BACKFILL QUERY:")
    print("-" * 80)
    
    if samples:
        sample = samples[0]
        if sample['assigned_po_id'] and sample['bag_number']:
            print(f"Testing with Submission ID {sample['id']}:")
            print(f"  PO: {sample['assigned_po_id']}, Bag #: {sample['bag_number']}")
            
            # Run the backfill query to see what it finds
            cursor.execute("""
                SELECT b.id as bag_id, b.bag_number, sb.box_number, r.po_id
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN receiving r ON sb.receiving_id = r.id
                WHERE b.bag_number = ?
                AND r.po_id = ?
                LIMIT 1
            """, (sample['bag_number'], sample['assigned_po_id']))
            
            match = cursor.fetchone()
            if match:
                print(f"  ✓ Query found matching bag:")
                print(f"    Bag ID: {match['bag_id']}")
                print(f"    Bag #: {match['bag_number']}")
                print(f"    Box #: {match['box_number']}")
                print(f"    PO: {match['po_id']}")
            else:
                print(f"  ✗ Query found NO matching bag")
                print(f"  This means the bag doesn't exist in the receiving system")
    
    print()
    print("=" * 80)
    print()
    
    # Summary
    print("SUMMARY:")
    print("-" * 80)
    cursor.execute("SELECT COUNT(*) FROM bags")
    total_bags = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM receiving")
    total_receiving = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM warehouse_submissions WHERE bag_id IS NULL")
    missing_bag_id = cursor.fetchone()[0]
    
    print(f"Total bags in database: {total_bags}")
    print(f"Total receiving records: {total_receiving}")
    print(f"Submissions missing bag_id: {missing_bag_id}")
    print()
    
    if total_bags == 0:
        print("⚠️  NO BAGS EXIST in the database")
        print("   These submissions were created before bags were received")
        print("   bag_id = NULL is CORRECT - no backfill possible")
    elif missing_bag_id > 0:
        print("⚠️  Some submissions can't be matched to bags")
        print("   Possible reasons:")
        print("   1. Bags haven't been created in receiving yet")
        print("   2. Bag numbers don't match")
        print("   3. PO assignments don't match")
        print("   4. Submissions predate the receiving system")
    
    print("=" * 80)
    
    conn.close()

if __name__ == '__main__':
    debug_bag_backfill()

