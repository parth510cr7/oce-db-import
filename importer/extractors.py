from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


CASE_HEADER_RE = re.compile(r"^\s*Case\s+(\d+)\s+(.*)$", re.IGNORECASE)

DOMAIN_PATTERNS = [
    ("physio_expertise", re.compile(r"\bPhysiotherapy\s+Expertise\b", re.IGNORECASE)),
    ("communication", re.compile(r"\bCommunication\b", re.IGNORECASE)),
    ("collaboration", re.compile(r"\bCollaboration\b", re.IGNORECASE)),
    ("management", re.compile(r"\bManagement\b", re.IGNORECASE)),
    ("scholarship", re.compile(r"\bScholarship\b", re.IGNORECASE)),
    ("professionalism", re.compile(r"\bProfessionalism\b", re.IGNORECASE)),
]

CPTE_DOMAIN_PATTERNS = [
    ("assessment_and_diagnosis", re.compile(r"\bAssessment\s+and\s+Diagnosis\b", re.IGNORECASE)),
    ("care_planning", re.compile(r"\bCare\s+Planning\b", re.IGNORECASE)),
    ("client_safety_client_centred_care", re.compile(r"\bClient\s+Safety\b.*\bClient-?Centred\s+Care\b", re.IGNORECASE)),
    ("professional_responsibilities", re.compile(r"\bProfessional\s+Responsibilities\b", re.IGNORECASE)),
    ("collaboration", re.compile(r"\bCollaboration\b", re.IGNORECASE)),
    ("communication", re.compile(r"\bCommunication\b", re.IGNORECASE)),
    ("practice_management", re.compile(r"\bPractice\s+Management\b", re.IGNORECASE)),
]


@dataclass(frozen=True)
class ExtractedCase:
    title: str
    body: str


@dataclass(frozen=True)
class ExtractedCriterion:
    domain_key: str
    key: str
    description: str


def heuristic_extract_domain_bullets(chunks: List[Dict[str, Any]]) -> Tuple[List[ExtractedCriterion], List[Dict[str, Any]]]:
    """
    From the Domains PPT PDF we often get:
      DOMAIN_NAME
      • bullet 1
      • bullet 2

    We treat each bullet as a criterion description with anchors TBD.
    """
    warnings: List[Dict[str, Any]] = []
    criteria: List[ExtractedCriterion] = []

    domain_headers = {
        "physio_expertise": re.compile(r"^\s*PHYSIOTHERAPY\s+EXPERTISE\s*$", re.IGNORECASE),
        "communication": re.compile(r"^\s*COMMUNICATION\s*$", re.IGNORECASE),
        "collaboration": re.compile(r"^\s*COLLABORATION\s*$", re.IGNORECASE),
        "management": re.compile(r"^\s*MANAGEMENT\s*$", re.IGNORECASE),
        "scholarship": re.compile(r"^\s*SCHOLARSHIP\s*$", re.IGNORECASE),
        "professionalism": re.compile(r"^\s*PROFESSIONALISM\s*$", re.IGNORECASE),
    }

    current_domain: str | None = None
    buf: List[str] = []

    def flush_buf():
        nonlocal buf
        for line in buf:
            clean = line.strip("•- \t").strip()
            if not clean:
                continue
            key = f"heur_{len(criteria)+1}"
            criteria.append(ExtractedCriterion(domain_key=current_domain or "unknown", key=key, description=clean))
        buf = []

    for ch in chunks:
        for line in (ch.get("text") or "").splitlines():
            line_stripped = line.strip()
            # domain header switch
            for dk, pat in domain_headers.items():
                if pat.match(line_stripped):
                    if current_domain and buf:
                        flush_buf()
                    current_domain = dk
                    break
            else:
                # bullet collection when inside domain
                if current_domain:
                    if line_stripped.startswith("•") or line_stripped.startswith("-"):
                        buf.append(line_stripped)

    if current_domain and buf:
        flush_buf()

    if not criteria:
        warnings.append({"type": "no_domain_bullets", "message": "No domain bullet criteria extracted."})

    return criteria, warnings


def heuristic_detect_domains(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    text = "\n".join((c.get("text") or "") for c in chunks)
    found = []
    for key, pat in DOMAIN_PATTERNS:
        if pat.search(text):
            found.append({"key": key})
    return found


def heuristic_detect_cpte_domains(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    text = "\n".join((c.get("text") or "") for c in chunks)
    found = []
    for key, pat in CPTE_DOMAIN_PATTERNS:
        if pat.search(text):
            found.append({"key": key})
    return found


def heuristic_extract_cases_from_chunks(chunks: List[Dict[str, Any]]) -> Tuple[List[ExtractedCase], List[Dict[str, Any]]]:
    """
    Very lightweight extraction:
    - Finds lines like 'Case 12  Foo Bar'
    - Collects nearby text until the next Case header (within the same chunk only)

    This is intentionally conservative: it gives us importable 'draft cases' with provenance
    without claiming to be an official OCE case bank.
    """
    warnings: List[Dict[str, Any]] = []
    extracted: List[ExtractedCase] = []

    for ch in chunks:
        text = ch.get("text", "")
        if not text:
            continue
        lines = text.splitlines()
        hits = []
        for i, line in enumerate(lines):
            m = CASE_HEADER_RE.match(line)
            if m:
                hits.append((i, m.group(1), m.group(2).strip()))
        if not hits:
            continue

        for idx, hit in enumerate(hits):
            start, case_no, title_rest = hit
            end = hits[idx + 1][0] if idx + 1 < len(hits) else len(lines)
            body = "\n".join(lines[start:end]).strip()
            title = f"Case {case_no} {title_rest}".strip()
            extracted.append(ExtractedCase(title=title, body=body))

    if not extracted:
        warnings.append({"type": "no_cases_found", "message": "No 'Case N ...' headers detected in extracted text."})

    domains = heuristic_detect_domains(chunks)
    if not domains:
        warnings.append(
            {
                "type": "rubric_missing",
                "message": "No clinical scoring anchors/criteria were extracted. Provide the exported Domains PPT PDF (and any rubric docs) to populate rubric_sets/domains/criteria.",
            }
        )
    else:
        warnings.append(
            {
                "type": "rubric_partial",
                "message": "Detected domain keywords, but not anchors/criteria. Domains can be created now; provide rubric anchors to score accurately.",
                "domains_detected": [d["key"] for d in domains],
            }
        )

    return extracted, warnings

