from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Tuple

import psycopg
from psycopg.rows import dict_row

from importer import db


ANCHORS_4PT = {
    "1": "Unsafe / insufficient",
    "2": "Developing (incomplete)",
    "3": "Entry-to-practice (meets standard)",
    "4": "Strong (clear and comprehensive)",
}


@dataclass(frozen=True)
class CriterionSeed:
    domain_key: str
    key: str
    description: str


def seeds() -> Tuple[str, str, str, List[Tuple[str, str]], List[CriterionSeed]]:
    rubric_name = "CPTE Training Rubric"
    rubric_version = "v1"
    rubric_case_type = "both"

    domains = [
        ("clinical_reasoning", "Clinical Reasoning & Decision-Making"),
        ("client_centred_safety", "Client-Centred Care & Safety"),
        ("communication_collaboration", "Communication & Collaboration"),
        ("professional_responsibilities", "Professional Responsibilities"),
    ]

    criteria = [
        CriterionSeed(
            domain_key="clinical_reasoning",
            key="assessment_accuracy",
            description="Prioritize relevant subjective and objective questions based on the clinical presentation.",
        ),
        CriterionSeed(
            domain_key="clinical_reasoning",
            key="data_synthesis",
            description="Interpret findings and history to form an accurate physiotherapy diagnosis or working hypothesis.",
        ),
        CriterionSeed(
            domain_key="clinical_reasoning",
            key="care_planning",
            description="Develop an evidence-informed, safe, effective plan of care aligned to the client’s needs.",
        ),
        CriterionSeed(
            domain_key="client_centred_safety",
            key="safety_identification",
            description="Recognize contraindications, red flags, and when immediate medical referral is required.",
        ),
        CriterionSeed(
            domain_key="client_centred_safety",
            key="informed_consent",
            description="Explain risks, benefits, and alternatives clearly and obtain ongoing informed consent.",
        ),
        CriterionSeed(
            domain_key="client_centred_safety",
            key="individuality",
            description="Adapt approach to the client’s goals, values, and cultural context.",
        ),
        CriterionSeed(
            domain_key="communication_collaboration",
            key="framing_tone",
            description="Communicate professionally and clearly without overstepping boundaries or sounding abrasive.",
        ),
        CriterionSeed(
            domain_key="communication_collaboration",
            key="interprofessional_skills",
            description="Collaborate appropriately and refer to other providers when indicated.",
        ),
        CriterionSeed(
            domain_key="professional_responsibilities",
            key="ethical_practice",
            description="Follow legal, ethical, and professional standards expected of entry-to-practice physiotherapists.",
        ),
        CriterionSeed(
            domain_key="professional_responsibilities",
            key="conflict_resolution",
            description="Manage difficult behaviour or disputes with clients/team members using appropriate strategies.",
        ),
    ]

    return rubric_name, rubric_version, rubric_case_type, domains, criteria


def main() -> int:
    if not os.environ.get("DATABASE_URL"):
        raise RuntimeError("DATABASE_URL is required")

    rubric_name, rubric_version, rubric_case_type, domains, criteria = seeds()

    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        conn.autocommit = True
        rubric_set_id = db.upsert_rubric_set(
            conn, name=rubric_name, version=rubric_version, case_type=rubric_case_type, active=False
        )

        domain_id_by_key = {}
        for key, display_name in domains:
            domain_id_by_key[key] = db.upsert_rubric_domain(conn, rubric_set_id=rubric_set_id, key=key, display_name=display_name)

        for c in criteria:
            domain_id = domain_id_by_key[c.domain_key]
            db.upsert_rubric_criterion(conn, rubric_domain_id=domain_id, key=c.key, description=c.description, anchors=ANCHORS_4PT)

    print(f"Upserted rubric_set {rubric_name} {rubric_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

