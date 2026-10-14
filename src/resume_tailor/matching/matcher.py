"""Match JD requirements against evidence that actually exists in the master resume."""
from __future__ import annotations
import re
from ..config import Settings
from ..jd.extractor import load_lexicon
from ..models import JDRequirement, MasterResume, RequirementMatch
from ..parsing.resume_structure import alias_pattern, DATE_RANGE

_SEARCHABLE = ("bullet", "project_header", "skill_line", "summary", "credential", "role_header")
_MON = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}


def _snippet(text: str, pats, width: int = 70) -> str:
    for p in pats:
        m = p.search(text)
        if m:
            a = max(0, m.start() - width // 2)
            return ("..." if a else "") + text[a:a + width].replace("\t", " ") + ("..." if a + width < len(text) else "")
    return text[:width]


def _find(master: MasterResume, pats) -> list[dict]:
    out = []
    for p in master.paragraphs:
        if p.kind in _SEARCHABLE and p.text and any(x.search(p.text) for x in pats):
            out.append({"para_index": p.index, "kind": p.kind, "snippet": _snippet(p.text, pats)})
    return out


def _months(master: MasterResume) -> int:
    total = 0
    for e in master.experience:
        def ym(s):
            m = re.match(r"([A-Za-z]{3})?[a-z]*\.?\s*(\d{4})", s or "")
            return (int(m.group(2)), _MON.get((m.group(1) or "jan").lower(), 1)) if m else None
        a, b = ym(e["start"]), ym(e["end"]) or ym(e["start"])
        if a and b:
            total += (b[0] - a[0]) * 12 + (b[1] - a[1])
    return total


def match_requirements(reqs: list[JDRequirement], master: MasterResume, settings: Settings) -> list[RequirementMatch]:
    lex = load_lexicon(settings)
    credit = settings.scoring["evidence_strength"]
    results = []
    for r in reqs:
        if r.category == "qualification":
            words = [w for w in re.findall(r"[A-Za-z]{4,}", r.term.replace("Degree:", "")) if w.lower() not in
                     ("related", "field", "preferred", "degree", "equivalent")]
            edu = [p for p in master.paragraphs if p.kind == "credential" and
                   any(re.search(rf"\b{re.escape(w)}\b", p.text, re.I) for w in words)]
            if edu:
                ev = [{"para_index": p.index, "kind": p.kind, "snippet": p.text[:70]} for p in edu]
                results.append(RequirementMatch(r, "supported", "direct", credit["direct"], ev, "high",
                                                "Education entry matches the required field."))
            else:
                results.append(RequirementMatch(r, "needs_review", "none", 0.0, [], "low",
                                                "No matching education entry found; check manually."))
            continue
        if r.category == "experience":
            need = int(re.match(r"Experience: (\d+)", r.term).group(1))
            have = _months(master) / 12
            ok = have >= need
            results.append(RequirementMatch(r, "supported" if ok else "gap", "direct" if ok else "none",
                                            credit["direct"] if ok else 0.0, [], "medium",
                                            f"Master documents about {have:.1f} years of experience."))
            continue
        spec = lex.get(r.term)
        pats = [alias_pattern(a.lower()) for a in sorted(set(spec["aliases"]), key=len, reverse=True)] if spec else []
        ev = _find(master, pats) if pats else []
        if r.category == "soft":
            results.append(RequirementMatch(r, "supported" if ev else "unverified", "listed" if ev else "none",
                                            credit["listed"] if ev else 0.0, ev, "low",
                                            "" if ev else "Soft skill not evidenced in the master resume. It is not "
                                            "added automatically; add it yourself only if it is true."))
            continue
        demonstrated = [e for e in ev if e["kind"] in ("bullet", "project_header")]
        if demonstrated and spec.get("cap") == "synonym":
            results.append(RequirementMatch(r, "supported", "synonym", credit["synonym"], demonstrated, "medium",
                                            "Matched through related wording (e.g. 'Spring Boot'), not the exact term."))
        elif demonstrated:
            results.append(RequirementMatch(r, "supported", "direct", credit["direct"], demonstrated, "high"))
        elif ev:
            results.append(RequirementMatch(r, "listed_only", "listed", credit["listed"], ev, "medium",
                                            "Named in skills/summary only; no bullet shows it in use."))
        else:
            rel_ev, rel_names = [], []
            for name in spec.get("related", []) if spec else []:
                hits = _find(master, [alias_pattern(name.lower())])
                if hits:
                    rel_ev += hits
                    rel_names.append(name)
            if rel_ev:
                results.append(RequirementMatch(r, "needs_review", "related", credit["related"], rel_ev, "low",
                                                f"Only related evidence ({', '.join(rel_names)}). The master does not state "
                                                f"'{r.term}' itself, so it will not be claimed unless you confirm it is true."))
            else:
                results.append(RequirementMatch(r, "gap", "none", 0.0, [], "medium",
                                                "No supporting evidence in the master resume; will not be added."))
    return results


def coverage(matches: list[RequirementMatch]) -> dict:
    out = {}
    for level in ("mandatory", "preferred", "optional"):
        ms = [m for m in matches if m.requirement.importance == level]
        if not ms:
            continue
        strict = sum(m.credit for m in ms if m.strength in ("direct", "synonym", "listed")) / len(ms)
        with_rel = sum(m.credit for m in ms) / len(ms)
        out[level] = {"count": len(ms), "evidenced_pct": round(100 * strict, 1),
                      "including_related_pct": round(100 * with_rel, 1)}
    return out
