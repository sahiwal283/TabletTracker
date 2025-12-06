"""
Product and Tablet Type business logic service
"""
from typing import Dict, List, Optional
from app.utils.db_utils import db_query, db_execute, db_connection


class ProductService:
    """Service for Product and Tablet Type operations"""
    
    @staticmethod
    def get_all_tablet_types() -> List[Dict]:
        """Get all tablet types with category information"""
        return db_query('''
            SELECT tt.*, 
                   ttc.category_name,
                   ttc.category_order
            FROM tablet_types tt
            LEFT JOIN tablet_type_categories ttc ON tt.category_id = ttc.id
            ORDER BY ttc.category_order, tt.tablet_type_name
        ''', fetch_all=True)
    
    @staticmethod
    def get_tablet_type_by_id(tablet_type_id: int) -> Optional[Dict]:
        """Get a single tablet type by ID"""
        return db_query(
            'SELECT * FROM tablet_types WHERE id = ?',
            (tablet_type_id,),
            fetch_one=True
        )
    
    @staticmethod
    def get_all_products() -> List[Dict]:
        """Get all products with tablet type information"""
        return db_query('''
            SELECT pd.*, tt.tablet_type_name, tt.inventory_item_id
            FROM product_details pd
            JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            ORDER BY pd.product_name
        ''', fetch_all=True)
    
    @staticmethod
    def get_product_by_name(product_name: str) -> Optional[Dict]:
        """Get a product by name"""
        return db_query('''
            SELECT pd.*, tt.tablet_type_name, tt.inventory_item_id
            FROM product_details pd
            JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            WHERE pd.product_name = ?
        ''', (product_name,), fetch_one=True)
    
    @staticmethod
    def get_categories() -> List[Dict]:
        """Get all categories ordered by category_order"""
        return db_query('''
            SELECT * FROM tablet_type_categories
            ORDER BY category_order
        ''', fetch_all=True)
    
    @staticmethod
    def update_tablet_type_category(tablet_type_id: int, category_name: Optional[str]) -> bool:
        """Update a tablet type's category"""
        if category_name:
            # Get category_id from category_name
            category = db_query(
                'SELECT id FROM tablet_type_categories WHERE category_name = ?',
                (category_name,),
                fetch_one=True
            )
            if category:
                db_execute(
                    'UPDATE tablet_types SET category_id = ? WHERE id = ?',
                    (category['id'], tablet_type_id)
                )
                return True
        else:
            # Remove category
            db_execute(
                'UPDATE tablet_types SET category_id = NULL WHERE id = ?',
                (tablet_type_id,)
            )
            return True
        return False


class TabletTypeModel:
    """Model for Tablet Type operations"""
    
    @staticmethod
    def get_all() -> List[Dict]:
        """Get all tablet types"""
        return ProductService.get_all_tablet_types()
    
    @staticmethod
    def get_by_id(tablet_type_id: int) -> Optional[Dict]:
        """Get tablet type by ID"""
        return ProductService.get_tablet_type_by_id(tablet_type_id)

