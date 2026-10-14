"""Deterministic JD requirement extraction with importance levels."""
from __future__ import annotations
import re
from ..config import Settings
from ..models import JDRequirement
from ..parsing.resume_structure import alias_pattern
from .sanitize import sanitize_jd

PREFERRED = re.compile(r"\b(preferred|desirable|nice to have|a plus|bonus|good to have|ideally)\b", re.I)
MANDATORY = re.compile(r"\b(must|mandatory|required|essential|minimum)\b", re.I)
DEGREE = re.compile(r"(bachelor|master|b\.?e\.?|b\.?tech|degree)[^.\n]{0,80}?\bin\b\s+([^.\n]+)", re.I)
YEARS = re.compile(r"(\d+)\s*\+?\s*(?:-\s*\d+\s*)?years?", re.I)
LIST_INTRO = re.compile(r"(experience in|knowledge of|expertise in|familiar with|hands[- ]on|proficien\w+ in|using)\s+(.*)", re.I)


def load_lexicon(settings: Settings) -> dict[str, dict]:
    lex = {}
    jd = settings.lexicon.get("terms", {})
    for name, spec in jd.items():
        lex[name] = {"category": spec["category"], "aliases": list(spec["aliases"]),   # explicit only: the term name is NOT an implicit alias
                     "related": spec.get("related", []), "cap": spec.get("cap")}
    covered = [set(a.lower() for a in v["aliases"]) for v in lex.values()]
    for name, spec in settings.taxonomy["skills"].items():       # resume taxonomy doubles as JD vocabulary
        aliases = {name.lower(), *(a.lower() for a in spec)}
        if not any(aliases <= c for c in covered):                 # skip terms the lexicon already covers
            lex[name] = {"category": "tool", "aliases": sorted(aliases), "related": []}
    return lex


def _section_default(header: str) -> str | None:
    h = header.lower().rstrip(":").strip()
    if re.search(r"prefer|nice to have|desirable|plus", h): return "preferred"
    if re.search(r"required|must|minimum|qualification|requirement", h): return "mandatory"
    if re.search(r"responsibilit|what you.?ll do|duties", h): return "preferred"
    if re.search(r"overview|description|about|summary|benefit|we offer", h): return "optional"
    return None


def extract_requirements(jd_text: str, settings: Settings) -> tuple[list[JDRequirement], list[str], list[str]]:
    """Returns (requirements, unclassified candidate phrases, warnings)."""
    text, warnings = sanitize_jd(jd_text, settings.app["limits"]["max_jd_chars"])
    lex = load_lexicon(settings)
    pats = {n: [alias_pattern(a.lower()) for a in sorted(set(s["aliases"]), key=len, reverse=True)] for n, s in lex.items()}
    section, found, mentions, lines_for = "optional", {}, {}, []
    stop = set(settings.lexicon.get("stop_candidates", []))
    candidates: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"^[\s*\-•·▪●]+", "", raw).strip()
        if not line:
            continue
        if (line.endswith(":") and len(line) < 60) or (len(line.split()) <= 4 and _section_default(line)):
            sd = _section_default(line)
            if sd:
                section = sd
            continue
        level, notes = section, []
        if PREFERRED.search(line):
            if section == "mandatory":
                notes.append("Marked 'preferred' inside a required section; treated as preferred.")
            level = "preferred"
        elif MANDATORY.search(line):
            level = "mandatory"
        for name, plist in pats.items():
            if any(p.search(line) for p in plist):
                lvl = level
                if lex[name]["category"] == "soft" and level == "mandatory":
                    lvl = "preferred"      # soft skills are rarely hard filters; weighted as preferred

                mentions[name] = mentions.get(name, 0) + sum(len(p.findall(line)) > 0 for p in plist[:1])
                prev = found.get(name)
                rank = {"optional": 0, "preferred": 1, "mandatory": 2}
                if prev is None or rank[lvl] > rank[prev.importance]:
                    n2 = notes + (["Soft skill: weighted as preferred."] if lvl != level else [])
                    found[name] = JDRequirement(name, lex[name]["category"], lvl, 1, line, n2)
                else:
                    prev.mentions += 1
        m = DEGREE.search(line)
        if m:
            key = "Degree: " + re.sub(r"\s*\b(preferred|required)\b\s*$", "", m.group(2).strip().rstrip("."), flags=re.I)
            found[key] = JDRequirement(key, "qualification", level, 1, line, notes)
        for y in YEARS.finditer(line):
            key = f"Experience: {y.group(0)}"
            found[key] = JDRequirement(key, "experience", level, 1, line, notes)
        li = LIST_INTRO.search(line)
        if li:   # surface items the lexicon does not know, for the user to review
            for item in re.split(r"[,;/()]| and ", li.group(2)):
                item = item.strip(" .:-")
                words = item.split()
                if 0 < len(words) <= 4 and not any(p.search(item) for pl in pats.values() for p in pl) \
                        and not (set(w.lower() for w in words) <= stop) and item not in candidates:
                    candidates.append(item)
    reqs = list(found.values())
    for r in reqs:
        r.mentions = max(r.mentions, mentions.get(r.term, 1))
    return reqs, candidates, warnings
