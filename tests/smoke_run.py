import os
import sys
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
            # Create a user (idempotent by email)
            cur.execute(
                """
                insert into users(email, name, role)
                values ('student@example.com', 'Demo Student', 'student')
                on conflict (email) do update set name = excluded.name
                returning id::text as id
                """
            )
            user_id = cur.fetchone()["id"]

            # Pick a case
            cur.execute("select id::text as id, title from cases order by created_at desc limit 1")
            case_row: Optional[dict] = cur.fetchone()
            if not case_row:
                print("No cases found. Re-run importer with --write-cases.", file=sys.stderr)
                return 2
            case_id = case_row["id"]

            # Create attempt
            cur.execute(
                """
                insert into attempts(user_id, case_id, modality, transcription)
                values (%s, %s, 'text', '{}'::jsonb)
                returning id::text as id
                """,
                (user_id, case_id),
            )
            attempt_id = cur.fetchone()["id"]

            # Create response for first prompt
            cur.execute(
                """
                select id::text as id from case_prompts
                where case_id = %s
                order by order_index asc
                limit 1
                """,
                (case_id,),
            )
            prompt_id = cur.fetchone()["id"]
            cur.execute(
                """
                insert into responses(attempt_id, prompt_id, response_text)
                values (%s, %s, %s)
                """,
                (attempt_id, prompt_id, "I would start by ensuring informed consent, then proceed with a focused subjective and objective assessment..."),
            )

            # Score across whatever rubric domains exist (if none exist, skip scoring)
            cur.execute(
                """
                select rd.id::text as id
                from rubric_domains rd
                join rubric_sets rs on rs.id = rd.rubric_set_id
                order by rs.created_at desc, rd.key asc
                """
            )
            domain_rows = cur.fetchall()
            for d in domain_rows:
                cur.execute(
                    """
                    insert into scores(attempt_id, rubric_domain_id, score_value, max_value, weight_applied)
                    values (%s, %s, 1, 2, null)
                    """,
                    (attempt_id, d["id"]),
                )

            # Feedback skeleton
            cur.execute(
                """
                insert into feedback_summaries(attempt_id, overall_summary, next_steps, generated_by)
                values (%s, %s, %s, %s)
                """,
                (
                    attempt_id,
                    "Good high-level structure; needs more case-specific red flags and measurable objective tests.",
                    "Practice stating top 3 differential diagnoses + 2 red flags + 3 objective tests tied to the scenario.",
                    "smoke_test",
                ),
            )

            print(f"Smoke test created attempt_id={attempt_id} for case_id={case_id} ({case_row['title']})")

            cur.execute(
                """
                select
                  (select count(*) from responses where attempt_id = %s) as responses,
                  (select count(*) from scores where attempt_id = %s) as scores,
                  (select count(*) from feedback_summaries where attempt_id = %s) as summaries
                """,
                (attempt_id, attempt_id, attempt_id),
            )
            print(cur.fetchone())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

