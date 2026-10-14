"""Transparent, deterministic ATS compatibility ESTIMATE. Not a score from any commercial ATS."""
from __future__ import annotations
import re
from ..config import Settings
from ..jd.extractor import load_lexicon
from ..models import ATSScoreBreakdown
from ..parsing.resume_structure import alias_pattern
from .parse_checks import structure_checks

DISCLAIMER = ("Internal compatibility estimate computed from documented rules. It is NOT a score from any real ATS, "
              "and a high value does not guarantee shortlisting or an interview.")
USABLE = ("direct", "synonym", "listed")


def _credit(m) -> float:
    return m.credit if m.strength in USABLE else 0.0      # 'related' evidence earns nothing until you confirm it


def _wavg(ms, rw) -> float:
    den = sum(rw[m.requirement.importance] for m in ms)
    return sum(rw[m.requirement.importance] * _credit(m) for m in ms) / den if den else 0.0


def stuffing_warnings(resume, settings: Settings, baseline: dict | None = None) -> tuple[list[str], dict]:
    text = " ".join(p.text for p in resume.paragraphs)
    counts = {}
    for name, spec in load_lexicon(settings).items():
        counts[name] = sum(len(alias_pattern(a.lower()).findall(text)) for a in spec["aliases"])
    limit = settings.scoring["stuffing"]["max_term_repetitions"]
    warns = [f"'{n}' appears {c} times" for n, c in counts.items()
             if c > limit and (baseline is None or c > baseline.get(n, 0))]
    return warns, counts


def compute_score(reqs, matches, resume, docx_path, settings: Settings, pdf_overlap=None, baseline_counts=None) -> ATSScoreBreakdown:
    sc = settings.scoring
    w, rw = sc["weights"], sc["requirement_weights"]
    tech = [m for m in matches if m.requirement.category in ("technical", "tool")]
    kw = w["keyword_coverage"] * _wavg(matches, rw)
    skills = w["skills_alignment"] * _wavg(tech, rw)
    dem_den = sum(rw[m.requirement.importance] for m in tech)
    dem = sum(rw[m.requirement.importance] for m in tech if m.strength in ("direct", "synonym")) / dem_den if dem_den else 0.0
    lex = load_lexicon(settings)
    hit = [m for m in matches if m.strength in USABLE]
    pats = [alias_pattern(a.lower()) for m in hit for a in lex.get(m.requirement.term, {"aliases": []})["aliases"]]
    bl = resume.bullets
    brel = sum(any(p.search(b.text) for p in pats) for b in bl) / len(bl) if bl else 0.0
    exp = w["experience_alignment"] * (0.6 * dem + 0.4 * brel)
    spts, schecks = structure_checks(resume, docx_path, pdf_overlap)
    structure = w["structure_parsing"] * spts / 10
    lens = [len(b.text.split()) for b in bl]
    len_ok = sum(8 <= n <= 35 for n in lens) / len(lens) if lens else 0.0
    sw, counts = stuffing_warnings(resume, settings, baseline_counts)
    stuff_ok = max(0.0, 1 - 0.34 * len(sw))
    text = " ".join(p.text for p in resume.paragraphs if p.kind in ("summary", "bullet", "skill_line"))
    forms = [(m, [a for a in lex.get(m.requirement.term, {"aliases": []})["aliases"] if alias_pattern(a.lower()).search(m.requirement.source_line)]) for m in hit]
    forms = [f for f in forms if f[1]]
    worded = sum(any(alias_pattern(a.lower()).search(text) for a in al) for _, al in forms) / len(forms) if forms else 0.0
    clarity = w["clarity_terminology"] * (0.4 * len_ok + 0.3 * stuff_ok + 0.3 * worded)
    sub = {
        "keyword_coverage": {"score": round(kw, 1), "max": w["keyword_coverage"],
                             "how": f"Weighted share (mandatory {rw['mandatory']}, preferred {rw['preferred']}, optional {rw['optional']}) of the {len(matches)} JD requirements with evidence in the resume; evidence strength multiplies credit; 'related' evidence earns 0."},
        "skills_alignment": {"score": round(skills, 1), "max": w["skills_alignment"],
                             "how": f"Same weighting over the {len(tech)} technical/tool requirements."},
        "experience_alignment": {"score": round(exp, 1), "max": w["experience_alignment"],
                                 "how": f"60% share of technical requirements shown in bullets/projects ({dem:.0%}) + 40% of bullets that mention an evidenced JD term ({brel:.0%})."},
        "structure_parsing": {"score": round(structure, 1), "max": w["structure_parsing"], "how": "Sum of parsing checks.", "checks": schecks},
        "clarity_terminology": {"score": round(clarity, 1), "max": w["clarity_terminology"],
                                "how": f"40% bullets of 8-35 words ({len_ok:.0%}), 30% no keyword stuffing ({len(sw)} warnings), 30% JD wording used for evidenced terms ({worded:.0%})."},
    }
    overall = round(max(0.0, min(100.0, sum(v["score"] for v in sub.values()))), 1)
    by = lambda lvl: [m for m in matches if m.requirement.importance == lvl]
    pct = lambda ms: round(100 * sum(_credit(m) for m in ms) / len(ms), 1) if ms else None
    metrics = {
        "mandatory_keyword_coverage_pct": pct(by("mandatory")), "preferred_keyword_coverage_pct": pct(by("preferred")),
        "supported_skill_coverage_pct": pct(tech),
        "experience_alignment_pct": round(100 * (0.6 * dem + 0.4 * brel), 1),
        "missing_mandatory": [m.requirement.term for m in by("mandatory") if m.status == "gap"],
        "missing_preferred": [m.requirement.term for m in by("preferred") if m.status == "gap"],
        "unsupported_or_unverified": [m.requirement.term for m in matches if m.status in ("needs_review", "unverified")],
        "listed_only": [m.requirement.term for m in matches if m.status == "listed_only"],
        "parsing_checks": schecks,
    }
    return ATSScoreBreakdown(overall, sub, metrics, sw, DISCLAIMER)
