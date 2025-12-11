#!/usr/bin/env python3
"""
Check machine submissions and verify turns/cards_made are correct
"""
import sqlite3
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config

def check_machine_submissions():
    db_path = Config.DATABASE_PATH
    
    print("=" * 80)
    print("CHECKING MACHINE SUBMISSIONS")
    print("=" * 80)
    print(f"Database: {db_path}")
    print()
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get all machine submissions
    cursor.execute("""
        SELECT ws.id, ws.employee_name, ws.product_name, ws.created_at,
               ws.displays_made, ws.packs_remaining, ws.loose_tablets,
               ws.submission_type, mc.machine_count, mc.machine_id
        FROM warehouse_submissions ws
        LEFT JOIN machine_counts mc ON ws.product_name = (
            SELECT pd.product_name 
            FROM product_details pd 
            JOIN tablet_types tt ON pd.tablet_type_id = tt.id 
            WHERE tt.id = mc.tablet_type_id 
            LIMIT 1
        )
        WHERE ws.submission_type = 'machine'
        ORDER BY ws.created_at DESC
    """)
    
    machine_subs = cursor.fetchall()
    
    print(f"Total machine submissions: {len(machine_subs)}")
    print()
    
    if not machine_subs:
        print("⚠️  No machine submissions found")
        conn.close()
        return
    
    print("MACHINE SUBMISSIONS:")
    print("-" * 80)
    print(f"{'ID':<5} {'Product':<30} {'Turns':<8} {'Cards':<8} {'Total':<8} {'Machine Count'}")
    print("-" * 80)
    
    issues = []
    for sub in machine_subs:
        turns = sub['displays_made'] or 0
        cards = sub['packs_remaining'] or 0
        total = sub['loose_tablets'] or 0
        mc_count = sub['machine_count'] or 0
        
        # Check if values look correct
        # For machine submissions:
        # - displays_made should = machine_count (turns)
        # - packs_remaining should = machine_count * cards_per_turn (cards made)
        # - loose_tablets should = total tablets
        
        status = "✓"
        if mc_count > 0:
            if turns != mc_count:
                status = "✗"
                issues.append(f"ID {sub['id']}: Turns ({turns}) != machine_count ({mc_count})")
        
        print(f"{sub['id']:<5} {sub['product_name'][:28]:<30} {turns:<8} {cards:<8} {total:<8} {mc_count}")
    
    print()
    print("=" * 80)
    print()
    
    # Check machine_counts table
    print("MACHINE_COUNTS TABLE:")
    print("-" * 80)
    cursor.execute("""
        SELECT mc.id, mc.machine_count, mc.employee_name, mc.count_date,
               tt.tablet_type_name, mc.machine_id
        FROM machine_counts mc
        LEFT JOIN tablet_types tt ON mc.tablet_type_id = tt.id
        ORDER BY mc.count_date DESC
        LIMIT 10
    """)
    mc_records = cursor.fetchall()
    
    print(f"Total machine_counts records: {len(mc_records)}")
    if mc_records:
        print("\nRecent machine_counts:")
        for mc in mc_records:
            print(f"  ID {mc['id']}: {mc['machine_count']} turns, {mc['tablet_type_name']}, {mc['count_date']}")
    
    print()
    print("=" * 80)
    
    if issues:
        print("\n⚠️  ISSUES FOUND:")
        for issue in issues:
            print(f"  • {issue}")
    else:
        print("\n✅ All machine submissions look correct")
    
    print("=" * 80)
    
    conn.close()

if __name__ == '__main__':
    check_machine_submissions()

