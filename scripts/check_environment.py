"""Reports what is installed. Required items fail the check; optional items only warn."""
from __future__ import annotations
import importlib
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

WINDOWS_SOFFICE = [
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
]


def find_soffice() -> str | None:
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    return next((p for p in WINDOWS_SOFFICE if os.path.isfile(p)), None)


def main() -> int:
    failures = 0

    def report(label: str, ok: bool, detail: str = "", required: bool = True) -> None:
        nonlocal failures
        tag = "OK  " if ok else ("FAIL" if required else "WARN")
        print(f"[{tag}] {label}" + (f" - {detail}" if detail else ""))
        if not ok and required:
            failures += 1

    v = sys.version_info
    report("Python >= 3.11", v >= (3, 11), f"found {v.major}.{v.minor}.{v.micro}")

    for mod in ("docx", "lxml", "fitz", "spacy", "yaml", "rapidfuzz", "streamlit"):
        try:
            importlib.import_module(mod)
            report(f"import {mod}", True)
        except ImportError as e:
            report(f"import {mod}", False, str(e))

    try:
        import spacy
        spacy.load("en_core_web_sm")
        report("spaCy model en_core_web_sm", True)
    except Exception as e:  # noqa: BLE001
        report("spaCy model en_core_web_sm", False, str(e)[:80])

    try:
        from resume_tailor.config import load_settings
        load_settings()
        report("config files valid", True)
    except Exception as e:  # noqa: BLE001
        report("config files valid", False, str(e))

    so = find_soffice()
    report("LibreOffice (PDF export, page-count check)", so is not None,
           so or "not found: PDF export will be skipped with a warning", required=False)
    report("Ollama (optional local LLM)", shutil.which("ollama") is not None,
           "not found: rule-based tailoring will be used", required=False)

    print("\nResult:", "ready" if failures == 0 else f"{failures} required item(s) missing")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
