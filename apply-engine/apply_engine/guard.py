"""Hard stop: fill must never click Submit. Only confirm() may."""

from __future__ import annotations

import os
import re
from typing import Any

CONFIRM_ENV = "APPLY_ENGINE_CONFIRM"

SUBMIT_TEXT = re.compile(
    r"\b(submit(\s+(your\s+)?application)?|send(\s+my)?\s+application|"
    r"finish\s+application|complete\s+application)\b",
    re.I,
)

# Navigation on a JD page is allowed. These are not submit.
APPLY_NAV_TEXT = re.compile(
    r"^(apply( (now|manually|for this job|for this position))?|"
    r"begin application|start application|apply manually)$",
    re.I,
)

# Broader match for Workday CTAs that include the role title after "Apply".
APPLY_NAV_LOOSE = re.compile(
    r"^apply(\s+(now|manually))?(\s+for\b.*)?$",
    re.I,
)

# Account create / sign-in on Workday. Allowed during auth even if type=submit.
AUTH_TEXT = re.compile(
    r"^(create(\s+an)?\s+account|sign\s+in|log\s+in|register)$",
    re.I,
)

NEXT_TEXT = re.compile(
    r"^(next|continue|save and continue|save & continue|save and go to next)$",
    re.I,
)


class SubmitBlockedError(RuntimeError):
    """Raised if fill tries to click a submit control."""


def confirm_enabled() -> bool:
    return os.environ.get(CONFIRM_ENV) == "1"


def is_submit_control(
    *,
    type_attr: str = "",
    text: str = "",
    aria: str = "",
    name: str = "",
    role: str = "",
) -> bool:
    if (type_attr or "").lower() == "submit":
        return True
    blob = f"{text} {aria} {name}"
    if SUBMIT_TEXT.search(blob):
        return True
    if (role or "").lower() == "button" and SUBMIT_TEXT.search(blob):
        return True
    return False


def is_apply_nav(text: str) -> bool:
    blob = (text or "").strip()
    if not blob:
        return False
    # Never treat LinkedIn/Indeed/autofill partner CTAs as our entry path.
    low = blob.lower()
    if any(x in low for x in ("linkedin", "indeed", "with google", "autofill", "ease apply")):
        return False
    return bool(APPLY_NAV_TEXT.match(blob) or APPLY_NAV_LOOSE.match(blob))


def is_auth_control(text: str = "", aria: str = "") -> bool:
    blob = (text or aria or "").strip()
    if not blob:
        return False
    if SUBMIT_TEXT.search(blob) and "submit" in blob.lower():
        return False
    return bool(AUTH_TEXT.match(blob)) or bool(re.search(r"\b(create account|sign in|log in)\b", blob, re.I))


def is_next_control(text: str = "") -> bool:
    return bool(NEXT_TEXT.match((text or "").strip()))


def assert_can_submit() -> None:
    if not confirm_enabled():
        raise SubmitBlockedError(
            "Submit is blocked. Run `python -m apply_engine confirm --queue-id ID`. "
            f"({CONFIRM_ENV} is not set)"
        )


def guarded_click(
    locator: Any,
    *,
    allow_submit: bool,
    allow_auth: bool = False,
    meta: dict[str, str] | None = None,
) -> None:
    """Click a Playwright locator only if it is not a job-submit control, unless confirm is on.

    Workday Create Account / Sign In may be type=submit on an auth form; those
    are allowed with allow_auth=True and do not count as application submit.
    """
    meta = meta or {}
    info = _locator_meta(locator, meta)
    if is_auth_control(info.get("text", ""), info.get("aria", "")) and allow_auth:
        locator.click()
        return
    if is_submit_control(**info):
        if not allow_submit:
            raise SubmitBlockedError(f"blocked submit click on {info!r}")
        assert_can_submit()
    locator.click()


def _locator_meta(locator: Any, meta: dict[str, str]) -> dict[str, str]:
    if meta:
        return {
            "type_attr": meta.get("type_attr", ""),
            "text": meta.get("text", ""),
            "aria": meta.get("aria", ""),
            "name": meta.get("name", ""),
            "role": meta.get("role", ""),
        }
    try:
        data = locator.evaluate(
            """el => ({
                type_attr: el.getAttribute('type') || el.type || '',
                text: (el.innerText || el.value || '').trim(),
                aria: el.getAttribute('aria-label') || '',
                name: el.getAttribute('name') || '',
                role: el.getAttribute('role') || ''
            })"""
        )
        return {k: str(v or "") for k, v in data.items()}
    except Exception:
        return {"type_attr": "", "text": "", "aria": "", "name": "", "role": ""}
