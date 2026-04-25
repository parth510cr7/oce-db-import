from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import psycopg
from psycopg.rows import dict_row


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export DB contents to JSON files.")
    p.add_argument("--out", default="exports", help="Output directory (default: exports)")
    p.add_argument("--limit-sources", type=int, default=0, help="Limit number of sources exported (0 = no limit)")
    p.add_argument(
        "--unsafe-include-raw-text",
        action="store_true",
        help="Include raw text fields (source_chunks.text, extractions.output_json). Off by default.",
    )
    return p.parse_args()


def require_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required")
    return url


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    def default(o: Any):
        # psycopg dict_row returns datetime objects for timestamptz; stringify for JSON export
        try:
            import datetime

            if isinstance(o, (datetime.datetime, datetime.date)):
                return o.isoformat()
        except Exception:
            pass
        return str(o)

    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=default) + "\n", encoding="utf-8")


def export_sources(conn: psycopg.Connection, out_dir: Path, *, limit_sources: int = 0, include_raw_text: bool = False) -> List[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select id::text as id, kind, filename, checksum, uploaded_at
            from sources
            order by uploaded_at asc
            """
            + (" limit %s" if limit_sources and limit_sources > 0 else ""),
            ((limit_sources,) if limit_sources and limit_sources > 0 else ()),
        )
        sources = cur.fetchall()

    write_json(out_dir / "sources.json", sources)

    exported_ids: List[str] = []
    for s in sources:
        source_id = s["id"]
        exported_ids.append(source_id)
        with conn.cursor() as cur:
            cur.execute(
                """
                select chunk_index, page_from, page_to, text, metadata
                from source_chunks
                where source_id = %s
                order by chunk_index asc
                """,
                (source_id,),
            )
            chunks = cur.fetchall()

        if not include_raw_text:
            # Replace text with metadata only (safer exports by default)
            for ch in chunks:
                t = ch.get("text") or ""
                ch["text_len"] = len(t)
                ch["text_sha256"] = __import__("hashlib").sha256(t.encode("utf-8", errors="ignore")).hexdigest() if t else None
                ch["text"] = None

        write_json(out_dir / "sources" / source_id / "source.json", s)
        write_json(out_dir / "sources" / source_id / "chunks.json", chunks)

        with conn.cursor() as cur:
            cur.execute(
                """
                select i.id::text as ingestion_id, i.status, i.started_at, i.finished_at, i.error_text
                from ingestions i
                where i.source_id = %s
                order by i.started_at asc nulls last
                """,
                (source_id,),
            )
            ingestions = cur.fetchall()
        write_json(out_dir / "sources" / source_id / "ingestions.json", ingestions)

        with conn.cursor() as cur:
            cur.execute(
                """
                select e.id::text as extraction_id, e.extractor_version, e.output_json, e.warnings, e.created_at
                from extractions e
                join ingestions i on i.id = e.ingestion_id
                where i.source_id = %s
                order by e.created_at asc
                """,
                (source_id,),
            )
            extractions = cur.fetchall()
        if not include_raw_text:
            for ex in extractions:
                ex["output_json"] = None
        write_json(out_dir / "sources" / source_id / "extractions.json", extractions)

    return exported_ids


def export_rubrics(conn: psycopg.Connection, out_dir: Path) -> None:
    with conn.cursor() as cur:
        cur.execute("select id::text as id, name, version, case_type, active, created_at from rubric_sets order by created_at asc")
        rubric_sets = cur.fetchall()
    write_json(out_dir / "rubric_sets.json", rubric_sets)

    for rs in rubric_sets:
        rs_id = rs["id"]
        with conn.cursor() as cur:
            cur.execute(
                """
                select id::text as id, key, display_name, default_weight
                from rubric_domains
                where rubric_set_id = %s
                order by key asc
                """,
                (rs_id,),
            )
            domains = cur.fetchall()
        write_json(out_dir / "rubrics" / rs_id / "rubric_set.json", rs)
        write_json(out_dir / "rubrics" / rs_id / "domains.json", domains)

        # Criteria per domain
        for d in domains:
            d_id = d["id"]
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select id::text as id, key, description, anchors
                    from rubric_criteria
                    where rubric_domain_id = %s
                    order by key asc
                    """,
                    (d_id,),
                )
                criteria = cur.fetchall()
            write_json(out_dir / "rubrics" / rs_id / "domains" / d["key"] / "criteria.json", criteria)


def export_cases(conn: psycopg.Connection, out_dir: Path) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            select id::text as id, title, case_type, setting, msk_focus, difficulty, source_id::text as source_id, status, created_at
            from cases
            order by created_at asc
            """
        )
        cases = cur.fetchall()
    write_json(out_dir / "cases.json", cases)

    for c in cases:
        case_id = c["id"]
        with conn.cursor() as cur:
            cur.execute(
                """
                select id::text as id, order_index, prompt_text, prompt_audio_url, prompt_type
                from case_prompts
                where case_id = %s
                order by order_index asc
                """,
                (case_id,),
            )
            prompts = cur.fetchall()
        write_json(out_dir / "cases" / case_id / "case.json", c)
        write_json(out_dir / "cases" / case_id / "prompts.json", prompts)

        with conn.cursor() as cur:
            cur.execute(
                """
                select id::text as id, expected_text, importance, rubric_criterion_id::text as rubric_criterion_id
                from case_expected_elements
                where case_id = %s
                order by id asc
                """,
                (case_id,),
            )
            expected = cur.fetchall()
        write_json(out_dir / "cases" / case_id / "expected_elements.json", expected)


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    with psycopg.connect(require_database_url(), row_factory=dict_row) as conn:
        conn.autocommit = True
        exported_sources = export_sources(
            conn,
            out_dir,
            limit_sources=args.limit_sources,
            include_raw_text=bool(args.unsafe_include_raw_text),
        )
        export_rubrics(conn, out_dir)
        export_cases(conn, out_dir)

    write_json(out_dir / "export_manifest.json", {"exported_sources": exported_sources})
    print(f"Wrote JSON export to: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

