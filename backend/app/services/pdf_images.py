from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


def pdf_image_rendering_available() -> bool:
    return shutil.which("pdftoppm") is not None


def render_pdf_page_images(
    pdf_bytes: bytes,
    *,
    max_pages: int = 8,
    dpi: int = 170,
) -> list[bytes]:
    """Render PDF pages to PNG bytes via poppler's pdftoppm.

    Returns an empty list when rendering is unavailable or fails, so callers
    can fall back to text-only extraction.
    """
    if not pdf_image_rendering_available():
        return []

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "document.pdf"
            pdf_path.write_bytes(pdf_bytes)
            subprocess.run(
                [
                    "pdftoppm",
                    "-png",
                    "-r",
                    str(dpi),
                    "-f",
                    "1",
                    "-l",
                    str(max_pages),
                    str(pdf_path),
                    str(Path(tmpdir) / "page"),
                ],
                capture_output=True,
                check=True,
                timeout=60,
            )
            return [path.read_bytes() for path in sorted(Path(tmpdir).glob("page-*.png"))]
    except Exception:
        return []
