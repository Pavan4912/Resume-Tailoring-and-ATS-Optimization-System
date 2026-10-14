"""Explicit, two-step dependency setup. The app itself never downloads anything.

  python scripts/install_offline.py download   # needs internet; fills vendor/wheels
  python scripts/install_offline.py install    # works offline; installs from vendor/wheels

Run both steps with the same Python version/OS you will run the app on
(Python 3.11 on Windows 11), inside your virtual environment.
"""
from __future__ import annotations
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WHEELS = ROOT / "vendor" / "wheels"
MODEL = "en_core_web_sm-3.7.1-py3-none-any.whl"
MODEL_URL = f"https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/{MODEL}"


def run(cmd: list[str]) -> None:
    print(">", " ".join(cmd))
    subprocess.run(cmd, check=True)


def download() -> None:
    WHEELS.mkdir(parents=True, exist_ok=True)
    run([sys.executable, "-m", "pip", "download", "-r", str(ROOT / "requirements-dev.txt"),
         "-d", str(WHEELS)])
    target = WHEELS / MODEL
    if not target.exists():
        print(f"> downloading spaCy model: {MODEL_URL}")
        urllib.request.urlretrieve(MODEL_URL, target)
    print(f"\nDone. {len(list(WHEELS.glob('*')))} files in {WHEELS}. You can now go offline.")


def install() -> None:
    if not WHEELS.is_dir() or not any(WHEELS.iterdir()):
        sys.exit("vendor/wheels is empty. Run 'download' once while online first.")
    run([sys.executable, "-m", "pip", "install", "--no-index", "--find-links", str(WHEELS),
         "-r", str(ROOT / "requirements-dev.txt")])
    run([sys.executable, "-m", "pip", "install", "--no-index", "--find-links", str(WHEELS),
         str(WHEELS / MODEL)])
    run([sys.executable, "-m", "pip", "install", "--no-index", "--no-deps", "-e", str(ROOT)])
    print("\nInstalled. Next: python scripts/check_environment.py")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("download", "install"):
        sys.exit(__doc__)
    {"download": download, "install": install}[sys.argv[1]]()
