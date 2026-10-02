"""apply attaches the candidate's own resume, not a generated one.

The generated PDF was thinner and more dated than the real resume (it listed a
single stale role where the real one has three), so `apply` sends
profile.resume_path. Tailoring still runs -- it grounds open-ended answers --
but its PDF is opt-in via --tailored-resume.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apply_engine.cli import _real_resume
from apply_engine.profile import load_profile

ROOT = Path(__file__).resolve().parents[1]


def _paths(profile_path: Path) -> dict:
    return {"profile": profile_path}


def test_absolute_resume_path_is_used(tmp_path):
    resume = tmp_path / "Real_Resume.pdf"
    resume.write_bytes(b"%PDF-1.4 real")
    prof = tmp_path / "profile.json"
    prof.write_text(json.dumps({
        "full_name": "A B", "first_name": "A", "last_name": "B",
        "email": "a@b.com", "resume_path": str(resume),
    }))
    profile = load_profile(prof)
    assert _real_resume(_paths(prof), profile) == resume


def test_deployment_path_falls_back_to_the_local_data_tree(tmp_path):
    """profile.resume_path points at /workspace/... on the grok box."""
    resume = tmp_path / "Real_Resume.pdf"
    resume.write_bytes(b"%PDF-1.4 real")
    prof = tmp_path / "profile.json"
    prof.write_text(json.dumps({
        "full_name": "A B", "first_name": "A", "last_name": "B",
        "email": "a@b.com",
        "resume_path": "/workspace/internship-apps/autofill/Real_Resume.pdf",
    }))
    profile = load_profile(prof)
    assert _real_resume(_paths(prof), profile) == resume


def test_missing_resume_returns_none_rather_than_a_generated_pdf(tmp_path):
    """Never silently substitute a previously generated resume."""
    (tmp_path / "some-tailored.pdf").write_bytes(b"%PDF-1.4 generated")
    prof = tmp_path / "profile.json"
    prof.write_text(json.dumps({
        "full_name": "A B", "first_name": "A", "last_name": "B",
        "email": "a@b.com",
        "resume_path": "/nowhere/Real_Resume.pdf",
    }))
    profile = load_profile(prof)
    assert _real_resume(_paths(prof), profile) is None


def test_unset_resume_path_returns_none(tmp_path):
    prof = tmp_path / "profile.json"
    prof.write_text(json.dumps({
        "full_name": "A B", "first_name": "A", "last_name": "B",
        "email": "a@b.com", "resume_path": "",
    }))
    assert _real_resume(_paths(prof), load_profile(prof)) is None


def test_generated_resume_carries_no_provenance_footer(tmp_path):
    """The PDF an employer opens must not name the company it was tailored for."""
    pytest.importorskip("fpdf")
    from apply_engine.jd import fetch_job_from_text
    from apply_engine.pdf import render_pdf
    from apply_engine.pool import load_pool
    from apply_engine.tailor import tailor

    profile = load_profile(ROOT / "examples" / "profile.json")
    pool = load_pool(ROOT / "examples" / "PROJECT_POOL.md")
    job = fetch_job_from_text("https://x.test/j/1", "SWE Intern", "Acme", "typescript react")
    out = render_pdf(tailor(profile, pool, job), tmp_path / "r.pdf")

    raw = out.read_bytes()
    assert b"nothing invented" not in raw
    assert b"Tailored for" not in raw


def test_drop_other_resumes_keeps_the_current_file():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from apply_engine.fill import _drop_other_resumes

    html = """
    <div id="old">walmart-summer-2027-intern-software-engineer-ii.pdf
      <button aria-label="Delete" onclick="this.parentElement.remove()">Delete</button>
    </div>
    <div id="keep">Jordan_Avery_Resume.pdf
      <button aria-label="Delete" onclick="this.parentElement.remove()">Delete</button>
    </div>
    """
    notes: list = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            removed = _drop_other_resumes(page, "/tmp/Jordan_Avery_Resume.pdf", notes)
            old_gone = page.locator("#old").count() == 0
            keep = page.locator("#keep").count() == 1
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert removed == 1
    assert old_gone and keep
