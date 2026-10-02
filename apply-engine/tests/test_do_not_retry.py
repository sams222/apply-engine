"""do-not-retry refusals: motorola / doordash / bedrock never reach a browser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apply_engine import retry_policy


@pytest.mark.parametrize(
    "url,company",
    [
        ("https://motorolasolutions.wd5.myworkdayjobs.com/en-US/Careers/job/Intern", ""),
        ("https://careers.doordash.com/jobs/123", ""),
        ("https://job-boards.greenhouse.io/bedrockrobotics/jobs/4567", ""),
        ("https://boards.greenhouse.io/doordashusa/jobs/99", ""),
        ("https://example.com/jobs/1", "Motorola Solutions"),
        ("https://example.com/jobs/2", "DoorDash USA"),
        ("https://example.com/jobs/3", "Bedrock Robotics"),
    ],
)
def test_seed_companies_blocked(url, company):
    blocked = retry_policy.check(url, company)
    assert blocked is not None, f"{url} {company} should be refused"
    assert blocked.source == "seed"


@pytest.mark.parametrize(
    "url,company",
    [
        ("https://jobs.ashbyhq.com/retell-ai/abc", "Retell AI"),
        ("https://job-boards.greenhouse.io/linkedin/jobs/5079761", "LinkedIn"),
        ("https://jobs.lever.co/viam/xyz", "Viam"),
        ("https://acme.wd1.myworkdayjobs.com/en-US/careers/job/NYC/Intern", "Acme"),
    ],
)
def test_normal_boards_allowed(url, company):
    assert retry_policy.check(url, company) is None


def test_file_entries_layer_on_top(tmp_path: Path):
    path = tmp_path / "do-not-retry.json"
    path.write_text(json.dumps({"companies": ["initech"]}))
    assert retry_policy.check("https://jobs.lever.co/initech/1", path=path) is not None
    # seed survives alongside file entries
    assert retry_policy.check("https://careers.doordash.com/x", path=path) is not None


def test_bare_list_file_shape(tmp_path: Path):
    path = tmp_path / "do-not-retry.json"
    path.write_text(json.dumps(["initech"]))
    assert retry_policy.check("https://jobs.lever.co/initech/1", path=path) is not None


def test_corrupt_file_keeps_seed(tmp_path: Path):
    path = tmp_path / "do-not-retry.json"
    path.write_text("{not json")
    assert retry_policy.check("https://careers.doordash.com/x", path=path) is not None
    assert retry_policy.check("https://jobs.lever.co/viam/1", path=path) is None


def test_emptied_file_cannot_re_enable_seed(tmp_path: Path):
    path = tmp_path / "do-not-retry.json"
    path.write_text(json.dumps({"companies": []}))
    assert retry_policy.check("https://careers.doordash.com/x", path=path) is not None


def test_result_payload_shape():
    blocked = retry_policy.check("https://careers.doordash.com/jobs/1")
    payload = retry_policy.result_payload(blocked, "https://careers.doordash.com/jobs/1")
    assert payload["status"] == "do_not_retry"
    assert payload["submit_clicked"] is False
    assert payload["blocked_token"] == "doordash"
