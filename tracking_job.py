"""
PythonAnywhere scheduled job: refresh shipments that are not delivered.
Run every 15 minutes.
"""
import sqlite3
from tracking_service import refresh_shipment_row

def main():
    conn = sqlite3.connect('tablet_counter.db')
    conn.row_factory = sqlite3.Row

    # Select shipments that likely need updates
    rows = conn.execute(
        """
        SELECT id FROM shipments
        WHERE (
            tracking_status IS NULL OR tracking_status NOT LIKE '%Delivered%'
        )
        ORDER BY COALESCE(last_checked_at, created_at) ASC
        LIMIT 50
        """
    ).fetchall()

    for r in rows:
        try:
            res = refresh_shipment_row(conn, r['id'])
            print('Refreshed', r['id'], res.get('data', {}).get('tracking_status'))
        except Exception as e:
            print('Error refreshing', r['id'], e)

    conn.close()

if __name__ == '__main__':
    main()

