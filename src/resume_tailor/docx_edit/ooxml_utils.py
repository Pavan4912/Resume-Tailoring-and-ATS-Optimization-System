"""Small OOXML helpers shared by the parser, snapshot and editor."""
from __future__ import annotations
import hashlib
from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = "{%s}" % W_NS
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def para_text(p) -> str:
    """Visible text of a paragraph element (tabs as \\t, includes hyperlink runs)."""
    out = []
    for el in p.iter():
        if el.tag == W + "t":
            out.append(el.text or "")
        elif el.tag == W + "tab" and el.getparent().tag == W + "r":
            out.append("\t")
        elif el.tag == W + "br":
            out.append("\n")
    return "".join(out)


def canon_hash(el) -> str:
    if el is None:
        return "-"
    return hashlib.sha1(etree.tostring(el, method="c14n")).hexdigest()[:12]


def style_id(p) -> str:
    s = p.find(f"{W}pPr/{W}pStyle")
    return s.get(W + "val") if s is not None else ""


def has_numbering(p) -> bool:
    return p.find(f"{W}pPr/{W}numPr") is not None
