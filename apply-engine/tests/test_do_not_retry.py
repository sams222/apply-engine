"""do-not-retry refusals: job-level seeds, company JSON, allowlist."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apply_engine import retry_policy

MOTO_R68388 = "https://motorolasolutions.wd5.myworkdayjobs.com/Careers/job/Chicago-IL/Intern_R68388"
MOTO_R68388_APPLY = MOTO_R68388 + "/apply"
MOTO_R68388_MANUAL = MOTO_R68388 + "/applyManually"
MOTO_R68388_UTM = MOTO_R68388 + "/apply?utm_source=Simplify"
MOTO_R68679 = "https://motorolasolutions.wd5.myworkdayjobs.com/Careers/job/Elgin-IL/Intern_R68679"
MOTO_OTHER = "https://motorolasolutions.wd5.myworkdayjobs.com/Careers/job/Austin-TX/Intern_R69999"
DD_BURNED = "https://job-boards.greenhouse.io/doordashusa/jobs/8171041"
DD_LABS = "https://job-boards.greenhouse.io/doordashusa/jobs/8263774"


@pytest.mark.parametrize("url", [MOTO_R68388, MOTO_R68388_APPLY, MOTO_R68388_MANUAL, MOTO_R68388_UTM])
def test_motorola_submitted_req_blocked_across_url_shapes(url):
    blocked = retry_policy.check(url)
    assert blocked is not None
    assert blocked.source == "seed"
    assert blocked.kind == "job"
    assert "R68388" in blocked.job_key.upper()
    payload = retry_policy.result_payload(blocked, url)
    assert payload["status"] == "do_not_retry"
    assert payload["submit_clicked"] is False
    assert payload["job_key"]
    assert payload["blocked_token"]


def test_motorola_approved_and_unrelated_reqs_pass():
    assert retry_policy.check(MOTO_R68679) is None
    assert retry_policy.check(MOTO_OTHER) is None
    assert retry_policy.check("https://example.com/jobs/1", "Motorola Solutions") is None


def test_doordash_seed_is_job_level():
    burned = retry_policy.check(DD_BURNED)
    assert burned is not None and burned.source == "seed"
    assert retry_policy.check(DD_LABS) is None
    assert retry_policy.check("https://careers.doordash.com/jobs/1") is None


def test_bedrock_is_not_a_company_seed():
    assert retry_policy.check("https://job-boards.greenhouse.io/bedrockrobotics/jobs/4567") is None
    assert retry_policy.check("https://example.com/jobs/3", "Bedrock Robotics") is None


def test_company_json_still_blocks_all(tmp_path: Path):
    path = tmp_path / "do-not-retry.json"
    path.write_text(json.dumps({"companies": ["motorola"]}))
    assert retry_policy.check(MOTO_R68679, path=path) is not None
    assert retry_policy.check(MOTO_OTHER, company="Motorola Solutions", path=path) is not None
    # Job-level seed still fires even without a company entry.
    assert retry_policy.check(MOTO_R68388, path=path) is not None


def test_allowlist_beats_company_block_not_job_block(tmp_path: Path):
    path = tmp_path / "do-not-retry.json"
    path.write_text(json.dumps({"companies": ["motorola"], "allow": ["R68679"]}))
    assert retry_policy.check(MOTO_R68679, path=path) is None
    assert retry_policy.check(MOTO_OTHER, path=path) is not None
    # Allowing the burned req does not lift the job-level seed.
    assert retry_policy.check(MOTO_R68388, path=path, allow_reqs=["R68388"]) is not None


def test_allow_url_and_allow_req_flags(tmp_path: Path):
    path = tmp_path / "do-not-retry.json"
    path.write_text(json.dumps({"companies": ["motorola"]}))
    assert retry_policy.check(MOTO_R68679, path=path, allow_reqs=["R68679"]) is None
    assert retry_policy.check(MOTO_R68679, path=path, allow_urls=[MOTO_R68679]) is None
    assert retry_policy.check(MOTO_R68388, path=path, allow_reqs=["R68679"]) is not None


def test_file_job_entries_layer_on_top(tmp_path: Path):
    path = tmp_path / "do-not-retry.json"
    path.write_text(json.dumps({"jobs": ["gh:acme:99"], "companies": ["initech"]}))
    assert retry_policy.check("https://job-boards.greenhouse.io/acme/jobs/99", path=path) is not None
    assert retry_policy.check("https://jobs.lever.co/initech/1", path=path) is not None
    assert retry_policy.check(DD_BURNED, path=path) is not None


def test_bare_list_file_shape(tmp_path: Path):
    path = tmp_path / "do-not-retry.json"
    path.write_text(json.dumps(["initech"]))
    assert retry_policy.check("https://jobs.lever.co/initech/1", path=path) is not None


def test_corrupt_file_keeps_seed(tmp_path: Path):
    path = tmp_path / "do-not-retry.json"
    path.write_text("{not json")
    assert retry_policy.check(DD_BURNED, path=path) is not None
    assert retry_policy.check(DD_LABS, path=path) is None
    assert retry_policy.check("https://jobs.lever.co/viam/1", path=path) is None


def test_emptied_file_cannot_re_enable_seed(tmp_path: Path):
    path = tmp_path / "do-not-retry.json"
    path.write_text(json.dumps({"jobs": [], "companies": []}))
    assert retry_policy.check(DD_BURNED, path=path) is not None
    assert retry_policy.check(MOTO_R68388, path=path) is not None


def test_job_key_workday_and_greenhouse_shapes():
    assert retry_policy.job_key(MOTO_R68388_UTM).endswith(":R68388")
    assert "motorolasolutions.wd5" in retry_policy.job_key(MOTO_R68388)
    assert retry_policy.job_key(DD_LABS) == "gh:doordashusa:8263774"
    assert retry_policy.job_key("https://boards.greenhouse.io/doordashusa/jobs/8171041") == "gh:doordashusa:8171041"


def test_result_payload_shape():
    blocked = retry_policy.check(DD_BURNED)
    payload = retry_policy.result_payload(blocked, DD_BURNED)
    assert payload["status"] == "do_not_retry"
    assert payload["submit_clicked"] is False
    assert payload["job_key"] == "gh:doordashusa:8171041"
    assert payload["blocked_token"]
    assert payload["matched"]
    assert payload["source"] == "seed"
