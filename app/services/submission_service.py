"""
Submission business logic service
"""
from typing import Dict, List, Optional
from datetime import datetime
from app.utils.db_utils import db_query, db_execute, db_connection
from app.utils.calculations import calculate_tablet_totals, calculate_machine_tablets


class SubmissionService:
    """Service for Submission operations"""
    
    @staticmethod
    def get_all_submissions(
        page: int = 1,
        per_page: int = 50,
        po_id: Optional[int] = None,
        item_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        tablet_type_id: Optional[int] = None,
        submission_type: Optional[str] = None
    ) -> Dict:
        """Get paginated submissions with filters"""
        offset = (page - 1) * per_page
        
        # Build WHERE clause
        conditions = []
        params = []
        
        if po_id:
            conditions.append('ws.assigned_po_id = ?')
            params.append(po_id)
        
        if item_id:
            conditions.append('ws.inventory_item_id = ?')
            params.append(item_id)
        
        if date_from:
            conditions.append('COALESCE(ws.submission_date, DATE(ws.created_at)) >= ?')
            params.append(date_from)
        
        if date_to:
            conditions.append('COALESCE(ws.submission_date, DATE(ws.created_at)) <= ?')
            params.append(date_to)
        
        if tablet_type_id:
            conditions.append('tt.id = ?')
            params.append(tablet_type_id)
        
        if submission_type:
            conditions.append('COALESCE(ws.submission_type, "packaged") = ?')
            params.append(submission_type)
        
        where_clause = ' AND ' + ' AND '.join(conditions) if conditions else ''
        
        # Get total count
        count_query = f'''
            SELECT COUNT(*) as total
            FROM warehouse_submissions ws
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
            LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            WHERE 1=1 {where_clause}
        '''
        total = db_query(count_query, tuple(params), fetch_one=True)['total']
        
        # Get submissions
        query = f'''
            SELECT ws.*, 
                   po.po_number, po.closed as po_closed,
                   pd.packages_per_display, pd.tablets_per_package,
                   COALESCE(ws.po_assignment_verified, 0) as po_verified,
                   (
                       CASE 
                           WHEN COALESCE(ws.submission_type, 'packaged') = 'machine' THEN
                               (SELECT mc.machine_count * COALESCE((SELECT CAST(setting_value AS INTEGER) FROM app_settings WHERE setting_key = 'cards_per_turn'), 1) * COALESCE(pd.tablets_per_package, 0)
                                FROM machine_counts mc
                                WHERE mc.id = (SELECT MAX(id) FROM machine_counts WHERE tablet_type_id = pd.tablet_type_id))
                           ELSE
                               (ws.displays_made * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0)) +
                               (ws.packs_remaining * COALESCE(pd.tablets_per_package, 0)) + 
                               ws.loose_tablets + ws.damaged_tablets
                       END
                   ) as calculated_total
            FROM warehouse_submissions ws
            LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
            LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            WHERE 1=1 {where_clause}
            ORDER BY ws.created_at DESC
            LIMIT ? OFFSET ?
        '''
        params.extend([per_page, offset])
        submissions = db_query(query, tuple(params), fetch_all=True)
        
        return {
            'submissions': submissions,
            'total': total,
            'page': page,
            'per_page': per_page,
            'pages': (total + per_page - 1) // per_page
        }
    
    @staticmethod
    def get_submission_by_id(submission_id: int) -> Optional[Dict]:
        """Get a single submission by ID"""
        return db_query('''
            SELECT ws.*, 
                   po.po_number, po.closed as po_closed,
                   COALESCE(ws.po_assignment_verified, 0) as po_verified
            FROM warehouse_submissions ws
            LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
            WHERE ws.id = ?
        ''', (submission_id,), fetch_one=True)
    
    @staticmethod
    def create_submission(data: Dict) -> int:
        """Create a new submission"""
        with db_connection() as conn:
            cursor = conn.execute('''
                INSERT INTO warehouse_submissions (
                    employee_name, product_name, displays_made, packs_remaining,
                    loose_tablets, damaged_tablets, submission_type, submission_date,
                    inventory_item_id, box_number, bag_number, bag_label_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data.get('employee_name'),
                data.get('product_name'),
                data.get('displays_made', 0),
                data.get('packs_remaining', 0),
                data.get('loose_tablets', 0),
                data.get('damaged_tablets', 0),
                data.get('submission_type', 'packaged'),
                data.get('submission_date'),
                data.get('inventory_item_id'),
                data.get('box_number'),
                data.get('bag_number'),
                data.get('bag_label_count')
            ))
            submission_id = cursor.lastrowid
            conn.commit()
            return submission_id
    
    @staticmethod
    def update_submission(submission_id: int, data: Dict) -> bool:
        """Update an existing submission"""
        updates = []
        params = []
        
        for key in ['product_name', 'displays_made', 'packs_remaining', 'loose_tablets', 
                   'damaged_tablets', 'submission_date', 'admin_notes']:
            if key in data:
                updates.append(f'{key} = ?')
                params.append(data[key])
        
        if not updates:
            return False
        
        params.append(submission_id)
        db_execute(f'''
            UPDATE warehouse_submissions 
            SET {', '.join(updates)}
            WHERE id = ?
        ''', tuple(params))
        return True

