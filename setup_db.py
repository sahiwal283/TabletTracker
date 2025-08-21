#!/usr/bin/env python3
"""
Database setup script for Tablet Counter
Run this once to initialize the database with sample data
"""

import sqlite3
from app import init_db

def setup_sample_data():
    """Add sample tablet types and products for testing"""
    conn = sqlite3.connect('tablet_counter.db')
    c = conn.cursor()
    
    # Tablet types matching your product configuration
    tablet_types = [
        ('18mg 7OH', None),
        ('18mg Pseudo', None), 
        ('18mg Hybrid', None),
        ('XL 7OH', None),
        ('XL Pseudo', None),
        ('XL Hybrid', None),
        ('1ct FIX Energy', None),
        ('5ct FIX Energy', None),
        ('12ct FIX Energy', None),
        ('1ct FIX Focus', None),
        ('5ct FIX Focus', None),
        ('12ct FIX Focus', None),
        ('1ct FIX Relax', None),
        ('5ct FIX Relax', None),
        ('12ct FIX Relax', None),
    ]
    
    for name, item_id in tablet_types:
        c.execute('''
            INSERT OR IGNORE INTO tablet_types (tablet_type_name, inventory_item_id)
            VALUES (?, ?)
        ''', (name, item_id))
    
    # Products matching your screenshot EXACTLY
    products = [
        # 7OH products - 18mg 7OH tablet type  
        ('7OH 1ct', '18mg 7OH', 20, 1),
        ('7OH 4ct', '18mg 7OH', 20, 4), 
        ('7OH 7ct', '18mg 7OH', 20, 7),
        
        # Pseudo products - 18mg Pseudo tablet type
        ('Pseudo 5ct', '18mg Pseudo', 20, 5),
        
        # Hybrid products - 18mg Hybrid tablet type  
        ('Hybrid 5ct', '18mg Hybrid', 20, 5),
        
        # XL 7OH products - XL 7OH tablet type
        ('XL 7OH 1ct', 'XL 7OH', 20, 1),
        ('XL 7OH 4ct', 'XL 7OH', 20, 4),
        ('XL 7OH 7ct', 'XL 7OH', 20, 7),
        
        # XL Pseudo products - XL Pseudo tablet type
        ('XL Pseudo 1ct', 'XL Pseudo', 20, 1), 
        ('XL Pseudo 5ct', 'XL Pseudo', 20, 5),
        
        # XL Hybrid products - XL Hybrid tablet type
        ('XL Hybrid 1ct', 'XL Hybrid', 20, 1),
        ('XL Hybrid 5ct', 'XL Hybrid', 20, 5),
        
        # FIX Energy products - specific tablet types per count
        ('FIX Energy 1ct', '1ct FIX Energy', 20, 1),
        ('FIX Energy 5ct', '5ct FIX Energy', 10, 5),
        ('FIX Energy 12ct', '12ct FIX Energy', 12, 12),
        
        # FIX Focus products - specific tablet types per count
        ('FIX Focus 1ct', '1ct FIX Focus', 20, 1),
        ('FIX Focus 5ct', '5ct FIX Focus', 10, 5), 
        ('FIX Focus 12ct', '12ct FIX Focus', 12, 12),
        
        # FIX Relax products - specific tablet types per count
        ('FIX Relax 1ct', '1ct FIX Relax', 20, 1),
        ('FIX Relax 5ct', '5ct FIX Relax', 10, 5),
        ('FIX Relax 12ct', '12ct FIX Relax', 12, 12),
    ]
    
    for product_name, tablet_type_name, ppd, tpp in products:
        # Get tablet type ID
        tablet_type = c.execute(
            'SELECT id FROM tablet_types WHERE tablet_type_name = ?', 
            (tablet_type_name,)
        ).fetchone()
        
        if tablet_type:
            c.execute('''
                INSERT OR IGNORE INTO product_details 
                (product_name, tablet_type_id, packages_per_display, tablets_per_package)
                VALUES (?, ?, ?, ?)
            ''', (product_name, tablet_type[0], ppd, tpp))
    
    # Add sample POs for testing
    sample_pos = [
        ('PO-TEST-001', '5254962000001245042', 'Test PO 1', 1000),
        ('PO-TEST-002', '5254962000001259184', 'Test PO 2', 2000),
    ]
    
    for po_number, zoho_id, tablet_type, quantity in sample_pos:
        cursor = c.execute('''
            INSERT OR IGNORE INTO purchase_orders (po_number, zoho_po_id, tablet_type, ordered_quantity)
            VALUES (?, ?, ?, ?)
        ''', (po_number, zoho_id, tablet_type, quantity))
        
        if cursor.lastrowid:  # New PO was inserted
            po_id = cursor.lastrowid
            
            # Add corresponding line item
            c.execute('''
                INSERT INTO po_lines 
                (po_id, po_number, inventory_item_id, line_item_name, quantity_ordered)
                VALUES (?, ?, ?, ?, ?)
            ''', (po_id, po_number, zoho_id, f'{tablet_type} Tablets', quantity))
    
    conn.commit()
    conn.close()
    print("✅ Sample data created successfully!")

if __name__ == '__main__':
    print("🔧 Initializing database...")
    init_db()
    print("✅ Database initialized!")
    
    print("📝 Setting up sample data...")
    setup_sample_data()
    
    print("🎉 Setup complete! You can now run:")
    print("   python app.py")
    print("   Then visit http://localhost:5000")
