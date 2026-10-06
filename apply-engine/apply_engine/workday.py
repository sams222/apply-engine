from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from apply_engine.detect import parse_company_from_url, parse_workday_tenant
from apply_engine.models import Profile
from apply_engine.util import dump_json, load_json, now_iso

PASSWORD_ENV = "WORKDAY_DEFAULT_PASSWORD"
EMAIL_ENV = "WORKDAY_EMAIL"

# Standalone Sign In walls (not the apply-wizard Create Account step).
# Path segments only — job titles containing "login" as a substring must not match.
_SIGN_IN_PATH_TOKENS = frozenset({"login", "log-in", "signin", "sign-in", "sign_in"})


class WorkdayConfigError(RuntimeError):
    """Workday cannot proceed (usually a missing password env var)."""

    def to_result(self, *, url: str = "") -> dict[str, Any]:
        payload = {
            "status": "error",
            "error": str(self),
            "ats": "workday",
        }
        if url:
            payload["url"] = url
        return payload


def workday_email(profile: Profile | None = None) -> str:
    """Account email for every Workday tenant: profile.email, else $WORKDAY_EMAIL."""
    if profile and str(profile.email or "").strip():
        return str(profile.email).strip()
    email = os.environ.get(EMAIL_ENV, "").strip()
    if not email:
        raise WorkdayConfigError("no Workday account email: set profile.email or WORKDAY_EMAIL")
    return email


def require_password() -> str:
    password = os.environ.get(PASSWORD_ENV)
    if not password:
        raise WorkdayConfigError(
            "WORKDAY_DEFAULT_PASSWORD is required for Workday create/sign-in; "
            "refusing to invent a password"
        )
    return password


def tenant_host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def account_map_path(queue_dir: Path, intern_autofill: Path | None = None) -> Path:
    if intern_autofill is not None:
        return intern_autofill / "workday-accounts.json"
    return Path(queue_dir) / "workday-accounts.json"


def load_account_map(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"tenants": {}}
    raw = load_json(path)
    if isinstance(raw, dict) and isinstance(raw.get("tenants"), dict):
        return raw
    if isinstance(raw, dict):
        return {"tenants": raw}
    return {"tenants": {}}


def save_account_map(path: Path, data: dict[str, Any]) -> None:
    dump_json(path, data)


def known_account_email(path: Path, url: str) -> str | None:
    host = tenant_host(url)
    tenant = parse_workday_tenant(url)
    data = load_account_map(path)
    tenants: dict = data.get("tenants") or {}
    row = tenants.get(host) or tenants.get(tenant)
    if isinstance(row, dict) and row.get("email"):
        return str(row["email"])
    return None


def is_standalone_sign_in_url(url: str) -> bool:
    """True for Workday login walls like /login, /private/login, /signin."""
    path = (urlparse(url or "").path or "").lower()
    return any(part in _SIGN_IN_PATH_TOKENS for part in path.split("/") if part)


def looks_like_standalone_sign_in(
    *,
    url: str = "",
    heading_sign_in: bool = False,
    heading_create_account: bool = False,
    verify_password_visible: bool = False,
    visible_password_count: int = 0,
    email_visible: bool = False,
    sign_in_submit_visible: bool = False,
    create_account_submit_visible: bool = False,
) -> bool:
    """True when the page is a Sign In wall, not the Create Account wizard.

    URL /login (incl. /private/login) plus a Sign In heading or auth widgets is
    enough. Overlay Sign In forms also ship a Create Account button, so that
    button alone does not veto Sign In.
    """
    _ = create_account_submit_visible
    if verify_password_visible or visible_password_count >= 2:
        return False
    if is_standalone_sign_in_url(url):
        return bool(
            heading_sign_in
            or email_visible
            or visible_password_count == 1
            or sign_in_submit_visible
        )
    if heading_sign_in:
        return True
    if heading_create_account:
        return False
    return bool(email_visible and visible_password_count == 1 and sign_in_submit_visible)


def prefer_sign_in(
    *,
    known: bool,
    verify_password_visible: bool,
    visible_password_count: int,
    standalone_sign_in: bool = False,
) -> bool:
    """Prefer Sign In only when the visible form is clearly sign-in.

    A Create Account page (Verify New Password, or 2+ password fields) must
    stay on the create path even if workday-accounts.json already has this tenant.
    A standalone Sign In wall (/private/login, heading Sign In, one password)
    is Sign In even when the tenant is not yet in workday-accounts.json.
    """
    if verify_password_visible:
        return False
    if visible_password_count >= 2:
        return False
    if standalone_sign_in and visible_password_count <= 1:
        return True
    if not known:
        return False
    return visible_password_count == 1


def emails_match(readback: str, expected: str) -> bool:
    return (readback or "").strip().lower() == (expected or "").strip().lower() and bool((readback or "").strip())


def auth_click_allowed(
    *,
    email_readback: str,
    expected_email: str,
    create_mode: bool,
    password_filled: bool,
    verify_filled: bool,
    consent_visible: bool,
    consent_checked: bool,
) -> bool:
    """Create Account / Sign In may be clicked only when the live widgets match."""
    if not emails_match(email_readback, expected_email):
        return False
    if not password_filled:
        return False
    if create_mode:
        if not verify_filled:
            return False
        if consent_visible and not consent_checked:
            return False
    return True




def is_blank_auth_shell(
    *,
    step_active: bool,
    email_input_count: int,
    password_input_count: int,
) -> bool:
    """True when Create Account/Sign In step/heading is active and no auth widgets painted."""
    if email_input_count > 0 or password_input_count > 0:
        return False
    return bool(step_active)


def sso_email_gate_visible(
    *,
    email_input_count: int,
    password_input_count: int,
    sign_in_with_email_visible: bool,
) -> bool:
    """True when Google/LinkedIn/'Sign in with email' is showing and no email/password fields."""
    if email_input_count > 0 or password_input_count > 0:
        return False
    return bool(sign_in_with_email_visible)


def should_reload_blank_auth_shell(
    *,
    is_blank: bool,
    page_url: str,
    already_reloaded: bool,
) -> bool:
    """Reload only a blank live myworkdayjobs.com page, and only once."""
    if not is_blank or already_reloaded:
        return False
    url = (page_url or "").strip().lower()
    if not url or url.startswith("about:") or url.startswith("data:") or url.startswith("file:"):
        return False
    return "myworkdayjobs.com" in url


def drop_unconfirmed_auth_filled(filled: list) -> list:
    """Strip rows whose method == workday-auth (never reached My Information)."""
    return [row for row in filled if row.get("method") != "workday-auth"]


def remember_account(path: Path, url: str, email: str) -> None:
    host = tenant_host(url)
    tenant = parse_workday_tenant(url) or parse_company_from_url(url)
    data = load_account_map(path)
    tenants: dict = dict(data.get("tenants") or {})
    tenants[host] = {
        "email": email,
        "tenant": tenant,
        "created_at": now_iso(),
        # password is never stored
    }
    data["tenants"] = tenants
    save_account_map(path, data)


def workday_job_base(url: str) -> str:
    """Strip trailing /apply* segments so we can rebuild apply URLs."""
    base = (url or "").split("?", 1)[0].rstrip("/")
    lower = base.lower()
    for suffix in ("/apply/applymanually", "/applymanually", "/apply"):
        if lower.endswith(suffix):
            base = base[: len(base) - len(suffix)]
            break
    return base.rstrip("/")


def workday_apply_urls(url: str) -> list[str]:
    """Preferred Workday entry URLs from a job posting URL (manual apply first)."""
    base = workday_job_base(url)
    if not base:
        return []
    return [
        f"{base}/apply/applyManually",
        f"{base}/apply",
    ]


def page_looks_like_workday_auth(body: str) -> bool:
    """Body-only hint. Prefer waiting for real email/password inputs in fill.py."""
    text = (body or "").lower()
    if "password requirements" in text and "email address" not in text:
        # listing/marketing copy can mention password rules without a form
        pass
    return (
        ("email address" in text or "email" in text)
        and ("create account" in text or "sign in" in text)
        and ("verify new password" in text or "verify password" in text or "password" in text)
    )


def page_looks_like_workday_form(body: str) -> bool:
    text = (body or "").lower()
    signals = (
        "my information",
        "legal name",
        "first name",
        "work experience",
        "my experience",
        "education",
        "previously worked",
    )
    return sum(1 for s in signals if s in text) >= 2


def page_looks_like_job_listing(body: str, url: str = "") -> bool:
    """True when still on a Careers JD (Apply CTA) rather than an application wizard."""
    text = (body or "").lower()
    u = (url or "").lower()
    if "/apply" in u and "job/" not in u.split("/apply", 1)[0][-20:]:
        # on an apply path — not a listing
        pass
    if page_looks_like_workday_auth(text) or page_looks_like_workday_form(text):
        return False
    has_apply_cta = bool(re.search(r"\bapply(\s+now)?\b", text))
    listing_signals = ("job description", "about the role", "posted on", "time type", "job requisition", "careers")
    return has_apply_cta and sum(1 for s in listing_signals if s in text) >= 1
