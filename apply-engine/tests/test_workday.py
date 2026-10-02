import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from apply_engine.detect import detect_ats
from apply_engine.guard import CONFIRM_ENV, SubmitBlockedError, guarded_click, is_auth_control, is_submit_control
from apply_engine.profile import load_profile
from apply_engine.workday import (
    PASSWORD_ENV,
    WorkdayConfigError,
    known_account_email,
    load_account_map,
    remember_account,
    require_password,
    workday_email,
)

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "examples" / "profile.json"
POOL = ROOT / "examples" / "PROJECT_POOL.md"
FIXTURE = ROOT / "tests" / "fixtures" / "workday.html"
WD_URL = "https://acme.wd1.myworkdayjobs.com/en-US/careers/job/NYC/Intern_R1"


def test_detect_workday_url():
    assert detect_ats(WD_URL) == "workday"


def test_workday_email_falls_back_to_profile():
    profile = load_profile(PROFILE)
    assert workday_email(profile) == profile.email

def test_workday_email_without_profile_uses_env(monkeypatch):
    monkeypatch.setenv("WORKDAY_EMAIL", "applicant@example.org")
    assert workday_email(None) == "applicant@example.org"
    monkeypatch.delenv("WORKDAY_EMAIL")
    with pytest.raises(WorkdayConfigError):
        workday_email(None)


def test_require_password_missing(monkeypatch):
    monkeypatch.delenv(PASSWORD_ENV, raising=False)
    with pytest.raises(WorkdayConfigError, match="WORKDAY_DEFAULT_PASSWORD"):
        require_password()


def test_require_password_from_env(monkeypatch):
    monkeypatch.setenv(PASSWORD_ENV, "test-only-not-used-in-prod")
    assert require_password() == "test-only-not-used-in-prod"


def test_account_map_stores_email_not_password(tmp_path):
    path = tmp_path / "workday-accounts.json"
    remember_account(path, WD_URL, "jordan.avery@example.org")
    data = load_account_map(path)
    blob = path.read_text(encoding="utf-8")
    assert "jordan.avery@example.org" in blob
    assert "password" not in blob.lower()
    tenants = data["tenants"]
    row = next(iter(tenants.values()))
    assert row["email"] == "jordan.avery@example.org"
    assert "password" not in row
    assert known_account_email(path, WD_URL) == "jordan.avery@example.org"


def test_password_never_hardcoded_in_package():
    for path in (ROOT / "apply_engine").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r'PASSWORD_ENV\s*=\s*["\'][^W]', text)
        assert not re.search(
            r'(password|WORKDAY_DEFAULT_PASSWORD)\s*=\s*["\'][^"\']{4,}["\']',
            text,
            re.I,
        )
    workday = (ROOT / "apply_engine" / "workday.py").read_text(encoding="utf-8")
    assert "os.environ.get(PASSWORD_ENV)" in workday
    assert "refusing to invent a password" in workday


def test_create_account_is_auth_not_job_submit_text():
    assert is_auth_control("Create Account")
    assert is_auth_control("Sign In")
    assert not is_submit_control(text="Create Account")
    assert is_submit_control(type_attr="submit", text="Create Account")
    assert is_submit_control(text="Submit Application")


def test_guarded_click_allows_auth_without_confirm(monkeypatch):
    monkeypatch.delenv(CONFIRM_ENV, raising=False)
    clicks: list = []

    class Loc:
        def click(self):
            clicks.append("auth")

    guarded_click(
        Loc(),
        allow_submit=False,
        allow_auth=True,
        meta={"type_attr": "submit", "text": "Create Account", "aria": "", "name": "", "role": "button"},
    )
    assert clicks == ["auth"]
    with pytest.raises(SubmitBlockedError):
        guarded_click(
            Loc(),
            allow_submit=False,
            allow_auth=True,
            meta={"type_attr": "submit", "text": "Submit Application", "aria": "", "name": "", "role": "button"},
        )


def test_cli_workday_missing_password(monkeypatch):
    env = os.environ.copy()
    env.pop(PASSWORD_ENV, None)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "apply_engine",
            "apply",
            "--url",
            WD_URL,
            "--profile",
            str(PROFILE),
            "--pool",
            str(POOL),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 2
    assert "WORKDAY_DEFAULT_PASSWORD" in proc.stdout
    assert "APPLY_ENGINE_RESULT" in proc.stdout
    assert "invent" in proc.stdout.lower() or "required" in proc.stdout


def test_fill_workday_missing_password_before_browser(monkeypatch):
    from apply_engine.fill import fill_application

    monkeypatch.delenv(PASSWORD_ENV, raising=False)
    monkeypatch.delenv(CONFIRM_ENV, raising=False)
    profile = load_profile(PROFILE)
    with pytest.raises(WorkdayConfigError):
        fill_application(
            url=WD_URL,
            profile=profile,
            resume=None,
            resume_path=PROFILE,
            profile_path=str(PROFILE),
            pool_path=str(POOL),
            queue_id="wd-missing",
            html=FIXTURE.read_text(encoding="utf-8"),
            submit=False,
        )


def _tailored(tmp_path):
    from apply_engine.jd import fetch_job_from_text
    from apply_engine.pool import load_pool
    from apply_engine.pdf import render_pdf
    from apply_engine.tailor import tailor

    profile = load_profile(PROFILE)
    pool = load_pool(POOL)
    job = fetch_job_from_text(WD_URL, "Software Engineering Intern", "acme", "React Native intern")
    tailored = tailor(profile, pool, job)
    pdf = render_pdf(tailored, tmp_path / "resume.pdf")
    return profile, tailored, pdf


def test_playwright_workday_wizard_does_not_submit(tmp_path, monkeypatch):
    pytest.importorskip("playwright")
    from apply_engine.fill import fill_application

    monkeypatch.delenv(CONFIRM_ENV, raising=False)
    monkeypatch.setenv(PASSWORD_ENV, "test-only-not-used-in-prod")
    profile, tailored, pdf = _tailored(tmp_path)
    accounts = tmp_path / "workday-accounts.json"
    try:
        artifact = fill_application(
            url=WD_URL,
            profile=profile,
            resume=tailored,
            resume_path=pdf,
            profile_path=str(PROFILE),
            pool_path=str(POOL),
            queue_id="wd-no-submit",
            html=FIXTURE.read_text(encoding="utf-8"),
            submit=False,
            tenant_map_path=accounts,
            screenshot_path=tmp_path / "shot.png",
        )
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert artifact.submit_clicked is False
    assert artifact.status == "waiting_confirm"
    mapped = {row["mapped_to"]: row["value"] for row in artifact.filled}
    assert mapped.get("first_name") == "Jordan"
    assert mapped.get("school") == "Hudson State University"
    assert mapped.get("resume")
    assert mapped.get("workday_password") == "[redacted]"
    # filled_log is UI readback: State widget says "New York", never profile "NY".
    assert mapped.get("state") == "New York"
    assert mapped.get("state") != profile.state
    assert mapped.get("postal_code") == "10001"
    assert mapped.get("previous_employee") == "No"
    assert mapped.get("phone")
    from apply_engine.workday_widgets import phone_digits_match

    assert phone_digits_match(str(mapped["phone"]), profile.phone)
    assert mapped.get("phone") != "intended-not-on-widget"
    deg = str(mapped.get("degree") or "")
    assert deg and deg.lower() != "select one"
    assert "bachelor" in deg.lower() or "b.s" in deg.lower() or "bs" in deg.lower()
    assert mapped.get("field_of_study") == "Computer Science"
    assert not any(s.get("label") == "State*" for s in artifact.skipped)
    assert "test-only-not-used-in-prod" not in str(artifact.to_dict())
    blob = accounts.read_text(encoding="utf-8")
    assert profile.email in blob
    assert "test-only-not-used-in-prod" not in blob
    assert "password" not in blob.lower()


def test_playwright_workday_confirm_submits(tmp_path, monkeypatch):
    pytest.importorskip("playwright")
    from apply_engine.fill import fill_application

    monkeypatch.setenv(CONFIRM_ENV, "1")
    monkeypatch.setenv(PASSWORD_ENV, "test-only-not-used-in-prod")
    profile, tailored, pdf = _tailored(tmp_path)
    try:
        artifact = fill_application(
            url=WD_URL,
            profile=profile,
            resume=tailored,
            resume_path=pdf,
            profile_path=str(PROFILE),
            pool_path=str(POOL),
            queue_id="wd-confirm",
            html=FIXTURE.read_text(encoding="utf-8"),
            submit=True,
            tenant_map_path=tmp_path / "workday-accounts.json",
        )
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert artifact.submit_clicked is True
    assert artifact.status == "submitted"

BLANK_AUTH = ROOT / "tests" / "fixtures" / "workday-blank-auth.html"


def _blank_auth_html(mode: str) -> str:
    return BLANK_AUTH.read_text(encoding="utf-8").replace("__BLANK_MODE__", mode)


def test_is_blank_auth_shell_detection():
    from apply_engine.workday import is_blank_auth_shell

    assert is_blank_auth_shell(step_active=True, email_input_count=0, password_input_count=0) is True
    assert is_blank_auth_shell(step_active=False, email_input_count=0, password_input_count=0) is False
    assert is_blank_auth_shell(step_active=True, email_input_count=1, password_input_count=0) is False
    assert is_blank_auth_shell(step_active=True, email_input_count=0, password_input_count=1) is False


def test_drop_unconfirmed_auth_filled_strips_workday_auth_rows():
    from apply_engine.workday import drop_unconfirmed_auth_filled

    filled = [
        {"label": "Email Address", "mapped_to": "email", "value": "jordan@example.com", "method": "workday-auth"},
        {"label": "password", "mapped_to": "workday_password", "value": "[redacted]", "method": "workday-auth"},
        {"label": "First Name", "mapped_to": "first_name", "value": "Jordan", "method": "fill"},
    ]
    assert drop_unconfirmed_auth_filled(filled) == [filled[2]]


def test_should_reload_blank_auth_shell_only_live_workday():
    from apply_engine.workday import should_reload_blank_auth_shell

    assert (
        should_reload_blank_auth_shell(
            is_blank=True,
            page_url="https://motorolasolutions.wd5.myworkdayjobs.com/Careers",
            already_reloaded=False,
        )
        is True
    )
    assert (
        should_reload_blank_auth_shell(
            is_blank=True,
            page_url="https://motorolasolutions.wd5.myworkdayjobs.com/Careers",
            already_reloaded=True,
        )
        is False
    )
    assert should_reload_blank_auth_shell(is_blank=False, page_url="https://x.myworkdayjobs.com/", already_reloaded=False) is False
    assert should_reload_blank_auth_shell(is_blank=True, page_url="about:blank", already_reloaded=False) is False
    assert should_reload_blank_auth_shell(is_blank=True, page_url="file:///tmp/x.html", already_reloaded=False) is False
    assert should_reload_blank_auth_shell(is_blank=True, page_url="data:text/html,", already_reloaded=False) is False
    assert should_reload_blank_auth_shell(is_blank=True, page_url="", already_reloaded=False) is False


def test_playwright_workday_waits_for_delayed_auth_paint(tmp_path, monkeypatch):
    pytest.importorskip("playwright")
    from apply_engine.fill import fill_application

    monkeypatch.delenv(CONFIRM_ENV, raising=False)
    monkeypatch.setenv(PASSWORD_ENV, "test-only-not-used-in-prod")
    profile, tailored, pdf = _tailored(tmp_path)
    try:
        artifact = fill_application(
            url=WD_URL,
            profile=profile,
            resume=tailored,
            resume_path=pdf,
            profile_path=str(PROFILE),
            pool_path=str(POOL),
            queue_id="wd-blank-delayed",
            html=_blank_auth_html("delayed"),
            submit=False,
            tenant_map_path=tmp_path / "workday-accounts.json",
        )
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert artifact.status == "waiting_confirm"
    mapped = {row["mapped_to"]: row["value"] for row in artifact.filled}
    assert mapped.get("email") == profile.email
    assert mapped.get("first_name") == "Jordan"
    assert any("auth widgets appeared after wait" in n for n in artifact.notes)
    assert "no Workday auth form on this page" not in artifact.notes


def test_playwright_workday_blank_auth_shell_refuses(tmp_path, monkeypatch):
    pytest.importorskip("playwright")
    from apply_engine import fill as fill_mod
    from apply_engine.fill import fill_application

    monkeypatch.delenv(CONFIRM_ENV, raising=False)
    monkeypatch.setenv(PASSWORD_ENV, "test-only-not-used-in-prod")
    monkeypatch.setattr(fill_mod, "AUTH_WIDGET_WAIT_MS", 400)
    monkeypatch.setattr(fill_mod, "AUTH_WIDGET_RELOAD_WAIT_MS", 200)
    monkeypatch.setattr(fill_mod, "AUTH_WIDGET_HEADER_WAIT_MS", 400)
    profile, tailored, pdf = _tailored(tmp_path)
    accounts = tmp_path / "workday-accounts.json"
    try:
        artifact = fill_application(
            url=WD_URL,
            profile=profile,
            resume=tailored,
            resume_path=pdf,
            profile_path=str(PROFILE),
            pool_path=str(POOL),
            queue_id="wd-blank-stuck",
            html=_blank_auth_html("stuck"),
            submit=False,
            tenant_map_path=accounts,
        )
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert artifact.submit_clicked is False
    assert artifact.status == "needs_user"
    mapped = {row["mapped_to"]: row["value"] for row in artifact.filled}
    assert "first_name" not in mapped
    assert "email" not in mapped
    assert "workday_password" not in mapped
    assert "no Workday auth form on this page" in artifact.notes
    assert any("not continuing wizard" in n for n in artifact.notes)
    assert any("blank Create Account/Sign In" in s.get("reason", "") for s in artifact.skipped)
    assert not accounts.exists()


def test_playwright_workday_header_signin_recovers_blank_shell(tmp_path, monkeypatch):
    pytest.importorskip("playwright")
    from apply_engine import fill as fill_mod
    from apply_engine.fill import fill_application

    monkeypatch.delenv(CONFIRM_ENV, raising=False)
    monkeypatch.setenv(PASSWORD_ENV, "test-only-not-used-in-prod")
    monkeypatch.setattr(fill_mod, "AUTH_WIDGET_WAIT_MS", 400)
    monkeypatch.setattr(fill_mod, "AUTH_WIDGET_RELOAD_WAIT_MS", 200)
    monkeypatch.setattr(fill_mod, "AUTH_WIDGET_HEADER_WAIT_MS", 2000)
    profile, tailored, pdf = _tailored(tmp_path)
    try:
        artifact = fill_application(
            url=WD_URL,
            profile=profile,
            resume=tailored,
            resume_path=pdf,
            profile_path=str(PROFILE),
            pool_path=str(POOL),
            queue_id="wd-blank-header",
            html=_blank_auth_html("header"),
            submit=False,
            tenant_map_path=tmp_path / "workday-accounts.json",
        )
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert artifact.status == "waiting_confirm"
    mapped = {row["mapped_to"]: row["value"] for row in artifact.filled}
    assert mapped.get("email") == profile.email
    assert mapped.get("first_name") == "Jordan"
    assert any("header Sign In" in n for n in artifact.notes)
    assert not any(s.get("label") == "Email Address*" for s in artifact.skipped)


def _soft_fail_html() -> str:
    """Auth succeeds onto the stepper-plus-error page from Walmart run 10."""
    html = FIXTURE.read_text(encoding="utf-8")
    html = html.replace(
        'show("personal");',
        'document.getElementById("auth").hidden = true;\n'
        '      document.getElementById("wd-error").hidden = false;',
    )
    return html.replace(
        "</body>",
        """
<div id="wd-error" hidden>
  <p>My Information</p>
  <h2>My Information</h2>
  <p>Something went wrong</p>
  <p>Please refresh the page and then try again.</p>
  <p>Error Code: I022e65ed</p>
</div>
</body>""",
    )


def _validation_html() -> str:
    """My Information paints with Workday's Errors Found banner already up."""
    html = FIXTURE.read_text(encoding="utf-8")
    return html.replace(
        "<h2>My Information</h2>",
        "<h2>My Information</h2>\n"
        '    <div role="alert">Errors Found</div>\n'
        "    <p>Error: Invalid LinkedIn URL</p>",
        1,
    )


def test_soft_fail_heading_is_not_a_form():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from apply_engine.fill import (
        _application_controls_visible,
        _await_workday_surface,
        _workday_error_page,
        _workday_validation_blocked,
    )

    html = """
    <h2>My Information</h2>
    <p>My Experience</p><p>Review</p>
    <p>Something went wrong</p>
    <p>Please refresh the page and then try again.</p>
    """
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            assert _workday_error_page(page)
            assert not _application_controls_visible(page)
            assert not _workday_validation_blocked(page)
            assert _await_workday_surface(page) == "error"
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            pytest.skip(f"chromium not installed: {exc}")
        raise


def test_validation_banner_blocks_but_fields_count_as_a_form():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from apply_engine.fill import (
        _application_controls_visible,
        _await_workday_surface,
        _workday_error_page,
        _workday_validation_blocked,
    )

    html = """
    <h2>My Information</h2>
    <div role="alert">Errors Found</div>
    <p>Error: Invalid LinkedIn URL</p>
    <label>First Name <input name="first_name" data-automation-id="legalName--firstName" /></label>
    <button type="button">Save and Continue</button>
    """
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            assert not _workday_error_page(page)
            assert _application_controls_visible(page)
            assert _workday_validation_blocked(page)
            assert _await_workday_surface(page) == "form"
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            pytest.skip(f"chromium not installed: {exc}")
        raise


def test_playwright_workday_soft_fail_is_needs_user(tmp_path, monkeypatch):
    pytest.importorskip("playwright")
    from apply_engine import fill as fill_mod
    from apply_engine.fill import fill_application

    monkeypatch.delenv(CONFIRM_ENV, raising=False)
    monkeypatch.setenv(PASSWORD_ENV, "test-only-not-used-in-prod")
    monkeypatch.setattr(fill_mod, "WIZARD_SURFACE_WAIT_MS", 800)
    profile, tailored, pdf = _tailored(tmp_path)
    try:
        artifact = fill_application(
            url=WD_URL,
            profile=profile,
            resume=tailored,
            resume_path=pdf,
            profile_path=str(PROFILE),
            pool_path=str(POOL),
            queue_id="wd-soft-fail",
            html=_soft_fail_html(),
            submit=False,
            tenant_map_path=tmp_path / "workday-accounts.json",
        )
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert artifact.submit_clicked is False
    assert artifact.status == "needs_user"
    mapped = {row["mapped_to"]: row["value"] for row in artifact.filled}
    assert "first_name" not in mapped
    assert "email" not in mapped
    assert any("error page did not clear" in n for n in artifact.notes)
    assert not any("review page" in n for n in artifact.notes)


def test_playwright_workday_validation_does_not_advance(tmp_path, monkeypatch):
    pytest.importorskip("playwright")
    from apply_engine.fill import fill_application

    monkeypatch.delenv(CONFIRM_ENV, raising=False)
    monkeypatch.setenv(PASSWORD_ENV, "test-only-not-used-in-prod")
    profile, tailored, pdf = _tailored(tmp_path)
    try:
        artifact = fill_application(
            url=WD_URL,
            profile=profile,
            resume=tailored,
            resume_path=pdf,
            profile_path=str(PROFILE),
            pool_path=str(POOL),
            queue_id="wd-validation",
            html=_validation_html(),
            submit=False,
            tenant_map_path=tmp_path / "workday-accounts.json",
        )
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert artifact.submit_clicked is False
    assert artifact.status == "needs_user"
    mapped = {row["mapped_to"]: row["value"] for row in artifact.filled}
    assert mapped.get("first_name") == "Jordan"
    assert "school" not in mapped
    assert any("not clicking Next" in n for n in artifact.notes)
    assert not any("review page" in n for n in artifact.notes)

