# Offline Resume Tailor

Local-only resume tailoring and ATS-compatibility estimator. No cloud AI, no telemetry, no network use after installation.

## Windows 11 setup (PowerShell, in the project folder)
1. Python 3.11 + LibreOffice (`winget install TheDocumentFoundation.LibreOffice`).
2. `py -3.11 -m venv .venv` then `.\.venv\Scripts\Activate.ps1`
3. While online, once: `python scripts/install_offline.py download`
4. Install (offline OK): `python scripts/install_offline.py install`
5. Verify: `python scripts/check_environment.py` then `python -m pytest`
6. Launch the app: `streamlit run src/resume_tailor/ui/app.py` (opens http://127.0.0.1:8501, local only)

## Using it
1. **Master Resume** page: import your .docx once. It is copied to `data/master/`, hashed and set read-only. A second import needs the explicit "replace" box; old files are kept.
2. **New Tailoring Session**: paste a JD (or import txt/docx/pdf), click *Analyze JD*, review the requirement table and proposed edits (approve / reject / edit text), then *Generate*.
3. Results appear in **ATS Report**, **Change Log**, **Export** and **History**. Each session gets its own folder in `output/` containing: tailored_resume.docx, tailored_resume.pdf (if LibreOffice is installed), ats_compatibility_report.html/json, change_report.md, jd_keyword_analysis.json, original_vs_tailored_diff.txt, session_metadata.json.

Command-line analysis only: `python scripts/analyze_jd.py --master resume.docx --jd jd.txt`

## What it will and will not do
- Edits are limited to: reordering your existing skills, reordering bullets within the same role/project, and review-required wording rules in `config/rewrite_rules.yaml`. It never adds a skill, number, employer, title or date. Edits are fact-checked by a grounding validator and the output is re-checked against the master (dates/titles/employers/contact/headings are locked).
- The professional summary is unchanged unless you enable the optional local LLM (`llm.enabled` + `llm.model` in `config/default.yaml`; Ollama on 127.0.0.1). The LLM path is implemented but NOT tested against a live model.
- The score is an internal estimate with documented weights in `config/scoring.yaml`. It is not a real ATS score and does not predict interviews.
- Tables, text boxes, hyperlink text and tab-aligned lines (role/date headers) are not edited; they are locked.
- Add your own wording rules in `config/rewrite_rules.yaml` (each fires only if the master already contains the `find` text).

## Troubleshooting
- `pyarrow requires NumPy 2.0`: re-run step 3 and 4 (requirements pin pyarrow==17.0.0).
- No PDF produced: install LibreOffice or set `pdf_export.soffice_path` in `config/default.yaml`; DOCX output is unaffected.
- PowerShell blocks activation: `Set-ExecutionPolicy -Scope Process Bypass`.
- Tests against your real resume: `$env:RESUME_TEST_MASTER="C:\path\resume.docx"; python -m pytest`
