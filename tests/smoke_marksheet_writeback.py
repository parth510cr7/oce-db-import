from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Optional

import psycopg
from psycopg.rows import dict_row


def require_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required")
    return url


def main() -> int:
    with psycopg.connect(require_database_url(), row_factory=dict_row) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            # Pick most recent attempt (or create one via smoke_run.py)
            cur.execute(
                """
                select a.id::text as attempt_id, a.case_id::text as case_id, a.modality
                from attempts a
                order by a.started_at desc
                limit 1
                """
            )
            arow: Optional[dict] = cur.fetchone()
            if not arow:
                print("No attempts found. Run tests/smoke_run.py first.", file=sys.stderr)
                return 2

            attempt_id = arow["attempt_id"]
            case_id = arow["case_id"]

            # Find a rubric_set (prefer case.rubric_set_id, else active OCE Domains)
            cur.execute("select rubric_set_id::text as rubric_set_id from cases where id = %s", (case_id,))
            rubric_set_id = cur.fetchone()["rubric_set_id"]
            if not rubric_set_id:
                # Prefer active, but fall back to any rubric set so smoke tests work.
                cur.execute(
                    """
                    select id::text as id
                    from rubric_sets
                    order by active desc, created_at desc
                    limit 1
                    """
                )
                r = cur.fetchone()
                if not r:
                    print("No rubric_sets found. Seed/create rubric first.", file=sys.stderr)
                    return 3
                rubric_set_id = r["id"]

            # Pick an actual domain key from this rubric set so we don't depend on hardcoded keys.
            cur.execute(
                """
                select key
                from rubric_domains
                where rubric_set_id = %s
                order by key asc
                limit 1
                """,
                (rubric_set_id,),
            )
            drow = cur.fetchone()
            if not drow:
                print("No rubric_domains found for rubric_set. Seed rubric domains first.", file=sys.stderr)
                return 3
            domain_key = drow["key"]

            # Ensure station_run
            cur.execute("select id::text as id from station_runs where attempt_id = %s", (attempt_id,))
            srow = cur.fetchone()
            if srow:
                station_run_id = srow["id"]
            else:
                cur.execute(
                    """
                    insert into station_runs(attempt_id, state, current_prompt_order_index)
                    values (%s, 'active', 0)
                    returning id::text as id
                    """,
                    (attempt_id,),
                )
                station_run_id = cur.fetchone()["id"]

            # Pick 1 response/prompt to use as evidence span anchor
            cur.execute(
                """
                select r.id::text as response_id, r.prompt_id::text as prompt_id, r.response_text
                from responses r
                where r.attempt_id = %s
                order by r.responded_at asc
                limit 1
                """,
                (attempt_id,),
            )
            resp = cur.fetchone()
            if not resp:
                print("No responses found for attempt. Run smoke_run.py first.", file=sys.stderr)
                return 4

            # Build a minimal marksheet JSON that passes validation and writes back
            marksheet = {
                "meta": {
                    "attempt_id": attempt_id,
                    "station_run_id": station_run_id,
                    "case_id": case_id,
                    "rubric_set_id": rubric_set_id,
                    "generated_by": "smoke/cloud-examiner-ai",
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                },
                "marksheet_header": {
                    "candidate_name": None,
                    "candidate_id": None,
                    "exam_name": None,
                    "station_name": "Smoke Station",
                    "date": datetime.now(timezone.utc).date().isoformat(),
                    "modality": "text",
                },
                "overall_result": {
                    "total_score": 0,
                    "total_max": 100,
                    "percentage": 0,
                    "grade": "BORDERLINE",
                    "pass_rule": ">=60% AND no critical flags",
                    "examiner_summary": "Smoke run marksheet.",
                },
                "domain_scores": [
                    {
                        "rubric_domain_key": domain_key,
                        "score_value": 1,
                        "max_value": 2,
                        "weight_applied": 1.0,
                        "rationale": "Demonstrated basic structure.",
                        "evidence_spans": [
                            {
                                "prompt_id": resp["prompt_id"],
                                "quote": (resp["response_text"] or "")[:80],
                                "start_char": 0,
                                "end_char": min(80, len(resp["response_text"] or "")),
                                "supports": "credit",
                                "span_confidence": 0.9,
                                "span_type": "verbatim",
                            }
                        ],
                    }
                ],
                "global_ratings": [],
                "checklist_marks": [],
                "critical_flags": [],
            }

    path = "/tmp/oce_smoke_marksheet.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(marksheet, f, indent=2)

    print(f"Wrote marksheet to {path}")
    print("Now run: python3 -m examiner.apply_marksheet --marksheet " + path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

