"""Analyse a JD against a master resume (read-only). Usage:
   python scripts/analyze_jd.py --master path\\to\\resume.docx --jd path\\to\\jd.txt [--out outdir]"""
from __future__ import annotations
import argparse, json, sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from resume_tailor.config import load_settings
from resume_tailor.jd.extractor import extract_requirements
from resume_tailor.matching.matcher import match_requirements, coverage
from resume_tailor.parsing.resume_structure import parse_master

ORDER = {"mandatory": 0, "preferred": 1, "optional": 2}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", required=True); ap.add_argument("--jd", required=True); ap.add_argument("--out")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    s = load_settings()
    master = parse_master(Path(a.master), s)
    reqs, candidates, warns = extract_requirements(Path(a.jd).read_text(encoding="utf-8", errors="replace"), s)
    matches = sorted(match_requirements(reqs, master, s), key=lambda m: (ORDER[m.requirement.importance], m.status))
    for w in warns: print("WARNING:", w)
    print(f"{'IMPORTANCE':<10} {'REQUIREMENT':<34} {'STATUS':<12} {'EVIDENCE':<8} NOTE")
    for m in matches:
        print(f"{m.requirement.importance:<10} {m.requirement.term[:33]:<34} {m.status:<12} {m.strength:<8} {m.note[:60]}")
    cov = coverage(matches)
    print("\nPreliminary keyword coverage (NOT the ATS score):")
    for k, v in cov.items():
        print(f"  {k}: {v['count']} requirements, evidenced {v['evidenced_pct']}%, incl. related {v['including_related_pct']}%")
    if candidates:
        print("\nPhrases the lexicon did not recognise (review manually):", "; ".join(candidates))
    if a.out:
        out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
        (out / "jd_keyword_analysis.json").write_text(json.dumps(
            {"warnings": warns, "unclassified_phrases": candidates, "coverage": cov,
             "matches": [asdict(m) for m in matches]}, indent=2, ensure_ascii=False), encoding="utf-8")
        print("\nWrote", out / "jd_keyword_analysis.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
