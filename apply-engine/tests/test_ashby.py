"""Ashby entry, Name→full_name, submit control (SPA / disabled→enabled), job-missing."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from apply_engine.cli import _assert_confirmable
from apply_engine.fields import map_field, profile_value
from apply_engine.guard import CONFIRM_ENV, SubmitBlockedError, is_submit_control
from apply_engine.profile import load_profile

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "examples" / "profile.json"
ASHBY_APP = ROOT / "tests" / "fixtures" / "ashby-application.html"
ASHBY_404 = ROOT / "tests" / "fixtures" / "ashby-job-missing.html"
POOL = ROOT / "examples" / "PROJECT_POOL.md"


def test_map_ashby_name_variants():
    assert map_field("Name") == "full_name"
    assert map_field("First and Last Name") == "full_name"
    assert map_field("First & Last Name") == "full_name"
    assert map_field("Name", "_systemfield_name") == "full_name"
    assert map_field("", "_systemfield_name") == "full_name"
    assert map_field("First Name") == "first_name"  # must not steal


def test_confirm_ignores_grecaptcha_and_deadline_name_s():
    _assert_confirmable({"skipped": [{"label": "g-recaptcha-response", "reason": "unmapped"}]})
    _assert_confirmable(
        {
            "skipped": [
                {
                    "label": (
                        "If you have a deadline from another company, please let us know "
                        "1) the company name(s) and 2) the date(s)."
                    ),
                    "reason": "unmapped",
                }
            ]
        }
    )


def test_submit_heuristics_ashby_button():
    assert is_submit_control(text="Submit Application")
    assert is_submit_control(type_attr="button", text="Submit Application")


def test_ashby_job_missing_helper():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright
    from apply_engine.fill import _ashby_job_missing, _enter_ashby_application

    html = ASHBY_404.read_text()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html, wait_until="domcontentloaded")
        assert _ashby_job_missing(page) is True
        notes: list[str] = []
        assert _enter_ashby_application(page, notes) is False
        assert any("job not found" in n.lower() for n in notes)
        assert any("needs_user" in n for n in notes)
        browser.close()


def test_ashby_enter_and_submit_control(tmp_path, monkeypatch):
    pytest.importorskip("playwright")
    from apply_engine.fill import (
        _click_submit,
        _enter_ashby_application,
        _iter_submit_candidates,
        fill_application,
    )
    from apply_engine.jd import fetch_job_from_text
    from apply_engine.pool import load_pool
    from apply_engine.pdf import render_pdf
    from apply_engine.tailor import tailor

    monkeypatch.delenv(CONFIRM_ENV, raising=False)
    profile = load_profile(PROFILE)
    assert profile_value(profile, "full_name")

    html = ASHBY_APP.read_text()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html, wait_until="domcontentloaded")
        notes: list[str] = []
        assert _enter_ashby_application(page, notes) is True
        assert page.locator("#_systemfield_name").count() == 1
        # Submit exists but disabled until name filled
        page.locator("#_systemfield_name").fill(profile.full_name or "Jordan Avery")
        page.wait_for_timeout(100)
        monkeypatch.setenv(CONFIRM_ENV, "1")
        assert _click_submit(page) is True
        assert page.evaluate("() => window.__submitted === true")
        browser.close()


def test_ashby_fill_maps_name_and_resume(tmp_path, monkeypatch):
    pytest.importorskip("playwright")
    from apply_engine.fill import fill_application
    from apply_engine.jd import fetch_job_from_text
    from apply_engine.pool import load_pool
    from apply_engine.pdf import render_pdf
    from apply_engine.tailor import tailor

    monkeypatch.delenv(CONFIRM_ENV, raising=False)
    profile = load_profile(PROFILE)
    pool = load_pool(POOL)
    job = fetch_job_from_text(
        "https://jobs.ashbyhq.com/decagon/16529089-a048-4bc3-8456-3f197135e00b",
        "Engineering Intern",
        "decagon",
        "Build agents.",
    )
    tailored = tailor(profile, pool, job)
    pdf = render_pdf(tailored, tmp_path / "resume.pdf")

    html = ASHBY_APP.read_text()
    artifact = fill_application(
        url="https://jobs.ashbyhq.com/decagon/16529089-a048-4bc3-8456-3f197135e00b",
        profile=profile,
        resume=tailored,
        resume_path=pdf,
        profile_path=str(PROFILE),
        pool_path=str(POOL),
        queue_id="test-ashby-decagon",
        html=html,
        submit=False,
    )
    mapped = {row.get("mapped_to") for row in artifact.filled}
    assert "resume" in mapped
    assert "full_name" in mapped or any(
        (row.get("label") or "").lower().startswith("first and last") for row in artifact.filled
    )
    assert artifact.submit_clicked is False
    assert not any("job not found" in (n or "").lower() for n in artifact.notes)


def test_ashby_fill_job_missing_needs_user(tmp_path, monkeypatch):
    pytest.importorskip("playwright")
    from apply_engine.fill import fill_application
    from apply_engine.jd import fetch_job_from_text
    from apply_engine.pool import load_pool
    from apply_engine.pdf import render_pdf
    from apply_engine.tailor import tailor

    monkeypatch.delenv(CONFIRM_ENV, raising=False)
    profile = load_profile(PROFILE)
    pool = load_pool(POOL)
    job = fetch_job_from_text(
        "https://jobs.ashbyhq.com/persona/eb77c97c-fa9d-4bf0-9566-e5ba4453b7d3",
        "Software Engineer Intern",
        "persona",
        "Identity.",
    )
    tailored = tailor(profile, pool, job)
    pdf = render_pdf(tailored, tmp_path / "resume.pdf")

    artifact = fill_application(
        url="https://jobs.ashbyhq.com/persona/eb77c97c-fa9d-4bf0-9566-e5ba4453b7d3",
        profile=profile,
        resume=tailored,
        resume_path=pdf,
        profile_path=str(PROFILE),
        pool_path=str(POOL),
        queue_id="test-ashby-persona-404",
        html=ASHBY_404.read_text(),
        submit=False,
    )
    assert artifact.filled == []
    assert artifact.status == "needs_user"
    assert any("job not found" in (n or "").lower() for n in artifact.notes)
