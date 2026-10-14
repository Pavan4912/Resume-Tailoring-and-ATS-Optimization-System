"""Structure / parsing compatibility checks (10 points)."""
from __future__ import annotations
import re, zipfile


def structure_checks(resume, docx_path, pdf_overlap: float | None) -> tuple[float, list[dict]]:
    checks = []
    have = {s.key for s in resume.sections}
    need = ["summary", "skills", "experience", "education"]
    pts = 4.0 * sum(k in have for k in need) / len(need)
    checks.append({"name": "Standard section headings detected", "points": round(pts, 2), "max": 4,
                   "detail": "found: " + ", ".join(k for k in need if k in have) + (" | missing: " + ", ".join(k for k in need if k not in have) if len(have & set(need)) < 4 else "")})
    c = 1.0 * ("email" in resume.contact) + 1.0 * ("phone" in resume.contact)
    checks.append({"name": "Contact details parseable", "points": c, "max": 2, "detail": ", ".join(sorted(resume.contact)) or "none"})
    with zipfile.ZipFile(docx_path) as z:
        xml = z.read("word/document.xml").decode("utf8", "ignore")
    risks = []
    if "<w:tbl>" in xml or "<w:tbl " in xml: risks.append("tables")
    if "txbxContent" in xml: risks.append("text boxes")
    m = re.search(r'<w:cols[^>]*w:num="(\d+)"', xml)
    if m and int(m.group(1)) > 1: risks.append("multiple columns")
    checks.append({"name": "Single-column reading order (no tables/text boxes/columns)", "points": 0.0 if risks else 2.0,
                   "max": 2, "detail": ("risk: " + ", ".join(risks)) if risks else "plain single-column body"})
    if pdf_overlap is None:
        checks.append({"name": "Text extraction check", "points": 1.0, "max": 2,
                       "detail": "DOCX text extracts fine; PDF extraction not verified (no LibreOffice)."})
    else:
        checks.append({"name": "Text extraction check", "points": 2.0 if pdf_overlap >= 0.9 else 0.0, "max": 2,
                       "detail": f"{pdf_overlap:.0%} of DOCX words found in exported PDF text"})
    return sum(x["points"] for x in checks), checks
