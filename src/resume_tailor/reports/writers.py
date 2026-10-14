"""All report files. Self-contained: no network resources, inline CSS only."""
from __future__ import annotations
import difflib, html, json
from dataclasses import asdict
from pathlib import Path


def _j(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def write_reports(folder: Path, ctx: dict) -> dict:
    files = {}
    ats = {"disclaimer": ctx["after"].disclaimer, "overall_before_tailoring": ctx["before"].overall,
           "overall_after_tailoring": ctx["after"].overall, "sub_scores": ctx["after"].sub,
           "metrics": ctx["after"].metrics, "stuffing_warnings": ctx["after"].warnings,
           "document_checks": ctx["checks"], "warnings": ctx["warnings"]}
    _j(folder / "ats_compatibility_report.json", ats)
    _j(folder / "jd_keyword_analysis.json", {"requirements_and_matches": [asdict(m) for m in ctx["matches"]],
                                            "unclassified_phrases": ctx["candidates"], "jd_warnings": ctx["jd_warnings"]})
    ch = ctx["changes"]
    md = ["# Change report", "", f"Role: {ctx['title']} | Company: {ctx['company']}", "",
          f"Internal ATS estimate: {ctx['before'].overall} (master) -> {ctx['after'].overall} (tailored). {ctx['after'].disclaimer}", ""]
    if not ch:
        md.append("No edits were applied; the tailored resume is identical in content to the master.")
    for i, c in enumerate(ch, 1):
        md += [f"## {i}. {c.section}", f"- **Original:** {c.original}", f"- **Revised:** {c.revised}", f"- **Reason:** {c.reason}",
               f"- **JD keyword/requirement:** {c.requirement}", f"- **Evidence in master:** {c.evidence}", f"- **Review status:** {c.review}", ""]
    md += ["## JD keywords not incorporated (and why)"]
    md += [f"- {m.requirement.term} [{m.requirement.importance}] {m.status}: {m.note}" for m in ctx["matches"] if m.status in ("gap", "needs_review", "unverified")] or ["- none"]
    md += ["", "## Content removed or de-emphasised", "- Nothing was removed. Bullets/skills may have been reordered (see above).",
           "", "## Facts requiring your verification"]
    md += [f"- {m.requirement.term}: {m.note}" for m in ctx["matches"] if m.status == "needs_review"] or ["- none"]
    md += ["", "## Formatting / layout", *[f"- {c['name']}: {'OK' if c['ok'] else 'WARNING ' + c['detail']}" for c in ctx["checks"]]]
    md += [f"- {w}" for w in ctx["warnings"]]
    (folder / "change_report.md").write_text("\n".join(md), encoding="utf-8")
    diff = "\n".join(difflib.unified_diff(ctx["master_lines"], ctx["tailored_lines"], "master", "tailored", lineterm=""))
    (folder / "original_vs_tailored_diff.txt").write_text(diff or "(no differences)", encoding="utf-8")
    e = html.escape
    rows = "".join(f"<tr><td>{e(k.replace('_',' '))}</td><td>{v['score']} / {v['max']}</td><td>{e(v['how'])}</td></tr>" for k, v in ctx["after"].sub.items())
    mrows = "".join(f"<tr><td>{e(m.requirement.term)}</td><td>{m.requirement.importance}</td><td>{m.status}</td><td>{m.strength}</td><td>{e(m.note)}</td></tr>" for m in ctx["matches"])
    crows = "".join(f"<tr><td>{'OK' if c['ok'] else 'WARN'}</td><td>{e(c['name'])}</td><td>{e(c['detail'])}</td></tr>" for c in ctx["checks"])
    chrows = "".join(f"<tr><td>{e(c.section)}</td><td>{e(c.original)}</td><td>{e(c.revised)}</td><td>{e(c.reason)}</td><td>{e(c.review)}</td></tr>" for c in ch)
    mt = ctx["after"].metrics
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>ATS compatibility report</title><style>
body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;max-width:1100px;color:#222}}table{{border-collapse:collapse;width:100%;margin:8px 0 20px}}
td,th{{border:1px solid #ccc;padding:6px;font-size:13px;vertical-align:top}}th{{background:#f0f0f0}}.big{{font-size:34px;font-weight:700}}.note{{background:#fff7e0;padding:8px;border:1px solid #e5d49a}}</style></head><body>
<h1>ATS compatibility report</h1><p>{e(ctx['title'])} - {e(ctx['company'])}</p><p class="note">{e(ctx['after'].disclaimer)}</p>
<p class="big">{ctx['after'].overall} / 100 <small>(master: {ctx['before'].overall})</small></p>
<h2>Sub-scores</h2><table><tr><th>Area</th><th>Score</th><th>How calculated</th></tr>{rows}</table>
<h2>Coverage</h2><p>Mandatory: {mt['mandatory_keyword_coverage_pct']}% | Preferred: {mt['preferred_keyword_coverage_pct']}% | Supported skill coverage: {mt['supported_skill_coverage_pct']}% | Experience alignment: {mt['experience_alignment_pct']}%</p>
<p><b>Missing mandatory:</b> {e(', '.join(mt['missing_mandatory']) or 'none')}<br><b>Missing preferred:</b> {e(', '.join(mt['missing_preferred']) or 'none')}<br>
<b>Unsupported/unverified:</b> {e(', '.join(mt['unsupported_or_unverified']) or 'none')}<br><b>Listed only (no bullet shows use):</b> {e(', '.join(mt['listed_only']) or 'none')}<br>
<b>Keyword stuffing warnings:</b> {e('; '.join(ctx['after'].warnings) or 'none')}</p>
<h2>Requirement matching</h2><table><tr><th>Requirement</th><th>Importance</th><th>Status</th><th>Evidence</th><th>Note</th></tr>{mrows}</table>
<h2>Document checks</h2><table><tr><th></th><th>Check</th><th>Detail</th></tr>{crows}</table>
<h2>Changes (original vs revised)</h2><table><tr><th>Section</th><th>Original</th><th>Revised</th><th>Reason</th><th>Review</th></tr>{chrows or '<tr><td colspan=5>No edits applied</td></tr>'}</table>
<p>{e(' | '.join(ctx['warnings']))}</p></body></html>"""
    (folder / "ats_compatibility_report.html").write_text(page, encoding="utf-8")
    return {n: str(folder / n) for n in ["ats_compatibility_report.json", "ats_compatibility_report.html", "change_report.md",
                                         "jd_keyword_analysis.json", "original_vs_tailored_diff.txt"]}
