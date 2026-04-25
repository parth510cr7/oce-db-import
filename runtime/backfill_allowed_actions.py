from __future__ import annotations

import argparse
from typing import Any, Dict, List

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from runtime.action_taxonomy import normalize_allowed_actions
from runtime.dbconn import connect


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill cases.allowed_actions to canonical action keys where possible.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    updated = 0
    scanned = 0

    with connect() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """
                select id::text as id, allowed_actions
                from cases
                order by created_at asc
                """
                + (" limit %s" if args.limit and args.limit > 0 else ""),
                ((args.limit,) if args.limit and args.limit > 0 else ()),
            )
            rows = cur.fetchall()

        for r in rows:
            scanned += 1
            raw = r.get("allowed_actions")
            canonical = sorted(normalize_allowed_actions(raw))

            # If already canonical (all items look like dotted keys), skip.
            already = False
            if isinstance(raw, list) and raw and all(isinstance(x, str) and "." in x for x in raw):
                already = True
            if already:
                continue

            if not canonical:
                continue

            if args.dry_run:
                print({"case_id": r["id"], "before": raw, "after": canonical})
                continue

            with conn.cursor() as cur:
                cur.execute(
                    """
                    update cases
                    set allowed_actions = %s
                    where id = %s
                    """,
                    (Json(canonical), r["id"]),
                )
            updated += 1

    print({"scanned": scanned, "updated": updated, "dry_run": bool(args.dry_run)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

