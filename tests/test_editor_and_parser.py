import shutil
from docx import Document
import pytest
from resume_tailor.config import load_settings
from resume_tailor.docx_edit.ooxml_utils import W, para_text
from resume_tailor.docx_edit.paragraph_editor import (replace_paragraph_text, editability,
                                                      UnsupportedParagraphError, line_texts)
from resume_tailor.parsing.resume_structure import parse_master
from resume_tailor.parsing.formatting import take_snapshot, diff_snapshots

S = load_settings()


def _body_paras(path):
    d = Document(path)
    return d, d.element.body.findall(W + "p")


def test_parse_synthetic(synth):
    m = parse_master(synth, S)
    kinds = {p.kind for p in m.paragraphs}
    assert {"name", "contact", "heading", "summary", "skill_line", "role_header", "bullet", "credential"} <= kinds
    assert m.experience[0]["title"] == "Software Engineer"
    assert (m.experience[0]["start"], m.experience[0]["end"]) == ("Jan 2022", "Present")
    assert m.contact["email"] == "asha@example.com"
    assert len(m.bullets) == 2 and m.bullets[0].parent_title == "Software Engineer"
    assert m.evidence["Spring Boot"].demonstrated and not m.evidence["React"].demonstrated
    assert m.evidence["React"].listed_in_skills


def test_headings_and_headers_locked(synth):
    m = parse_master(synth, S)
    for p in m.paragraphs:
        if p.kind in ("heading", "role_header", "credential", "name", "contact"):
            assert not p.editable


def test_edit_preserves_unchanged_run_formatting(synth, tmp_path):
    d, ps = _body_paras(synth)
    p = ps[5]                                                   # "Backend:" bold + plain runs
    assert para_text(p) == "Backend: Java, Spring Boot, Hibernate"
    replace_paragraph_text(p, "Backend: Java, Spring Boot, Hibernate, JPA")
    assert para_text(p) == "Backend: Java, Spring Boot, Hibernate, JPA"
    first = p.findall(W + "r")[0]
    assert first.find(W + "rPr/" + W + "b") is not None         # label still bold
    assert first.find(W + "t").text == "Backend:"
    last = p.findall(W + "r")[-1]
    assert last.find(W + "rPr/" + W + "b") is None              # inserted text not bold


def test_edit_fragmented_summary(synth):
    d, ps = _body_paras(synth)
    p = ps[3]
    replace_paragraph_text(p, "Java developer with 2 years of experience building REST APIs and microservices using Spring Boot.")
    assert para_text(p).endswith("microservices using Spring Boot.")


def test_hyperlink_and_tab_paragraphs_refused(synth):
    d, ps = _body_paras(synth)
    assert not editability(ps[-1])[0]
    with pytest.raises(UnsupportedParagraphError):
        replace_paragraph_text(ps[-1], "x")
    role = next(p for p in ps if "Software Engineer" in para_text(p))
    with pytest.raises(UnsupportedParagraphError):
        replace_paragraph_text(role, "Principal Engineer | Acme")


def test_line_edit_leaves_other_line(synth):
    d, ps = _body_paras(synth)
    p = ps[6]
    assert line_texts(p) == ["Tools: Maven, Git", "Frontend: HTML, React"]
    replace_paragraph_text(p, "Frontend: React, HTML", line=1)
    assert line_texts(p) == ["Tools: Maven, Git", "Frontend: React, HTML"]


def test_formatting_snapshot_clean_after_text_edit(synth, tmp_path):
    out = tmp_path / "edited.docx"
    shutil.copyfile(synth, out)
    d, ps = _body_paras(out)
    bullet = next(p for p in ps if para_text(p).startswith("Built REST"))
    replace_paragraph_text(bullet, "Built REST APIs and microservices with Spring Boot and Hibernate.")
    d.save(out)
    assert diff_snapshots(take_snapshot(synth), take_snapshot(out)) == []


def test_snapshot_detects_formatting_change(synth, tmp_path):
    out = tmp_path / "bad.docx"
    d, ps = _body_paras(synth)
    d.paragraphs[3].paragraph_format.space_after = 999999
    d.save(out)
    assert diff_snapshots(take_snapshot(synth), take_snapshot(out))


def test_real_master(real_master):
    m = parse_master(real_master, S)
    assert m.experience[0]["start"] == "Dec 2023" and m.experience[0]["end"] == "Sep 2026"
    assert len(m.bullets) == 12
    assert [b.parent_title for b in m.bullets].count("Software Engineer") == 4
    assert [b.parent_title for b in m.bullets].count("Cardnet Payment Integration System") == 3
    assert any(p.line == 1 and p.text.startswith("Frontend:") for p in m.paragraphs)
    assert not m.evidence["React"].demonstrated and m.evidence["Redis"].demonstrated
    # edit every editable bullet with an identical text: must be a no-op for formatting
    out = real_master.parent / "_tmp_check.docx"
    shutil.copyfile(real_master, out)
    try:
        d, ps = _body_paras(out)
        replace_paragraph_text(ps[16], "Optimized SQL queries, database indexes, and API workflows in backend operations.")
        d.save(out)
        assert diff_snapshots(take_snapshot(real_master), take_snapshot(out)) == []
    finally:
        out.unlink(missing_ok=True)


def test_insert_after_bold_label_is_not_bold(synth):
    d, ps = _body_paras(synth)
    p = ps[6]
    replace_paragraph_text(p, "Frontend: React, Next.js, HTML, React", line=1)
    bold_text = "".join(r.find(W + "t").text for r in p.findall(W + "r")
                        if r.find(W + "t") is not None and r.find(W + "rPr/" + W + "b") is not None)
    assert bold_text.replace(" ", "") == "Tools:Frontend:"
