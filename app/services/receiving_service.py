"""
Receiving and Shipping business logic service
"""
from typing import Dict, List, Optional
from datetime import datetime
from app.utils.db_utils import db_query, db_execute, db_connection


class ReceivingService:
    """Service for Receiving and Shipping operations"""
    
    @staticmethod
    def get_all_receivings(po_id: Optional[int] = None) -> List[Dict]:
        """Get all receiving records, optionally filtered by PO"""
        query = '''
            SELECT r.*, 
                   po.po_number,
                   COUNT(DISTINCT sb.id) as total_boxes,
                   COUNT(DISTINCT b.id) as total_bags
            FROM receiving r
            LEFT JOIN purchase_orders po ON r.po_id = po.id
            LEFT JOIN small_boxes sb ON r.id = sb.receiving_id
            LEFT JOIN bags b ON sb.id = b.small_box_id
        '''
        params = []
        
        if po_id:
            query += ' WHERE r.po_id = ?'
            params.append(po_id)
        
        query += ' GROUP BY r.id ORDER BY r.received_date DESC'
        
        return db_query(query, tuple(params), fetch_all=True)
    
    @staticmethod
    def get_receiving_by_id(receiving_id: int) -> Dict:
        """Get a receiving record with all boxes and bags"""
        receiving = db_query(
            'SELECT * FROM receiving WHERE id = ?',
            (receiving_id,),
            fetch_one=True
        )
        
        if not receiving:
            return {}
        
        # Get boxes
        boxes = db_query(
            'SELECT * FROM small_boxes WHERE receiving_id = ? ORDER BY box_number',
            (receiving_id,),
            fetch_all=True
        )
        
        # Get bags for each box
        for box in boxes:
            box['bags'] = db_query('''
                SELECT b.*, tt.tablet_type_name
                FROM bags b
                LEFT JOIN tablet_types tt ON b.tablet_type_id = tt.id
                WHERE b.small_box_id = ?
                ORDER BY b.bag_number
            ''', (box['id'],), fetch_all=True)
        
        receiving['boxes'] = boxes
        return receiving
    
    @staticmethod
    def create_receiving(data: Dict) -> int:
        """Create a new receiving record with boxes and bags"""
        with db_connection() as conn:
            # Create receiving record
            cursor = conn.execute('''
                INSERT INTO receiving (
                    po_id, received_date, received_by, total_small_boxes, notes
                ) VALUES (?, ?, ?, ?, ?)
            ''', (
                data.get('po_id'),
                data.get('received_date', datetime.now()),
                data.get('received_by'),
                data.get('total_boxes', 0),
                data.get('notes')
            ))
            receiving_id = cursor.lastrowid
            
            # Create boxes and bags
            for box_data in data.get('boxes', []):
                box_cursor = conn.execute('''
                    INSERT INTO small_boxes (
                        receiving_id, box_number, total_bags, notes
                    ) VALUES (?, ?, ?, ?)
                ''', (
                    receiving_id,
                    box_data.get('box_number'),
                    len(box_data.get('bags', [])),
                    box_data.get('notes')
                ))
                box_id = box_cursor.lastrowid
                
                # Create bags
                for bag_data in box_data.get('bags', []):
                    conn.execute('''
                        INSERT INTO bags (
                            small_box_id, bag_number, bag_label_count,
                            tablet_type_id, pill_count
                        ) VALUES (?, ?, ?, ?, ?)
                    ''', (
                        box_id,
                        bag_data.get('bag_number'),
                        bag_data.get('bag_label_count'),
                        bag_data.get('tablet_type_id'),
                        bag_data.get('pill_count')
                    ))
            
            conn.commit()
            return receiving_id
    
    @staticmethod
    def assign_po_to_receiving(receiving_id: int, po_id: Optional[int]) -> bool:
        """Assign or update PO assignment for a receiving record"""
        db_execute(
            'UPDATE receiving SET po_id = ? WHERE id = ?',
            (po_id, receiving_id)
        )
        return True
    
    @staticmethod
    def delete_receiving(receiving_id: int) -> bool:
        """Delete a receiving record and all associated boxes/bags"""
        with db_connection() as conn:
            # Get all box IDs
            boxes = db_query(
                'SELECT id FROM small_boxes WHERE receiving_id = ?',
                (receiving_id,),
                fetch_all=True
            )
            
            # Delete bags
            for box in boxes:
                db_execute(
                    'DELETE FROM bags WHERE small_box_id = ?',
                    (box['id'],)
                )
            
            # Delete boxes
            db_execute(
                'DELETE FROM small_boxes WHERE receiving_id = ?',
                (receiving_id,)
            )
            
            # Delete receiving record
            db_execute(
                'DELETE FROM receiving WHERE id = ?',
                (receiving_id,)
            )
            
            conn.commit()
            return True

