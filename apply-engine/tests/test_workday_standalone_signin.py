"""Standalone Workday Sign In (/private/login), not the Create Account wizard."""

from pathlib import Path

import pytest

from apply_engine.workday import is_standalone_sign_in_url, looks_like_standalone_sign_in

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "workday-standalone-login.html"
CREATE_FIXTURE = ROOT / "tests" / "fixtures" / "workday.html"
EXPDIA_LOGIN = (
    "https://expedia.wd108.myworkdayjobs.com/en-US/private/login"
    "?redirect=%2Fen-US%2Fprivate%2Fhome"
)
TEST_PASSWORD = "test-only-not-used-in-prod"


def test_private_login_url_is_standalone():
    assert is_standalone_sign_in_url(EXPDIA_LOGIN)
    assert looks_like_standalone_sign_in(
        url=EXPDIA_LOGIN,
        heading_sign_in=True,
        email_visible=True,
        visible_password_count=1,
        sign_in_submit_visible=True,
    )


def test_playwright_detects_standalone_login_not_create_account():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from apply_engine.fill import _on_sign_in_page, _standalone_sign_in_flags

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            html = FIXTURE.read_text(encoding="utf-8")
            page.route(
                "https://expedia.wd108.myworkdayjobs.com/**",
                lambda route: route.fulfill(status=200, content_type="text/html", body=html),
            )
            page.goto(EXPDIA_LOGIN)
            flags = _standalone_sign_in_flags(page)
            assert flags["heading_sign_in"]
            assert flags["email_visible"]
            assert flags["visible_password_count"] == 1
            assert flags["sign_in_submit_visible"]
            assert not flags["verify_password_visible"]
            assert not flags["heading_create_account"]
            assert _on_sign_in_page(page)

            page.set_content(CREATE_FIXTURE.read_text(encoding="utf-8"))
            create_flags = _standalone_sign_in_flags(page)
            assert create_flags["heading_create_account"]
            assert create_flags["verify_password_visible"] or create_flags["visible_password_count"] >= 2
            assert not _on_sign_in_page(page)
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            pytest.skip(f"chromium not installed: {exc}")
        raise


def test_playwright_fills_standalone_login_and_leaves_honeypot_empty():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from apply_engine.fill import _fill_and_submit_sign_in, _on_sign_in_page

    email = "jordan.avery@example.org"
    html = FIXTURE.read_text(encoding="utf-8")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.route(
                "https://expedia.wd108.myworkdayjobs.com/**",
                lambda route: route.fulfill(status=200, content_type="text/html", body=html),
            )
            page.goto(EXPDIA_LOGIN)
            assert _on_sign_in_page(page)
            notes: list[str] = []
            skipped: list[dict] = []
            ok = _fill_and_submit_sign_in(page, email, TEST_PASSWORD, notes, skipped)
            assert ok, (notes, skipped)
            assert page.evaluate("() => window.__signInClicked") is True
            assert page.evaluate("() => window.__signedIn") is True
            assert page.evaluate("() => window.__honeypotValue") == ""
            honey = page.locator('[data-automation-id="beecatcher"]')
            assert honey.input_value() == ""
            assert page.locator('[data-automation-id="legalName--firstName"]').is_visible()
            blob = " ".join(notes) + str(skipped)
            assert TEST_PASSWORD not in blob
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            pytest.skip(f"chromium not installed: {exc}")
        raise


def test_clear_login_wall_is_noop_on_create_account():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from apply_engine.fill import _clear_workday_login_wall

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(CREATE_FIXTURE.read_text(encoding="utf-8"))
            notes: list[str] = []
            skipped: list[dict] = []
            assert _clear_workday_login_wall(
                page,
                email="jordan.avery@example.org",
                password=TEST_PASSWORD,
                notes=notes,
                skipped=skipped,
            ) is True
            assert not any("standalone Sign In" in n for n in notes)
            assert page.locator("#email").input_value() == ""
            browser.close()
    except Exception as extra:
        if "Executable doesn't exist" in str(extra):
            pytest.skip(f"chromium not installed: {extra}")
        raise


def test_playwright_clicks_sign_in_with_email_then_fills_fields():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from apply_engine.fill import _fill_and_submit_sign_in, _sign_in_with_email_visible

    email = "jordan.avery@example.org"
    html = (ROOT / "tests" / "fixtures" / "workday-sso-email-gate.html").read_text(encoding="utf-8")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            assert _sign_in_with_email_visible(page)
            notes: list[str] = []
            skipped: list[dict] = []
            ok = _fill_and_submit_sign_in(page, email, TEST_PASSWORD, notes, skipped)
            assert ok, (notes, skipped)
            assert page.evaluate("() => window.__emailGateClicked") is True
            assert page.evaluate("() => window.__signInClicked") is True
            assert page.evaluate("() => window.__signedIn") is True
            assert any("Sign in with email" in n for n in notes)
            browser.close()
    except Exception as extra:
        if "Executable doesn't exist" in str(extra):
            pytest.skip(f"chromium not installed: {extra}")
        raise
