"""Every exit goes through APPLY_ENGINE_RESULT — Applier parses that line.

Regression: a JD URL that 404s raised httpx.HTTPStatusError out of fetch_job's
HTML fallback (raise_for_status sat outside the try), so `confirm` died with a
traceback and the bot got nothing parseable.
"""

from __future__ import annotations

import json

import httpx
import pytest

from apply_engine import cli
from apply_engine.jd import fetch_job


def _result_line(capsys) -> dict:
    out = capsys.readouterr().out
    line = [ln for ln in out.splitlines() if ln.startswith("APPLY_ENGINE_RESULT:")]
    assert line, f"no APPLY_ENGINE_RESULT in output:\n{out}"
    return json.loads(line[-1].split("APPLY_ENGINE_RESULT:", 1)[1].strip())


def test_jd_fetch_degrades_on_http_error(monkeypatch):
    """A 404 JD yields a URL-only posting, not an exception."""
    def boom(*_a, **_k):
        raise httpx.HTTPStatusError("404", request=None, response=None)

    monkeypatch.setattr("apply_engine.jd._get_json", lambda *a, **k: None)
    monkeypatch.setattr("apply_engine.jd._get_text", boom)

    job = fetch_job("https://job-boards.greenhouse.io/demo/jobs/1")
    assert job.source == "url-only"
    assert job.url == "https://job-boards.greenhouse.io/demo/jobs/1"
    assert job.ats == "greenhouse"
    assert job.company == "demo"


def test_jd_fetch_degrades_on_network_error(monkeypatch):
    def boom(*_a, **_k):
        raise OSError("name resolution failed")

    monkeypatch.setattr("apply_engine.jd._get_json", lambda *a, **k: None)
    monkeypatch.setattr("apply_engine.jd._get_text", boom)

    job = fetch_job("https://jobs.lever.co/acme/123")
    assert job.source == "url-only"
    assert job.company == "acme"


def test_unexpected_exception_still_emits_result(capsys, monkeypatch):
    """An unhandled error exits through the contract, never as a traceback."""
    def boom(*_a, **_k):
        raise RuntimeError("something exploded")

    monkeypatch.setattr(cli, "cmd_status", boom)
    rc = cli.main(["status"])
    payload = _result_line(capsys)

    assert rc == 1
    assert payload["status"] == "error"
    assert "RuntimeError" in payload["error"]
    assert payload["submit_clicked"] is False


def test_do_not_retry_emits_result_and_exit_3(capsys):
    rc = cli.main(["apply", "--url", "https://job-boards.greenhouse.io/doordashusa/jobs/8171041"])
    payload = _result_line(capsys)

    assert rc == 3
    assert payload["status"] == "do_not_retry"
    assert payload["submit_clicked"] is False


def test_systemexit_from_a_guard_is_not_swallowed(monkeypatch):
    """Guard refusals must stay SystemExit, not be reported as status:error."""
    def refuse(*_a, **_k):
        raise SystemExit("refusing confirm: required fields skipped")

    monkeypatch.setattr(cli, "cmd_confirm", refuse)
    with pytest.raises(SystemExit):
        cli.main(["confirm", "--queue-id", "whatever"])
