from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from importer.pdf_text import extract_pdf_pages


CHAPTER_TOC_RE = re.compile(r"(?<!\d)(\d{1,2})\s+([A-Za-z][A-Za-z0-9/,'’\\-\\s].{3,}?)\s+(\d{1,4})(?!\d)")
SECTION_RE = re.compile(r"^\s*SECTION\s+([IVXLC]+)\s*$", re.IGNORECASE)
CONTENTS_FUZZY_RE = re.compile(r"c\s*o\s*n\s*t\s*e\s*n\s*t\s*s", re.IGNORECASE)


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\x00", "")).strip()

def normalize_contents_digits(s: str) -> str:
    """
    Contents extraction often splits digits with spaces: '1 0 Manual...' and page '3 6 9'.
    Collapse digit runs so chapter numbers and page numbers parse correctly.
    """
    s = (s or "").replace("\x00", "")
    # Insert a hard boundary between TOC entries when a page number is immediately
    # followed by the next chapter number (e.g., "... System 3 2 Tissue ...").
    # This prevents collapsing "3 2" into "32".
    s = re.sub(r"(\d{1,4})\s+(\d{1,2})\s+([A-Za-z])", r"\1\n\2 \3", s)

    # Repeatedly collapse "digit space digit" into "digitdigit" (within numbers like 3 6 9).
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"(\d)\s+(\d)", r"\1\2", s)
    return normalize(s)


@dataclass(frozen=True)
class ChapterIndex:
    chapter_number: int
    title: str
    start_page: int
    end_page: int


def detect_chapters_from_contents(pages: List[Tuple[int, str]]) -> List[Tuple[int, str, int]]:
    """
    Extracts chapter start pages from the 'Contents' pages.
    Dutton has lines like: '4  Patient/Client Management  163'
    """
    chapters: Dict[int, Tuple[str, int]] = {}

    total_pages = len(pages)

    for _pdf_page_no, text in pages:
        t = text or ""
        # Only parse pages that look like the actual contents page
        if not (("Contents" in t or CONTENTS_FUZZY_RE.search(t)) and ("SECTION" in t or "SECTION I" in t or "SECTION IANATOMY" in t)):
            continue

        # Contents page may be extracted as one long line; scan all matches
        ln_all = normalize_contents_digits(t)
        for m in CHAPTER_TOC_RE.finditer(ln_all):
            chap_no = int(m.group(1))
            title = normalize(m.group(2))
            start_page = int(m.group(3))
            # Keep only real chapters for this book
            if chap_no < 1 or chap_no > 30:
                continue
            if start_page < 1 or start_page > total_pages:
                continue
            if len(title) > 90:
                continue
            chapters.setdefault(chap_no, (title, start_page))

        # Contents found and parsed; stop.
        break

    return [(c, chapters[c][0], chapters[c][1]) for c in sorted(chapters.keys())]


def build_ranges(starts: List[Tuple[int, str, int]], last_page: int) -> List[ChapterIndex]:
    out: List[ChapterIndex] = []
    for i, (cno, title, start) in enumerate(starts):
        end = (starts[i + 1][2] - 1) if i + 1 < len(starts) else last_page
        if start < 1:
            start = 1
        if end > last_page:
            end = last_page
        if end < start:
            end = start
        out.append(ChapterIndex(chapter_number=cno, title=title, start_page=start, end_page=end))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Build structured textbook JSON (chapter index + chapter text files).")
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--prefix", default="dutton_orthopaedic_4e")
    args = ap.parse_args()

    pdf_path = Path(args.pdf).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve() / args.prefix
    out_dir.mkdir(parents=True, exist_ok=True)

    pages = extract_pdf_pages(pdf_path)
    pages_tuples: List[Tuple[int, str]] = [(p.page_number, p.text) for p in pages]
    total_pages = len(pages_tuples)

    starts = detect_chapters_from_contents(pages_tuples)
    if not starts:
        raise SystemExit("Could not detect chapters from Contents.")

    chapter_ranges = build_ranges(starts, total_pages)

    # Write chapter text files + index JSON
    index_rows: List[Dict] = []
    for ch in chapter_ranges:
        raw = "\n\n".join(
            [
                f"[Page {pn}]\n{(pages_tuples[pn-1][1] or '').strip()}"
                for pn in range(ch.start_page, ch.end_page + 1)
                if (pages_tuples[pn-1][1] or "").strip()
            ]
        ).strip()
        txt_name = f"chapter_{ch.chapter_number:02d}.txt"
        (out_dir / txt_name).write_text(raw + "\n", encoding="utf-8")
        index_rows.append({**asdict(ch), "text_file": txt_name})

    (out_dir / "chapters.json").write_text(json.dumps(index_rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "manifest.json").write_text(
        json.dumps(
            {
                "source_pdf": str(pdf_path),
                "total_pages": total_pages,
                "chapters_detected": len(index_rows),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Wrote chapter index + text files to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

