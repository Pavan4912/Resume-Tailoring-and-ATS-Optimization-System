"""Streamlit UI (local only). Run: streamlit run src/resume_tailor/ui/app.py"""
from __future__ import annotations
import json, shutil, tempfile
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components
from resume_tailor.config import load_settings
from resume_tailor.jd.importer import read_jd_file
from resume_tailor.jd.sanitize import JDError
from resume_tailor.master.protection import MasterError, MasterStore
from resume_tailor.pipeline import PipelineError, finalize, prepare
from resume_tailor.storage.db import delete_session, list_sessions

S = load_settings()
store = MasterStore(S.path("master_dir"), S.app["limits"]["max_upload_mb"])
PAGES = ["Dashboard", "Master Resume", "New Tailoring Session", "ATS Report", "Change Log", "Export", "History"]


def _tmp_save(up) -> Path:
    t = tempfile.NamedTemporaryFile(delete=False, suffix=Path(up.name).suffix)
    t.write(up.getbuffer()); t.close()
    return Path(t.name)


def page_dashboard():
    st.header("Dashboard")
    a = store.active()
    if a:
        try:
            store.verify(); st.success(f"Master resume protected and verified: {a['original_name']} (SHA-256 {a['sha256'][:12]}...)")
        except Exception as e:  # noqa: BLE001
            st.error(str(e))
    else:
        st.warning("No master resume yet. Go to 'Master Resume' to import one.")
    rows = list_sessions(S.path("db_path"))
    st.subheader("Recent sessions")
    st.dataframe([{k: r[k] for k in ("created_at", "company", "title", "score")} for r in rows[:10]] or [], use_container_width=True)
    st.info("Privacy: everything stays on this computer. Master: data/master. Outputs: output/. History: data/db. No telemetry, no cloud AI.")


def page_master():
    st.header("Master Resume")
    a = store.active()
    if a:
        st.write(f"Active: **{a['original_name']}**, stored as `{a['file']}`, imported {a['imported_at']}")
        if st.button("Verify integrity now"):
            try:
                store.verify(); st.success("Hash matches the imported original.")
            except Exception as e:  # noqa: BLE001
                st.error(str(e))
        from resume_tailor.parsing.resume_structure import parse_master
        try:
            m = parse_master(store.verify(), S)
            for w in m.warnings: st.warning(w)
            st.dataframe([{"#": p.index, "line": p.line, "kind": p.kind, "editable": p.editable, "text": p.text[:90]} for p in m.paragraphs if p.text], use_container_width=True)
            weak = [k for k, e in m.evidence.items() if not e.demonstrated]
            st.caption("Skills listed but not shown in any bullet (weaker evidence): " + ", ".join(weak))
        except Exception as e:  # noqa: BLE001
            st.error(str(e))
    up = st.file_uploader("Import master resume (.docx)", type=["docx"])
    rep = st.checkbox("Replace the active master (the previous file is kept on disk)", disabled=not a)
    if up and st.button("Import"):
        tmp = _tmp_save(up)
        try:
            e = store.import_master(tmp, replace_active=rep); st.success(f"Imported {e['original_name']}.")
        except MasterError as ex:
            st.error(str(ex))
        finally:
            tmp.unlink(missing_ok=True)
    st.caption("PDF masters are not supported for editing: DOCX is required for high-fidelity formatting.")


def page_new():
    st.header("New Tailoring Session")
    if not store.active():
        st.warning("Import a master resume first."); return
    c1, c2 = st.columns(2)
    company = c1.text_input("Company"); title = c2.text_input("Job title")
    url = c1.text_input("Job URL (optional)"); fname = c2.text_input("Custom output filename (optional)")
    jd = st.text_area("Paste the full job description", height=220, key="jd_text")
    up = st.file_uploader("...or import a JD (.txt, .docx, .pdf)", type=["txt", "docx", "pdf"])
    if up:
        tmp = _tmp_save(up)
        try:
            jd = read_jd_file(tmp, S.app["limits"]["max_upload_mb"])
        except JDError as e:
            st.error(str(e))
        finally:
            tmp.unlink(missing_ok=True)
    if st.button("Analyze JD"):
        try:
            st.session_state.prep = prepare(S, store, jd)
            st.session_state.meta = {"company": company, "title": title, "url": url, "filename": fname}
            st.session_state.pop("result", None)
        except (JDError, PipelineError, MasterError) as e:
            st.error(str(e))
    prep = st.session_state.get("prep")
    if not prep: return
    for w in prep.warnings: st.warning(w)
    st.subheader("JD analysis")
    st.write("Preliminary keyword coverage (not the ATS score):", prep.coverage)
    st.dataframe([{"requirement": m.requirement.term, "importance": m.requirement.importance, "category": m.requirement.category,
                   "status": m.status, "evidence": m.strength, "note": m.note} for m in prep.matches], use_container_width=True)
    if prep.candidates: st.caption("Phrases not recognised (review manually): " + "; ".join(prep.candidates))
    st.subheader("Tailoring preview: approve, reject or edit")
    approved, overrides = set(), {}
    for p in prep.proposals:
        with st.expander(f"{p.section}: {p.kind}" + ("  [BLOCKED]" if p.blocked else "  [review required]" if not p.auto_accept else ""), expanded=not p.auto_accept):
            st.caption(p.reason + " | Evidence: " + p.evidence)
            if p.blocked:
                st.error(" ".join(p.problems)); continue
            for e in p.edits[:1] if len(p.edits) == 1 else p.edits:
                st.text("Original: " + e.old)
            if len(p.edits) == 1:
                overrides[p.id] = st.text_area("Revised (editable)", p.edits[0].new, key="t" + p.id)
            else:
                for e in p.edits: st.text("Revised:  " + e.new)
            if st.checkbox("Approve", value=p.auto_accept, key="a" + p.id): approved.add(p.id)
    if st.button("Generate tailored resume", type="primary"):
        try:
            st.session_state.result = finalize(S, store, prep, approved, overrides, st.session_state.meta)
            st.success("Done. See ATS Report, Change Log and Export.")
        except (PipelineError, MasterError) as e:
            st.error(str(e))


def _current():
    r = st.session_state.get("result")
    if r: return r["folder"]
    rows = list_sessions(S.path("db_path"))
    return rows[0]["folder"] if rows else None


def page_report():
    st.header("ATS Report"); f = _current()
    if not f: st.info("No session yet."); return
    j = json.loads((Path(f) / "ats_compatibility_report.json").read_text(encoding="utf-8"))
    st.caption(j["disclaimer"]); st.metric("Estimated score", j["overall_after_tailoring"], delta=round(j["overall_after_tailoring"] - j["overall_before_tailoring"], 1))
    st.dataframe([{"area": k, "score": v["score"], "max": v["max"], "how": v["how"]} for k, v in j["sub_scores"].items()], use_container_width=True)
    st.json(j["metrics"]); [st.warning(w) for w in j["warnings"]]


def page_changes():
    st.header("Change Log"); f = _current()
    if f: st.markdown((Path(f) / "change_report.md").read_text(encoding="utf-8")); st.code((Path(f) / "original_vs_tailored_diff.txt").read_text(encoding="utf-8"))
    else: st.info("No session yet.")


def page_export():
    st.header("Export"); f = _current()
    if not f: st.info("No session yet."); return
    st.write("Saved in:", f)
    for p in sorted(Path(f).glob("*")):
        if p.is_file(): st.download_button(p.name, p.read_bytes(), file_name=p.name, key="dl" + p.name)


def page_history():
    st.header("History")
    rows = list_sessions(S.path("db_path"))
    if not rows: st.info("No sessions yet."); return
    sel = st.selectbox("Session", rows, format_func=lambda r: f"{r['created_at']} | {r['company']} | {r['title']} | {r['score']}")
    rep = Path(sel["folder"]) / "ats_compatibility_report.html"
    if rep.exists(): components.html(rep.read_text(encoding="utf-8"), height=700, scrolling=True)
    if st.checkbox("I understand deleting a session permanently removes its output folder (never the master)") and st.button("Delete session"):
        out = S.path("output_dir").resolve(); fol = Path(sel["folder"]).resolve()
        if out in fol.parents: shutil.rmtree(fol, ignore_errors=True)
        delete_session(S.path("db_path"), sel["id"]); st.rerun()


st.set_page_config(page_title="Offline Resume Tailor", layout="wide")
page = st.sidebar.radio("Navigate", PAGES)
{"Dashboard": page_dashboard, "Master Resume": page_master, "New Tailoring Session": page_new, "ATS Report": page_report,
 "Change Log": page_changes, "Export": page_export, "History": page_history}[page]()
