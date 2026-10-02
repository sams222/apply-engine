from pathlib import Path

from apply_engine.pool import load_pool
from apply_engine.profile import load_profile
from apply_engine.tailor import assert_truthful, keyword_overlap_report, tailor
from apply_engine.jd import fetch_job_from_text

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "examples" / "profile.json"
POOL = ROOT / "examples" / "PROJECT_POOL.md"
FAKE_JD = (ROOT / "tests" / "fixtures" / "fake_jd.md").read_text(encoding="utf-8")


def _tailor(jd: str, title: str = "Software Engineering Intern"):
    profile = load_profile(PROFILE)
    pool = load_pool(POOL)
    job = fetch_job_from_text("https://job-boards.greenhouse.io/demo/jobs/1", title, "demo", jd)
    result = tailor(profile, pool, job)
    assert_truthful(result, pool)
    return result, pool


def test_react_native_jd_ranks_city_pulse_first():
    result, _ = _tailor(FAKE_JD)
    assert result.projects[0].title == "MetroMap"
    assert "react native" in result.matched_keywords or "expo" in result.matched_keywords


def test_mediapipe_jd_ranks_cragline_first():
    jd = "Climbing coach internship. Python, MediaPipe, CNN, computer vision."
    result, _ = _tailor(jd)
    assert result.projects[0].title == "Cragline"


def test_multi_agent_jd_ranks_relay_first():
    jd = "Need TypeScript/Node multi-agent orchestration experience."
    result, _ = _tailor(jd)
    assert result.projects[0].title == "Relay"


def test_never_invents_projects_or_kubernetes():
    result, pool = _tailor(FAKE_JD)
    titles = {e.title for e in result.all_entries()}
    allowed = {e.title for e in pool}
    assert titles <= allowed
    assert "Secret Project X" not in titles
    skills_l = {s.lower() for s in result.skills}
    assert "kubernetes" not in skills_l
    assert "aws" not in skills_l
    assert "google cloud" not in skills_l


def test_gpa_stays_absent_when_profile_omits_it():
    profile = load_profile(PROFILE)
    assert profile.gpa is None
    result, _ = _tailor(FAKE_JD)
    assert result.profile.gpa is None


def test_keyword_overlap_report_orders_city_pulse_highest_on_mobile_jd():
    pool = load_pool(POOL)
    scores = keyword_overlap_report(pool, FAKE_JD)
    assert scores["MetroMap"] > scores["Cragline"]
    assert scores["MetroMap"] >= scores["Relay"]
