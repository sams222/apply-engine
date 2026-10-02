"""Greenhouse LinkedIn/GitHub URL stickiness vs how-heard checkbox bleed + Discipline*."""

from __future__ import annotations

from pathlib import Path

import pytest

from apply_engine.fields import (
    FIELD_ALIASES,
    is_url_capable_control,
    is_url_profile_key,
    looks_like_phone_or_id_bleed,
    map_field,
    profile_value,
    url_readback_matches,
)
from apply_engine.guard import CONFIRM_ENV
from apply_engine.profile import load_profile

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "examples" / "profile.json"
FIXTURE = ROOT / "tests" / "fixtures" / "greenhouse-url-bleed.html"
POOL = ROOT / "examples" / "PROJECT_POOL.md"


def test_map_discipline_to_field_of_study():
    assert map_field("Discipline*") == "field_of_study"
    assert map_field("Discipline") == "field_of_study"
    assert map_field("Area of Study") == "field_of_study"
    profile = load_profile(PROFILE)
    assert profile_value(profile, "field_of_study") == "Computer Science"


def test_url_readback_rejects_option_id_bleed():
    intended_li = "https://linkedin.com/in/jordan-avery"
    intended_gh = "https://github.com/javery-dev"
    assert looks_like_phone_or_id_bleed("44718334008")
    assert looks_like_phone_or_id_bleed("44718332008")
    assert not url_readback_matches("44718334008", intended_li)
    assert not url_readback_matches("44718332008", intended_gh)
    assert url_readback_matches(intended_li, intended_li)
    assert url_readback_matches("https://www.linkedin.com/in/jordan-avery", intended_li)
    assert is_url_profile_key("linkedin") and is_url_profile_key("github")
    assert not is_url_capable_control("input", "checkbox")
    assert is_url_capable_control("input", "text")
    assert is_url_capable_control("input", "url")


def test_find_by_aliases_prefers_url_input_over_checkbox():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from apply_engine.fill import _find_by_aliases

    li_aliases = next(a for k, a in FIELD_ALIASES if k == "linkedin")
    gh_aliases = next(a for k, a in FIELD_ALIASES if k == "github")
    html = FIXTURE.read_text(encoding="utf-8")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html, wait_until="domcontentloaded")
        li = _find_by_aliases(page, li_aliases, key="linkedin")
        gh = _find_by_aliases(page, gh_aliases, key="github")
        assert li is not None and gh is not None
        assert li.evaluate("el => el.id") == "linkedin"
        assert gh.evaluate("el => el.id") == "github"
        assert li.evaluate("el => el.type") == "text"
        assert gh.evaluate("el => el.type") == "url"
        # Must not resolve to how-heard checkboxes.
        assert li.evaluate("el => el.type") != "checkbox"
        browser.close()


def test_fill_clears_stale_digits_and_skips_how_heard(tmp_path, monkeypatch):
    pytest.importorskip("playwright")
    from apply_engine.fill import _fill_standard_fields, fill_application
    from apply_engine.jd import fetch_job_from_text
    from apply_engine.pdf import render_pdf
    from apply_engine.pool import load_pool
    from apply_engine.tailor import tailor

    monkeypatch.delenv(CONFIRM_ENV, raising=False)
    profile = load_profile(PROFILE)
    profile.linkedin = "https://linkedin.com/in/jordan-avery"
    profile.github = "https://github.com/javery-dev"
    profile.field_of_study = "Computer Science"

    pool = load_pool(POOL)
    job = fetch_job_from_text(
        "https://job-boards.greenhouse.io/fiveringsllc/jobs/5420708008",
        "Trading Operations Engineer Intern",
        "Five Rings LLC",
        "Software engineering internship.",
    )
    tailored = tailor(profile, pool, job)
    pdf = render_pdf(tailored, tmp_path / "resume.pdf")
    html = FIXTURE.read_text(encoding="utf-8")

    try:
        artifact = fill_application(
            url="https://job-boards.greenhouse.io/fiveringsllc/jobs/5420708008",
            profile=profile,
            resume=tailored,
            resume_path=pdf,
            profile_path=str(PROFILE),
            pool_path=str(POOL),
            queue_id="test-fiverings-url-bleed",
            html=html,
            submit=False,
            screenshot_path=tmp_path / "shot.png",
        )
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or "playwright" in str(exc).lower():
            pytest.skip(f"chromium not installed: {exc}")
        raise

    mapped = {row["mapped_to"]: row["value"] for row in artifact.filled}
    assert "linkedin" in mapped, artifact.skipped
    assert "github" in mapped, artifact.skipped
    assert "field_of_study" in mapped, artifact.skipped
    assert "linkedin.com/in/jordan-avery" in (mapped["linkedin"] or "").lower()
    assert "github.com/javery-dev" in (mapped["github"] or "").lower()
    assert "computer science" in (mapped["field_of_study"] or "").lower()

    for row in artifact.skipped:
        label = (row.get("label") or "").lower()
        readback = str(row.get("readback") or "")
        if "linkedin" in label or "github" in label:
            assert not looks_like_phone_or_id_bleed(readback), row

    # Direct DOM pass: clear+fill stickiness and checkbox non-touch.
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html, wait_until="domcontentloaded")
        filled: list = []
        skipped: list = []
        notes: list = []
        _fill_standard_fields(
            page,
            profile=profile,
            resume=tailored,
            resume_path=str(pdf),
            filled=filled,
            skipped=skipped,
            notes=notes,
        )
        assert "jordan-avery" in page.input_value("#linkedin")
        assert "javery-dev" in page.input_value("#github")
        assert page.input_value("#discipline") == "Computer Science"
        assert page.is_checked("#hear_linkedin") is False
        assert page.is_checked("#hear_github") is False
        assert page.input_value("#decoy-linkedin") == "44718334008"
        browser.close()
