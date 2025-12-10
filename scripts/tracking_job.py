"""
PythonAnywhere scheduled job: refresh shipments that are not delivered.
Run every 15 minutes.
"""
import sqlite3
from tracking_service import refresh_shipment_row

def ensure_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    # Add tracking columns if missing (safe no-ops if already exist)
    cur.execute("PRAGMA table_info(shipments)")
    existing = {row[1] for row in cur.fetchall()}
    needed = {
        "carrier_code": "TEXT",
        "tracking_status": "TEXT",
        "last_checkpoint": "TEXT",
        "delivered_at": "DATE",
        "last_checked_at": "TIMESTAMP",
    }
    for col, coltype in needed.items():
        if col not in existing:
            try:
                cur.execute(f"ALTER TABLE shipments ADD COLUMN {col} {coltype}")
            except Exception:
                pass
    conn.commit()

def main():
    conn = sqlite3.connect('tablet_counter.db')
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)

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

