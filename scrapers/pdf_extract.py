"""Download a PDF, extract text via pdfminer.six, dedupe by sha256.

The extracted text is the substrate for full-text search on the dashboard.
Scanned/image-only PDFs will produce empty or near-empty output — those are
flagged and not OCR'd in Phase 1.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import requests
from pdfminer.high_level import extract_text
from pdfminer.pdfparser import PDFSyntaxError


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def fetch(url: str, timeout: int = 30) -> bytes:
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.content


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes. Returns '' on parse error."""
    try:
        return extract_text(io.BytesIO(pdf_bytes)) or ""
    except (PDFSyntaxError, Exception):  # pdfminer raises a wide variety
        return ""


def save_extracted_text(text: str, sha256: str, attachments_dir: Path) -> str:
    """Write extracted text to attachments_dir/<sha>.txt; return repo-relative path."""
    attachments_dir.mkdir(parents=True, exist_ok=True)
    out = attachments_dir / f"{sha256}.txt"
    out.write_text(text, encoding="utf-8")
    return str(out.as_posix())


def is_meaningful_text(text: str, min_chars: int = 200) -> bool:
    """Heuristic: did the PDF actually have selectable text?

    A scanned-image agenda will produce near-empty output even on a "successful"
    parse. Use this to decide whether to skip OCR-only documents.
    """
    return len(text.strip()) >= min_chars
