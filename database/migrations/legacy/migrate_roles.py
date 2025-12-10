#!/usr/bin/env python3
"""
Database migration to add role-based access control to employees table
"""

import sqlite3
import sys
from datetime import datetime

def migrate_add_roles():
    """Add role column to employees table and create roles table"""
    try:
        conn = sqlite3.connect('tablet_counter.db')
        cursor = conn.cursor()
        
        print("🔧 Starting role-based access control migration...")
        
        # Check if role column already exists
        cursor.execute("PRAGMA table_info(employees)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'role' not in columns:
            print("📝 Adding role column to employees table...")
            cursor.execute('''
                ALTER TABLE employees 
                ADD COLUMN role TEXT DEFAULT 'warehouse_staff'
            ''')
            
            # Update existing employees to have default role
            cursor.execute('''
                UPDATE employees 
                SET role = 'warehouse_staff' 
                WHERE role IS NULL OR role = ''
            ''')
        else:
            print("✅ Role column already exists in employees table")
        
        # Create roles table for role definitions
        print("📋 Creating roles table...")
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role_name TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL,
                permissions TEXT NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Insert default roles
        roles = [
            ('warehouse_staff', 'Warehouse Staff', 'warehouse,count', 'Can submit warehouse counts and view basic info'),
            ('supervisor', 'Supervisor', 'warehouse,count,dashboard,shipping', 'Can access warehouse operations, dashboard, and shipping'),
            ('manager', 'Manager', 'warehouse,count,dashboard,shipping,reports', 'Can access all operations except admin functions'),
            ('admin', 'Administrator', 'all', 'Full system access including employee management and configuration')
        ]
        
        for role_name, display_name, permissions, description in roles:
            cursor.execute('''
                INSERT OR REPLACE INTO roles (role_name, display_name, permissions, description)
                VALUES (?, ?, ?, ?)
            ''', (role_name, display_name, permissions, description))
        
        conn.commit()
        print("✅ Migration completed successfully!")
        
        # Show current employee roles
        print("\n📊 Current employees and their roles:")
        cursor.execute('''
            SELECT username, full_name, role, is_active 
            FROM employees 
            ORDER BY role, username
        ''')
        employees = cursor.fetchall()
        
        if employees:
            print(f"{'Username':<15} {'Name':<20} {'Role':<15} {'Active'}")
            print("-" * 65)
            for username, full_name, role, is_active in employees:
                status = "✅" if is_active else "❌"
                print(f"{username:<15} {full_name:<20} {role:<15} {status}")
        else:
            print("No employees found in database")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Migration failed: {str(e)}")
        return False

if __name__ == "__main__":
    success = migrate_add_roles()
    sys.exit(0 if success else 1)
