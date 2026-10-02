import os
from pathlib import Path

import pytest

from apply_engine.guard import (
    CONFIRM_ENV,
    SubmitBlockedError,
    assert_can_submit,
    confirm_enabled,
    is_apply_nav,
    is_submit_control,
)
from apply_engine.fields import map_field, profile_value
from apply_engine.profile import load_profile

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "examples" / "profile.json"
FIXTURE = ROOT / "tests" / "fixtures" / "greenhouse.html"
POOL = ROOT / "examples" / "PROJECT_POOL.md"


class FakeLocator:
    def __init__(self, meta: dict, clicks: list):
        self._meta = meta
        self._clicks = clicks

    def evaluate(self, _js: str):
        return self._meta

    def click(self):
        self._clicks.append(self._meta)


def test_submit_heuristics():
    assert is_submit_control(type_attr="submit", text="Apply")
    assert is_submit_control(text="Submit Application")
    assert is_submit_control(text="Send Application")
    assert not is_submit_control(type_attr="button", text="Apply")
    assert is_apply_nav("Apply for this job")
    assert not is_apply_nav("Submit Application")


def test_assert_can_submit_requires_env(monkeypatch):
    monkeypatch.delenv(CONFIRM_ENV, raising=False)
    assert confirm_enabled() is False
    with pytest.raises(SubmitBlockedError):
        assert_can_submit()
    monkeypatch.setenv(CONFIRM_ENV, "1")
    assert_can_submit()


def test_guarded_click_blocks_submit_without_flag(monkeypatch):
    from apply_engine.guard import guarded_click

    monkeypatch.delenv(CONFIRM_ENV, raising=False)
    clicks: list = []
    loc = FakeLocator({"type_attr": "submit", "text": "Submit Application", "aria": "", "name": "", "role": "button"}, clicks)
    with pytest.raises(SubmitBlockedError):
        guarded_click(loc, allow_submit=False)
    assert clicks == []


def test_guarded_click_allows_submit_only_with_confirm(monkeypatch):
    from apply_engine.guard import guarded_click

    monkeypatch.setenv(CONFIRM_ENV, "1")
    clicks: list = []
    loc = FakeLocator({"type_attr": "submit", "text": "Submit Application", "aria": "", "name": "", "role": "button"}, clicks)
    guarded_click(loc, allow_submit=True)
    assert len(clicks) == 1


def test_fill_defaults_submit_false():
    import inspect
    from apply_engine.fill import fill_application

    assert inspect.signature(fill_application).parameters["submit"].default is False


def test_gpa_not_invented_from_profile():
    profile = load_profile(PROFILE)
    assert profile_value(profile, "gpa") is None
    assert map_field("GPA") == "gpa"
    assert map_field("First Name") == "first_name"
    assert map_field("Email Address") == "email"


def test_playwright_fill_does_not_submit(tmp_path, monkeypatch):
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
        "https://job-boards.greenhouse.io/demo/jobs/1",
        "Software Engineering Intern",
        "demo",
        "React Native Expo Firebase maps TypeScript",
    )
    tailored = tailor(profile, pool, job)
    pdf = render_pdf(tailored, tmp_path / "resume.pdf")
    html = FIXTURE.read_text(encoding="utf-8")
    try:
        artifact = fill_application(
            url="https://job-boards.greenhouse.io/demo/jobs/1",
            profile=profile,
            resume=tailored,
            resume_path=pdf,
            profile_path=str(PROFILE),
            pool_path=str(POOL),
            queue_id="test-no-submit",
            html=html,
            submit=False,
            screenshot_path=tmp_path / "shot.png",
        )
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or "playwright" in str(exc).lower():
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert artifact.submit_clicked is False
    assert artifact.status == "waiting_confirm"
    mapped = {row["mapped_to"]: row["value"] for row in artifact.filled}
    assert mapped.get("first_name") == "Jordan"
    assert mapped.get("email") == "jordan.avery@example.com"
    assert mapped.get("work_authorized_us") == "Yes"
    assert mapped.get("need_sponsorship") == "No"
    assert "gpa" not in mapped
    assert any(s["reason"].startswith("gpa omitted") for s in artifact.skipped)


def test_playwright_confirm_does_submit(tmp_path, monkeypatch):
    pytest.importorskip("playwright")
    from apply_engine.fill import fill_application
    from apply_engine.jd import fetch_job_from_text
    from apply_engine.pool import load_pool
    from apply_engine.pdf import render_pdf
    from apply_engine.tailor import tailor

    monkeypatch.setenv(CONFIRM_ENV, "1")
    profile = load_profile(PROFILE)
    pool = load_pool(POOL)
    job = fetch_job_from_text(
        "https://job-boards.greenhouse.io/demo/jobs/1",
        "Intern",
        "demo",
        "React Native",
    )
    tailored = tailor(profile, pool, job)
    pdf = render_pdf(tailored, tmp_path / "resume.pdf")
    html = FIXTURE.read_text(encoding="utf-8")
    try:
        artifact = fill_application(
            url="https://job-boards.greenhouse.io/demo/jobs/1",
            profile=profile,
            resume=tailored,
            resume_path=pdf,
            profile_path=str(PROFILE),
            pool_path=str(POOL),
            queue_id="test-confirm",
            html=html,
            submit=True,
        )
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert artifact.submit_clicked is True
    assert artifact.status == "submitted"


def test_pre_submit_objection_leaves_form_unsubmitted(tmp_path, monkeypatch):
    pytest.importorskip("playwright")
    from apply_engine.fill import fill_application
    from apply_engine.jd import fetch_job_from_text
    from apply_engine.pdf import render_pdf
    from apply_engine.pool import load_pool
    from apply_engine.tailor import tailor

    monkeypatch.setenv(CONFIRM_ENV, "1")
    profile = load_profile(PROFILE)
    job = fetch_job_from_text("https://job-boards.greenhouse.io/demo/jobs/1", "Intern", "demo", "React Native")
    tailored = tailor(profile, load_pool(POOL), job)
    try:
        artifact = fill_application(
            url="https://job-boards.greenhouse.io/demo/jobs/1", profile=profile, resume=tailored,
            resume_path=render_pdf(tailored, tmp_path / "resume.pdf"), profile_path=str(PROFILE),
            pool_path=str(POOL), queue_id="test-objection", html=FIXTURE.read_text(encoding="utf-8"),
            submit=True, pre_submit=lambda fresh: ["answer changed: Work authorization"],
        )
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert artifact.submit_clicked is False
    assert artifact.status == "needs_user"
    assert any("confirm stopped before Submit" in n for n in artifact.notes)


def test_submit_true_without_env_raises_before_browser(monkeypatch):
    from apply_engine.fill import fill_application

    monkeypatch.delenv(CONFIRM_ENV, raising=False)
    profile = load_profile(PROFILE)
    with pytest.raises(SubmitBlockedError):
        fill_application(
            url="https://example.com",
            profile=profile,
            resume=None,
            resume_path=PROFILE,
            profile_path=str(PROFILE),
            pool_path=str(POOL),
            queue_id="x",
            submit=True,
        )
