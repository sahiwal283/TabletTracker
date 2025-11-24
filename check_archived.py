#!/usr/bin/env python3
"""
Quick script to check archived submissions in the database
Run this in PythonAnywhere console to verify archived submissions exist
"""

import sqlite3

def check_archived():
    conn = sqlite3.connect('tablet_counter.db')
    conn.row_factory = sqlite3.Row
    
    # Check if archived column exists
    try:
        conn.execute('SELECT archived FROM warehouse_submissions LIMIT 1')
        print("✅ archived column exists")
        has_archived = True
    except sqlite3.OperationalError:
        print("❌ archived column does NOT exist - run migrate_db.py first!")
        conn.close()
        return
    
    # Count archived submissions
    archived_count = conn.execute('''
        SELECT COUNT(*) as count 
        FROM warehouse_submissions 
        WHERE COALESCE(archived, FALSE) = TRUE
    ''').fetchone()['count']
    
    print(f"\n📊 Archived submissions: {archived_count}")
    
    # Show which POs have archived submissions
    if archived_count > 0:
        print("\n📦 POs with archived submissions:")
        po_archived = conn.execute('''
            SELECT po.po_number, po.closed, COUNT(ws.id) as archived_count
            FROM purchase_orders po
            JOIN warehouse_submissions ws ON po.id = ws.assigned_po_id
            WHERE COALESCE(ws.archived, FALSE) = TRUE
            GROUP BY po.id, po.po_number, po.closed
            ORDER BY po.po_number DESC
            LIMIT 10
        ''').fetchall()
        
        for row in po_archived:
            status = "CLOSED" if row['closed'] else "OPEN"
            print(f"  - {row['po_number']} ({status}): {row['archived_count']} archived submissions")
    
    # Count non-archived submissions
    non_archived_count = conn.execute('''
        SELECT COUNT(*) as count 
        FROM warehouse_submissions 
        WHERE COALESCE(archived, FALSE) = FALSE
    ''').fetchone()['count']
    
    print(f"\n📊 Non-archived submissions: {non_archived_count}")
    
    # Count closed POs
    closed_pos = conn.execute('''
        SELECT COUNT(*) as count 
        FROM purchase_orders 
        WHERE closed = TRUE
    ''').fetchone()['count']
    
    print(f"\n📊 Closed POs: {closed_pos}")
    
    conn.close()
    print("\n✅ Check complete!")
    print("\n💡 To view archived submissions:")
    print("   - Go to: /submissions?show_archived=true")
    print("   - Or click 'Show Archived' button on the submissions page")

if __name__ == "__main__":
    check_archived()

