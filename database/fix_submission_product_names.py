"""
Fix submission product names to match product_details

Updates old submission product names to match current product_details naming:
- "FIX MIT - Vimto" → "FIX MIT - Vimto 12ct"
- "Hyroxi MIT A - Pineapple" → "Hyroxi MIT A - Pineapple Express"
- etc.

This ensures calculations work correctly without relying on fragile string matching.
"""
import sqlite3
from config import Config

def fix_submission_product_names():
    print("🔧 Fixing submission product names to match product_details...")
    
    conn = sqlite3.connect(Config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    
    try:
        # Define mappings from old names to new names
        # Based on query results showing mismatches
        name_mappings = {
            'FIX MIT - Vimto': 'FIX MIT - Vimto 12ct',
            'Hyroxi MIT A - Pineapple': 'Hyroxi MIT A - Pineapple Express',
            'FIX MIT - Blue Magic': 'FIX MIT - Blue Magic 12ct',
            'FIX MIT - Pina Royale': 'FIX MIT - Pina Royale 12ct',
            'FIX MIT - Pink Karma': 'FIX MIT - Pink Karma 12ct',
            'FIX MIT - Just Peachy': 'FIX MIT - Just Peachy 12ct',
            'FIX MIT - Spear-Mit': 'FIX MIT - Spear-Mit 12ct',
            'Hyroxi Mit A - Spearmint': 'Hyroxi MIT A - Spearmint',
            'Hyroxi Mit A - Mango Peach': 'Hyroxi MIT A - Mango Peach',
            'Hyroxi Mit A - Purple Haze': 'Hyroxi MIT A - Purple Haze',
            'Hyroxi Mit A - BlueRaz': 'Hyroxi MIT A - BlueRaz',
            'Hyroxi MIT A - Pink Rozay': 'Hyroxi MIT A - Pink Rosé',
        }
        
        total_updated = 0
        
        for old_name, new_name in name_mappings.items():
            # Check if the new product name exists in product_details
            check = conn.execute('''
                SELECT product_name FROM product_details WHERE product_name = ?
            ''', (new_name,)).fetchone()
            
            if not check:
                print(f"  ⚠️  Skipping '{old_name}' → '{new_name}' (target doesn't exist in product_details)")
                continue
            
            # Count how many submissions need updating
            count = conn.execute('''
                SELECT COUNT(*) as cnt FROM warehouse_submissions WHERE product_name = ?
            ''', (old_name,)).fetchone()
            
            if count and count['cnt'] > 0:
                # Update the submissions
                conn.execute('''
                    UPDATE warehouse_submissions 
                    SET product_name = ?
                    WHERE product_name = ?
                ''', (new_name, old_name))
                
                print(f"  ✅ Updated {count['cnt']} submissions: '{old_name}' → '{new_name}'")
                total_updated += count['cnt']
            else:
                print(f"  ℹ️  No submissions found with name: '{old_name}'")
        
        conn.commit()
        print(f"\n✅ Total submissions updated: {total_updated}")
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()

if __name__ == '__main__':
    fix_submission_product_names()
