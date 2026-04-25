from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from importer.pdf_text import extract_pdf_pages


CASE_RE = re.compile(r"\bCase\s+(\d{1,3})\b", re.IGNORECASE)
CASE_TITLE_RE = re.compile(r"^\s*Case\s+(\d{1,3})\s+(.+?)\s*$", re.IGNORECASE)
CASE_TOC_RE = re.compile(r"^\s*Case\s+([0-9]{1,3}|[sSvV])\s+(.+?)\.{3,}\s*(\d{1,4})\s*$", re.IGNORECASE)
CASE_TOC_DOTDOT_RE = re.compile(r"^\s*Case\s+(\d{1,3})\s+(.+?)\s*\.\s*\.\s*\.\s*(\d{1,4})\s*$", re.IGNORECASE)
CASE_TOC_WRAP_RE = re.compile(r"^\s*Case\s+(\d{1,3})\s+(.+?)\s*$", re.IGNORECASE)
CASE_TOC_ROMAN_RE = re.compile(r"^\s*Case\s+k\s+k\s+(.+?)\.{3,}\s*(\d{1,4})\s*$", re.IGNORECASE)

# Heuristic heading line: mostly caps, short, no punctuation heavy
HEADING_RE = re.compile(r"^[A-Z][A-Z \-/&]{2,60}$")


@dataclass(frozen=True)
class StructuredCase:
    case_number: int
    title: str
    page_start: int
    page_end: int
    section_files: Dict[str, str]
    raw_text_file: str


def normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line.replace("\x00", "")).strip()


def detect_case_starts(pages: List[Tuple[int, str]]) -> List[Tuple[int, int, str]]:
    """
    Returns list of (case_number, start_page, title_guess).
    """
    starts: List[Tuple[int, int, str]] = []
    for page_no, text in pages:
        if not text:
            continue
        # Skip table-of-contents style pages that list many cases
        if len(CASE_RE.findall(text)) >= 4:
            continue
        # Look for an explicit title line first
        for line in text.splitlines():
            line_n = normalize_line(line)
            m = CASE_TITLE_RE.match(line_n)
            if m:
                # Skip TOC-like lines with dot leaders / page numbers
                if "...." in line_n or re.search(r"\.{6,}\s*\d+\s*$", line_n):
                    continue
                case_no = int(m.group(1))
                title = normalize_line(m.group(2))
                starts.append((case_no, page_no, title))
                break
    # Deduplicate by case_no keeping earliest page
    best: Dict[int, Tuple[int, str]] = {}
    for case_no, page_no, title in starts:
        if case_no not in best or page_no < best[case_no][0]:
            best[case_no] = (page_no, title)
    return [(case_no, best[case_no][0], best[case_no][1]) for case_no in sorted(best.keys())]


def detect_case_starts_from_toc(pages: List[Tuple[int, str]]) -> List[Tuple[int, int, str]]:
    """
    Deterministic strategy for textbooks with a Case TOC that includes case start pages.

    Returns (case_number, start_page, title) where start_page is the book page number
    printed in the TOC. In many PDFs this matches the PDF page index; when it doesn't,
    the caller can provide an offset mapping later.
    """
    toc: Dict[int, Tuple[int, str]] = {}
    pending: Optional[Tuple[int, str]] = None  # (case_no, title_so_far)

    for _pdf_page_no, text in pages:
        if not text:
            continue
        # Search line-by-line for TOC entries like:
        # "Case 17 Acute Exacerbation ... ..................366"
        for line in text.splitlines():
            ln = normalize_line(line)
            # Finish a wrapped TOC entry if we were waiting for a page number line
            if pending and re.search(r"\.{3,}\s*\d{3,4}\s*$", ln):
                m_page = re.search(r"(\d{3,4})\s*$", ln)
                if m_page:
                    start_page = int(m_page.group(1))
                    case_no, title_so_far = pending
                    toc.setdefault(case_no, (start_page, title_so_far))
                    pending = None
                continue

            m = CASE_TOC_RE.match(ln) or CASE_TOC_DOTDOT_RE.match(ln)
            if m:
                raw_no = m.group(1).lower()
                if raw_no == "s":
                    case_no = 6
                elif raw_no == "v":
                    case_no = 8
                else:
                    case_no = int(raw_no)
                title = normalize_line(m.group(2))
                start_page = int(m.group(3))
                toc.setdefault(case_no, (start_page, title))
                pending = None
                continue

            # Handle OCR/ligature weirdness: "Case kk" corresponds to Case 11 in this PDF's TOC
            m_roman = CASE_TOC_ROMAN_RE.match(ln)
            if m_roman:
                case_no = 11
                title = normalize_line(m_roman.group(1))
                start_page = int(m_roman.group(2))
                toc.setdefault(case_no, (start_page, title))
                pending = None
                continue

            # Detect wrapped entry start (e.g., Case 7 line on one line, dot-leaders+page on next)
            if len(CASE_RE.findall(text)) >= 4:
                m_wrap = CASE_TOC_WRAP_RE.match(ln)
                if m_wrap:
                    case_no = int(m_wrap.group(1))
                    title_part = normalize_line(m_wrap.group(2))
                    if not re.search(r"\.{3,}\s*\d{3,4}\s*$", ln):
                        pending = (case_no, title_part)
    return [(c, toc[c][0], toc[c][1]) for c in sorted(toc.keys())]


def slice_case_pages(case_starts: List[Tuple[int, int, str]], total_pages: int) -> List[Tuple[int, int, int, str]]:
    out: List[Tuple[int, int, int, str]] = []
    for idx, (case_no, start_page, title) in enumerate(case_starts):
        end_page = (case_starts[idx + 1][1] - 1) if idx + 1 < len(case_starts) else total_pages
        out.append((case_no, start_page, end_page, title))
    return out


def split_into_sections(raw_text: str) -> Dict[str, str]:
    """
    Best-effort sectioning by detecting headings.
    Falls back to single 'body' section.
    """
    lines = [l.rstrip() for l in raw_text.splitlines()]
    section_order: List[str] = []
    sections: Dict[str, List[str]] = {}
    current = "body"
    sections[current] = []
    section_order.append(current)

    for line in lines:
        ln = normalize_line(line)
        if not ln:
            continue
        if HEADING_RE.match(ln) and not CASE_RE.search(ln):
            current = ln.lower().replace(" ", "_")
            if current not in sections:
                sections[current] = []
                section_order.append(current)
            continue
        sections[current].append(ln)

    out: Dict[str, str] = {}
    for k in section_order:
        txt = "\n".join(sections.get(k, [])).strip()
        if txt:
            out[k] = txt
    return out or {"body": raw_text.strip()}


def safe_slug(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "section"


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a structured JSON case bank from a PDF.")
    ap.add_argument("--pdf", required=True, help="Path to the source PDF book.")
    ap.add_argument("--out", required=True, help="Output directory for case JSON files.")
    ap.add_argument("--case-prefix", default="reid_chung", help="Folder prefix under out/")
    ap.add_argument(
        "--strategy",
        default="toc",
        choices=["toc", "in_text"],
        help="Case detection strategy: 'toc' (recommended) or 'in_text' (fallback).",
    )
    ap.add_argument(
        "--min-case",
        type=int,
        default=1,
        help="Only include cases with number >= this (useful to trim false positives).",
    )
    ap.add_argument(
        "--max-case",
        type=int,
        default=999,
        help="Only include cases with number <= this.",
    )
    args = ap.parse_args()

    pdf_path = Path(args.pdf).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve() / args.case_prefix
    out_dir.mkdir(parents=True, exist_ok=True)

    pages = extract_pdf_pages(pdf_path)
    pages_tuples: List[Tuple[int, str]] = [(p.page_number, p.text) for p in pages]
    total_pages = len(pages_tuples)

    if args.strategy == "toc":
        case_starts = detect_case_starts_from_toc(pages_tuples)
    else:
        case_starts = detect_case_starts(pages_tuples)

    case_starts = [(c, p, t) for (c, p, t) in case_starts if args.min_case <= c <= args.max_case]
    if not case_starts:
        raise SystemExit("No case starts detected. (This parser looks for lines beginning with 'Case <N> ...').")

    ranges = slice_case_pages(case_starts, total_pages)
    structured: List[StructuredCase] = []

    for case_no, start, end, title_guess in ranges:
        # Gather text from start..end pages
        selected = [t for (pn, t) in pages_tuples if start <= pn <= end and (t or "").strip()]
        raw = "\n\n".join([f"[Page {pn}]\n{pages_tuples[pn-1][1].strip()}" for pn in range(start, end + 1) if (pages_tuples[pn-1][1] or "").strip()])

        # Improve title: prefer first matching title line in the selected text
        title = title_guess
        for line in "\n".join(selected).splitlines():
            m = CASE_TITLE_RE.match(normalize_line(line))
            if m and int(m.group(1)) == case_no:
                title = normalize_line(m.group(2))
                break

        sections = split_into_sections(raw)
        section_files: Dict[str, str] = {}
        for sk, stxt in sections.items():
            fname = f"case_{case_no:02d}_{safe_slug(sk)}.txt"
            section_files[sk] = fname
            (out_dir / fname).write_text(stxt + "\n", encoding="utf-8")
        sc = StructuredCase(
            case_number=case_no,
            title=title,
            page_start=start,
            page_end=end,
            section_files=section_files,
            raw_text_file=f"case_{case_no:02d}_raw.txt",
        )
        structured.append(sc)

        # Write raw separately to keep JSON readable/diffable
        (out_dir / f"case_{case_no:02d}_raw.txt").write_text(raw, encoding="utf-8")

        out_path = out_dir / f"case_{case_no:02d}.json"
        out_path.write_text(json.dumps(asdict(sc), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    manifest = {
        "source_pdf": str(pdf_path),
        "total_pages": total_pages,
        "cases_detected": len(structured),
        "case_files": [f"case_{c.case_number:02d}.json" for c in structured],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(structured)} structured cases to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

