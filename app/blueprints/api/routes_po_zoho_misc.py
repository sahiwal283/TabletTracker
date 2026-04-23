"""
API routes - all /api/* endpoints
"""
import os
import sqlite3

import requests
from config import Config
from flask import current_app, jsonify

from app.services.zoho_service import zoho_api
from app.utils.auth_utils import (
    admin_required,
)
from app.utils.db_utils import db_read_only, db_transaction

from . import bp


@bp.route('/api/po_tracking/<int:po_id>')
def get_po_tracking(po_id):
    """Get all tracking information for a PO (supports multiple shipments)"""
    try:
        with db_read_only() as conn:
            # Get all shipments for this PO
            shipments = conn.execute('''
                SELECT id, tracking_number, carrier, shipped_date, estimated_delivery, actual_delivery, notes, created_at
                FROM shipments
                WHERE po_id = ?
                ORDER BY created_at DESC
            ''', (po_id,)).fetchall()

            if shipments:
                # Return all shipments
                shipments_list = []
                for shipment in shipments:
                    shipments_list.append({
                        'id': shipment['id'],
                        'tracking_number': shipment['tracking_number'],
                        'carrier': shipment['carrier'],
                        'shipped_date': shipment['shipped_date'],
                        'estimated_delivery': shipment['estimated_delivery'],
                        'actual_delivery': shipment['actual_delivery'],
                        'notes': shipment['notes']
                    })

                return jsonify({
                    'shipments': shipments_list,
                    'has_tracking': True
                })
            else:
                return jsonify({
                    'shipments': [],
                    'has_tracking': False
                })
    except Exception as e:
        return jsonify({'error': str(e)}), 500



@bp.route('/api/find_org_id')
def find_organization_id():
    """Help find the correct Zoho Organization ID"""
    try:
        # Get token first
        token = zoho_api.get_access_token()
        if not token:
            return jsonify({
                'success': False,
                'error': 'Failed to get access token. Check your credentials.'
            })

        # Try to get organizations
        url = 'https://www.zohoapis.com/inventory/v1/organizations'
        headers = {'Authorization': f'Zoho-oauthtoken {token}'}

        response = requests.get(url, headers=headers)
        current_app.logger.debug(f"Organizations API - Status: {response.status_code}")
        current_app.logger.debug(f"Organizations API - Response: {response.text}")

        if response.status_code == 200:
            data = response.json()
            orgs = data.get('organizations', [])
            return jsonify({
                'success': True,
                'organizations': orgs,
                'message': f'Found {len(orgs)} organizations. Use the organization_id from the one you want.'
            })
        else:
            return jsonify({
                'success': False,
                'error': f'Failed to get organizations: {response.status_code} - {response.text}'
            })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Error finding organizations: {str(e)}'
        })



@bp.route('/api/test_zoho_connection')
@admin_required
def test_zoho_connection():
    """Test if Zoho API credentials are working - admin only"""
    try:
        # Try to get an access token
        token = zoho_api.get_access_token()
        if not token:
            return jsonify({
                'success': False,
                'error': 'Failed to get access token. Check your CLIENT_ID, CLIENT_SECRET, and REFRESH_TOKEN in .env file'
            })

        # Try to make a simple API call
        result = zoho_api.make_request('items', method='GET', extra_params={'per_page': 10})
        if result:
            item_count = len(result.get('items', []))
            return jsonify({
                'success': True,
                'message': f'✅ Connected to Zoho! Found {item_count} inventory items.',
                'organization_id': zoho_api.organization_id
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Got access token but API call failed. Check your ORGANIZATION_ID or check the terminal for detailed error info.'
            })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Connection test failed: {str(e)}'
        })



@bp.route('/api/clear_po_data', methods=['POST'])
@admin_required
def clear_po_data():
    """Clear all PO data for fresh sync testing"""
    try:
        with db_transaction() as conn:
            # Clear all PO-related data
            conn.execute('DELETE FROM po_lines')
            conn.execute('DELETE FROM purchase_orders WHERE zoho_po_id IS NOT NULL')  # Keep sample test POs
            conn.execute('DELETE FROM warehouse_submissions')

            return jsonify({
                'success': True,
                'message': '✅ Cleared all synced PO data. Ready for fresh sync!'
            })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Clear failed: {str(e)}'
        }), 500

# ===== PRODUCTION REPORT ENDPOINTS =====



# Temporarily removed force-reload route due to import issues

@bp.route('/debug/server-info')
@admin_required
def server_debug_info():
    """Debug route to check server state - admin only"""
    import time

    try:
        # Check file timestamps
        app_py_time = os.path.getmtime('app.py')
        version_time = os.path.getmtime('__version__.py')

        # Check if we can read version
        try:
            from __version__ import __title__, __version__
            version_info = f"{__title__} v{__version__}"
        except Exception:
            version_info = "Version import failed"

        # Check current working directory
        cwd = os.getcwd()

        # Check if template exists (using absolute path)
        template_path = os.path.join(current_app.root_path, '..', 'templates', 'receiving_management.html')
        template_path = os.path.abspath(template_path)
        template_exists = os.path.exists(template_path)

        # Find database path and check what tables exist (use Config.DATABASE_PATH)
        db_path = Config.DATABASE_PATH
        db_full_path = os.path.abspath(db_path)
        db_exists = os.path.exists(db_path)

        # Check what tables actually exist in this database
        tables_info = "Database not accessible"
        if db_exists:
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cursor.fetchall()]
                tables_info = f"Tables: {tables}"
                conn.close()
            except Exception as e:
                tables_info = f"Database error: {e}"

        return f"""
        <h2>Server Debug Info</h2>
        <p><strong>Version:</strong> {version_info}</p>
        <p><strong>Working Directory:</strong> {cwd}</p>
        <p><strong>App.py Modified:</strong> {time.ctime(app_py_time)}</p>
        <p><strong>Version.py Modified:</strong> {time.ctime(version_time)}</p>
        <p><strong>Receiving Template Exists:</strong> {template_exists}</p>
        <p><strong>Python Path:</strong> {os.sys.path[0]}</p>
        <hr>
        <p><strong>Database Path:</strong> {db_full_path}</p>
        <p><strong>Database Exists:</strong> {db_exists}</p>
        <p><strong>{tables_info}</strong></p>
        <hr>
        <p><a href="/receiving">Test Receiving Route</a></p>
        <p><a href="/receiving/debug">Test Debug Route</a></p>
        """

    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except sqlite3.Error:
                # Debug endpoint should not mask the original error.
                pass
        return f"<h2>Server Debug Error</h2><p>{str(e)}</p>"
