"""
Machines API routes for managing production machines.
"""
import json
import time

from flask import Blueprint, current_app, jsonify, request

from app.utils.auth_utils import admin_required, employee_required
from app.utils.db_utils import db_read_only, db_transaction

bp = Blueprint('api_machines', __name__)
VALID_MACHINE_ROLES = {'sealing', 'blister', 'packaging', 'stickering', 'bottle'}
VALID_COMPRESSOR_STATUS = {'working', 'down', 'maintenance'}
VALID_ROLL_TYPES = {'pvc', 'foil'}


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


def _ensure_asset_tracking_tables(conn):
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS compressors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            compressor_name TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'working',
            machine_id INTEGER,
            notes TEXT,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at INTEGER,
            updated_at INTEGER
        )
        '''
    )
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS blister_material_rolls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_id INTEGER NOT NULL,
            material_type TEXT NOT NULL,
            roll_code TEXT NOT NULL,
            started_at_ms INTEGER NOT NULL,
            ended_at_ms INTEGER,
            start_press_count REAL NOT NULL DEFAULT 0,
            end_press_count REAL,
            blisters_per_press INTEGER NOT NULL DEFAULT 1,
            total_blisters REAL,
            status TEXT NOT NULL DEFAULT 'active'
        )
        '''
    )


def _coerce_positive_int(v, default=1):
    try:
        n = int(v)
        return n if n > 0 else default
    except Exception:
        return default


def _resolve_machine_id_from_station(conn, station_id):
    try:
        row = conn.execute(
            'SELECT machine_id FROM workflow_stations WHERE id = ?',
            (_coerce_positive_int(station_id, 0),),
        ).fetchone()
        if not row:
            return None
        return row['machine_id']
    except Exception:
        return None


def _blister_press_count_for_station(conn, station_id):
    sid = _coerce_positive_int(station_id, 0)
    if sid < 1:
        return 0.0
    try:
        row = conn.execute(
            '''
            SELECT COALESCE(SUM(
                CASE
                    WHEN json_extract(payload, '$.counter_end') IS NOT NULL
                     AND json_extract(payload, '$.counter_start') IS NOT NULL
                     AND CAST(json_extract(payload, '$.counter_end') AS REAL) >= CAST(json_extract(payload, '$.counter_start') AS REAL)
                    THEN CAST(json_extract(payload, '$.counter_end') AS REAL) - CAST(json_extract(payload, '$.counter_start') AS REAL)
                    ELSE COALESCE(CAST(json_extract(payload, '$.count_total') AS REAL), 0)
                END
            ), 0) AS presses
            FROM workflow_events
            WHERE event_type = 'BLISTER_COMPLETE'
              AND (
                station_id = ?
                OR CAST(json_extract(payload, '$.station_id') AS INTEGER) = ?
                OR CAST(json_extract(payload, '$.stationId') AS INTEGER) = ?
              )
            ''',
            (sid, sid, sid),
        ).fetchone()
        return float(row['presses'] or 0)
    except Exception:
        return 0.0


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
            _ensure_asset_tracking_tables(conn)
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
                try:
                    comp_rows = conn.execute(
                        '''
                        SELECT id, compressor_name, status
                        FROM compressors
                        WHERE is_active = TRUE AND machine_id = ?
                        ORDER BY compressor_name
                        ''',
                        (m.get('id'),),
                    ).fetchall()
                    m['assigned_compressors'] = [dict(r) for r in comp_rows]
                except Exception:
                    m['assigned_compressors'] = []
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
            _ensure_asset_tracking_tables(conn)
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
            _ensure_asset_tracking_tables(conn)
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


@bp.route('/api/compressors', methods=['GET'])
@employee_required
def get_compressors():
    try:
        with db_read_only() as conn:
            _ensure_asset_tracking_tables(conn)
            rows = conn.execute(
                '''
                SELECT c.id, c.compressor_name, c.status, c.machine_id, c.notes,
                       m.machine_name
                FROM compressors c
                LEFT JOIN machines m ON m.id = c.machine_id
                WHERE c.is_active = TRUE
                ORDER BY c.compressor_name
                '''
            ).fetchall()
            return jsonify({'success': True, 'compressors': [dict(r) for r in rows]})
    except Exception as e:
        current_app.logger.error(f"GET /api/compressors error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/compressors', methods=['POST'])
@admin_required
def create_compressor():
    try:
        data = request.get_json() or {}
        compressor_name = (data.get('compressor_name') or '').strip()
        status = (data.get('status') or 'working').strip().lower()
        if not compressor_name:
            return jsonify({'success': False, 'error': 'Compressor name is required'}), 400
        if status not in VALID_COMPRESSOR_STATUS:
            return jsonify({'success': False, 'error': 'Invalid compressor status'}), 400
        machine_id = data.get('machine_id')
        machine_id = _coerce_positive_int(machine_id, 0) or None
        now_ms = int(time.time() * 1000)
        with db_transaction() as conn:
            _ensure_asset_tracking_tables(conn)
            conn.execute(
                '''
                INSERT INTO compressors (
                    compressor_name, status, machine_id, notes, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, TRUE, ?, ?)
                ''',
                (
                    compressor_name,
                    status,
                    machine_id,
                    (data.get('notes') or '').strip() or None,
                    now_ms,
                    now_ms,
                ),
            )
            return jsonify({'success': True, 'message': 'Compressor added'})
    except Exception as e:
        current_app.logger.error(f"POST /api/compressors error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/compressors/<int:compressor_id>', methods=['PUT'])
@admin_required
def update_compressor(compressor_id):
    try:
        data = request.get_json() or {}
        status = (data.get('status') or 'working').strip().lower()
        if status not in VALID_COMPRESSOR_STATUS:
            return jsonify({'success': False, 'error': 'Invalid compressor status'}), 400
        machine_id = _coerce_positive_int(data.get('machine_id'), 0) or None
        notes_val = (data.get('notes') or '').strip() or None
        new_name = None
        if 'compressor_name' in data:
            new_name = (data.get('compressor_name') or '').strip()
            if not new_name:
                return jsonify({'success': False, 'error': 'Compressor name is required'}), 400
        now_ms = int(time.time() * 1000)
        with db_transaction() as conn:
            _ensure_asset_tracking_tables(conn)
            row = conn.execute(
                '''
                SELECT compressor_name FROM compressors
                WHERE id = ? AND is_active = TRUE
                ''',
                (compressor_id,),
            ).fetchone()
            if not row:
                return jsonify({'success': False, 'error': 'Compressor not found'}), 404
            current_name = row['compressor_name']
            final_name = current_name
            if new_name is not None:
                if new_name != current_name:
                    dup = conn.execute(
                        '''
                        SELECT id FROM compressors
                        WHERE compressor_name = ? AND id != ? AND is_active = TRUE
                        ''',
                        (new_name, compressor_id),
                    ).fetchone()
                    if dup:
                        return (
                            jsonify(
                                {
                                    'success': False,
                                    'error': 'A compressor with that name already exists',
                                }
                            ),
                            400,
                        )
                final_name = new_name
            conn.execute(
                '''
                UPDATE compressors
                SET compressor_name = ?, status = ?, machine_id = ?, notes = ?, updated_at = ?
                WHERE id = ? AND is_active = TRUE
                ''',
                (
                    final_name,
                    status,
                    machine_id,
                    notes_val,
                    now_ms,
                    compressor_id,
                ),
            )
            return jsonify({'success': True, 'message': 'Compressor updated'})
    except Exception as e:
        current_app.logger.error(f"PUT /api/compressors/{compressor_id} error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/blister-material-rolls/summary', methods=['GET'])
@employee_required
def get_blister_roll_summary():
    try:
        station_id = _coerce_positive_int(request.args.get('station_id'), 0)
        machine_id = _coerce_positive_int(request.args.get('machine_id'), 0)
        with db_read_only() as conn:
            _ensure_asset_tracking_tables(conn)
            if machine_id < 1 and station_id > 0:
                machine_id = _resolve_machine_id_from_station(conn, station_id) or 0
            if station_id < 1 and machine_id > 0:
                row = conn.execute(
                    '''
                    SELECT id FROM workflow_stations
                    WHERE machine_id = ? AND COALESCE(station_kind, 'sealing') = 'blister'
                    ORDER BY id LIMIT 1
                    ''',
                    (machine_id,),
                ).fetchone()
                station_id = int(row['id']) if row else 0

            press_count = _blister_press_count_for_station(conn, station_id)
            active_rows = conn.execute(
                '''
                SELECT *
                FROM blister_material_rolls
                WHERE machine_id = ? AND status = 'active'
                ORDER BY id DESC
                ''',
                (machine_id,),
            ).fetchall() if machine_id > 0 else []
            active = {}
            for r in active_rows:
                d = dict(r)
                used = max(0.0, (press_count - float(d.get('start_press_count') or 0.0)) * float(d.get('blisters_per_press') or 1.0))
                d['blisters_used_live'] = used
                active[str(d.get('material_type') or '').lower()] = d
            return jsonify(
                {
                    'success': True,
                    'machine_id': machine_id if machine_id > 0 else None,
                    'station_id': station_id if station_id > 0 else None,
                    'current_press_count': press_count,
                    'active_rolls': active,
                }
            )
    except Exception as e:
        current_app.logger.error(f"GET /api/blister-material-rolls/summary error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/blister-material-rolls/change', methods=['POST'])
@admin_required
def change_blister_material_roll():
    try:
        data = request.get_json() or {}
        material_type = str(data.get('material_type') or '').strip().lower()
        if material_type not in VALID_ROLL_TYPES:
            return jsonify({'success': False, 'error': 'material_type must be pvc or foil'}), 400
        station_id = _coerce_positive_int(data.get('station_id'), 0)
        machine_id = _coerce_positive_int(data.get('machine_id'), 0)
        roll_code = (data.get('roll_code') or '').strip()
        with db_transaction() as conn:
            _ensure_asset_tracking_tables(conn)
            if machine_id < 1 and station_id > 0:
                machine_id = _resolve_machine_id_from_station(conn, station_id) or 0
            if machine_id < 1:
                return jsonify({'success': False, 'error': 'machine_id or station_id required'}), 400
            if station_id < 1:
                row = conn.execute(
                    '''
                    SELECT id FROM workflow_stations
                    WHERE machine_id = ? AND COALESCE(station_kind, 'sealing') = 'blister'
                    ORDER BY id LIMIT 1
                    ''',
                    (machine_id,),
                ).fetchone()
                station_id = int(row['id']) if row else 0
            if station_id < 1:
                return jsonify({'success': False, 'error': 'No blister station mapped to machine'}), 400

            machine = conn.execute(
                'SELECT cards_per_turn FROM machines WHERE id = ?',
                (machine_id,),
            ).fetchone()
            blisters_per_press = _coerce_positive_int(machine['cards_per_turn'] if machine else 1, 1)
            current_press_count = _blister_press_count_for_station(conn, station_id)
            now_ms = int(time.time() * 1000)

            active_row = conn.execute(
                '''
                SELECT id, start_press_count, blisters_per_press
                FROM blister_material_rolls
                WHERE machine_id = ? AND material_type = ? AND status = 'active'
                ORDER BY id DESC LIMIT 1
                ''',
                (machine_id, material_type),
            ).fetchone()
            if active_row:
                start_press = float(active_row['start_press_count'] or 0.0)
                bpp = float(active_row['blisters_per_press'] or blisters_per_press)
                total_blisters = max(0.0, (current_press_count - start_press) * bpp)
                conn.execute(
                    '''
                    UPDATE blister_material_rolls
                    SET ended_at_ms = ?, end_press_count = ?, total_blisters = ?, status = 'closed'
                    WHERE id = ?
                    ''',
                    (now_ms, current_press_count, total_blisters, active_row['id']),
                )

            if not roll_code:
                roll_code = f'{material_type.upper()}-{now_ms}'
            conn.execute(
                '''
                INSERT INTO blister_material_rolls (
                    machine_id, material_type, roll_code,
                    started_at_ms, start_press_count, blisters_per_press, status
                ) VALUES (?, ?, ?, ?, ?, ?, 'active')
                ''',
                (machine_id, material_type, roll_code, now_ms, current_press_count, blisters_per_press),
            )
            return jsonify(
                {
                    'success': True,
                    'machine_id': machine_id,
                    'station_id': station_id,
                    'material_type': material_type,
                    'roll_code': roll_code,
                    'current_press_count': current_press_count,
                    'blisters_per_press': blisters_per_press,
                }
            )
    except Exception as e:
        current_app.logger.error(f"POST /api/blister-material-rolls/change error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
