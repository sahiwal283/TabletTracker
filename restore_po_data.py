#!/usr/bin/env python3
"""
Restore PO line items and purchase order data from backup
"""
import sqlite3
import os

def main():
    backup_file = 'backups/tablet_counter.db.backup_20251104_165629'
    current_db = 'tablet_counter.db'
    
    print("=" * 70)
    print("Restoring PO Line Items & Purchase Order Data")
    print("=" * 70)
    print()
    
    backup_conn = sqlite3.connect(backup_file)
    current_conn = sqlite3.connect(current_db)
    
    backup_cursor = backup_conn.cursor()
    current_cursor = current_conn.cursor()
    
    # Check which tables exist in backup
    backup_cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    backup_tables = {row[0] for row in backup_cursor.fetchall()}
    
    # Restore po_lines table
    print("📋 Restoring po_lines table...")
    if 'po_lines' in backup_tables:
        try:
            # Get count from backup
            backup_cursor.execute("SELECT COUNT(*) FROM po_lines")
            backup_count = backup_cursor.fetchone()[0]
            print(f"   📊 Backup has {backup_count} line items")
            
            if backup_count > 0:
                # Get columns from current database
                current_cursor.execute("PRAGMA table_info(po_lines)")
                current_columns = [row[1] for row in current_cursor.fetchall()]
                
                # Get columns from backup database
                backup_cursor.execute("PRAGMA table_info(po_lines)")
                backup_columns = [row[1] for row in backup_cursor.fetchall()]
                
                # Find common columns
                common_columns = [col for col in backup_columns if col in current_columns]
                print(f"   📋 Common columns: {', '.join(common_columns)}")
                
                # Clear current data
                current_cursor.execute("DELETE FROM po_lines")
                
                # Copy data
                columns_str = ', '.join(common_columns)
                placeholders = ', '.join(['?' for _ in common_columns])
                
                backup_cursor.execute(f"SELECT {columns_str} FROM po_lines")
                rows = backup_cursor.fetchall()
                
                current_cursor.executemany(
                    f"INSERT INTO po_lines ({columns_str}) VALUES ({placeholders})",
                    rows
                )
                
                current_conn.commit()
                
                # Verify
                current_cursor.execute("SELECT COUNT(*) FROM po_lines")
                new_count = current_cursor.fetchone()[0]
                print(f"   ✅ Restored {new_count} line items")
            else:
                print(f"   ⏭️  Skipping (no data)")
        except Exception as e:
            print(f"   ❌ Error: {e}")
    else:
        print(f"   ⚠️  Table doesn't exist in backup")
    print()
    
    # Restore purchase_orders table (to get tablet_type and other PO data)
    print("📋 Restoring purchase_orders table...")
    if 'purchase_orders' in backup_tables:
        try:
            # Get count from backup
            backup_cursor.execute("SELECT COUNT(*) FROM purchase_orders")
            backup_count = backup_cursor.fetchone()[0]
            print(f"   📊 Backup has {backup_count} purchase orders")
            
            if backup_count > 0:
                # Get columns from current database
                current_cursor.execute("PRAGMA table_info(purchase_orders)")
                current_columns = [row[1] for row in current_cursor.fetchall()]
                
                # Get columns from backup database
                backup_cursor.execute("PRAGMA table_info(purchase_orders)")
                backup_columns = [row[1] for row in backup_cursor.fetchall()]
                
                # Find common columns (excluding id to avoid conflicts)
                common_columns = [col for col in backup_columns if col in current_columns and col != 'id']
                print(f"   📋 Common columns: {', '.join(common_columns)}")
                
                # For each PO in backup, update or insert in current
                backup_cursor.execute(f"SELECT id, {', '.join(common_columns)} FROM purchase_orders")
                rows = backup_cursor.fetchall()
                
                for row in rows:
                    backup_id = row[0]
                    values = row[1:]
                    
                    # Check if PO exists in current database
                    current_cursor.execute("SELECT id FROM purchase_orders WHERE id = ?", (backup_id,))
                    exists = current_cursor.fetchone()
                    
                    if exists:
                        # Update existing PO
                        set_clause = ', '.join([f"{col} = ?" for col in common_columns])
                        current_cursor.execute(
                            f"UPDATE purchase_orders SET {set_clause} WHERE id = ?",
                            (*values, backup_id)
                        )
                    else:
                        # Insert new PO
                        columns_with_id = ['id'] + common_columns
                        placeholders = ', '.join(['?' for _ in columns_with_id])
                        current_cursor.execute(
                            f"INSERT INTO purchase_orders ({', '.join(columns_with_id)}) VALUES ({placeholders})",
                            (backup_id, *values)
                        )
                
                current_conn.commit()
                
                # Verify
                current_cursor.execute("SELECT COUNT(*) FROM purchase_orders")
                new_count = current_cursor.fetchone()[0]
                print(f"   ✅ Total purchase orders: {new_count}")
            else:
                print(f"   ⏭️  Skipping (no data)")
        except Exception as e:
            print(f"   ❌ Error: {e}")
            import traceback
            traceback.print_exc()
    else:
        print(f"   ⚠️  Table doesn't exist in backup")
    print()
    
    backup_conn.close()
    current_conn.close()
    
    print("=" * 70)
    print("✅ PO DATA RESTORATION COMPLETE!")
    print("=" * 70)
    print("\nNext: Reload your web app in PythonAnywhere dashboard")

if __name__ == '__main__':
    main()

