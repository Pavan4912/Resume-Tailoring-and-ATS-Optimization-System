"""Run-aware in-place paragraph editing.

Only text inside existing <w:t> elements is changed. Unchanged words keep their original runs
(and therefore their bold/italic/colour). Inserted text joins the run of the character after it (or before it at the end of a line).
Paragraphs containing hyperlinks, tabs, fields or drawings are refused rather than risked.
Soft line breaks (a run holding only <w:br/>) split a paragraph into independently editable lines.
"""
from __future__ import annotations
import difflib
import re
from .ooxml_utils import W, XML_SPACE

# a token is a word plus its trailing whitespace, so run boundaries (e.g. after a bold "Label: ")
# line up with token starts and inserted text cannot be matched onto the wrong space
_TOKEN = re.compile(r"\s+|\S+\s*")
_SAFE_CHILDREN = {W + "pPr", W + "r", W + "bookmarkStart", W + "bookmarkEnd", W + "proofErr"}
_SAFE_RUN_CHILDREN = {W + "rPr", W + "t"}


class UnsupportedParagraphError(Exception):
    pass


def _is_break_run(r) -> bool:
    kids = [c.tag for c in r if c.tag != W + "rPr"]
    return bool(kids) and all(k == W + "br" for k in kids)


def editability(p) -> tuple[bool, str]:
    for ch in p:
        if ch.tag not in _SAFE_CHILDREN:
            return False, f"contains <{ch.tag.split('}')[1]}> (hyperlink/field/other)"
    for r in p.findall(W + "r"):
        if _is_break_run(r):
            continue
        for ch in r:
            if ch.tag not in _SAFE_RUN_CHILDREN:
                return False, f"run contains <{ch.tag.split('}')[1]}> (tab/break/drawing)"
    return True, ""


def line_runs(p) -> list[list]:
    """Text runs grouped into lines (split at break-only runs)."""
    lines, cur = [], []
    for r in p.findall(W + "r"):
        if _is_break_run(r):
            lines.append(cur)
            cur = []
        elif r.find(W + "t") is not None:
            cur.append(r)
    lines.append(cur)
    return lines


def line_texts(p) -> list[str]:
    return ["".join(t.text or "" for r in rs for t in r.findall(W + "t")) for rs in line_runs(p)]


def _tokens(s: str) -> list[str]:
    return _TOKEN.findall(s)


def replace_paragraph_text(p, new_text: str, line: int = 0) -> None:
    ok, why = editability(p)
    if not ok:
        raise UnsupportedParagraphError(why)
    groups = line_runs(p)
    if line >= len(groups) or not groups[line]:
        raise UnsupportedParagraphError("line has no text runs")
    if "\n" in new_text:
        raise UnsupportedParagraphError("new text must not contain line breaks")
    runs = groups[line]
    owner, old = [], []
    for ri, r in enumerate(runs):
        for t in r.findall(W + "t"):
            for ch in (t.text or ""):
                owner.append(ri)
                old.append(ch)
    old_text = "".join(old)
    if old_text == new_text:
        return
    a, b = _tokens(old_text), _tokens(new_text)
    starts, pos = [], 0
    for tok in a:
        starts.append(pos)
        pos += len(tok)
    starts.append(pos)
    out = [[] for _ in runs]
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        c1, c2 = starts[i1], starts[i2]
        if tag == "equal":
            for c in range(c1, c2):
                out[owner[c]].append(old_text[c])
        elif tag == "delete":
            continue
        else:
            # Inserted text joins the run of the character that FOLLOWS it (so text added right
            # after a bold label stays plain); at the very end it joins the preceding run.
            if c1 < len(owner):
                target = owner[c1]
            else:
                target = owner[c1 - 1]
            out[target].append("".join(b[j1:j2]))
    for r, chunks in zip(runs, out):
        ts = r.findall(W + "t")
        text = "".join(chunks)
        if not text:
            r.getparent().remove(r)
            continue
        ts[0].text = text
        ts[0].set(XML_SPACE, "preserve")
        for extra in ts[1:]:
            r.remove(extra)
    if line_texts(p)[line] != new_text:
        raise RuntimeError("internal error: text mismatch after edit")
