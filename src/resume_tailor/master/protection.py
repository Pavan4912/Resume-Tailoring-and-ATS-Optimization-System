"""Protected storage for the master resume. Originals are never modified, renamed or deleted."""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import stat
import zipfile
from datetime import datetime, timezone
from pathlib import Path

MANIFEST = "manifest.json"


class MasterError(Exception):
    pass


class IntegrityError(MasterError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_docx(path: Path, max_mb: int = 10) -> None:
    """Reject wrong types, oversize, corrupt zips and macro-enabled files."""
    path = Path(path)
    if path.suffix.lower() != ".docx":
        raise MasterError("Only .docx files are supported as a master resume (macro-enabled .docm is rejected).")
    if not path.is_file():
        raise MasterError(f"File not found: {path}")
    if path.stat().st_size > max_mb * 1024 * 1024:
        raise MasterError(f"File exceeds the {max_mb} MB limit.")
    if path.stat().st_size == 0:
        raise MasterError("File is empty.")
    try:
        with zipfile.ZipFile(path) as z:
            if z.testzip() is not None:
                raise MasterError("DOCX archive is corrupted.")
            names = z.namelist()
    except zipfile.BadZipFile as e:
        raise MasterError("File is not a valid DOCX (bad zip archive).") from e
    if "word/document.xml" not in names:
        raise MasterError("File is a zip archive but not a Word document (word/document.xml missing).")
    if any("vbaProject" in n for n in names):
        raise MasterError("Document contains macros (vbaProject); refusing to import.")


class MasterStore:
    def __init__(self, master_dir: Path, max_mb: int = 10):
        self.dir = Path(master_dir)
        self.max_mb = max_mb
        self.dir.mkdir(parents=True, exist_ok=True)

    # -- manifest -------------------------------------------------------
    def _read(self) -> dict:
        p = self.dir / MANIFEST
        if not p.exists():
            return {"active": None, "masters": []}
        return json.loads(p.read_text(encoding="utf-8"))

    def _write(self, data: dict) -> None:
        (self.dir / MANIFEST).write_text(json.dumps(data, indent=2), encoding="utf-8")

    def active(self) -> dict | None:
        m = self._read()
        return next((e for e in m["masters"] if e["id"] == m["active"]), None)

    # -- import ---------------------------------------------------------
    def import_master(self, src: Path, replace_active: bool = False) -> dict:
        """Copy src into the protected directory. Never overwrites an existing master file.
        If a master is already active, replace_active=True is required to switch;
        the previous master file is kept on disk."""
        src = Path(src)
        validate_docx(src, self.max_mb)
        data = self._read()
        if data["active"] and not replace_active:
            raise MasterError("A master resume is already active. Pass replace_active=True to switch "
                              "(the previous master stays on disk, untouched).")
        digest = sha256_file(src)
        for e in data["masters"]:
            if e["sha256"] == digest:
                data["active"] = e["id"]
                self._write(data)
                return e
        n = len(data["masters"]) + 1
        stored = f"master_v{n}_{src.name}"
        dest = self.dir / stored
        if dest.exists():
            raise MasterError(f"Refusing to overwrite existing file {dest.name}")
        shutil.copyfile(src, dest)
        if sha256_file(dest) != digest:
            dest.unlink()
            raise MasterError("Copy verification failed; import aborted.")
        os.chmod(dest, stat.S_IREAD)  # read-only attribute (Windows) / 0400 (POSIX)
        entry = {"id": f"v{n}", "file": stored, "original_name": src.name, "sha256": digest,
                 "size": dest.stat().st_size,
                 "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        data["masters"].append(entry)
        data["active"] = entry["id"]
        self._write(data)
        return entry

    # -- integrity ------------------------------------------------------
    def path_of(self, entry: dict) -> Path:
        return self.dir / entry["file"]

    def verify(self, entry: dict | None = None) -> Path:
        entry = entry or self.active()
        if entry is None:
            raise MasterError("No master resume has been imported.")
        p = self.path_of(entry)
        if not p.is_file():
            raise IntegrityError(f"Master file missing: {p.name}")
        actual = sha256_file(p)
        if actual != entry["sha256"]:
            raise IntegrityError("Master resume has changed since import (hash mismatch). "
                                 "Restore the original file or re-import deliberately.")
        return p

    def make_working_copy(self, session_dir: Path, name: str = "working_copy.docx") -> Path:
        """Verified byte-for-byte copy into a session folder (never into the master dir)."""
        src = self.verify()
        session_dir = Path(session_dir)
        if session_dir.resolve() == self.dir.resolve() or self.dir.resolve() in session_dir.resolve().parents:
            raise MasterError("Session output must not be inside the master directory.")
        session_dir.mkdir(parents=True, exist_ok=True)
        dest = session_dir / name
        if dest.exists():
            raise MasterError(f"{dest.name} already exists in the session folder; not overwriting.")
        shutil.copyfile(src, dest)
        os.chmod(dest, stat.S_IWRITE | stat.S_IREAD)
        return dest
