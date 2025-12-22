#!/usr/bin/env python
"""
Diagnostic script to investigate cross-flavor receipt assignment bug
"""
import sqlite3

db_path = 'database/tablet_counter.db'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

print("🔍 Investigating Receipt 2786-37 and 2786-32 submissions")
print("="*80)

for receipt in ['2786-37', '2786-32']:
    print(f"\n📋 Receipt: {receipt}")
    print("-"*80)
    
    submissions = conn.execute('''
        SELECT 
            ws.id,
            ws.submission_type,
            ws.product_name,
            ws.inventory_item_id as ws_inventory_item,
            ws.box_number as ws_box,
            ws.bag_number as ws_bag,
            ws.bag_id as ws_bag_id,
            ws.assigned_po_id,
            ws.receipt_number,
            b.id as bag_table_id,
            b.tablet_type_id as bag_tablet_type_id,
            tt.tablet_type_name as bag_flavor,
            tt.inventory_item_id as bag_inventory_item,
            sb.box_number as actual_box,
            r.id as receive_id,
            po.po_number
        FROM warehouse_submissions ws
        LEFT JOIN bags b ON ws.bag_id = b.id
        LEFT JOIN tablet_types tt ON b.tablet_type_id = tt.id
        LEFT JOIN small_boxes sb ON b.small_box_id = sb.id
        LEFT JOIN receiving r ON sb.receiving_id = r.id
        LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
        WHERE ws.receipt_number = ?
        ORDER BY ws.submission_type, ws.created_at
    ''', (receipt,)).fetchall()
    
    for sub in submissions:
        sub_dict = dict(sub)
        print(f"\n  Submission ID: {sub_dict['id']}")
        print(f"  Type: {sub_dict['submission_type']}")
        print(f"  Product: {sub_dict['product_name']}")
        print(f"  Submission inventory_item_id: {sub_dict['ws_inventory_item']}")
        print(f"  Submission box/bag: {sub_dict['ws_box']}/{sub_dict['ws_bag']}")
        print(f"  Submission bag_id: {sub_dict['ws_bag_id']}")
        print(f"  ---")
        print(f"  ASSIGNED TO:")
        print(f"  PO: {sub_dict['po_number']}")
        print(f"  Bag ID in bags table: {sub_dict['bag_table_id']}")
        print(f"  Bag's tablet_type_id: {sub_dict['bag_tablet_type_id']}")
        print(f"  Bag's flavor: {sub_dict['bag_flavor']}")
        print(f"  Bag's inventory_item_id: {sub_dict['bag_inventory_item']}")
        print(f"  Bag's actual box: {sub_dict['actual_box']}")
        print()
        
        # Check for mismatch
        if sub_dict['ws_inventory_item'] and sub_dict['bag_inventory_item']:
            if sub_dict['ws_inventory_item'] != sub_dict['bag_inventory_item']:
                print(f"  ❌ MISMATCH! Submission inventory ({sub_dict['ws_inventory_item']}) != Bag inventory ({sub_dict['bag_inventory_item']})")
                print(f"  Submission thinks it's: {sub_dict['product_name']}")
                print(f"  But assigned to bag for: {sub_dict['bag_flavor']}")

print("\n" + "="*80)
print("Checking ALL bags for PO-00156-1 and PO-00156-3:")
print("="*80)

for po_pattern in ['PO-00156-1%', 'PO-00156-3%']:
    print(f"\n📦 Receives matching: {po_pattern}")
    bags = conn.execute('''
        SELECT 
            r.id as receive_id,
            po.po_number,
            tt.tablet_type_name,
            tt.inventory_item_id,
            sb.box_number,
            b.bag_number,
            b.id as bag_id,
            b.bag_label_count
        FROM bags b
        JOIN small_boxes sb ON b.small_box_id = sb.id
        JOIN receiving r ON sb.receiving_id = r.id
        JOIN purchase_orders po ON r.po_id = po.id
        JOIN tablet_types tt ON b.tablet_type_id = tt.id
        WHERE po.po_number LIKE ?
        ORDER BY po.po_number, sb.box_number, b.bag_number
    ''', (po_pattern,)).fetchall()
    
    for bag in bags:
        bag_dict = dict(bag)
        print(f"  {bag_dict['po_number']}: {bag_dict['tablet_type_name']} - Box {bag_dict['box_number']}, Bag {bag_dict['bag_number']} (bag_id={bag_dict['bag_id']})")

conn.close()
print("\n✅ Diagnostic complete")

