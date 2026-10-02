"""Long-form degree strings must still match a short Workday option.

Regression: a profile saying "Bachelor of Science in Computer Science" filtered
a Degree list offering "Bachelor of Science (B.S.)" down to zero options,
because only terms[0] was ever typed into the filter box. Degree then landed in
`skipped` on every Workday application.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apply_engine.workday_widgets import (
    degree_fallback_terms,
    pick_option_substring,
    readback_committed,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "workday.html"

OPTIONS = ["Bachelor of Science (B.S.)", "B.S. Computer Science", "Master of Science"]


@pytest.mark.parametrize(
    "degree",
    [
        "Bachelor of Science in Computer Science",
        "B.S. Computer Science",
        "Bachelors of Science",
        "Bachelor of Arts",
    ],
)
def test_degree_variants_match_an_option(degree):
    picked = pick_option_substring(OPTIONS, degree_fallback_terms(degree))
    assert picked, f"{degree!r} matched no option"
    assert readback_committed(picked, degree_fallback_terms(degree))


def test_probe_order_prefers_full_term_then_fallbacks():
    terms = degree_fallback_terms("Bachelor of Science in Computer Science")
    assert terms[0] == "Bachelor of Science in Computer Science"
    assert "Bachelor" in terms  # the probe that actually filters to a hit
    assert "BA" not in terms


def test_long_form_degree_fills_on_fixture(tmp_path, monkeypatch):
    """End-to-end: the long-form degree commits on the Workday wizard fixture.

    The Degree control only exists once the wizard reaches Education, so this
    goes through fill_application rather than poking the bare fixture.
    """
    pytest.importorskip("playwright")

    from apply_engine.fill import fill_application
    from apply_engine.guard import CONFIRM_ENV
    from apply_engine.jd import fetch_job_from_text
    from apply_engine.pdf import render_pdf
    from apply_engine.pool import load_pool
    from apply_engine.profile import load_profile
    from apply_engine.tailor import tailor

    monkeypatch.delenv(CONFIRM_ENV, raising=False)
    monkeypatch.setenv("WORKDAY_DEFAULT_PASSWORD", "test-only-not-used-in-prod")

    profile = load_profile(ROOT / "examples" / "profile.json")
    # The shape that used to fail: long-form degree, short option list.
    profile.degree = "Bachelor of Science in Computer Science"

    pool = load_pool(ROOT / "examples" / "PROJECT_POOL.md")
    url = "https://acme.wd1.myworkdayjobs.com/en-US/careers/job/NYC/Intern_R1"
    job = fetch_job_from_text(url, "Software Engineering Intern", "acme", "React Native intern")
    tailored = tailor(profile, pool, job)
    pdf = render_pdf(tailored, tmp_path / "resume.pdf")

    try:
        artifact = fill_application(
            url=url,
            profile=profile,
            resume=tailored,
            resume_path=pdf,
            profile_path=str(ROOT / "examples" / "profile.json"),
            pool_path=str(ROOT / "examples" / "PROJECT_POOL.md"),
            queue_id="degree-longform",
            html=FIXTURE.read_text(encoding="utf-8"),
            submit=False,
            tenant_map_path=tmp_path / "workday-accounts.json",
            screenshot_path=tmp_path / "shot.png",
        )
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            pytest.skip(f"chromium not installed: {exc}")
        raise

    mapped = {r["mapped_to"]: r["value"] for r in artifact.filled if isinstance(r, dict)}
    degree = str(mapped.get("degree") or "")
    assert degree, f"degree was skipped: {artifact.skipped}"
    assert degree.strip().lower() != "select one"
    assert "bachelor" in degree.lower() or "b.s" in degree.lower()
    assert artifact.submit_clicked is False
