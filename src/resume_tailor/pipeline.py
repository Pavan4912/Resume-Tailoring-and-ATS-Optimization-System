"""Orchestrates the 16-step workflow. Two phases: prepare() (analysis + proposals) and finalize() (apply + report)."""
from __future__ import annotations
import copy, json, re, shutil, uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from docx import Document
from .ats.scoring import compute_score, stuffing_warnings
from .checks.integrity_checks import run_checks
from .checks.pdf_export import convert_to_pdf, find_soffice, pdf_info, text_overlap
from .config import Settings
from .docx_edit.ooxml_utils import W
from .docx_edit.paragraph_editor import line_texts, replace_paragraph_text
from .jd.extractor import extract_requirements
from .master.protection import MasterStore, sha256_file
from .matching.matcher import coverage, match_requirements
from .models import ApprovedEdit, ChangeRecord, TailoringSession
from .parsing.resume_structure import parse_master
from .reports.writers import write_reports
from .storage.db import save_session
from .tailoring.grounding import validate
from .tailoring.llm_adapter import propose_summary
from .tailoring.proposer import propose


class PipelineError(Exception):
    pass


class ValidationError(PipelineError):
    pass


@dataclass
class Prepared:
    jd_text: str
    reqs: list
    candidates: list
    warnings: list
    matches: list
    proposals: list
    master: object
    master_sha: str
    coverage: dict = field(default_factory=dict)


def prepare(settings: Settings, store: MasterStore, jd_text: str) -> Prepared:
    path = store.verify()                                           # steps 1-2: load + integrity
    master = parse_master(path, settings)                           # step 3
    reqs, cands, warns = extract_requirements(jd_text, settings)    # step 4
    if not reqs:
        warns.append("No recognisable requirements were found; results will be mostly empty.")
    matches = match_requirements(reqs, master, settings)            # steps 5-6
    props = propose(master, matches, settings)                      # step 7
    pr, note = propose_summary(master, matches, settings)
    if pr:
        props.append(pr)
    if note:
        warns.append(note)
    if not settings.app["llm"].get("enabled"):
        warns.append("No local LLM enabled: rule-based tailoring only. The professional summary is left unchanged.")
    for p in props:
        validate(p, master, settings)
    return Prepared(jd_text, reqs, cands, warns, matches, props, master, master.sha256, coverage(matches))


def _slug(s: str, n: int = 40) -> str:
    return re.sub(r"[^\w\-]+", "_", s.strip())[:n].strip("_") or "x"


def _lines(m) -> list[str]:
    return [p.text for p in m.paragraphs if p.text]


def finalize(settings: Settings, store: MasterStore, prep: Prepared, approved_ids, overrides=None, meta=None) -> dict:
    meta, overrides = meta or {}, overrides or {}
    path = store.verify()
    if sha256_file(path) != prep.master_sha:
        raise PipelineError("The master resume changed after analysis. Start a new session.")
    chosen: list[tuple] = []                                         # step 8: user approval (+ manual edits)
    for pr in prep.proposals:
        if pr.id not in approved_ids:
            continue
        pr2, decision = copy.deepcopy(pr), "auto_accepted" if pr.auto_accept else "user_approved"
        ov = overrides.get(pr.id)
        if ov is not None and len(pr2.edits) == 1 and ov.strip() != pr2.edits[0].new.strip():
            pr2.edits[0].new, pr2.mode, pr2.allowed_words, decision = ov.strip(), "rewrite", [], "manual_edit"
        validate(pr2, prep.master, settings)
        if pr2.blocked:
            raise ValidationError(f"Edit '{pr.id}' rejected: " + " ".join(pr2.problems))
        chosen.append((pr2, decision))
    used = {}
    for pr2, _ in chosen:
        for e in pr2.edits:
            if (e.para_index, e.line) in used:
                raise ValidationError(f"Edits '{used[(e.para_index, e.line)]}' and '{pr2.id}' both change the same line "
                                      f"(paragraph {e.para_index}). Approve only one of them.")
            used[(e.para_index, e.line)] = pr2.id
    date = datetime.now().strftime("%Y-%m-%d")
    base = f"{date}_{_slug(meta.get('title', 'Role'))}_{_slug(meta.get('company', 'Company'))}"
    out_root = settings.path("output_dir")
    out_root.mkdir(parents=True, exist_ok=True)
    folder, n = out_root / base, 1
    while True:                                                      # never overwrite an existing session
        try:
            folder.mkdir(); break
        except FileExistsError:
            n += 1; folder = out_root / f"{base}_{n}"
    name = _slug(meta.get("filename") or "tailored_resume", 60)
    work = store.make_working_copy(folder, f"{name}.docx")           # fresh copy of the ORIGINAL master
    warnings = list(prep.warnings)
    d = Document(str(work))                                          # step 9: in-place edits
    paras = d.element.body.findall(W + "p")
    for pr2, _ in chosen:
        for e in pr2.edits:
            p = paras[e.para_index]
            actual = line_texts(p)[e.line]
            if actual.strip() != e.old.strip():
                raise PipelineError(f"Unexpected text in paragraph {e.para_index}; aborting without output.")
            lead, trail = actual[:len(actual) - len(actual.lstrip())], actual[len(actual.rstrip()):]
            replace_paragraph_text(p, lead + e.new.strip() + trail, e.line)
    d.save(str(work))                                                # step 10
    after = parse_master(work, settings)
    checks = run_checks(prep.master, after, path, work)              # step 11
    crit = [c for c in checks if c["critical"] and not c["ok"]]
    if crit:
        work.unlink(missing_ok=True)
        raise PipelineError("Integrity check failed, no resume produced: " + "; ".join(c["name"] for c in crit))
    pdf_overlap, files = None, {"docx": str(work)}                   # steps 13-14
    pcfg = settings.app["pdf_export"]
    if pcfg.get("enabled"):
        so = find_soffice(pcfg.get("soffice_path", ""))
        tmp = folder / "_render_tmp"
        pdf, w1 = convert_to_pdf(work, folder, so, pcfg["timeout_seconds"])
        if w1:
            warnings.append(w1)
        if pdf:
            info = pdf_info(pdf)
            pdf_overlap = text_overlap(" ".join(_lines(after)), info["text"])
            files["pdf"] = str(pdf)
            mpdf, _ = convert_to_pdf(path, tmp, so, pcfg["timeout_seconds"])
            if mpdf:
                mp = pdf_info(mpdf)["pages"]
                if info["pages"] > mp:
                    warnings.append(f"Layout overflow: tailored resume is {info['pages']} pages vs {mp} in the master.")
                checks.append({"name": "Page count matches master", "ok": info["pages"] <= mp, "critical": False,
                               "detail": f"master {mp}, tailored {info['pages']}"})
            checks.append({"name": "DOCX text matches exported PDF text", "ok": pdf_overlap >= 0.9, "critical": False,
                           "detail": f"{pdf_overlap:.0%}"})
        shutil.rmtree(tmp, ignore_errors=True)
    if checks and not all(c["ok"] for c in checks):
        warnings.append("Some document checks raised warnings; see the report.")
    base_counts = stuffing_warnings(prep.master, settings)[1]
    before = compute_score(prep.reqs, prep.matches, prep.master, path, settings)
    t_matches = match_requirements(prep.reqs, after, settings)
    score = compute_score(prep.reqs, t_matches, after, work, settings, pdf_overlap, base_counts)   # step 15
    changes = []
    for pr2, decision in chosen:
        for e in pr2.edits:
            changes.append(ChangeRecord(pr2.section, e.old, e.new, pr2.reason, pr2.requirement, pr2.evidence,
                                        {"auto_accepted": "auto-accepted (reorder only)", "user_approved": "approved after review",
                                         "manual_edit": "manually edited by user"}[decision]))
    ctx = dict(title=meta.get("title", ""), company=meta.get("company", ""), before=before, after=score, matches=t_matches,
               candidates=prep.candidates, jd_warnings=prep.warnings, changes=changes, checks=checks, warnings=warnings,
               master_lines=_lines(prep.master), tailored_lines=_lines(after))
    files.update(write_reports(folder, ctx))
    sid = uuid.uuid4().hex[:8]
    sess = TailoringSession(sid, datetime.now(timezone.utc).isoformat(timespec="seconds"), meta.get("company", ""),
                            meta.get("title", ""), str(folder), prep.master_sha, score.overall, files, warnings)
    (folder / "session_metadata.json").write_text(json.dumps({
        **sess.__dict__, "job_url": meta.get("url", ""), "approved_edits": [ApprovedEdit(p.id, p.edits, d).proposal_id for p, d in chosen],
        "score_master": before.overall, "coverage": prep.coverage, "libreoffice": bool(find_soffice(pcfg.get("soffice_path", "")))},
        indent=2, default=str), encoding="utf-8")
    files["session_metadata.json"] = str(folder / "session_metadata.json")
    save_session(settings.path("db_path"), sess)                     # step 16
    return {"session": sess, "score": score, "score_master": before, "changes": changes, "checks": checks,
            "warnings": warnings, "files": files, "folder": str(folder)}
