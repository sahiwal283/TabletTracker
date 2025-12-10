#!/usr/bin/env python3
"""
Analyze the relationship between warehouse_submissions and bags/receiving
to understand if bag_id should be set or if NULL is acceptable
"""
import sqlite3
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config

def analyze_bag_relationship():
    db_path = Config.DATABASE_PATH
    
    print("=" * 80)
    print("ANALYZING BAG_ID RELATIONSHIP")
    print("=" * 80)
    print(f"Database: {db_path}")
    print()
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Check total submissions
    cursor.execute("SELECT COUNT(*) FROM warehouse_submissions")
    total = cursor.fetchone()[0]
    
    # Check submissions with bag_id
    cursor.execute("SELECT COUNT(*) FROM warehouse_submissions WHERE bag_id IS NOT NULL")
    with_bag_id = cursor.fetchone()[0]
    
    # Check submissions without bag_id
    cursor.execute("SELECT COUNT(*) FROM warehouse_submissions WHERE bag_id IS NULL")
    without_bag_id = cursor.fetchone()[0]
    
    print("OVERVIEW:")
    print("-" * 80)
    print(f"Total submissions: {total}")
    print(f"With bag_id: {with_bag_id}")
    print(f"Without bag_id: {without_bag_id}")
    print()
    
    # Check if there are any bags at all
    cursor.execute("SELECT COUNT(*) FROM bags")
    total_bags = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM receiving")
    total_receiving = cursor.fetchone()[0]
    
    print("RECEIVING SYSTEM:")
    print("-" * 80)
    print(f"Total receiving records: {total_receiving}")
    print(f"Total bags: {total_bags}")
    print()
    
    # Check submissions that have assigned_po_id
    cursor.execute("SELECT COUNT(*) FROM warehouse_submissions WHERE assigned_po_id IS NOT NULL")
    with_po = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM warehouse_submissions WHERE assigned_po_id IS NULL")
    without_po = cursor.fetchone()[0]
    
    print("PURCHASE ORDER ASSIGNMENTS:")
    print("-" * 80)
    print(f"Submissions with assigned_po_id: {with_po}")
    print(f"Submissions without assigned_po_id: {without_po}")
    print()
    
    # Check if submissions without bag_id have assigned_po_id
    cursor.execute("""
        SELECT COUNT(*) 
        FROM warehouse_submissions 
        WHERE bag_id IS NULL AND assigned_po_id IS NOT NULL
    """)
    missing_bag_with_po = cursor.fetchone()[0]
    
    print("SUBMISSIONS MISSING bag_id:")
    print("-" * 80)
    print(f"Total missing bag_id: {without_bag_id}")
    print(f"Missing bag_id but have assigned_po_id: {missing_bag_with_po}")
    print(f"Missing bag_id and no assigned_po_id: {without_bag_id - missing_bag_with_po}")
    print()
    
    # Check if any bags exist for the POs that have submissions
    if missing_bag_with_po > 0:
        print("CHECKING FOR MATCHING BAGS:")
        print("-" * 80)
        cursor.execute("""
            SELECT DISTINCT ws.assigned_po_id, ws.bag_number, COUNT(*) as count
            FROM warehouse_submissions ws
            WHERE ws.bag_id IS NULL 
            AND ws.assigned_po_id IS NOT NULL
            GROUP BY ws.assigned_po_id, ws.bag_number
            LIMIT 10
        """)
        examples = cursor.fetchall()
        
        if examples:
            print("Sample submissions missing bag_id:")
            for row in examples:
                po_id = row['assigned_po_id']
                bag_num = row['bag_number']
                count = row['count']
                
                # Check if there are any bags for this PO
                cursor.execute("""
                    SELECT COUNT(*) 
                    FROM bags b
                    JOIN small_boxes sb ON b.small_box_id = sb.id
                    JOIN receiving r ON sb.receiving_id = r.id
                    WHERE r.po_id = ? AND b.bag_number = ?
                """, (po_id, bag_num))
                matching_bags = cursor.fetchone()[0]
                
                status = "✓ Has matching bags" if matching_bags > 0 else "✗ No matching bags"
                print(f"  PO {po_id}, Bag #{bag_num}: {count} submissions - {status}")
        print()
    
    # Check date ranges
    print("DATE ANALYSIS:")
    print("-" * 80)
    cursor.execute("""
        SELECT 
            MIN(created_at) as earliest,
            MAX(created_at) as latest
        FROM warehouse_submissions
        WHERE bag_id IS NULL
    """)
    date_range = cursor.fetchone()
    
    if date_range and date_range['earliest']:
        print(f"Submissions missing bag_id date range:")
        print(f"  Earliest: {date_range['earliest']}")
        print(f"  Latest: {date_range['latest']}")
    
    cursor.execute("""
        SELECT 
            MIN(created_at) as earliest,
            MAX(created_at) as latest
        FROM receiving
    """)
    receiving_range = cursor.fetchone()
    
    if receiving_range and receiving_range['earliest']:
        print(f"\nReceiving records date range:")
        print(f"  Earliest: {receiving_range['earliest']}")
        print(f"  Latest: {receiving_range['latest']}")
    else:
        print("\n⚠️  No receiving records found - receiving system may not be in use yet")
    
    print()
    print("=" * 80)
    print()
    
    # Conclusion
    print("CONCLUSION:")
    print("-" * 80)
    
    if total_bags == 0:
        print("⚠️  No bags exist in the database")
        print("   These submissions were created before the receiving/bags system")
        print("   bag_id = NULL is CORRECT for these submissions")
        print("   No backfill needed - NULL is the expected value")
    elif missing_bag_with_po > 0 and total_bags > 0:
        print("⚠️  Some submissions have POs but no matching bags")
        print("   This could mean:")
        print("   1. Bags haven't been created in receiving yet")
        print("   2. Submissions were created before bags were received")
        print("   3. bag_id should remain NULL until bags are received")
    else:
        print("✅ All submissions that should have bag_id have it")
        print("   Remaining NULL values are expected (pre-receiving system)")
    
    print("=" * 80)
    
    conn.close()

if __name__ == '__main__':
    analyze_bag_relationship()

