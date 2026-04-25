from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional

from pypdf import PdfReader


@dataclass(frozen=True)
class PageText:
    page_number: int  # 1-indexed
    text: str


def extract_pdf_pages(path: Path) -> List[PageText]:
    reader = PdfReader(str(path))
    pages: List[PageText] = []
    for idx, page in enumerate(reader.pages):
        text = (page.extract_text() or "").replace("\x00", "")
        pages.append(PageText(page_number=idx + 1, text=text))
    return pages


def chunk_pages(
    pages: List[PageText],
    *,
    max_chars: int = 4000,
    min_chars: int = 1200,
) -> Iterator[dict]:
    chunk_index = 0
    buf: List[str] = []
    page_from: Optional[int] = None
    page_to: Optional[int] = None

    def flush():
        nonlocal chunk_index, buf, page_from, page_to
        if not buf:
            return
        yield {
            "chunk_index": chunk_index,
            "text": "\n\n".join(buf).strip(),
            "page_from": page_from,
            "page_to": page_to,
            "metadata": {"type": "pdf_text"},
        }
        chunk_index += 1
        buf = []
        page_from = None
        page_to = None

    current_len = 0
    for p in pages:
        t = (p.text or "").replace("\x00", "").strip()
        if not t:
            continue
        if page_from is None:
            page_from = p.page_number
        page_to = p.page_number

        if current_len + len(t) > max_chars and current_len >= min_chars:
            yield from flush()
            current_len = 0
            page_from = p.page_number
            page_to = p.page_number

        buf.append(f"[Page {p.page_number}]\n{t}")
        current_len += len(t)

    yield from flush()

