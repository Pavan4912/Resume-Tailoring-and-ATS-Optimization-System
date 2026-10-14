import os, stat, zipfile
import pytest
from resume_tailor.master.protection import MasterStore, MasterError, IntegrityError, sha256_file


def test_import_hash_and_readonly(tmp_path, synth):
    st = MasterStore(tmp_path / "master")
    e = st.import_master(synth)
    stored = st.path_of(e)
    assert sha256_file(stored) == e["sha256"] == sha256_file(synth)
    assert not os.access(stored, os.W_OK) or os.geteuid() == 0   # read-only (root ignores the bit)
    assert st.verify() == stored


def test_tamper_detected(tmp_path, synth):
    st = MasterStore(tmp_path / "master")
    e = st.import_master(synth)
    p = st.path_of(e)
    os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
    p.write_bytes(p.read_bytes() + b"x")
    with pytest.raises(IntegrityError):
        st.verify()


def test_second_import_requires_explicit_replace_and_keeps_old(tmp_path, synth):
    from conftest import build_resume
    st = MasterStore(tmp_path / "master")
    first = st.import_master(synth)
    other = build_resume(tmp_path / "other.docx", extra_bullet="Extra bullet.")
    with pytest.raises(MasterError):
        st.import_master(other)
    second = st.import_master(other, replace_active=True)
    assert st.path_of(first).exists() and first["sha256"] != second["sha256"]
    assert st.active()["id"] == second["id"]


@pytest.mark.parametrize("name,content", [("a.txt", b"hi"), ("b.docx", b""), ("c.docx", b"not a zip")])
def test_rejects_bad_files(tmp_path, name, content):
    f = tmp_path / name
    f.write_bytes(content)
    with pytest.raises(MasterError):
        MasterStore(tmp_path / "m").import_master(f)


def test_rejects_zip_without_document_and_macros(tmp_path):
    z = tmp_path / "fake.docx"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("hello.txt", "x")
    with pytest.raises(MasterError):
        MasterStore(tmp_path / "m").import_master(z)
    z2 = tmp_path / "macro.docx"
    with zipfile.ZipFile(z2, "w") as zf:
        zf.writestr("word/document.xml", "<x/>"); zf.writestr("word/vbaProject.bin", "x")
    with pytest.raises(MasterError):
        MasterStore(tmp_path / "m2").import_master(z2)


def test_size_limit(tmp_path, synth):
    with pytest.raises(MasterError):
        MasterStore(tmp_path / "m", max_mb=0).import_master(synth)


def test_working_copies_independent_and_master_untouched(tmp_path, synth):
    st = MasterStore(tmp_path / "master")
    e = st.import_master(synth)
    before = sha256_file(st.path_of(e))
    a = st.make_working_copy(tmp_path / "out" / "s1")
    b = st.make_working_copy(tmp_path / "out" / "s2")
    a.write_bytes(b"corrupted by session 1")
    assert sha256_file(b) == before                      # no cross-contamination
    assert sha256_file(st.path_of(e)) == before          # master unchanged
    with pytest.raises(MasterError):
        st.make_working_copy(tmp_path / "master" / "inside")
    with pytest.raises(MasterError):
        st.make_working_copy(tmp_path / "out" / "s1")    # existing copy is never overwritten
