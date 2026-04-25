from __future__ import annotations

import argparse
import sys

from examiner.writeback import apply_marksheet, connect, load_marksheet_json
from scoring.passfail import compute_and_persist_station_result
from psycopg.types.json import Json


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate a marksheet JSON and write it to the DB (scores/checklist/globals/flags), then compute pass/fail.")
    ap.add_argument("--marksheet", required=True, help="Path to marksheet JSON file")
    args = ap.parse_args()

    ms = load_marksheet_json(args.marksheet)

    with connect() as conn:
        conn.autocommit = True

        stats, warnings = apply_marksheet(conn, marksheet=ms)
        for w in warnings:
            print(f"[warning] {w}", file=sys.stderr)

        # Snapshot rules used for determinism/auditability
        with conn.cursor() as cur:
            cur.execute(
                """
                update attempts
                set scoring_rules_snapshot = %s
                where id = %s
                """,
                (Json({"passfail": "from_exam_station_rules_json_or_default"}), ms.meta.attempt_id),
            )

        # Compute deterministic station result and persist on station_runs
        result = compute_and_persist_station_result(
            conn,
            station_run_id=ms.meta.station_run_id,
            attempt_id=ms.meta.attempt_id,
            case_id=ms.meta.case_id,
            rubric_set_id=ms.meta.rubric_set_id,
        )

    print({"writeback": stats.__dict__, "result": result})
    return 0


if __name__ == "__main__":
    # Important: run as a module so imports resolve:
    #   python3 -m examiner.apply_marksheet --marksheet <file>
    raise SystemExit(main())

