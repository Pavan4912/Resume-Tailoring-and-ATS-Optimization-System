"""Formatting snapshots used to prove that edits did not disturb the design."""
from __future__ import annotations
import zipfile
from pathlib import Path
from lxml import etree
from ..docx_edit.ooxml_utils import W, canon_hash, style_id, para_text
from ..models import FormattingSnapshot


def take_snapshot(docx_path: Path) -> FormattingSnapshot:
    with zipfile.ZipFile(docx_path) as z:
        doc = etree.fromstring(z.read("word/document.xml"))
        footers = {n: canon_hash(etree.fromstring(z.read(n)))
                   for n in z.namelist() if n.startswith(("word/footer", "word/header"))}
    body = doc.find(W + "body")
    paras = {}
    for i, p in enumerate(body.findall(W + "p")):
        paras[i] = {
            "style": style_id(p),
            "ppr": canon_hash(p.find(W + "pPr")),
            "runs": [canon_hash(r.find(W + "rPr")) for r in p.iter(W + "r")],
            "text": para_text(p),
        }
    return FormattingSnapshot(paragraphs=paras, sect_pr=canon_hash(body.find(W + "sectPr")),
                              footers=footers, paragraph_count=len(paras))


def diff_snapshots(before: FormattingSnapshot, after: FormattingSnapshot) -> list[str]:
    """Return human-readable formatting differences. Empty list = no unintended change found."""
    issues = []
    if before.sect_pr != after.sect_pr:
        issues.append("Page/section properties (size, margins, orientation) changed.")
    if before.footers != after.footers:
        issues.append("Header/footer content or formatting changed.")
    if before.paragraph_count != after.paragraph_count:
        issues.append(f"Paragraph count changed: {before.paragraph_count} -> {after.paragraph_count}.")
        return issues
    for i, b in before.paragraphs.items():
        a = after.paragraphs[i]
        if b["style"] != a["style"]:
            issues.append(f"Paragraph {i}: style changed {b['style']!r} -> {a['style']!r}.")
        if b["ppr"] != a["ppr"]:
            issues.append(f"Paragraph {i}: paragraph properties (spacing/indent/numbering/tabs) changed.")
        new_fmts = set(a["runs"]) - set(b["runs"])
        if new_fmts:
            issues.append(f"Paragraph {i}: run formatting not present in the original appeared.")
    return issues
