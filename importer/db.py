from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json


def require_database_url() -> str:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required (e.g. postgresql://user@localhost:5432/oce_sim)")
    return database_url


@dataclass(frozen=True)
class SourceRef:
    id: str
    kind: str
    filename: str
    checksum: str


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def connect():
    return psycopg.connect(require_database_url(), row_factory=dict_row)


def upsert_source(conn: psycopg.Connection, *, kind: str, path: Path) -> SourceRef:
    checksum = sha256_file(path)
    filename = path.name

    with conn.cursor() as cur:
        cur.execute(
            """
            insert into sources(kind, filename, checksum)
            values (%s, %s, %s)
            on conflict (checksum) do update set filename = excluded.filename
            returning id::text as id, kind, filename, checksum
            """,
            (kind, filename, checksum),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError("Failed to upsert source")
        return SourceRef(**row)


def create_ingestion(conn: psycopg.Connection, *, source_id: str) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into ingestions(source_id, status, started_at)
            values (%s, 'running', now())
            returning id::text as id
            """,
            (source_id,),
        )
        row = cur.fetchone()
        return row["id"]


def finish_ingestion(conn: psycopg.Connection, *, ingestion_id: str, status: str, error_text: Optional[str] = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            update ingestions
            set status = %s,
                finished_at = now(),
                error_text = %s
            where id = %s
            """,
            (status, error_text, ingestion_id),
        )


def insert_source_chunks(
    conn: psycopg.Connection,
    *,
    source_id: str,
    chunks: Iterable[dict[str, Any]],
) -> None:
    rows = list(chunks)
    if not rows:
        return

    with conn.cursor() as cur:
        for r in rows:
            cur.execute(
                """
                insert into source_chunks(source_id, chunk_index, text, page_from, page_to, metadata)
                values (%s, %s, %s, %s, %s, %s)
                on conflict (source_id, chunk_index) do update
                set text = excluded.text,
                    page_from = excluded.page_from,
                    page_to = excluded.page_to,
                    metadata = excluded.metadata
                """,
                (
                    source_id,
                    r["chunk_index"],
                    r["text"],
                    r.get("page_from"),
                    r.get("page_to"),
                    Json(r.get("metadata", {})),
                ),
            )


def insert_extraction(conn: psycopg.Connection, *, ingestion_id: str, extractor_version: str, output_json: Any, warnings: Any) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into extractions(ingestion_id, extractor_version, output_json, warnings)
            values (%s, %s, %s, %s)
            returning id
            """,
            (ingestion_id, extractor_version, Json(output_json), Json(warnings)),
        )
        return cur.fetchone()["id"]


def create_case_with_single_prompt(
    conn: psycopg.Connection,
    *,
    title: str,
    case_type: str,
    prompt_text: str,
    source_id: Optional[str],
    status: str = "draft",
) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into cases(title, case_type, source_id, status)
            values (%s, %s, %s, %s)
            returning id
            """,
            (title, case_type, source_id, status),
        )
        case_id = cur.fetchone()["id"]
        cur.execute(
            """
            insert into case_prompts(case_id, order_index, prompt_text, prompt_type)
            values (%s, 0, %s, 'stem')
            """,
            (case_id, prompt_text),
        )
        return case_id


def upsert_rubric_set(conn: psycopg.Connection, *, name: str, version: str, case_type: str, active: bool = False) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into rubric_sets(name, version, case_type, active)
            values (%s, %s, %s, %s)
            on conflict (name, version) do update
            set case_type = excluded.case_type,
                active = excluded.active
            returning id::text as id
            """,
            (name, version, case_type, active),
        )
        return cur.fetchone()["id"]


def upsert_rubric_domain(
    conn: psycopg.Connection,
    *,
    rubric_set_id: str,
    key: str,
    display_name: str,
    default_weight: Optional[float] = None,
) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into rubric_domains(rubric_set_id, key, display_name, default_weight)
            values (%s, %s, %s, %s)
            on conflict (rubric_set_id, key) do update
            set display_name = excluded.display_name,
                default_weight = excluded.default_weight
            returning id::text as id
            """,
            (rubric_set_id, key, display_name, default_weight),
        )
        return cur.fetchone()["id"]


def upsert_rubric_criterion(
    conn: psycopg.Connection,
    *,
    rubric_domain_id: str,
    key: str,
    description: str,
    anchors: Any,
) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into rubric_criteria(rubric_domain_id, key, description, anchors)
            values (%s, %s, %s, %s)
            on conflict (rubric_domain_id, key) do update
            set description = excluded.description,
                anchors = excluded.anchors
            returning id::text as id
            """,
            (rubric_domain_id, key, description, Json(anchors)),
        )
        return cur.fetchone()["id"]

