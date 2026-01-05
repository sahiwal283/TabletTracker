"""
Tablet Types API routes for managing tablet types, products, and categories.
"""
from flask import Blueprint, request, jsonify, current_app
import traceback
import json
from app.utils.db_utils import db_read_only, db_transaction
from app.utils.auth_utils import admin_required, role_required

bp = Blueprint('api_tablet_types', __name__)


@bp.route('/api/update_tablet_type_inventory', methods=['POST'])
@admin_required
def update_tablet_type_inventory():
    """Update a tablet type's inventory item ID and variety pack configuration"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Invalid JSON data'}), 400
            
        tablet_type_id = data.get('tablet_type_id')
        if not tablet_type_id:
            return jsonify({'success': False, 'error': 'Tablet type ID required'}), 400
            
        inventory_item_id = (data.get('inventory_item_id') or '').strip()
        
        is_variety_pack = data.get('is_variety_pack', False)
        tablets_per_bottle = data.get('tablets_per_bottle')
        bottles_per_pack = data.get('bottles_per_pack')
        
        with db_transaction() as conn:
            updates = []
            params = []
            
            if inventory_item_id:
                existing = conn.execute('''
                    SELECT tablet_type_name FROM tablet_types 
                    WHERE inventory_item_id = ? AND id != ?
                ''', (inventory_item_id, tablet_type_id)).fetchone()
                
                if existing:
                    return jsonify({
                        'success': False, 
                        'error': f'Inventory ID already used by {existing["tablet_type_name"]}'
                    })
                updates.append('inventory_item_id = ?')
                params.append(inventory_item_id)
            else:
                updates.append('inventory_item_id = NULL')
            
            if 'is_variety_pack' in data:
                updates.append('is_variety_pack = ?')
                params.append(is_variety_pack)
            
            if 'tablets_per_bottle' in data:
                updates.append('tablets_per_bottle = ?')
                params.append(tablets_per_bottle)
            
            if 'bottles_per_pack' in data:
                updates.append('bottles_per_pack = ?')
                params.append(bottles_per_pack)
            
            if updates:
                params.append(tablet_type_id)
                conn.execute(f'''
                    UPDATE tablet_types 
                    SET {', '.join(updates)}
                    WHERE id = ?
                ''', tuple(params))
            
            return jsonify({'success': True, 'message': 'Tablet type updated successfully'})
    except Exception as e:
        current_app.logger.error(f"Error updating tablet type inventory: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/save_product', methods=['POST'])
@admin_required
def save_product():
    """Save or update a product configuration"""
    try:
        data = request.get_json()
        
        required_fields = ['product_name', 'tablet_type_id', 'packages_per_display', 'tablets_per_package']
        for field in required_fields:
            if field not in data or data[field] is None:
                return jsonify({'success': False, 'error': f'{field} is required'}), 400
        
        try:
            tablet_type_id = int(data['tablet_type_id'])
            packages_per_display = int(data['packages_per_display'])
            tablets_per_package = int(data['tablets_per_package'])
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid numeric values for tablet_type_id, packages_per_display, or tablets_per_package'}), 400
        
        with db_transaction() as conn:
            product_name = data.get('product_name')
            
            if data.get('id'):
                try:
                    product_id = int(data['id'])
                except (ValueError, TypeError):
                    return jsonify({'success': False, 'error': 'Invalid product ID'}), 400
                    
                conn.execute('''
                    UPDATE product_details 
                    SET product_name = ?, tablet_type_id = ?, packages_per_display = ?, tablets_per_package = ?
                    WHERE id = ?
                ''', (product_name, tablet_type_id, packages_per_display, tablets_per_package, product_id))
                message = f"Updated {product_name}"
            else:
                conn.execute('''
                    INSERT INTO product_details (product_name, tablet_type_id, packages_per_display, tablets_per_package)
                    VALUES (?, ?, ?, ?)
                ''', (product_name, tablet_type_id, packages_per_display, tablets_per_package))
                message = f"Created {product_name}"
            
            return jsonify({'success': True, 'message': message})
    except Exception as e:
        current_app.logger.error(f"Error saving product: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/delete_product/<int:product_id>', methods=['DELETE'])
@admin_required
def delete_product(product_id):
    """Delete a product configuration"""
    try:
        with db_transaction() as conn:
            product = conn.execute('SELECT product_name FROM product_details WHERE id = ?', (product_id,)).fetchone()
            if not product:
                return jsonify({'success': False, 'error': 'Product not found'}), 404
            
            conn.execute('DELETE FROM product_details WHERE id = ?', (product_id,))
            
            return jsonify({'success': True, 'message': f"Deleted {product['product_name']}"})
    except Exception as e:
        current_app.logger.error(f"Error deleting product: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/get_or_create_tablet_type', methods=['POST'])
@role_required('dashboard')
def get_or_create_tablet_type():
    """Get existing tablet type by name or create new one"""
    try:
        data = request.get_json()
        tablet_type_name = data.get('tablet_type_name', '').strip()
        
        if not tablet_type_name:
            return jsonify({'success': False, 'error': 'Tablet type name required'}), 400
        
        with db_transaction() as conn:
            existing = conn.execute(
                'SELECT id FROM tablet_types WHERE tablet_type_name = ?', 
                (tablet_type_name,)
            ).fetchone()
            
            if existing:
                tablet_type_id = existing['id']
            else:
                cursor = conn.execute(
                    'INSERT INTO tablet_types (tablet_type_name) VALUES (?)',
                    (tablet_type_name,)
                )
                tablet_type_id = cursor.lastrowid
            
            return jsonify({'success': True, 'tablet_type_id': tablet_type_id})
    except Exception as e:
        current_app.logger.error(f"Error getting/creating tablet type: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/update_tablet_inventory_ids', methods=['POST'])
@admin_required
def update_tablet_inventory_ids():
    """Update tablet types with inventory item IDs from PO line items"""
    try:
        with db_transaction() as conn:
            tablet_types = conn.execute('''
                SELECT id, tablet_type_name 
                FROM tablet_types 
                WHERE inventory_item_id IS NULL OR inventory_item_id = ''
            ''').fetchall()
            
            updated_count = 0
            
            for tablet_type in tablet_types:
                current_app.logger.info(f"Processing tablet type: {tablet_type['tablet_type_name']}")
                
                # Find matching PO line items by tablet type name
                po_lines = conn.execute('''
                    SELECT DISTINCT pl.inventory_item_id
                    FROM po_lines pl
                    JOIN purchase_orders po ON pl.po_id = po.id
                    WHERE po.tablet_type = ?
                    AND pl.inventory_item_id IS NOT NULL
                    AND pl.inventory_item_id != ''
                    LIMIT 1
                ''', (tablet_type['tablet_type_name'],)).fetchall()
                
                if po_lines:
                    inventory_item_id = po_lines[0]['inventory_item_id']
                    conn.execute('''
                        UPDATE tablet_types 
                        SET inventory_item_id = ?
                        WHERE id = ?
                    ''', (inventory_item_id, tablet_type['id']))
                    updated_count += 1
                    current_app.logger.info(f"Updated {tablet_type['tablet_type_name']} with inventory_item_id: {inventory_item_id}")
            
            return jsonify({
                'success': True,
                'message': f'Updated {updated_count} tablet type(s) with inventory item IDs'
            })
    except Exception as e:
        current_app.logger.error(f"Error updating tablet inventory IDs: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/tablet_types/categories', methods=['GET'])
@role_required('dashboard')
def get_tablet_type_categories():
    """Get all tablet types grouped by their configured categories"""
    try:
        with db_read_only() as conn:
            tablet_types = conn.execute('''
                SELECT id, tablet_type_name, category 
                FROM tablet_types 
                ORDER BY tablet_type_name
            ''').fetchall()
            
            categories = {}
            unassigned = []
            
            for tt in tablet_types:
                category = tt['category'] if tt['category'] else None
                if not category:
                    unassigned.append({
                        'id': tt['id'],
                        'name': tt['tablet_type_name']
                    })
                else:
                    if category not in categories:
                        categories[category] = []
                    categories[category].append({
                        'id': tt['id'],
                        'name': tt['tablet_type_name']
                    })
            
            if unassigned:
                if 'Other' not in categories:
                    categories['Other'] = []
                categories['Other'].extend(unassigned)
            
            category_order = sorted(categories.keys())
            
            return jsonify({
                'success': True,
                'categories': categories,
                'category_order': category_order
            })
    except Exception as e:
        current_app.logger.error(f"Error getting tablet type categories: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/tablet_type/category', methods=['POST'])
@admin_required
def update_tablet_type_category():
    """Update category for a tablet type"""
    try:
        data = request.get_json()
        tablet_type_id = data.get('tablet_type_id')
        category = data.get('category')
        
        if not tablet_type_id:
            return jsonify({'success': False, 'error': 'Tablet type ID required'}), 400
        
        with db_transaction() as conn:
            conn.execute('''
                UPDATE tablet_types 
                SET category = ?
                WHERE id = ?
            ''', (category, tablet_type_id))
            
            return jsonify({'success': True, 'message': 'Category updated successfully'})
    except Exception as e:
        current_app.logger.error(f"Error updating tablet type category: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/tablet_types', methods=['GET'])
@role_required('dashboard')
def get_tablet_types():
    """Get all tablet types/products for dropdowns"""
    try:
        with db_read_only() as conn:
            tablet_types = conn.execute('''
                SELECT id, tablet_type_name, inventory_item_id, category
                FROM tablet_types 
                ORDER BY tablet_type_name
            ''').fetchall()
            
            return jsonify({
                'success': True,
                'tablet_types': [dict(row) for row in tablet_types]
            })
    except Exception as e:
        current_app.logger.error(f"Error getting tablet types: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/categories', methods=['GET'])
@admin_required
def get_categories():
    """Get all unique categories"""
    try:
        with db_read_only() as conn:
            categories = conn.execute('''
                SELECT DISTINCT category 
                FROM tablet_types 
                WHERE category IS NOT NULL AND category != ''
                ORDER BY category
            ''').fetchall()
            
            category_list = [cat['category'] for cat in categories] if categories else []
            
            deleted_categories_set = set()
            try:
                deleted_categories_json = conn.execute('''
                    SELECT setting_value FROM app_settings WHERE setting_key = 'deleted_categories'
                ''').fetchone()
                if deleted_categories_json and deleted_categories_json['setting_value']:
                    try:
                        deleted_categories_set = set(json.loads(deleted_categories_json['setting_value']))
                    except (json.JSONDecodeError, ValueError, TypeError):
                        deleted_categories_set = set()
            except Exception as e:
                current_app.logger.warning(f"Could not load deleted categories: {e}")
            
            try:
                category_order_json = conn.execute('''
                    SELECT setting_value FROM app_settings WHERE setting_key = 'category_order'
                ''').fetchone()
                if category_order_json and category_order_json['setting_value']:
                    try:
                        preferred_order = json.loads(category_order_json['setting_value'])
                    except (json.JSONDecodeError, ValueError, TypeError):
                        preferred_order = sorted(category_list)
                else:
                    preferred_order = sorted(category_list)
            except Exception as e:
                current_app.logger.warning(f"Could not load category order: {e}")
                preferred_order = sorted(category_list)
            
            all_categories = [cat for cat in category_list if cat not in deleted_categories_set]
            all_categories.sort(key=lambda x: (preferred_order.index(x) if x in preferred_order else len(preferred_order) + 1, x))
            
            return jsonify({'success': True, 'categories': all_categories})
    except Exception as e:
        current_app.logger.error(f"Error getting categories: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/categories', methods=['POST'])
@admin_required
def add_category():
    """Add a new category"""
    try:
        data = request.get_json()
        category_name = data.get('category_name', '').strip()
        
        if not category_name:
            return jsonify({'success': False, 'error': 'Category name required'}), 400
        
        with db_read_only() as conn:
            existing = conn.execute('''
                SELECT DISTINCT category 
                FROM tablet_types 
                WHERE category = ?
            ''', (category_name,)).fetchone()
            
            if existing:
                return jsonify({'success': False, 'error': 'Category already exists'}), 400
            
            return jsonify({
                'success': True, 
                'message': f'Category "{category_name}" is ready. Assign tablet types to make it active.'
            })
    except Exception as e:
        current_app.logger.error(f"Error adding category: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/categories/rename', methods=['POST'])
@admin_required
def rename_category():
    """Rename a category (updates all tablet types with that category)"""
    try:
        data = request.get_json()
        old_name = data.get('old_name', '').strip()
        new_name = data.get('new_name', '').strip()
        
        if not old_name or not new_name:
            return jsonify({'success': False, 'error': 'Both old and new category names required'}), 400
        
        if old_name == new_name:
            return jsonify({'success': False, 'error': 'New name must be different from old name'}), 400
        
        with db_transaction() as conn:
            existing = conn.execute('''
                SELECT DISTINCT category 
                FROM tablet_types 
                WHERE category = ?
            ''', (new_name,)).fetchone()
            
            if existing:
                return jsonify({'success': False, 'error': 'Category name already exists'}), 400
            
            old_exists = conn.execute('''
                SELECT COUNT(*) as count
                FROM tablet_types 
                WHERE category = ?
            ''', (old_name,)).fetchone()
            
            if old_exists['count'] == 0:
                return jsonify({'success': False, 'error': f'Category "{old_name}" not found or has no tablet types assigned'}), 404
            
            cursor = conn.execute('''
                UPDATE tablet_types 
                SET category = ?
                WHERE category = ?
            ''', (new_name, old_name))
            
            rows_updated = cursor.rowcount
            
            verify_update = conn.execute('''
                SELECT COUNT(*) as count
                FROM tablet_types 
                WHERE category = ?
            ''', (new_name,)).fetchone()
            
            if verify_update['count'] != old_exists['count']:
                return jsonify({'success': False, 'error': 'Failed to update all tablet types. Transaction rolled back.'}), 500
            
            return jsonify({
                'success': True, 
                'message': f'Category renamed from "{old_name}" to "{new_name}" ({rows_updated} tablet types updated)'
            })
    except Exception as e:
        current_app.logger.error(f"Error renaming category: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/categories/delete', methods=['POST'])
@admin_required
def delete_category():
    """Delete a category (removes category from all tablet types)"""
    try:
        data = request.get_json()
        category_name = data.get('category_name', '').strip()
        
        if not category_name:
            return jsonify({'success': False, 'error': 'Category name required'}), 400
        
        with db_transaction() as conn:
            category_exists = conn.execute('''
            SELECT COUNT(*) as count
            FROM tablet_types 
            WHERE category = ?
        ''', (category_name,)).fetchone()
        
            rows_updated = 0
        
            if category_exists['count'] > 0:
                cursor = conn.execute('''
                    UPDATE tablet_types 
                    SET category = NULL
                    WHERE category = ?
                ''', (category_name,))
                
                rows_updated = cursor.rowcount
                
                verify_delete = conn.execute('''
                    SELECT COUNT(*) as count
                    FROM tablet_types 
                    WHERE category = ?
                ''', (category_name,)).fetchone()
                
                if verify_delete['count'] != 0:
                    return jsonify({'success': False, 'error': 'Failed to delete category. Transaction rolled back.'}), 500
                
                try:
                    deleted_categories_json = conn.execute('''
                    SELECT setting_value FROM app_settings WHERE setting_key = 'deleted_categories'
                ''').fetchone()
                
                    deleted_categories = set()
                    if deleted_categories_json and deleted_categories_json['setting_value']:
                        try:
                            deleted_categories = set(json.loads(deleted_categories_json['setting_value']))
                        except (json.JSONDecodeError, ValueError, TypeError):
                            deleted_categories = set()
                
                    deleted_categories.add(category_name)
                
                    conn.execute('''
                        INSERT OR REPLACE INTO app_settings (setting_key, setting_value, description) 
                        VALUES (?, ?, ?)
                        ''', ('deleted_categories', json.dumps(list(deleted_categories)), 'List of deleted categories that should not appear'))
                except Exception as e:
                    current_app.logger.warning(f"Could not track deleted category: {e}")
            
            return jsonify({
                'success': True, 
                'message': f'Category "{category_name}" deleted. {rows_updated} tablet type(s) have been unassigned.'
            })
    except Exception as e:
        current_app.logger.error(f"Error deleting category: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/add_tablet_type', methods=['POST'])
@admin_required
def add_tablet_type():
    """Add a new tablet type"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Invalid JSON data'}), 400
            
        tablet_type_name = (data.get('tablet_type_name') or '').strip()
        inventory_item_id = (data.get('inventory_item_id') or '').strip()
        
        if not tablet_type_name:
            return jsonify({'success': False, 'error': 'Tablet type name required'}), 400
            
        with db_transaction() as conn:
            existing = conn.execute(
                'SELECT id FROM tablet_types WHERE tablet_type_name = ?', 
                (tablet_type_name,)
            ).fetchone()
            
            if existing:
                return jsonify({'success': False, 'error': 'Tablet type already exists'}), 400
        
            if inventory_item_id:
                existing_id = conn.execute(
                    'SELECT tablet_type_name FROM tablet_types WHERE inventory_item_id = ?',
                    (inventory_item_id,)
                ).fetchone()
                
                if existing_id:
                    return jsonify({
                        'success': False, 
                        'error': f'Inventory ID already used by {existing_id["tablet_type_name"]}'
                    }), 400
        
            is_variety_pack = data.get('is_variety_pack', False)
            tablets_per_bottle = data.get('tablets_per_bottle')
            bottles_per_pack = data.get('bottles_per_pack')
            variety_pack_contents = data.get('variety_pack_contents')
        
            conn.execute('''
                INSERT INTO tablet_types (tablet_type_name, inventory_item_id, is_variety_pack, tablets_per_bottle, bottles_per_pack, variety_pack_contents)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (tablet_type_name, inventory_item_id if inventory_item_id else None, 
                  is_variety_pack, tablets_per_bottle, bottles_per_pack, variety_pack_contents))
            
            return jsonify({'success': True, 'message': f'Added tablet type: {tablet_type_name}'})
    except Exception as e:
        current_app.logger.error(f"Error adding tablet type: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/delete_tablet_type/<int:tablet_type_id>', methods=['DELETE'])
@admin_required
def delete_tablet_type(tablet_type_id):
    """Delete a tablet type and its associated products"""
    try:
        with db_transaction() as conn:
            tablet_type = conn.execute(
                'SELECT tablet_type_name FROM tablet_types WHERE id = ?', 
                (tablet_type_id,)
            ).fetchone()
            
            if not tablet_type:
                return jsonify({'success': False, 'error': 'Tablet type not found'}), 404
            
            conn.execute('DELETE FROM product_details WHERE tablet_type_id = ?', (tablet_type_id,))
            conn.execute('DELETE FROM tablet_types WHERE id = ?', (tablet_type_id,))
            
            return jsonify({'success': True, 'message': f'Deleted {tablet_type["tablet_type_name"]} and its products'})
    except Exception as e:
        current_app.logger.error(f"Error deleting tablet type: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/refresh_products', methods=['POST'])
@admin_required
def refresh_products():
    """Clear and rebuild products with updated configuration"""
    try:
        from setup_db import setup_sample_data
        
        with db_transaction() as conn:
            conn.execute('DELETE FROM warehouse_submissions')
            conn.execute('DELETE FROM product_details')
            conn.execute('DELETE FROM tablet_types')
        
        setup_sample_data()
        
        return jsonify({
            'success': True, 
            'message': 'Products refreshed with updated configuration'
        })
    except Exception as e:
        current_app.logger.error(f"Error refreshing products: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

