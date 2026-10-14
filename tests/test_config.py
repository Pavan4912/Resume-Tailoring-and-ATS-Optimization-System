import pytest
from resume_tailor.config import load_settings, ConfigError


def test_default_config_loads():
    s = load_settings()
    assert sum(s.scoring["weights"].values()) == 100
    assert s.app["privacy"]["telemetry"] is False
    assert s.app["llm"]["enabled"] is False
    assert "Java" in s.taxonomy["skills"]


def test_bad_weights_rejected(tmp_path):
    import shutil
    from resume_tailor.config import PROJECT_ROOT
    shutil.copytree(PROJECT_ROOT / "config", tmp_path / "config")
    p = tmp_path / "config" / "scoring.yaml"
    p.write_text(p.read_text().replace("keyword_coverage: 35", "keyword_coverage: 50"))
    with pytest.raises(ConfigError):
        load_settings(tmp_path)
