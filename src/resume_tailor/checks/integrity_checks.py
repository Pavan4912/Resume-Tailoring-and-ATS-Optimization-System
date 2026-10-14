"""Compare tailored vs master: locked facts, structure, formatting."""
from __future__ import annotations
import re, zipfile
from ..models import MasterResume
from ..parsing.formatting import diff_snapshots


def _hyperlinks(path) -> int:
    with zipfile.ZipFile(path) as z:
        return len(re.findall(rb"<w:hyperlink\b", z.read("word/document.xml")))


def run_checks(before: MasterResume, after: MasterResume, before_path, after_path) -> list[dict]:
    res = []

    def add(name, ok, detail="", critical=False):
        res.append({"name": name, "ok": bool(ok), "critical": critical, "detail": detail})

    exp = lambda m: [(e["title"], e["employer"], e["start"], e["end"]) for e in m.experience]
    add("Employers, titles and employment dates unchanged", exp(before) == exp(after), "", True)
    add("Education/certification lines unchanged", [e["text"] for e in before.education] == [e["text"] for e in after.education], "", True)
    add("Contact details unchanged", before.contact == after.contact, "", True)
    add("Section headings unchanged", [s.heading for s in before.sections] == [s.heading for s in after.sections], "", True)
    changed_locked = [p.index for p, q in zip(before.paragraphs, after.paragraphs) if not p.editable and p.text != q.text]
    add("Locked paragraphs unchanged", not changed_locked, f"changed: {changed_locked}" if changed_locked else "", True)
    add("No missing or duplicated sections", len(before.sections) == len(after.sections), "")
    ep = lambda m: sum(1 for p in m.paragraphs if not p.text)
    add("Empty paragraph count unchanged", ep(before) == ep(after))
    add("Bullet count unchanged", len(before.bullets) == len(after.bullets))
    bad = [b.para_index for b in after.bullets if len(b.text) < 5 or not b.text[0].isalnum()]
    add("No malformed bullets", not bad, f"paragraphs: {bad}" if bad else "")
    add("Hyperlinks preserved", _hyperlinks(before_path) == _hyperlinks(after_path))
    fmt = diff_snapshots(before.snapshot, after.snapshot)
    add("Page setup, styles, spacing and run formatting preserved", not fmt, "; ".join(fmt[:5]))
    add("Text extracted from output", len(" ".join(p.text for p in after.paragraphs)) > 100, "", True)
    return res
