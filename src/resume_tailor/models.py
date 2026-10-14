"""Core data structures (Stage 3 subset). Later stages add JD / edit / score models."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class ParagraphInfo:
    index: int                 # index among body paragraphs
    style: str
    text: str
    kind: str                  # name|headline|contact|heading|summary|skill_line|role_header|project_header|credential|bullet|other
    section: str = ""          # normalised section key
    run_count: int = 0
    editable: bool = True      # False for locked / structurally unsafe paragraphs
    lock_reason: str = ""
    line: int = 0              # line within the paragraph (soft line breaks)


@dataclass
class ResumeBullet:
    para_index: int
    text: str
    parent_para_index: int     # role or project header this bullet belongs to
    parent_title: str


@dataclass
class ResumeSection:
    key: str                   # summary|skills|experience|projects|education|certifications|awards|other
    heading: str
    heading_index: int
    para_indices: list[int] = field(default_factory=list)


@dataclass
class ResumeEvidence:
    skill: str                 # canonical name
    listed_in_skills: bool = False
    in_summary: bool = False
    bullet_locations: list[int] = field(default_factory=list)   # paragraph indices
    header_locations: list[int] = field(default_factory=list)   # project tech lines
    @property
    def demonstrated(self) -> bool:
        return bool(self.bullet_locations or self.header_locations)


@dataclass
class FormattingSnapshot:
    paragraphs: dict[int, dict]      # index -> {style, ppr, runs:[rpr hashes]}
    sect_pr: str
    footers: dict[str, str]
    paragraph_count: int


@dataclass
class MasterResume:
    path: str
    sha256: str
    paragraphs: list[ParagraphInfo]
    sections: list[ResumeSection]
    bullets: list[ResumeBullet]
    evidence: dict[str, ResumeEvidence]
    contact: dict[str, str]
    experience: list[dict]           # title, employer, start, end, para_index
    education: list[dict]
    warnings: list[str] = field(default_factory=list)
    snapshot: FormattingSnapshot | None = None


@dataclass
class JDRequirement:
    term: str
    category: str                 # technical|tool|soft|qualification|experience
    importance: str               # mandatory|preferred|optional
    mentions: int
    source_line: str
    notes: list[str] = field(default_factory=list)


@dataclass
class RequirementMatch:
    requirement: JDRequirement
    status: str                   # supported|listed_only|needs_review|gap|unverified
    strength: str                 # direct|listed|related|none
    credit: float                 # 0..1 evidence multiplier (from scoring.yaml)
    evidence: list[dict] = field(default_factory=list)   # {para_index, kind, snippet}
    confidence: str = "low"       # high|medium|low
    note: str = ""


@dataclass
class Edit:
    para_index: int
    line: int
    old: str
    new: str


@dataclass
class ProposedEdit:
    id: str
    kind: str                     # skills_reorder | bullet_reorder | terminology | summary_llm
    section: str
    edits: list
    reason: str
    requirement: str
    evidence: str
    auto_accept: bool
    mode: str                     # reorder | rewrite
    allowed_words: list = field(default_factory=list)
    problems: list = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return bool(self.problems)


@dataclass
class ApprovedEdit:
    proposal_id: str
    edits: list
    decision: str                 # auto_accepted | user_approved | manual_edit


@dataclass
class ChangeRecord:
    section: str
    original: str
    revised: str
    reason: str
    requirement: str
    evidence: str
    review: str


@dataclass
class ATSScoreBreakdown:
    overall: float
    sub: dict
    metrics: dict
    warnings: list
    disclaimer: str


@dataclass
class TailoringSession:
    id: str
    created_at: str
    company: str
    title: str
    folder: str
    master_sha256: str
    score: float
    files: dict
    warnings: list
