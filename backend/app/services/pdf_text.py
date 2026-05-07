from __future__ import annotations

import io
import shutil
import subprocess
import tempfile

import pdfplumber


def _extract_with_pdfplumber(pdf_bytes: bytes, *, max_pages: int) -> str:
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = pdf.pages[:max_pages]
            text = "\n".join(page.extract_text() or "" for page in pages)
        return text.strip()
    except Exception:
        return ""


def _extract_with_pdftotext(pdf_bytes: bytes) -> str:
    if not shutil.which("pdftotext"):
        return ""

    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
            tmp.write(pdf_bytes)
            tmp.flush()
            result = subprocess.run(
                ["pdftotext", tmp.name, "-"],
                capture_output=True,
                text=True,
                check=True,
            )
        return result.stdout.strip()
    except Exception:
        return ""


def extract_pdf_text(pdf_bytes: bytes, *, max_pages: int = 2) -> str:
    pdfplumber_text = _extract_with_pdfplumber(pdf_bytes, max_pages=max_pages)
    pdftotext_text = _extract_with_pdftotext(pdf_bytes)

    if len(pdftotext_text) > len(pdfplumber_text):
        return pdftotext_text
    return pdfplumber_text
