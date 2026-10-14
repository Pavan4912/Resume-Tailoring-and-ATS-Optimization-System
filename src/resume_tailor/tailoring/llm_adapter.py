"""Optional LOCAL LLM summary proposal (Ollama on 127.0.0.1). Off by default. Not tested against a live model."""
from __future__ import annotations
import json
import urllib.request
from ..config import Settings
from ..models import Edit, MasterResume, ProposedEdit, RequirementMatch


def propose_summary(master: MasterResume, matches: list[RequirementMatch], settings: Settings):
    cfg = settings.app["llm"]
    if not cfg.get("enabled") or not cfg.get("model"):
        return None, None
    host = cfg["host"]
    if not host.startswith(("http://127.0.0.1", "http://localhost")):
        return None, "LLM host must be local (127.0.0.1/localhost); LLM step skipped."
    summ = next((p for p in master.paragraphs if p.kind == "summary" and p.editable), None)
    if summ is None:
        return None, None
    terms = [m.requirement.term for m in matches if m.strength in ("direct", "synonym")]
    prompt = ("Rewrite this resume summary in 2-3 sentences. Use ONLY facts already in it. Do not add skills, "
              "numbers or years. You may emphasise these supported topics: " + ", ".join(terms) +
              ".\n\nSUMMARY:\n" + summ.text + "\n\nReturn only the rewritten summary.")
    try:
        req = urllib.request.Request(host.rstrip("/") + "/api/generate", method="POST",
                                     data=json.dumps({"model": cfg["model"], "prompt": prompt, "stream": False}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            text = json.loads(r.read())["response"].strip().replace("\n", " ")
    except Exception as e:  # noqa: BLE001
        return None, f"Local LLM unavailable ({e}); rule-based mode used."
    return ProposedEdit(id=f"summary-{summ.index}", kind="summary_llm", section="Professional Summary",
                        edits=[Edit(summ.index, summ.line, summ.text, text)],
                        reason="Local-LLM rewrite of the summary (review carefully).", requirement="summary alignment",
                        evidence="Generated only from the master's own summary.", auto_accept=False, mode="rewrite"), None
