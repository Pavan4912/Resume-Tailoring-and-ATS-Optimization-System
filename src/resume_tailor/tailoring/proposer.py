"""Rule-based, evidence-grounded proposals. Nothing here can add a skill the master does not contain."""
from __future__ import annotations
import re
from collections import defaultdict
from ..config import Settings
from ..jd.extractor import load_lexicon
from ..models import Edit, MasterResume, ProposedEdit, RequirementMatch
from ..parsing.resume_structure import alias_pattern

IMP = {"mandatory": 3, "preferred": 2, "optional": 1}


def _score(text, ev, pats) -> int:
    return sum(IMP[m.requirement.importance] for m in ev if any(p.search(text) for p in pats.get(m.requirement.term, [])))


def propose(master: MasterResume, matches: list[RequirementMatch], settings: Settings) -> list[ProposedEdit]:
    lex = load_lexicon(settings)
    pats = {t: [alias_pattern(a.lower()) for a in s["aliases"]] for t, s in lex.items()}
    ev = [m for m in matches if m.strength in ("direct", "synonym", "listed") and m.requirement.category != "soft"]
    out: list[ProposedEdit] = []
    para = {(p.index, p.line): p for p in master.paragraphs}
    # 1) skills lines: most JD-relevant existing items first
    for p in master.paragraphs:
        if p.kind != "skill_line" or not p.editable or ":" not in p.text:
            continue
        label, body = p.text.split(":", 1)
        body = body.strip()
        items = re.split(r",\s*(?![^()]*\))", body)
        if len(items) < 2 or f"{label}: {', '.join(items)}" != p.text:
            continue
        order = sorted(range(len(items)), key=lambda i: (-_score(items[i], ev, pats), i))
        new_items = [items[i] for i in order]
        if new_items != items:
            top = [i for i in new_items if _score(i, ev, pats) > 0][:3]
            out.append(ProposedEdit(
                id=f"skills-{p.index}-{p.line}", kind="skills_reorder", section="Technical Skills",
                edits=[Edit(p.index, p.line, p.text, f"{label}: {', '.join(new_items)}")],
                reason="Existing skills reordered so the ones the JD asks for come first. No skill added or removed.",
                requirement=", ".join(top) or "-", evidence=f"All items already listed in the '{label}' line.",
                auto_accept=True, mode="reorder"))
    # 2) bullets: most relevant first within the same role/project
    groups = defaultdict(list)
    for b in master.bullets:
        if para[(b.para_index, 0)].editable:
            groups[b.parent_para_index].append(b)
    for parent, bl in groups.items():
        if len(bl) < 2:
            continue
        sc = [_score(b.text, ev, pats) for b in bl]
        order = sorted(range(len(bl)), key=lambda i: (-sc[i], i))
        if order == list(range(len(bl))):
            continue
        edits = []
        for pos, src in enumerate(order):
            if bl[pos].text != bl[src].text:
                edits.append(Edit(bl[pos].para_index, 0, bl[pos].text, bl[src].text))
        if edits:
            out.append(ProposedEdit(
                id=f"bullets-{parent}", kind="bullet_reorder", section=f"Experience/Projects: {bl[0].parent_title}",
                edits=edits, reason="Bullets reordered (wording untouched) so the most JD-relevant achievements lead.",
                requirement="relevance ordering", evidence="Same bullets, same facts, new order.",
                auto_accept=True, mode="reorder"))
    # 3) review-required terminology rules (config/rewrite_rules.yaml)
    present = {m.requirement.term for m in matches}
    for n, rule in enumerate(settings.rules.get("rules", [])):
        if rule["trigger"] not in present:
            continue
        for p in master.paragraphs:
            if p.editable and p.kind in ("bullet", "summary") and rule["find"] in p.text:
                out.append(ProposedEdit(
                    id=f"rule-{n}-{p.index}", kind="terminology", section=p.kind.title(),
                    edits=[Edit(p.index, p.line, p.text, p.text.replace(rule["find"], rule["replace"], 1))],
                    reason=rule["reason"], requirement=rule["trigger"],
                    evidence=f"Master text: '{rule['find']}'", auto_accept=False, mode="rewrite",
                    allowed_words=rule.get("allowed_words", [])))
    return out
