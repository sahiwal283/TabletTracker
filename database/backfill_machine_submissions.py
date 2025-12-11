#!/usr/bin/env python3
"""
Backfill turns and cards_made for machine submissions
For machine submissions:
- displays_made = machine_count (turns)
- packs_remaining = machine_count * cards_per_turn (cards made)
- loose_tablets = total_tablets (machine_count * cards_per_turn * tablets_per_package)
"""
import sqlite3
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config

def backfill_machine_submissions():
    db_path = Config.DATABASE_PATH
    
    print("=" * 80)
    print("BACKFILL MACHINE SUBMISSIONS - TURNS & CARDS MADE")
    print("=" * 80)
    print(f"Database: {db_path}")
    print()
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get cards_per_turn setting (default to 1 if not set)
    cursor.execute("SELECT setting_value FROM app_settings WHERE setting_key = 'cards_per_turn'")
    cards_per_turn_setting = cursor.fetchone()
    cards_per_turn = int(cards_per_turn_setting['setting_value']) if cards_per_turn_setting else 1
    
    print(f"Cards per turn setting: {cards_per_turn}")
    print()
    
    # Get all machine submissions
    cursor.execute("""
        SELECT ws.id, ws.product_name, ws.displays_made, ws.packs_remaining, 
               ws.loose_tablets, ws.created_at, ws.submission_date,
               pd.tablets_per_package, pd.tablet_type_id
        FROM warehouse_submissions ws
        LEFT JOIN product_details pd ON ws.product_name = pd.product_name
        WHERE ws.submission_type = 'machine'
        ORDER BY ws.created_at
    """)
    
    machine_subs = cursor.fetchall()
    
    print(f"Found {len(machine_subs)} machine submissions")
    print()
    
    if not machine_subs:
        print("⚠️  No machine submissions found")
        conn.close()
        return
    
    print("BEFORE BACKFILL:")
    print("-" * 80)
    print(f"{'ID':<5} {'Product':<30} {'Turns':<8} {'Cards':<8} {'Total':<8} {'Status'}")
    print("-" * 80)
    
    needs_backfill = []
    for sub in machine_subs:
        turns = sub['displays_made'] or 0
        cards = sub['packs_remaining'] or 0
        total = sub['loose_tablets'] or 0
        tablets_per_pkg = sub['tablets_per_package'] or 0
        
        # Check if values need backfilling
        # If turns is 0 but we have total tablets, we can calculate backwards
        # If cards is 0 but we have turns, we can calculate
        needs_fix = False
        
        if turns == 0 and total > 0 and tablets_per_pkg > 0:
            # Can calculate: turns = total / (cards_per_turn * tablets_per_package)
            needs_fix = True
        elif cards == 0 and turns > 0:
            # Can calculate: cards = turns * cards_per_turn
            needs_fix = True
        elif total == 0 and turns > 0 and tablets_per_pkg > 0:
            # Can calculate: total = turns * cards_per_turn * tablets_per_package
            needs_fix = True
        
        status = "✓ OK" if not needs_fix else "✗ NEEDS FIX"
        if needs_fix:
            needs_backfill.append(sub)
        
        print(f"{sub['id']:<5} {sub['product_name'][:28]:<30} {turns:<8} {cards:<8} {total:<8} {status}")
    
    print()
    print("=" * 80)
    print()
    
    if not needs_backfill:
        print("✅ All machine submissions already have correct values!")
        conn.close()
        return
    
    print(f"BACKFILLING {len(needs_backfill)} submission(s)...")
    print("-" * 80)
    
    updated = 0
    for sub in needs_backfill:
        sub_id = sub['id']
        turns = sub['displays_made'] or 0
        cards = sub['packs_remaining'] or 0
        total = sub['loose_tablets'] or 0
        tablets_per_pkg = sub['tablets_per_package'] or 0
        
        new_turns = turns
        new_cards = cards
        new_total = total
        
        # Strategy 1: If we have total tablets, calculate backwards
        if total > 0 and tablets_per_pkg > 0 and cards_per_turn > 0:
            if turns == 0:
                # Calculate turns from total: turns = total / (cards_per_turn * tablets_per_package)
                new_turns = total // (cards_per_turn * tablets_per_pkg)
                if new_turns > 0:
                    new_cards = new_turns * cards_per_turn
                    print(f"  Submission {sub_id}: Calculated {new_turns} turns from {total} tablets")
            elif cards == 0 and turns > 0:
                # Calculate cards from turns
                new_cards = turns * cards_per_turn
                new_total = turns * cards_per_turn * tablets_per_pkg
                print(f"  Submission {sub_id}: Calculated {new_cards} cards from {turns} turns")
            elif total == 0 and turns > 0:
                # Calculate total from turns
                new_cards = turns * cards_per_turn
                new_total = turns * cards_per_turn * tablets_per_pkg
                print(f"  Submission {sub_id}: Calculated {new_total} total from {turns} turns")
        
        # Strategy 2: Try to get from machine_counts table if available
        if new_turns == 0:
            # Try to find matching machine_count record
            cursor.execute("""
                SELECT mc.machine_count
                FROM machine_counts mc
                JOIN product_details pd ON mc.tablet_type_id = pd.tablet_type_id
                WHERE pd.product_name = ?
                AND DATE(mc.count_date) = DATE(?)
                ORDER BY mc.count_date DESC
                LIMIT 1
            """, (sub['product_name'], sub['submission_date'] or sub['created_at']))
            
            mc_record = cursor.fetchone()
            if mc_record:
                new_turns = mc_record['machine_count']
                new_cards = new_turns * cards_per_turn
                if tablets_per_pkg > 0:
                    new_total = new_turns * cards_per_turn * tablets_per_pkg
                print(f"  Submission {sub_id}: Found machine_count {new_turns} from machine_counts table")
        
        # Update if values changed
        if new_turns != turns or new_cards != cards or new_total != total:
            try:
                cursor.execute("""
                    UPDATE warehouse_submissions
                    SET displays_made = ?,
                        packs_remaining = ?,
                        loose_tablets = ?
                    WHERE id = ?
                """, (new_turns, new_cards, new_total, sub_id))
                updated += 1
                print(f"    ✓ Updated: Turns={new_turns}, Cards={new_cards}, Total={new_total}")
            except Exception as e:
                print(f"    ✗ Error updating submission {sub_id}: {e}")
    
    conn.commit()
    
    print()
    print("=" * 80)
    print("AFTER BACKFILL:")
    print("-" * 80)
    
    # Show updated values
    cursor.execute("""
        SELECT id, product_name, displays_made, packs_remaining, loose_tablets
        FROM warehouse_submissions
        WHERE submission_type = 'machine'
        ORDER BY created_at
    """)
    
    updated_subs = cursor.fetchall()
    print(f"{'ID':<5} {'Product':<30} {'Turns':<8} {'Cards':<8} {'Total':<8}")
    print("-" * 80)
    for sub in updated_subs:
        print(f"{sub['id']:<5} {sub['product_name'][:28]:<30} {sub['displays_made']:<8} {sub['packs_remaining']:<8} {sub['loose_tablets']:<8}")
    
    print()
    print("=" * 80)
    print(f"✅ Updated {updated} machine submission(s)")
    print("=" * 80)
    
    conn.close()

if __name__ == '__main__':
    backfill_machine_submissions()

