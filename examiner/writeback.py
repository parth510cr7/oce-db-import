from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from examiner.marksheet_models import Marksheet


def require_database_url() -> str:
    import os

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required")
    return url


def connect() -> psycopg.Connection:
    return psycopg.connect(require_database_url(), row_factory=dict_row)


@dataclass(frozen=True)
class WritebackStats:
    scores_upserted: int
    global_marks_upserted: int
    checklist_marks_upserted: int
    critical_flags_inserted: int


def _lookup_rubric_domain_id(conn: psycopg.Connection, *, rubric_set_id: str, domain_key: str) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            select id::text as id
            from rubric_domains
            where rubric_set_id = %s and key = %s
            """,
            (rubric_set_id, domain_key),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError(f"rubric_domain not found for key={domain_key} rubric_set_id={rubric_set_id}")
        return row["id"]


def _lookup_global_rating_id(conn: psycopg.Connection, *, rubric_set_id: str, global_key: str) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            select id::text as id
            from global_ratings
            where rubric_set_id = %s and key = %s
            """,
            (rubric_set_id, global_key),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError(f"global_rating not found for key={global_key} rubric_set_id={rubric_set_id}")
        return row["id"]


def _lookup_checklist_item_id(conn: psycopg.Connection, *, case_id: str, checklist_key: str) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            select id::text as id
            from checklist_items
            where case_id = %s and key = %s
            """,
            (case_id, checklist_key),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError(f"checklist_item not found for key={checklist_key} case_id={case_id}")
        return row["id"]


def _validate_evidence_spans_for_credit(ms: Marksheet) -> List[str]:
    """
    Hard fairness rule: anything that grants credit (domain/global/checklist) must include evidence spans.
    We return a list of warnings; we do not fail hard to avoid blocking early usage.
    """
    warnings: List[str] = []

    for ds in ms.domain_scores:
        if ds.score_value > 0 and not ds.evidence_spans:
            warnings.append(f"domain_scores[{ds.rubric_domain_key}] has score_value>0 but no evidence_spans")

    for gr in ms.global_ratings:
        if gr.score_value > 0 and not gr.evidence_spans:
            warnings.append(f"global_ratings[{gr.global_key}] has score_value>0 but no evidence_spans")

    for cm in ms.checklist_marks:
        if cm.mark_value > 0 and not cm.evidence_spans:
            warnings.append(f"checklist_marks[{cm.checklist_key}] has mark_value>0 but no evidence_spans")

    for cf in ms.critical_flags:
        if cf.severity == "critical":
            if cf.detection_confidence is None:
                warnings.append(f"critical_flags[{cf.flag_key}] critical has no detection_confidence")
            if not cf.evidence_spans:
                warnings.append(f"critical_flags[{cf.flag_key}] critical has no evidence_spans")

    return warnings


def apply_marksheet(conn: psycopg.Connection, *, marksheet: Marksheet) -> Tuple[WritebackStats, List[str]]:
    ms = marksheet
    warnings = _validate_evidence_spans_for_credit(ms)

    # Basic referential sanity checks
    with conn.cursor() as cur:
        cur.execute("select 1 from attempts where id = %s", (ms.meta.attempt_id,))
        if cur.fetchone() is None:
            raise RuntimeError(f"attempt_id not found: {ms.meta.attempt_id}")
        cur.execute("select 1 from station_runs where id = %s", (ms.meta.station_run_id,))
        if cur.fetchone() is None:
            raise RuntimeError(f"station_run_id not found: {ms.meta.station_run_id}")

    scores_upserted = 0
    global_marks_upserted = 0
    checklist_marks_upserted = 0
    critical_flags_inserted = 0

    # Scores (upsert)
    for ds in ms.domain_scores:
        rubric_domain_id = _lookup_rubric_domain_id(conn, rubric_set_id=ms.meta.rubric_set_id, domain_key=ds.rubric_domain_key)
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into scores(attempt_id, rubric_domain_id, score_value, max_value, weight_applied, rationale, evidence_spans, scored_by, scored_at)
                values (%s, %s, %s, %s, %s, %s, %s, %s, now())
                on conflict (attempt_id, rubric_domain_id) do update
                  set score_value = excluded.score_value,
                      max_value = excluded.max_value,
                      weight_applied = excluded.weight_applied,
                      rationale = excluded.rationale,
                      evidence_spans = excluded.evidence_spans,
                      scored_by = excluded.scored_by,
                      scored_at = excluded.scored_at
                """,
                (
                    ms.meta.attempt_id,
                    rubric_domain_id,
                    ds.score_value,
                    ds.max_value,
                    ds.weight_applied,
                    ds.rationale,
                    Json([s.model_dump() for s in ds.evidence_spans]),
                    ms.meta.generated_by,
                ),
            )
        scores_upserted += 1

    # Global rating marks (upsert)
    for gr in ms.global_ratings:
        global_rating_id = _lookup_global_rating_id(conn, rubric_set_id=ms.meta.rubric_set_id, global_key=gr.global_key)
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into global_rating_marks(station_run_id, global_rating_id, score_value, max_value, rationale, evidence_spans)
                values (%s, %s, %s, %s, %s, %s)
                on conflict (station_run_id, global_rating_id) do update
                  set score_value = excluded.score_value,
                      max_value = excluded.max_value,
                      rationale = excluded.rationale,
                      evidence_spans = excluded.evidence_spans
                """,
                (
                    ms.meta.station_run_id,
                    global_rating_id,
                    gr.score_value,
                    gr.max_value,
                    gr.rationale,
                    Json([s.model_dump() for s in gr.evidence_spans]),
                ),
            )
        global_marks_upserted += 1

    # Checklist marks (upsert)
    for cm in ms.checklist_marks:
        checklist_item_id = _lookup_checklist_item_id(conn, case_id=ms.meta.case_id, checklist_key=cm.checklist_key)
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into checklist_marks(station_run_id, checklist_item_id, mark_value, evidence_spans)
                values (%s, %s, %s, %s)
                on conflict (station_run_id, checklist_item_id) do update
                  set mark_value = excluded.mark_value,
                      evidence_spans = excluded.evidence_spans
                """,
                (
                    ms.meta.station_run_id,
                    checklist_item_id,
                    cm.mark_value,
                    Json([s.model_dump() for s in cm.evidence_spans]),
                ),
            )
        checklist_marks_upserted += 1

    # Critical flags: replace-all per station_run for idempotency
    with conn.cursor() as cur:
        cur.execute("delete from critical_flags where station_run_id = %s", (ms.meta.station_run_id,))

    for cf in ms.critical_flags:
        # Confidence gating: do not store "critical" as critical if low confidence
        sev = cf.severity
        if sev == "critical":
            if cf.detection_confidence is None or cf.detection_confidence < 0.85 or not cf.evidence_spans:
                sev = "major"
                warnings.append(
                    f"critical_flag[{cf.flag_key}] downgraded to major (confidence/evidence insufficient)"
                )

        with conn.cursor() as cur:
            cur.execute(
                """
                insert into critical_flags(station_run_id, flag_key, severity, description, evidence_spans, detection_confidence)
                values (%s, %s, %s, %s, %s, %s)
                """,
                (
                    ms.meta.station_run_id,
                    cf.flag_key,
                    sev,
                    cf.description,
                    Json([s.model_dump() for s in cf.evidence_spans]),
                    cf.detection_confidence,
                ),
            )
        critical_flags_inserted += 1

    return (
        WritebackStats(
            scores_upserted=scores_upserted,
            global_marks_upserted=global_marks_upserted,
            checklist_marks_upserted=checklist_marks_upserted,
            critical_flags_inserted=critical_flags_inserted,
        ),
        warnings,
    )


def load_marksheet_json(path: str) -> Marksheet:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return Marksheet.model_validate(data)

