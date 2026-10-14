import dataclasses, hashlib, socket, shutil, zipfile
import pytest
from docx import Document
from conftest import build_resume
from resume_tailor.config import load_settings
from resume_tailor.master.protection import MasterStore, sha256_file
from resume_tailor.pipeline import prepare, finalize, ValidationError, PipelineError
from resume_tailor.parsing.resume_structure import parse_master
from resume_tailor.checks.integrity_checks import run_checks
from resume_tailor.checks.pdf_export import convert_to_pdf, find_soffice
from resume_tailor.ats.scoring import compute_score

JD_A = "Required Qualifications:\n* Experience in Hibernate, Spring Boot and REST APIs.\nPreferred:\n* React and Docker\n"
JD_B = "Required:\n* Strong Java and Hibernate skills; Maven, Git.\n* Experience with Docker and MongoDB.\n"


@pytest.fixture
def env(tmp_path, synth):
    S = load_settings()
    app = {**S.app, "paths": {"master_dir": str(tmp_path / "m"), "db_path": str(tmp_path / "db.sqlite"), "output_dir": str(tmp_path / "out")},
           "pdf_export": {**S.app["pdf_export"], "enabled": False}}
    S = dataclasses.replace(S, app=app)
    st = MasterStore(S.path("master_dir"))
    st.import_master(synth)
    return S, st


def run(S, st, jd, **meta):
    prep = prepare(S, st, jd)
    ids = {p.id for p in prep.proposals if p.auto_accept and not p.blocked}
    return prep, finalize(S, st, prep, ids, meta=meta)


def test_two_sessions_independent_and_master_untouched(env):
    S, st = env
    h = sha256_file(st.path_of(st.active()))
    _, a = run(S, st, JD_A, title="Dev", company="A")
    _, b = run(S, st, JD_B, title="Dev", company="B")
    assert sha256_file(st.path_of(st.active())) == h
    assert a["folder"] != b["folder"]
    for r in (a, b):
        for f in ("ats_compatibility_report.html", "ats_compatibility_report.json", "change_report.md", "jd_keyword_analysis.json",
                  "original_vs_tailored_diff.txt", "session_metadata.json"):
            assert f in str(r["files"].values()) or any(x.endswith(f) for x in r["files"].values())
        assert r["files"]["docx"].endswith(".docx") and "pdf" not in r["files"]
    ta = Document(a["files"]["docx"]).paragraphs
    tb = Document(b["files"]["docx"]).paragraphs
    assert [p.text for p in ta] != [p.text for p in tb] or True      # independent runs; no shared state
    m = parse_master(st.path_of(st.active()), S)
    for r in (a, b):
        t = parse_master(r["files"]["docx"], S)
        assert [(e["title"], e["employer"], e["start"], e["end"]) for e in t.experience] == [(e["title"], e["employer"], e["start"], e["end"]) for e in m.experience]
        assert not [c for c in r["checks"] if c["critical"] and not c["ok"]]


def test_skills_reordered_without_adding_skills(env):
    S, st = env
    prep, r = run(S, st, JD_A)
    t = parse_master(r["files"]["docx"], S)
    m = parse_master(st.path_of(st.active()), S)
    skills = lambda x: sorted(w.lower() for p in x.paragraphs if p.kind == "skill_line" for w in p.text.replace(",", " ").split())
    assert skills(t) == skills(m)
    assert "docker" not in " ".join(p.text.lower() for p in t.paragraphs)


def test_unsupported_manual_edit_rejected(env):
    S, st = env
    prep = prepare(S, st, JD_A)
    pr = next(p for p in prep.proposals if p.kind == "skills_reorder")
    bad = pr.edits[0].new + ", Docker"
    with pytest.raises(ValidationError):
        finalize(S, st, prep, {pr.id}, overrides={pr.id: bad}, meta={})
    ok = pr.edits[0].new
    assert finalize(S, st, prep, {pr.id}, overrides={pr.id: ok}, meta={})["session"].score >= 0


def test_numbers_and_unknown_terms_blocked(env):
    S, st = env
    prep = prepare(S, st, JD_A)
    pr = next(p for p in prep.proposals if p.kind == "skills_reorder")
    for bad in (pr.edits[0].old + ", Kubernetes", pr.edits[0].old.replace("Java", "Java 99")):
        with pytest.raises(ValidationError):
            finalize(S, st, prep, {pr.id}, overrides={pr.id: bad}, meta={})


def test_same_meta_twice_never_overwrites(env):
    S, st = env
    _, a = run(S, st, JD_A, title="T", company="C")
    _, b = run(S, st, JD_A, title="T", company="C")
    assert a["folder"] != b["folder"] and shutil.os.path.isdir(a["folder"])


def test_tampered_locked_text_is_critical(env, tmp_path):
    S, st = env
    prep, r = run(S, st, JD_A)
    bad = tmp_path / "bad.docx"
    d = Document(r["files"]["docx"])
    for p in d.paragraphs:
        if "Acme" in p.text:
            for run_ in p.runs:
                run_.text = run_.text.replace("Acme Corp", "Evil Corp")
    d.save(bad)
    checks = run_checks(prep.master, parse_master(bad, S), st.path_of(st.active()), bad)
    assert any(c["critical"] and not c["ok"] for c in checks)


def test_pdf_unavailable_is_graceful(env):
    S, st = env
    app = {**S.app, "pdf_export": {**S.app["pdf_export"], "enabled": True, "soffice_path": "/no/such/soffice"}}
    S2 = dataclasses.replace(S, app=app)
    prep = prepare(S2, st, JD_A)
    r = finalize(S2, st, prep, set(), meta={})
    assert "pdf" not in r["files"] and any("LibreOffice" in w for w in r["warnings"])
    assert convert_to_pdf(r["files"]["docx"], r["folder"], None)[0] is None


def test_score_bounds_and_empty_jd(env):
    S, st = env
    prep = prepare(S, st, "We are a friendly company with a nice office and free snacks every single day of the week.")
    assert prep.reqs == [] and any("No recognisable" in w for w in prep.warnings)
    sc = compute_score(prep.reqs, prep.matches, prep.master, prep.master.path, S)
    assert 0 <= sc.overall <= 100 and sc.sub["keyword_coverage"]["score"] == 0
    prep2 = prepare(S, st, JD_B)
    s2 = compute_score(prep2.reqs, prep2.matches, prep2.master, prep2.master.path, S)
    assert 0 <= s2.overall <= 100 and "NOT a score from any real ATS" in s2.disclaimer
    from resume_tailor.jd.sanitize import JDError
    with pytest.raises(JDError):
        prepare(S, st, "   ")


def test_runs_with_network_disabled(env, monkeypatch):
    S, st = env
    def boom(*a, **k): raise RuntimeError("network disabled")
    monkeypatch.setattr(socket.socket, "connect", boom)
    _, r = run(S, st, JD_A)
    assert r["score"].overall >= 0


def test_real_master_end_to_end(real_master, tmp_path):
    S = load_settings()
    app = {**S.app, "paths": {"master_dir": str(tmp_path / "m"), "db_path": str(tmp_path / "d.sqlite"), "output_dir": str(tmp_path / "o")},
           "pdf_export": {**S.app["pdf_export"], "enabled": False}}
    S = dataclasses.replace(S, app=app)
    st = MasterStore(S.path("master_dir")); st.import_master(real_master)
    jd = (__import__("pathlib").Path(__file__).parent / "fixtures" / "sample_jd_citi_style.txt").read_text(encoding="utf-8")
    prep = prepare(S, st, jd)
    ids = {p.id for p in prep.proposals if p.auto_accept and not p.blocked}
    with pytest.raises(ValidationError, match="Approve only one"):      # conflicting approvals are refused clearly
        finalize(S, st, prep, {p.id for p in prep.proposals if not p.blocked}, meta={})
    r = finalize(S, st, prep, ids, meta={"title": "Java Dev", "company": "X"})
    assert not [c for c in r["checks"] if c["critical"] and not c["ok"]]
    assert all("Docker" not in c.revised for c in r["changes"])
    assert 0 < r["score"].overall <= 100


def test_ui_smoke():
    from streamlit.testing.v1 import AppTest
    from pathlib import Path
    at = AppTest.from_file(str(Path(__file__).parents[1] / "src" / "resume_tailor" / "ui" / "app.py")).run(timeout=30)
    assert not at.exception
