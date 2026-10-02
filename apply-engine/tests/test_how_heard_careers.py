"""How Did You Hear About Us? is always the company's own careers page.

The hunter hands us a careers-page / board URL, so that is the truthful answer.
Tenants spell the option differently ("Company Website", "Careers Page",
"Walmart Careers", "Corporate Website"), so match the shape.
"""

from __future__ import annotations

import pytest

from apply_engine.fields import (
    HOW_HEARD_PRIMARY,
    pick_select_option,
    profile_value,
    value_candidates,
)
from apply_engine.profile import load_profile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _candidates():
    profile = load_profile(ROOT / "examples" / "profile.json")
    return profile, value_candidates("how_heard", profile_value(profile, "how_heard"), profile)


def _pick(options):
    _, cands = _candidates()
    for cand in cands:
        got = pick_select_option(options, cand)
        if got:
            return got
    return None


def test_answer_is_the_company_site_not_a_social_network():
    profile, _ = _candidates()
    assert profile_value(profile, "how_heard") == HOW_HEARD_PRIMARY
    assert "facebook" not in HOW_HEARD_PRIMARY.lower()


@pytest.mark.parametrize(
    "options,expected",
    [
        (["LinkedIn", "Indeed", "Company Website", "Friend"], "Company Website"),
        (["Careers Page", "Social Media", "Referral"], "Careers Page"),
        (["Walmart Careers", "LinkedIn", "Glassdoor"], "Walmart Careers"),
        (["Corporate Website", "Employee Referral"], "Corporate Website"),
        (["Google Careers Site", "Recruiter"], "Google Careers Site"),
        (["Company Career Site", "Job Fair"], "Company Career Site"),
    ],
)
def test_company_option_is_chosen_however_it_is_spelled(options, expected):
    assert _pick(options) == expected


def test_other_is_the_fallback_when_no_company_option_exists():
    assert _pick(["LinkedIn", "Indeed", "Glassdoor", "Other"]) == "Other"


def test_nothing_is_picked_when_there_is_no_honest_option():
    """Never invent an answer: no company option and no Other means skip."""
    assert _pick(["LinkedIn", "Indeed", "Glassdoor"]) is None


def test_careers_substring_match_does_not_leak_to_other_keys():
    """The shape match is scoped to how-heard terms only."""
    assert pick_select_option(["Walmart Careers", "Yes", "No"], "Yes") == "Yes"
    assert pick_select_option(["Careers Page", "New York"], "New York") == "New York"
