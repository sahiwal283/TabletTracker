#!/usr/bin/env python3
"""
Verify machine submission backfill - check actual data
"""
import sqlite3
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config

def verify_backfill():
    db_path = Config.DATABASE_PATH
    
    print("=" * 80)
    print("VERIFYING MACHINE SUBMISSION BACKFILL")
    print("=" * 80)
    print(f"Database: {db_path}")
    print()
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get all machine submissions (simple query, no JOIN)
    cursor.execute("""
        SELECT id, employee_name, product_name, 
               displays_made, packs_remaining, loose_tablets,
               created_at, submission_date, submission_type
        FROM warehouse_submissions
        WHERE submission_type = 'machine'
        ORDER BY created_at
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
    print(f"{'ID':<5} {'Product':<35} {'Turns':<8} {'Cards':<8} {'Total':<10} {'Date'}")
    print("-" * 80)
    
    all_correct = True
    for sub in machine_subs:
        turns = sub['displays_made'] or 0
        cards = sub['packs_remaining'] or 0
        total = sub['loose_tablets'] or 0
        
        # Get product details for validation
        cursor.execute("""
            SELECT tablets_per_package
            FROM product_details
            WHERE product_name = ?
            LIMIT 1
        """, (sub['product_name'],))
        pd = cursor.fetchone()
        tablets_per_pkg = pd['tablets_per_package'] if pd else 0
        
        # Get cards_per_turn
        cursor.execute("SELECT setting_value FROM app_settings WHERE setting_key = 'cards_per_turn'")
        cpt_setting = cursor.fetchone()
        cards_per_turn = int(cpt_setting['setting_value']) if cpt_setting else 6
        
        # Validate the values
        status = "✓"
        issues = []
        
        if turns == 0:
            status = "✗"
            issues.append("Turns = 0")
            all_correct = False
        elif cards == 0:
            status = "✗"
            issues.append("Cards = 0")
            all_correct = False
        else:
            # Check if cards = turns * cards_per_turn
            expected_cards = turns * cards_per_turn
            if cards != expected_cards:
                status = "⚠️"
                issues.append(f"Cards should be {expected_cards}, got {cards}")
            
            # Check if total = turns * cards_per_turn * tablets_per_package
            if tablets_per_pkg > 0:
                expected_total = turns * cards_per_turn * tablets_per_pkg
                if total != expected_total:
                    status = "⚠️"
                    issues.append(f"Total should be {expected_total}, got {total}")
        
        date_str = (sub['submission_date'] or sub['created_at'])[:10]
        print(f"{sub['id']:<5} {sub['product_name'][:33]:<35} {turns:<8} {cards:<8} {total:<10} {date_str} {status}")
        if issues:
            for issue in issues:
                print(f"      ⚠️  {issue}")
    
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
        ORDER BY mc.count_date DESC, mc.id DESC
    """)
    mc_records = cursor.fetchall()
    
    print(f"Total machine_counts records: {len(mc_records)}")
    if mc_records:
        print("\nAll machine_counts:")
        for mc in mc_records:
            print(f"  ID {mc['id']}: {mc['machine_count']} turns, {mc['tablet_type_name']}, {mc['count_date']}, Machine ID: {mc['machine_id']}")
    
    print()
    print("=" * 80)
    print()
    
    # Summary
    if all_correct:
        print("✅ All machine submissions have correct turns and cards_made values!")
    else:
        print("⚠️  Some machine submissions need backfilling")
        print("   Run: python3 database/backfill_machine_submissions.py")
    
    print("=" * 80)
    
    conn.close()

if __name__ == '__main__':
    verify_backfill()

