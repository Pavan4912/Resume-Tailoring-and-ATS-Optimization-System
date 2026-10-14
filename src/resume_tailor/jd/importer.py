"""Read a JD from TXT / DOCX / PDF (local parsing only)."""
from __future__ import annotations
from pathlib import Path
from .sanitize import JDError


def read_jd_file(path: Path, max_mb: int = 10) -> str:
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in (".txt", ".docx", ".pdf"):
        raise JDError("Unsupported JD file type. Use .txt, .docx or .pdf.")
    if not path.is_file() or path.stat().st_size == 0:
        raise JDError("JD file is missing or empty.")
    if path.stat().st_size > max_mb * 1024 * 1024:
        raise JDError(f"JD file exceeds {max_mb} MB.")
    try:
        if ext == ".txt":
            return path.read_text(encoding="utf-8", errors="replace")
        if ext == ".docx":
            from docx import Document
            return "\n".join(p.text for p in Document(str(path)).paragraphs)
        import fitz
        with fitz.open(str(path)) as doc:
            return "\n".join(page.get_text() for page in doc)
    except JDError:
        raise
    except Exception as e:  # noqa: BLE001
        raise JDError(f"Could not read the JD file (corrupted or unsupported): {e}") from e
