"""Configuration loading and validation. No network access."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(ValueError):
    pass


def _load(path: Path) -> dict:
    if not path.is_file():
        raise ConfigError(f"Missing config file: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ConfigError(f"Config file is empty or malformed: {path}")
    return data


@dataclass(frozen=True)
class Settings:
    app: dict
    scoring: dict
    taxonomy: dict
    lexicon: dict
    rules: dict
    root: Path

    def path(self, key: str) -> Path:
        p = Path(self.app["paths"][key])
        return p if p.is_absolute() else self.root / p


def load_settings(root: Path | None = None) -> Settings:
    root = Path(root) if root else PROJECT_ROOT
    cfg = root / "config"
    app = _load(cfg / "default.yaml")
    scoring = _load(cfg / "scoring.yaml")
    taxonomy = _load(cfg / "skills_taxonomy.yaml")
    lexicon = _load(cfg / "jd_lexicon.yaml")
    rp = cfg / "rewrite_rules.yaml"
    rules = _load(rp) if rp.exists() else {"rules": []}
    total = sum(scoring.get("weights", {}).values())
    if total != 100:
        raise ConfigError(f"Scoring weights must sum to 100, got {total}")
    return Settings(app=app, scoring=scoring, taxonomy=taxonomy, lexicon=lexicon, rules=rules, root=root)
