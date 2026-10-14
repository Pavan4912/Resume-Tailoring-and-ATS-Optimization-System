"""Parse a master DOCX into a structured MasterResume plus an evidence inventory."""
from __future__ import annotations
import re
import zipfile
from pathlib import Path
from lxml import etree
from ..config import Settings
from ..docx_edit.ooxml_utils import W, para_text, style_id, has_numbering
from ..docx_edit.paragraph_editor import editability, line_texts
from ..master.protection import sha256_file
from ..models import (MasterResume, ParagraphInfo, ResumeBullet, ResumeEvidence, ResumeSection)
from .formatting import take_snapshot

SECTION_KEYS = [
    ("summary", r"summary|profile|objective|about"),
    ("skills", r"skill|competenc|technolog"),
    ("experience", r"experience|employment|work history"),
    ("projects", r"project"),
    ("education", r"education|academic"),
    ("certifications", r"certif|licen[sc]e"),
    ("awards", r"award|achievement|honou?r"),
]
_DATE = r"(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+)?\d{4}"
DATE_RANGE = re.compile(rf"({_DATE})\s*[–—-]\s*({_DATE}|Present|Current|Till date)", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"\+?\d[\d\s-]{8,}\d")


def section_key(heading: str) -> str:
    h = heading.lower()
    for key, pat in SECTION_KEYS:
        if re.search(pat, h):
            return key
    return "other"


def _is_heading(p, text: str) -> bool:
    sid = style_id(p).lower()
    if sid.startswith("heading"):
        return True
    return bool(text) and text.isupper() and len(text) < 40 and not has_numbering(p)


def alias_pattern(alias: str) -> re.Pattern:
    return re.compile(r"(?<![\w.+#])" + re.escape(alias) + r"(?![\w+#])", re.I)


def _skill_table(settings: Settings) -> dict[str, list[re.Pattern]]:
    table = {}
    for canon, aliases in settings.taxonomy["skills"].items():
        names = {canon.lower(), *(a.lower() for a in aliases)}
        table[canon] = [alias_pattern(n) for n in sorted(names, key=len, reverse=True)]
    return table


def parse_master(path: Path, settings: Settings) -> MasterResume:
    path = Path(path)
    with zipfile.ZipFile(path) as z:
        root = etree.fromstring(z.read("word/document.xml"))
    body = root.find(W + "body")
    if body.find(W + "tbl") is not None:
        warn_tables = ["Document contains tables: in-place editing of table cells is not supported yet; "
                       "table text is read-only in this version."]
    else:
        warn_tables = []
    pels = body.findall(W + "p")
    warnings = list(warn_tables)
    paras: list[ParagraphInfo] = []
    sections: list[ResumeSection] = []
    bullets: list[ResumeBullet] = []
    experience, education = [], []
    contact: dict[str, str] = {}
    cur_section = "header"
    cur_parent: tuple[int, str] | None = None
    cur: ResumeSection | None = None

    entries = []
    for i, p in enumerate(pels):
        lts = [t.strip() for t in line_texts(p)] if editability(p)[0] else [para_text(p).strip()]
        for ln, t in enumerate(lts):
            entries.append((i, p, ln, t, len(lts)))
    for i, p, ln, text, nlines in entries:
        sid = style_id(p)
        can_edit, why = editability(p)
        info = ParagraphInfo(index=i, style=sid, text=text, kind="other", section=cur_section,
                             run_count=len(p.findall(W + "r")), editable=can_edit, lock_reason=why, line=ln)
        if not text:
            paras.append(info)
            continue
        if nlines == 1 and _is_heading(p, text):
            cur_section = section_key(text)
            info.kind, info.section = "heading", cur_section
            cur = ResumeSection(key=cur_section, heading=text, heading_index=i)
            sections.append(cur)
            cur_parent = None
            info.editable, info.lock_reason = False, "section heading (locked)"
        else:
            info.section = cur_section
            if cur is not None:
                cur.para_indices.append(i)
            if cur_section == "header":
                if EMAIL.search(text) or PHONE.search(text):
                    info.kind = "contact"
                    em, ph = EMAIL.search(text), PHONE.search(text)
                    if em: contact["email"] = em.group()
                    if ph: contact["phone"] = ph.group().strip()
                    if "linkedin" in text.lower(): contact["linkedin"] = "present"
                elif i == 0 or "name" not in contact:
                    info.kind = "name"; contact["name"] = text
                else:
                    info.kind = "headline"
                info.editable, info.lock_reason = False, f"{info.kind} (locked)"
            elif has_numbering(p) or sid.lower().startswith("list"):
                info.kind = "bullet"
                if cur_parent:
                    bullets.append(ResumeBullet(i, text, cur_parent[0], cur_parent[1]))
            elif cur_section == "summary":
                info.kind = "summary"
            elif cur_section == "skills":
                info.kind = "skill_line" if ":" in text else "other"
            elif cur_section in ("experience", "projects"):
                is_role = cur_section == "experience"
                info.kind = "role_header" if is_role else "project_header"
                info.editable, info.lock_reason = False, f"{info.kind} (title/employer/dates locked)"
                cur_parent = (i, text.split("|")[0].strip())
                if is_role:
                    m = DATE_RANGE.search(text)
                    parts = text.split("\t")[0].split("|")
                    experience.append({
                        "para_index": i, "title": parts[0].strip(),
                        "employer": re.split(r"\s+[—–-]\s+", parts[1].strip())[0] if len(parts) > 1 else "",
                        "start": m.group(1) if m else "", "end": m.group(2) if m else "",
                    })
                    if not m:
                        warnings.append(f"Role header at paragraph {i} has no parsable date range.")
            elif cur_section in ("education", "certifications"):
                info.kind = "credential"
                info.editable, info.lock_reason = False, "credential (locked)"
                m = DATE_RANGE.search(text)
                education.append({"para_index": i, "text": text, "dates": m.group() if m else ""})
        paras.append(info)

    if "email" not in contact: warnings.append("No email address found in the header.")
    if "phone" not in contact: warnings.append("No phone number found in the header.")
    for need in ("summary", "skills", "experience", "education"):
        if not any(s.key == need for s in sections):
            warnings.append(f"No '{need}' section detected.")

    evidence = build_evidence(paras, settings)
    for b in bullets:
        if re.search(r"\b(reduc\w+|improv\w+|increas\w+|decreas\w+|optimi[sz]\w+)\b", b.text, re.I) \
                and not re.search(r"\d", b.text):
            warnings.append(f"Paragraph {b.para_index}: improvement claim has no metric. Do not add numbers "
                            f"unless you can supply real ones.")
    return MasterResume(path=str(path), sha256=sha256_file(path), paragraphs=paras, sections=sections,
                        bullets=bullets, evidence=evidence, contact=contact, experience=experience,
                        education=education, warnings=warnings, snapshot=take_snapshot(path))


def _atoms(item: str) -> list[str]:
    """Search terms for a skills-line item that is not in the taxonomy."""
    atoms = {item}
    for m in re.finditer(r"\(([^)]+)\)", item):
        atoms.add(m.group(1))
    base = re.sub(r"\([^)]*\)", "", item).strip()
    atoms.add(base)
    if " " not in base:
        atoms.update(a for a in base.split("/") if a)
    return [a.strip() for a in atoms if a.strip()]


def build_evidence(paras: list[ParagraphInfo], settings: Settings) -> dict[str, ResumeEvidence]:
    terms = _skill_table(settings)
    for p in paras:   # skills-line items not covered by the taxonomy are still genuine evidence
        if p.kind != "skill_line":
            continue
        for item in re.split(r"[,;]", p.text.split(":", 1)[1]):
            item = item.strip()
            if item and not any(pt.search(item) for pts in terms.values() for pt in pts) \
                    and item not in terms:
                terms[item] = [alias_pattern(a) for a in _atoms(item)]
    ev: dict[str, ResumeEvidence] = {}
    for name, pats in terms.items():
        e = ResumeEvidence(skill=name)
        for p in paras:
            if not p.text or p.kind in ("name", "headline", "contact", "heading"):
                continue
            if not any(pt.search(p.text) for pt in pats):
                continue
            if p.kind == "skill_line":
                e.listed_in_skills = True
            elif p.kind == "summary":
                e.in_summary = True
            elif p.kind == "bullet":
                if p.index not in e.bullet_locations:
                    e.bullet_locations.append(p.index)
            elif p.kind == "project_header":
                e.header_locations.append(p.index)
        if e.listed_in_skills or e.in_summary or e.demonstrated:
            ev[name] = e
    return ev
