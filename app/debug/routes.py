"""
Debug and diagnostic routes
"""

from flask import render_template, request, session, redirect, url_for, flash, jsonify, current_app
from . import bp
from ..utils.decorators import admin_required
from ..models.database import get_db

@bp.route('/server-info')
def server_debug_info():
    """Debug route to check server state - no auth required"""
    import os
    import sys
    from datetime import datetime
    
    debug_info = {
        'timestamp': datetime.now().isoformat(),
        'python_version': sys.version,
        'working_directory': os.getcwd(),
        'flask_env': current_app.config.get('ENV', 'unknown'),
        'database_url': current_app.config.get('DATABASE_URL', 'not set'),
        'session_keys': list(session.keys()) if session else [],
        'request_method': request.method,
        'request_path': request.path,
        'request_args': dict(request.args),
    }
    
    # Check database connection
    try:
        conn = get_db()
        conn.execute('SELECT 1').fetchone()
        debug_info['database_status'] = 'connected'
        conn.close()
    except Exception as e:
        debug_info['database_status'] = f'error: {str(e)}'
    
    return jsonify(debug_info)

@bp.route('/receiving')
@admin_required
def receiving_debug():
    """Debug receiving system state"""
    try:
        conn = get_db()
        
        # Get receiving stats
        receiving_count = conn.execute('SELECT COUNT(*) as count FROM receiving').fetchone()['count']
        boxes_count = conn.execute('SELECT COUNT(*) as count FROM small_boxes').fetchone()['count'] 
        bags_count = conn.execute('SELECT COUNT(*) as count FROM bags').fetchone()['count']
        
        # Get recent activity
        recent_receiving = conn.execute('''
            SELECT r.*, po.po_number 
            FROM receiving r 
            JOIN purchase_orders po ON r.po_id = po.id 
            ORDER BY r.received_date DESC 
            LIMIT 10
        ''').fetchall()
        
        conn.close()
        
        debug_data = {
            'receiving_records': receiving_count,
            'total_boxes': boxes_count,
            'total_bags': bags_count,
            'recent_activity': [dict(r) for r in recent_receiving]
        }
        
        return jsonify(debug_data)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
