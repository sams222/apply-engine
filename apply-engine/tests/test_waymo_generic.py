"""Waymo careers.withwaymo.com (generic/Greenhouse-embed) question mapping + noise ignore."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apply_engine.detect import detect_ats
from apply_engine.fields import (
    HOW_HEARD_PRIMARY,
    is_noise_field,
    map_field,
    pick_select_option,
    profile_value,
    select_readback_matches,
    value_candidates,
)
from apply_engine.profile import load_profile

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "waymo-generic.html"
POOL = ROOT / "examples" / "PROJECT_POOL.md"
def _real_profile() -> Path:
    """The real profile, wherever the data tree lives on this box.

    Deployment keeps it under /workspace/internship-apps; a checkout keeps
    internship-apps as a sibling of the package. These tests need the real
    values (NY / 10001 / sponsorship=no), not the @example.com sample, so they
    skip rather than pass vacuously when no data tree is present.
    """
    candidates = [
        ROOT.parent / "internship-apps" / "autofill" / "profile.json",
        Path("/workspace/internship-apps/autofill/profile.json"),
    ]
    for cand in candidates:
        if cand.exists():
            return cand
    pytest.skip("no internship-apps data tree on this box", allow_module_level=True)


REAL_PROFILE = _real_profile()


def test_detect_waymo_gh_jid_as_greenhouse():
    assert detect_ats("https://careers.withwaymo.com/jobs?gh_jid=8193731") == "greenhouse"
    assert detect_ats("https://careers.withwaymo.com/jobs", html='gh_jid=1 form_submission job_questions greenhouse') == "greenhouse"


def test_noise_fields_ignored():
    assert is_noise_field("Opacity", element_id="vjs_select_540")
    assert is_noise_field("Color", element_id="vjs_select_535")
    assert is_noise_field("Font Size")
    assert is_noise_field("Locations")
    assert is_noise_field("Departments")
    assert map_field("Opacity", element_id="vjs_select_540") is None
    assert map_field("Locations") is None


def test_waymo_question_mapping_from_profile():
    profile = load_profile(REAL_PROFILE)
    assert map_field("Do you require work authorization? (required)") == "need_sponsorship"
    assert profile_value(profile, "need_sponsorship") == "No"
    assert map_field(
        "If yes, what kind? (If you do not require work authorization sponsorship please select Not Applicable.) (required)"
    ) == "sponsorship_type"
    assert profile_value(profile, "sponsorship_type") == "Not applicable"
    assert map_field("How did you hear about this opportunity?") == "how_heard"
    # We reach every posting through the company's own careers page, so that is
    # the answer regardless of what the profile carries.
    assert profile_value(profile, "how_heard") == HOW_HEARD_PRIMARY
    assert map_field("Would you require an export license under the circumstances described below? (required)") == "export_license"
    assert profile_value(profile, "export_license") == "No"
    assert "Never" in (profile_value(profile, "previous_employee") or "")
    assert map_field(
        "Please review and acknowledge our Candidate Privacy Policy linked below: (required)"
    ) == "policy_ack"
    ai = (
        "To ensure a fair and accurate assessment of each candidate's unique capabilities, Waymo prohibits "
        "the use of unauthorized outside assistance during the interview process. This includes, but is not "
        "limited to, artificial intelligence (AI) tools, generative software, or third-party resources, unless "
        "explicitly authorized by the hiring team. By submitting this application, you acknowledge and agree "
        "to adhere to these guidelines. (required)"
    )
    assert map_field(ai) == "policy_ack"
    assert profile_value(profile, "policy_ack") == "I acknowledge"
    assert map_field("Please provide the state/region in which you currently reside. (required)") == "state"
    assert pick_select_option(["", "New York", "Illinois"], "NY") == "New York"
    assert select_readback_matches("New York", "NY", key="state")
    assert select_readback_matches(
        "Social Media (Facebook, Twitter, etc.)", "Facebook", key="how_heard"
    )
    assert "Social Media" in value_candidates("how_heard", "Facebook", profile)
    # Classic authorized-to-work must NOT flip to sponsorship.
    assert map_field("Are you authorized to work in the United States?") == "work_authorized_us"
    assert map_field("Will you now or in the future require visa sponsorship?") == "need_sponsorship"
    assert map_field(
        "Are you legally authorized to work in the US now and in the future "
        "for any employer without visa sponsorship?"
    ) == "work_authorized_without_sponsorship"
    assert map_field(
        "Will you require employer support to obtain or maintain authorization "
        "to work in that country? e.g. (work permit)"
    ) == "need_sponsorship"


def test_waymo_fixture_fill_sticks(tmp_path, monkeypatch):
    pytest.importorskip("playwright")
    from apply_engine.fill import fill_application
    from apply_engine.guard import CONFIRM_ENV
    from apply_engine.jd import fetch_job_from_text
    from apply_engine.pdf import render_pdf
    from apply_engine.pool import load_pool
    from apply_engine.tailor import tailor

    monkeypatch.delenv(CONFIRM_ENV, raising=False)
    profile = load_profile(REAL_PROFILE)
    pool = load_pool(POOL)
    job = fetch_job_from_text(
        "https://careers.withwaymo.com/jobs?gh_jid=8193731",
        "Software Engineering Intern",
        "Waymo",
        "Python C++ ML perception planning",
    )
    tailored = tailor(profile, pool, job)
    pdf = render_pdf(tailored, tmp_path / "resume.pdf")
    html = FIXTURE.read_text(encoding="utf-8")
    try:
        artifact = fill_application(
            url="https://careers.withwaymo.com/jobs?gh_jid=8193731",
            profile=profile,
            resume=tailored,
            resume_path=pdf,
            profile_path=str(REAL_PROFILE),
            pool_path=str(POOL),
            queue_id="test-waymo-generic",
            html=html,
            submit=False,
            screenshot_path=tmp_path / "shot.png",
        )
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or "playwright" in str(exc).lower():
            pytest.skip(f"chromium not installed: {exc}")
        raise

    assert artifact.submit_clicked is False
    mapped = {row["mapped_to"]: row["value"] for row in artifact.filled}
    skipped_labels = [str(s.get("label") or s) for s in artifact.skipped]

    # Noise must not appear as blockers.
    for noise in ("Color", "Opacity", "Font Size", "Text Edge Style", "Font Family", "Locations", "Departments"):
        assert noise not in skipped_labels, skipped_labels

    assert mapped.get("need_sponsorship") == "No"
    assert "not applicable" in str(mapped.get("sponsorship_type") or "").lower()
    # Fixture has no Company Website option, so Other is the honest careers-page fallback.
    how = str(mapped.get("how_heard") or "").lower()
    assert "other" in how or "company website" in how or "career" in how, mapped.get("how_heard")
    assert mapped.get("export_license") == "No"
    assert "never" in str(mapped.get("previous_employee") or "").lower()
    assert "acknowledge" in str(mapped.get("policy_ack") or "").lower()
    assert "new york" in str(mapped.get("state") or "").lower()
    # Location job-alert must not steal New York, NY into an empty readback skip.
    loc_skips = [s for s in artifact.skipped if str(s.get("label") or "").lower() == "location"]
    assert not loc_skips, loc_skips


def test_prefilled_ethnicity_is_not_mistaken_for_sponsorship():
    from apply_engine.fields import map_field

    assert map_field("Please select your ethnicity. Not Applicable (United States of America)") == "race_ethnicity"
    assert map_field("What kind of work authorization sponsorship do you need? Not applicable") == "sponsorship_type"
