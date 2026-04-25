from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from importer import db
from importer.extractors import (
    heuristic_detect_domains,
    heuristic_detect_cpte_domains,
    heuristic_extract_cases_from_chunks,
    heuristic_extract_domain_bullets,
)
from importer.pdf_text import chunk_pages, extract_pdf_pages


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Import a source document into Postgres with provenance.")
    p.add_argument("--source", required=True, help="Path to source PDF (or exported PPT PDF).")
    p.add_argument("--kind", required=True, choices=["pdf"], help="Source kind.")
    p.add_argument("--case-type-default", default="case1_assessment", help="Default case_type for extracted cases.")
    p.add_argument("--write-cases", action="store_true", help="If set, create draft cases from extracted case headers.")
    p.add_argument("--write-rubric", action="store_true", help="If set, create a rubric_set + rubric_domains if detected.")
    p.add_argument("--write-criteria", action="store_true", help="If set, create rubric_criteria from domain bullet lists (anchors TBD).")
    p.add_argument("--rubric-name", default="OCE Domains", help="Rubric set name when using --write-rubric.")
    p.add_argument("--rubric-version", default="v1", help="Rubric set version when using --write-rubric.")
    p.add_argument("--rubric-case-type", default="both", choices=["assessment", "treatment_management", "both"])
    p.add_argument("--detect-cpte", action="store_true", help="If set, detect CPTE domains and store them in output_json (no criteria extraction).")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    path = Path(args.source).expanduser().resolve()
    if not path.exists():
        raise SystemExit(f"Missing file: {path}")

    with db.connect() as conn:
        conn.autocommit = True

        source = db.upsert_source(conn, kind=args.kind, path=path)
        ingestion_id = db.create_ingestion(conn, source_id=source.id)

        try:
            pages = extract_pdf_pages(path)
            chunks = list(chunk_pages(pages))
            db.insert_source_chunks(conn, source_id=source.id, chunks=chunks)

            extracted_cases, warnings = heuristic_extract_cases_from_chunks(chunks)
            detected_domains = heuristic_detect_domains(chunks)
            detected_cpte_domains = heuristic_detect_cpte_domains(chunks) if args.detect_cpte else []
            extracted_criteria, criteria_warnings = heuristic_extract_domain_bullets(chunks)
            output_json: Dict[str, Any] = {
                "source_filename": source.filename,
                "source_checksum": source.checksum,
                "chunks": len(chunks),
                "cases": [{"title": c.title, "body_preview": c.body[:500]} for c in extracted_cases],
                "detected_domains": detected_domains,
                "detected_cpte_domains": detected_cpte_domains,
                "criteria_preview": [
                    {"domain_key": c.domain_key, "key": c.key, "description": c.description[:200]} for c in extracted_criteria[:50]
                ],
            }
            warnings.extend(criteria_warnings)

            db.insert_extraction(
                conn,
                ingestion_id=ingestion_id,
                extractor_version="heuristic_v1",
                output_json=output_json,
                warnings=warnings,
            )

            created_case_ids: List[str] = []
            if args.write_cases and extracted_cases:
                for c in extracted_cases[:200]:
                    case_id = db.create_case_with_single_prompt(
                        conn,
                        title=c.title,
                        case_type=args.case_type_default,
                        prompt_text=c.body,
                        source_id=source.id,
                    )
                    created_case_ids.append(case_id)

            rubric_set_id = None
            if args.write_rubric and detected_domains:
                rubric_set_id = db.upsert_rubric_set(
                    conn,
                    name=args.rubric_name,
                    version=args.rubric_version,
                    case_type=args.rubric_case_type,
                    active=False,
                )
                key_to_name = {
                    "physio_expertise": "Physiotherapy Expertise",
                    "communication": "Communication",
                    "collaboration": "Collaboration",
                    "management": "Management",
                    "scholarship": "Scholarship",
                    "professionalism": "Professionalism",
                }
                for d in detected_domains:
                    key = d["key"]
                    db.upsert_rubric_domain(conn, rubric_set_id=rubric_set_id, key=key, display_name=key_to_name.get(key, key))

            if args.write_criteria and rubric_set_id and extracted_criteria:
                # Map domain_key -> rubric_domain_id
                with conn.cursor() as cur:
                    cur.execute(
                        "select id::text as id, key from rubric_domains where rubric_set_id = %s",
                        (rubric_set_id,),
                    )
                    domain_rows = cur.fetchall()
                domain_map = {r["key"]: r["id"] for r in domain_rows}

                for c in extracted_criteria:
                    domain_id = domain_map.get(c.domain_key)
                    if not domain_id:
                        continue
                    # anchors unknown from PPT; store placeholder scale so downstream scoring has a shape
                    anchors = {"0": "Not demonstrated", "1": "Partially demonstrated", "2": "Demonstrated"}
                    db.upsert_rubric_criterion(conn, rubric_domain_id=domain_id, key=c.key, description=c.description, anchors=anchors)

            db.finish_ingestion(conn, ingestion_id=ingestion_id, status="succeeded")

        except Exception as e:
            db.finish_ingestion(conn, ingestion_id=ingestion_id, status="failed", error_text=str(e))
            raise

    print(json.dumps({"status": "ok", "source_id": source.id, "ingestion_id": ingestion_id}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

