#!/usr/bin/env python3
"""
Prune extra small_boxes (and their bags) for one receiving, keeping the first N rows by id.

Use when a draft was corrupted with duplicate boxes (e.g. concurrent "Edit draft" loads).

  # Dry run (default): print what would be deleted
  DATABASE_PATH=/path/to/instance/tablettracker.db \\
    python scripts/prune_receiving_boxes.py RECEIVING_ID --keep 65

  # Apply
  DATABASE_PATH=... python scripts/prune_receiving_boxes.py RECEIVING_ID --keep 65 --execute

Requires: no warehouse_submissions referencing bags you are about to delete (otherwise aborts).
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("receiving_id", type=int, help="receiving.id")
    p.add_argument("--keep", type=int, required=True, help="Number of small_boxes rows to keep (lowest id first)")
    p.add_argument("--execute", action="store_true", help="Actually delete; default is dry run only")
    args = p.parse_args()

    db_path = os.environ.get("DATABASE_PATH")
    if not db_path:
        print("Set DATABASE_PATH to your SQLite file.", file=sys.stderr)
        return 2
    if not os.path.isfile(db_path):
        print(f"DATABASE_PATH is not a file: {db_path}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    rows = conn.execute(
        "SELECT id, box_number FROM small_boxes WHERE receiving_id = ? ORDER BY id ASC",
        (args.receiving_id,),
    ).fetchall()
    if not rows:
        print(f"No small_boxes for receiving_id={args.receiving_id}")
        return 1
    if len(rows) <= args.keep:
        print(f"Nothing to do: {len(rows)} box(es) <= --keep {args.keep}")
        return 0

    keep_ids = [int(r["id"]) for r in rows[: args.keep]]
    drop_ids = [int(r["id"]) for r in rows[args.keep :]]
    bag_rows = conn.execute(
        f"SELECT id FROM bags WHERE small_box_id IN ({','.join('?' * len(drop_ids))})",
        tuple(drop_ids),
    ).fetchall()
    bag_ids = [int(r["id"]) for r in bag_rows]

    if bag_ids:
        col_rows = conn.execute("PRAGMA table_info(warehouse_submissions)").fetchall()
        ws_cols = {r[1] for r in col_rows} if col_rows else set()
        if "bag_id" in ws_cols:
            qmarks = ",".join("?" * len(bag_ids))
            sub_count = conn.execute(
                f"SELECT COUNT(*) AS c FROM warehouse_submissions WHERE bag_id IN ({qmarks})",
                tuple(bag_ids),
            ).fetchone()
            n_sub = int(sub_count["c"] if sub_count else 0)
            if n_sub > 0:
                print(
                    f"ABORT: {n_sub} warehouse_submissions reference bags that would be deleted. "
                    "Resolve submissions first or pick a different recovery strategy.",
                    file=sys.stderr,
                )
                return 3

    print(f"Receiving {args.receiving_id}: {len(rows)} small_boxes; keeping ids {keep_ids[0]}..{keep_ids[-1]} ({len(keep_ids)} rows)")
    print(f"Would drop {len(drop_ids)} small_boxes ids: {drop_ids[:8]}{'...' if len(drop_ids) > 8 else ''}")
    print(f"Would delete {len(bag_ids)} bag row(s) under those boxes")

    if not args.execute:
        print("\nDry run only. Pass --execute to apply.")
        return 0

    with conn:
        if bag_ids:
            conn.execute(
                f"DELETE FROM bags WHERE id IN ({','.join('?' * len(bag_ids))})",
                tuple(bag_ids),
            )
        conn.execute(
            f"DELETE FROM small_boxes WHERE id IN ({','.join('?' * len(drop_ids))})",
            tuple(drop_ids),
        )
        conn.execute(
            "UPDATE receiving SET total_small_boxes = ? WHERE id = ?",
            (len(keep_ids), args.receiving_id),
        )

    print("Done. Re-open the draft in the app to verify.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
