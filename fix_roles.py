#!/usr/bin/env python3
"""
Fix empty roles in the employees table
Run this script to assign default roles to existing employees
"""

import sqlite3
import sys

def fix_empty_roles():
    """Update employees with empty/null roles to have default warehouse_staff role"""
    try:
        conn = sqlite3.connect('tablet_counter.db')
        conn.row_factory = sqlite3.Row
        
        # Find employees with empty/null roles
        empty_roles = conn.execute('''
            SELECT id, username, full_name, role 
            FROM employees 
            WHERE role IS NULL OR role = ''
        ''').fetchall()
        
        if not empty_roles:
            print("✅ All employees have valid roles!")
            conn.close()
            return
        
        print(f"🔧 Found {len(empty_roles)} employees with empty roles:")
        for emp in empty_roles:
            print(f"  - {emp['username']} ({emp['full_name']}) - role: '{emp['role']}'")
        
        # Update empty roles to warehouse_staff
        conn.execute('''
            UPDATE employees 
            SET role = 'warehouse_staff' 
            WHERE role IS NULL OR role = ''
        ''')
        
        updated_count = conn.total_changes
        conn.commit()
        
        print(f"✅ Updated {updated_count} employees to 'warehouse_staff' role")
        print("\n📝 To set specific roles:")
        print("   - Use Admin Panel > Manage Employees")
        print("   - Or visit /debug-session to check roles")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Error fixing roles: {e}")
        sys.exit(1)

if __name__ == '__main__':
    fix_empty_roles()
