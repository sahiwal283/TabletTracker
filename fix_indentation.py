#!/usr/bin/env python3
"""
Fix indentation error in production.py on PythonAnywhere
Run this script on PythonAnywhere if git pull doesn't fix the indentation
"""

def fix_indentation():
    file_path = 'app/blueprints/production.py'
    
    print("Reading production.py...")
    with open(file_path, 'r') as f:
        lines = f.readlines()
    
    # Check current indentation
    line527 = lines[526]
    spaces = len(line527) - len(line527.lstrip())
    print(f"Line 527 currently has {spaces} leading spaces")
    
    if spaces == 12:
        print("✅ Indentation is already correct!")
        return
    
    print(f"❌ Fixing indentation (need 12 spaces, have {spaces})")
    
    # Fix the indentation - lines 527-531 need 12 spaces (3 levels)
    lines[526] = '            cards_per_turn_setting = get_setting(\'cards_per_turn\', \'1\')\n'
    lines[527] = '            try:\n'
    lines[528] = '                cards_per_turn = int(cards_per_turn_setting)\n'
    lines[529] = '            except (ValueError, TypeError):\n'
    lines[530] = '                cards_per_turn = 1\n'
    
    print("Writing fixed file...")
    with open(file_path, 'w') as f:
        f.writelines(lines)
    
    # Verify
    print("Verifying...")
    with open(file_path, 'r') as f:
        lines = f.readlines()
    line527 = lines[526]
    spaces = len(line527) - len(line527.lstrip())
    
    if spaces == 12:
        print("✅ Fix applied successfully!")
        print("\nNext step: Reload your web app on PythonAnywhere")
        return True
    else:
        print(f"❌ Fix failed - line 527 still has {spaces} spaces")
        return False

if __name__ == '__main__':
    fix_indentation()

