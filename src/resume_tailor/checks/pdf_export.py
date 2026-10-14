"""Optional local DOCX->PDF via LibreOffice (headless), plus extraction checks."""
from __future__ import annotations
import os, re, shutil, subprocess, tempfile
from pathlib import Path

WIN = [r"C:\Program Files\LibreOffice\program\soffice.exe", r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"]


def find_soffice(configured: str = "") -> str | None:
    if configured:
        return configured if os.path.isfile(configured) else None
    return shutil.which("soffice") or shutil.which("libreoffice") or next((p for p in WIN if os.path.isfile(p)), None)


def convert_to_pdf(docx: Path, outdir: Path, soffice: str | None, timeout: int = 90):
    """Returns (pdf_path | None, warning | None). Never raises."""
    if not soffice:
        return None, "LibreOffice not found: PDF export and page-count validation were skipped."
    outdir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as prof:
        cmd = [soffice, f"-env:UserInstallation={Path(prof).as_uri()}", "--headless", "--convert-to", "pdf",
               "--outdir", str(outdir), str(docx)]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=timeout)
        except Exception as e:  # noqa: BLE001
            return None, f"PDF conversion failed ({type(e).__name__}); DOCX output is unaffected."
    pdf = outdir / (Path(docx).stem + ".pdf")
    return (pdf, None) if pdf.exists() else (None, "PDF conversion produced no file.")


def pdf_info(pdf: Path) -> dict:
    import fitz
    with fitz.open(str(pdf)) as d:
        text = "\n".join(p.get_text() for p in d)
        return {"pages": len(d), "text": text}


def text_overlap(docx_text: str, pdf_text: str) -> float:
    norm = lambda t: set(re.findall(r"[a-z0-9+#]+", t.lower()))
    a, b = norm(docx_text), norm(pdf_text)
    return len(a & b) / len(a) if a else 0.0
