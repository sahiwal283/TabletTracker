"""
Machines API routes for managing production machines.
"""
from flask import Blueprint, request, jsonify, current_app
from app.utils.db_utils import db_read_only, db_transaction
from app.utils.auth_utils import admin_required, employee_required

bp = Blueprint('api_machines', __name__)


@bp.route('/api/machines', methods=['GET'])
@employee_required
def get_machines():
    """Get all active machines"""
    try:
        with db_read_only() as conn:
            machines = conn.execute('''
                SELECT * FROM machines 
                WHERE is_active = TRUE
                ORDER BY machine_name
            ''').fetchall()
            
            machines_list = [dict(m) for m in machines]
            current_app.logger.info(f"GET /api/machines - Found {len(machines_list)} active machines")
            return jsonify({'success': True, 'machines': machines_list})
    except Exception as e:
        current_app.logger.error(f"GET /api/machines error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/machines', methods=['POST'])
@admin_required
def create_machine():
    """Create a new machine"""
    try:
        data = request.get_json()
        machine_name = data.get('machine_name', '').strip()
        cards_per_turn = data.get('cards_per_turn')
        
        if not machine_name:
            return jsonify({'success': False, 'error': 'Machine name is required'}), 400
        
        try:
            cards_per_turn = int(cards_per_turn)
            if cards_per_turn < 1:
                return jsonify({'success': False, 'error': 'Cards per turn must be at least 1'}), 400
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid cards per turn value'}), 400
        
        with db_transaction() as conn:
            existing = conn.execute('SELECT id FROM machines WHERE machine_name = ?', (machine_name,)).fetchone()
            if existing:
                return jsonify({'success': False, 'error': 'Machine name already exists'}), 400
            
            conn.execute('''
                INSERT INTO machines (machine_name, cards_per_turn, is_active)
                VALUES (?, ?, TRUE)
            ''', (machine_name, cards_per_turn))
            
            return jsonify({'success': True, 'message': f'Machine "{machine_name}" created successfully'})
    except Exception as e:
        current_app.logger.error(f"Error creating machine: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/machines/<int:machine_id>', methods=['PUT'])
@admin_required
def update_machine(machine_id):
    """Update a machine's configuration"""
    try:
        data = request.get_json()
        machine_name = data.get('machine_name', '').strip()
        cards_per_turn = data.get('cards_per_turn')
        
        if not machine_name:
            return jsonify({'success': False, 'error': 'Machine name is required'}), 400
        
        try:
            cards_per_turn = int(cards_per_turn)
            if cards_per_turn < 1:
                return jsonify({'success': False, 'error': 'Cards per turn must be at least 1'}), 400
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid cards per turn value'}), 400
        
        with db_transaction() as conn:
            machine = conn.execute('SELECT id FROM machines WHERE id = ?', (machine_id,)).fetchone()
            if not machine:
                return jsonify({'success': False, 'error': 'Machine not found'}), 404
            
            existing = conn.execute('SELECT id FROM machines WHERE machine_name = ? AND id != ?', (machine_name, machine_id)).fetchone()
            if existing:
                return jsonify({'success': False, 'error': 'Machine name already exists'}), 400
            
            conn.execute('''
                UPDATE machines 
                SET machine_name = ?, cards_per_turn = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (machine_name, cards_per_turn, machine_id))
            
            return jsonify({'success': True, 'message': f'Machine "{machine_name}" updated successfully'})
    except Exception as e:
        current_app.logger.error(f"Error updating machine: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/machines/<int:machine_id>', methods=['DELETE'])
@admin_required
def delete_machine(machine_id):
    """Soft delete a machine (set is_active = FALSE)"""
    try:
        with db_transaction() as conn:
            machine = conn.execute('SELECT machine_name FROM machines WHERE id = ?', (machine_id,)).fetchone()
            if not machine:
                return jsonify({'success': False, 'error': 'Machine not found'}), 404
            
            conn.execute('''
                UPDATE machines 
                SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (machine_id,))
            
            return jsonify({'success': True, 'message': f'Machine "{machine["machine_name"]}" deleted successfully'})
    except Exception as e:
        current_app.logger.error(f"Error deleting machine: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

