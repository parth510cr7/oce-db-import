from __future__ import annotations

import argparse
import os
from typing import Dict, List, Optional, Tuple

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json


def require_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required")
    return url


OCE_GLOBAL_ANCHORS_0_4 = {
    "0": "Unsafe / not at entry-to-practice level",
    "1": "Borderline (major gaps)",
    "2": "Meets standard (safe, organized)",
    "3": "Strong (clear, comprehensive, prioritized)",
    "4": "Excellent (highly efficient and patient-centred)",
}


def get_latest_rubric_set_id(conn: psycopg.Connection, *, name: str) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            select id::text as id
            from rubric_sets
            where name = %s
            order by created_at desc
            limit 1
            """,
            (name,),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError(f"Missing rubric_set: {name}")
        return row["id"]


def upsert_global_rating(conn: psycopg.Connection, *, rubric_set_id: str, key: str, display_name: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into global_ratings(rubric_set_id, key, display_name, anchors)
            values (%s, %s, %s, %s)
            on conflict (rubric_set_id, key) do update
            set display_name = excluded.display_name,
                anchors = excluded.anchors
            """,
            (rubric_set_id, key, display_name, Json(OCE_GLOBAL_ANCHORS_0_4)),
        )


def ensure_oce_global_ratings(conn: psycopg.Connection) -> str:
    rubric_set_id = get_latest_rubric_set_id(conn, name="OCE Domains")
    upsert_global_rating(conn, rubric_set_id=rubric_set_id, key="overall", display_name="Overall competence")
    upsert_global_rating(conn, rubric_set_id=rubric_set_id, key="safety", display_name="Safety")
    upsert_global_rating(conn, rubric_set_id=rubric_set_id, key="communication", display_name="Communication")
    return rubric_set_id


def checklist_exists(conn: psycopg.Connection, *, case_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("select 1 from checklist_items where case_id = %s limit 1", (case_id,))
        return cur.fetchone() is not None


def insert_checklist_items(conn: psycopg.Connection, *, case_id: str, items: List[Tuple[str, str, bool, float]]) -> None:
    with conn.cursor() as cur:
        for key, text, is_critical, weight in items:
            cur.execute(
                """
                insert into checklist_items(case_id, key, text, is_critical, weight)
                values (%s, %s, %s, %s, %s)
                on conflict (case_id, key) do update
                set text = excluded.text,
                    is_critical = excluded.is_critical,
                    weight = excluded.weight
                """,
                (case_id, key, text, is_critical, weight),
            )


def build_case1_checklist() -> List[Tuple[str, str, bool, float]]:
    return [
        ("safety_red_flags", "Screens for key red flags/contraindications relevant to this presentation.", True, 2),
        ("consent_plain", "Obtains informed consent in plain language and checks understanding.", True, 2),
        ("focused_subjective", "Uses a focused subjective history (mechanism/onset, irritability, 24h pattern, function, goals).", False, 1),
        ("focused_objective", "Selects appropriate objective tests/measures linked to hypotheses.", False, 1),
        ("working_dx", "States a working diagnosis plus at least one alternative differential.", False, 1),
        ("next_steps", "Provides appropriate immediate next steps and safety-netting.", True, 2),
        ("structure_prioritization", "Answer is structured and prioritized (top items first; avoids rambling).", False, 1),
    ]


def build_case2_checklist() -> List[Tuple[str, str, bool, float]]:
    return [
        ("plan_top3", "Proposes a safe, evidence-informed plan with top 3 interventions.", True, 2),
        ("dosage_progression", "Includes basic dosage/progression (progress/regress criteria).", False, 1),
        ("smart_goals", "Sets 2 measurable goals aligned to client priorities and barriers.", False, 1),
        ("precautions_monitoring", "States precautions/contraindications and how to monitor/respond.", True, 2),
        ("reassess_modify", "Defines reassessment outcomes and when to modify/escalate.", False, 1),
        ("self_management", "Provides self-management/home program and discharge criteria.", False, 1),
        ("collab_referral", "States when/how to collaborate or refer to other providers.", False, 1),
        ("structure_prioritization", "Answer is structured and prioritized (top items first; avoids rambling).", False, 1),
    ]


def infer_case_type(case_type: str) -> str:
    if case_type == "case1_assessment":
        return "case1"
    if case_type == "case2_treatment_management":
        return "case2"
    return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed OSCE marking primitives: global ratings + checklist items.")
    ap.add_argument("--only-source-id", default="", help="If set, seed checklist only for cases from this sources.id")
    ap.add_argument("--status", default="published", choices=["draft", "published", "any"])
    args = ap.parse_args()

    with psycopg.connect(require_database_url(), row_factory=dict_row) as conn:
        conn.autocommit = True

        ensure_oce_global_ratings(conn)

        where = []
        params: List[str] = []
        if args.only_source_id:
            where.append("source_id::text = %s")
            params.append(args.only_source_id)
        if args.status != "any":
            where.append("status = %s")
            params.append(args.status)
        where_sql = ("where " + " and ".join(where)) if where else ""

        with conn.cursor() as cur:
            cur.execute(
                f"""
                select id::text as id, case_type
                from cases
                {where_sql}
                """,
                params,
            )
            cases = cur.fetchall()

        created = 0
        for c in cases:
            case_id = c["id"]
            if checklist_exists(conn, case_id=case_id):
                continue
            ct = infer_case_type(c["case_type"])
            if ct == "case1":
                items = build_case1_checklist()
            elif ct == "case2":
                items = build_case2_checklist()
            else:
                # skip unknown case types for now
                continue
            insert_checklist_items(conn, case_id=case_id, items=items)
            created += 1

    print(f"Seeded checklist for {created} cases and ensured OCE global ratings exist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

