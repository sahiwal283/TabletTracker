"""
Machines API routes for managing production machines.
"""
import json

from flask import Blueprint, current_app, jsonify, request

from app.utils.auth_utils import admin_required, employee_required
from app.utils.db_utils import db_read_only, db_transaction

bp = Blueprint('api_machines', __name__)
VALID_MACHINE_ROLES = {'sealing', 'blister', 'packaging', 'stickering', 'bottle'}


def _normalize_machine_role(raw_role, default='sealing'):
    role = (raw_role or default or 'sealing').strip().lower()
    if role not in VALID_MACHINE_ROLES:
        return None
    return role


def _ensure_machine_metadata_columns(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(machines)").fetchall()}
    adds = []
    if 'area_name' not in cols:
        adds.append("ALTER TABLE machines ADD COLUMN area_name TEXT")
    if 'machine_category' not in cols:
        adds.append("ALTER TABLE machines ADD COLUMN machine_category TEXT")
    if 'raw_materials_json' not in cols:
        adds.append("ALTER TABLE machines ADD COLUMN raw_materials_json TEXT")
    if 'components_json' not in cols:
        adds.append("ALTER TABLE machines ADD COLUMN components_json TEXT")
    if 'compressor_json' not in cols:
        adds.append("ALTER TABLE machines ADD COLUMN compressor_json TEXT")
    for sql in adds:
        conn.execute(sql)


@bp.route('/api/machines', methods=['GET'])
@employee_required
def get_machines():
    """Get all active machines"""
    try:
        role = request.args.get('role')
        normalized_role = None
        if role is not None and str(role).strip() != '':
            normalized_role = _normalize_machine_role(role, default=None)
            if not normalized_role:
                return jsonify({'success': False, 'error': 'Invalid role.'}), 400
        with db_read_only() as conn:
            _ensure_machine_metadata_columns(conn)
            if normalized_role:
                machines = conn.execute(
                    '''
                    SELECT * FROM machines
                    WHERE is_active = TRUE AND machine_role = ?
                    ORDER BY machine_name
                    ''',
                    (normalized_role,),
                ).fetchall()
            else:
                machines = conn.execute('''
                    SELECT * FROM machines
                    WHERE is_active = TRUE
                    ORDER BY machine_name
                ''').fetchall()

            machines_list = [dict(m) for m in machines]
            for m in machines_list:
                for k in ('raw_materials_json', 'components_json', 'compressor_json'):
                    raw = m.get(k)
                    try:
                        m[k.replace('_json', '')] = json.loads(raw) if raw else []
                    except Exception:
                        m[k.replace('_json', '')] = []
            return jsonify({'success': True, 'machines': machines_list})
    except Exception as e:
        current_app.logger.error(f"GET /api/machines error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/machines', methods=['POST'])
@admin_required
def create_machine():
    """Create a new machine"""
    try:
        data = request.get_json() or {}
        machine_name = data.get('machine_name', '').strip()
        cards_per_turn = data.get('cards_per_turn')
        machine_role = _normalize_machine_role(data.get('machine_role'), default='sealing')

        if not machine_name:
            return jsonify({'success': False, 'error': 'Machine name is required'}), 400
        if not machine_role:
            return jsonify({'success': False, 'error': 'Machine role is invalid'}), 400

        try:
            cards_per_turn = int(cards_per_turn)
            if cards_per_turn < 1:
                return jsonify({'success': False, 'error': 'Output units per cycle must be at least 1'}), 400
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid output-units value'}), 400

        with db_transaction() as conn:
            _ensure_machine_metadata_columns(conn)
            existing = conn.execute('SELECT id FROM machines WHERE machine_name = ?', (machine_name,)).fetchone()
            if existing:
                return jsonify({'success': False, 'error': 'Machine name already exists'}), 400

            conn.execute('''
                INSERT INTO machines (
                    machine_name, cards_per_turn, machine_role, area_name, machine_category,
                    raw_materials_json, components_json, compressor_json, is_active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, TRUE)
            ''', (
                machine_name,
                cards_per_turn,
                machine_role,
                (data.get('area_name') or '').strip() or None,
                (data.get('machine_category') or '').strip() or None,
                json.dumps(data.get('raw_materials') or []),
                json.dumps(data.get('components') or []),
                json.dumps(data.get('compressor') or []),
            ))

            return jsonify({'success': True, 'message': f'Machine "{machine_name}" created successfully'})
    except Exception as e:
        current_app.logger.error(f"Error creating machine: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/machines/<int:machine_id>', methods=['PUT'])
@admin_required
def update_machine(machine_id):
    """Update a machine's configuration"""
    try:
        data = request.get_json() or {}
        machine_name = data.get('machine_name', '').strip()
        cards_per_turn = data.get('cards_per_turn')
        machine_role = _normalize_machine_role(data.get('machine_role'), default='sealing')

        if not machine_name:
            return jsonify({'success': False, 'error': 'Machine name is required'}), 400
        if not machine_role:
            return jsonify({'success': False, 'error': 'Machine role is invalid'}), 400

        try:
            cards_per_turn = int(cards_per_turn)
            if cards_per_turn < 1:
                return jsonify({'success': False, 'error': 'Output units per cycle must be at least 1'}), 400
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid output-units value'}), 400

        with db_transaction() as conn:
            _ensure_machine_metadata_columns(conn)
            machine = conn.execute('SELECT id FROM machines WHERE id = ?', (machine_id,)).fetchone()
            if not machine:
                return jsonify({'success': False, 'error': 'Machine not found'}), 404

            existing = conn.execute('SELECT id FROM machines WHERE machine_name = ? AND id != ?', (machine_name, machine_id)).fetchone()
            if existing:
                return jsonify({'success': False, 'error': 'Machine name already exists'}), 400

            conn.execute('''
                UPDATE machines
                SET machine_name = ?, cards_per_turn = ?, machine_role = ?,
                    area_name = ?, machine_category = ?, raw_materials_json = ?,
                    components_json = ?, compressor_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (
                machine_name,
                cards_per_turn,
                machine_role,
                (data.get('area_name') or '').strip() or None,
                (data.get('machine_category') or '').strip() or None,
                json.dumps(data.get('raw_materials') or []),
                json.dumps(data.get('components') or []),
                json.dumps(data.get('compressor') or []),
                machine_id,
            ))

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
