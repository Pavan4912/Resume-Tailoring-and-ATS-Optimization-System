"""Factual-integrity gate: an edit may only rearrange or reword what the master already supports."""
from __future__ import annotations
import re
from ..config import Settings
from ..jd.extractor import load_lexicon
from ..models import MasterResume, ProposedEdit
from ..parsing.resume_structure import alias_pattern

_W = re.compile(r"[A-Za-z0-9+#.]+")
_NUM = re.compile(r"\d+(?:\.\d+)?")


def _words(t: str) -> list[str]:
    return sorted(w.lower().strip(".") for w in _W.findall(t))


def term_hits(text: str, settings: Settings) -> set[str]:
    out = set()
    for name, spec in load_lexicon(settings).items():
        if any(alias_pattern(a.lower()).search(text) for a in spec["aliases"]):
            out.add(name)
    return out


def validate(pr: ProposedEdit, master: MasterResume, settings: Settings) -> ProposedEdit:
    pr.problems = []
    info = {(p.index, p.line): p for p in master.paragraphs}
    for e in pr.edits:
        p = info.get((e.para_index, e.line))
        if p is None or not p.editable:
            pr.problems.append(f"Paragraph {e.para_index} is locked or missing.")
        elif p.text.strip() != e.old.strip():
            pr.problems.append(f"Paragraph {e.para_index} no longer matches the master text.")
        if "\n" in e.new or not e.new.strip():
            pr.problems.append("Replacement text is empty or contains a line break.")
    if pr.problems:
        return pr
    old_all = " ".join(e.old for e in pr.edits)
    new_all = " ".join(e.new for e in pr.edits)
    if pr.mode == "reorder":
        if _words(old_all) != _words(new_all):
            pr.problems.append("Reordering must not add or remove any words.")
        return pr
    vocab = {w for p in master.paragraphs for w in _words(p.text)}
    allowed = {w.lower() for w in pr.allowed_words}
    new_terms = term_hits(new_all, settings) - term_hits(old_all, settings)
    for t in sorted(new_terms):
        pr.problems.append(f"'{t}' is not supported by the master resume. Add it to the master first if it is true.")
    for n in set(_NUM.findall(new_all)) - set(_NUM.findall(old_all)):
        pr.problems.append(f"New number '{n}' is not in the original text (no invented metrics).")
    novel = [w for w in set(_words(new_all)) if w not in vocab and w not in allowed
             and w not in {"a", "an", "the", "and", "of", "in", "to", "for", "with", "on"}]
    if len(novel) > max(2, len(_words(new_all)) // 4):
        pr.problems.append(f"Too many words that do not appear anywhere in the master: {', '.join(sorted(novel)[:6])}.")
    return pr
