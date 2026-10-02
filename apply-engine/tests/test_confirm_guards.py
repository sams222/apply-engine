import json
from pathlib import Path

import pytest

from apply_engine.cli import _assert_confirmable, _assert_safe_profile


def test_refuse_examples_profile(tmp_path: Path):
    examples = tmp_path / "examples"
    examples.mkdir()
    p = examples / "profile.json"
    p.write_text(json.dumps({"email": "jordan.avery@example.com", "phone": "+1-555-0100"}))
    with pytest.raises(SystemExit, match="demo profile|placeholder"):
        _assert_safe_profile(p)


def test_accept_real_profile(tmp_path: Path):
    p = tmp_path / "autofill" / "profile.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({
        "email": "jordan.avery@example.org",
        "phone": "(212) 555-0147",
        "linkedin": "https://linkedin.com/in/jordan-avery",
        "github": "https://github.com/javery-dev",
    }))
    assert _assert_safe_profile(p) == p.resolve()


def test_refuse_skipped_name():
    with pytest.raises(SystemExit, match="Name"):
        _assert_confirmable({"skipped": [{"label": "Name", "reason": "unmapped"}]})


def test_refuse_required_star_fields():
    with pytest.raises(SystemExit, match="Citizenship"):
        _assert_confirmable({"skipped": [{"label": "Citizenship Status*", "reason": "unmapped"}]})


def test_allow_decorative_waymo_noise_skips():
    _assert_confirmable(
        {
            "skipped": [
                {"label": "Color", "reason": "unmapped"},
                {"label": "Opacity*", "reason": "unmapped"},
                {"label": "Font Size", "reason": "unmapped"},
                {"label": "Text Edge Style", "reason": "unmapped"},
                {"label": "Font Family", "reason": "unmapped"},
            ]
        }
    )
