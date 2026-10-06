from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, Callable

from apply_engine.answers import answer_open_ended, looks_open_ended
from apply_engine.detect import ATS_ASHBY, ATS_GREENHOUSE, ATS_LEVER, ATS_WORKDAY, detect_ats
from apply_engine.fields import (
    profile_url_forms,
    is_honeypot,
    FIELD_ALIASES,
    is_noise_field,
    is_url_capable_control,
    is_url_profile_key,
    map_field,
    pick_select_option,
    profile_value,
    select_readback_matches,
    url_readback_matches,
    value_candidates,
)
from apply_engine.guard import (
    SUBMIT_TEXT,
    SubmitBlockedError,
    guarded_click,
    is_apply_nav,
    is_auth_control,
    is_next_control,
    is_submit_control,
)
from apply_engine.forms import fill_form
from apply_engine.models import JobPosting, Profile, ReviewArtifact, TailoredResume
from apply_engine.util import now_iso

AUTH_FIELD_LABELS = re.compile(
    r"^(email address|password|new password|verify new password|verify password|"
    r"confirm password|re-enter password)$",
    re.I,
)

REACT_SET_VALUE = """(el, value) => {
  const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const desc = Object.getOwnPropertyDescriptor(proto, 'value');
  if (desc && desc.set) desc.set.call(el, value);
  else el.value = value;
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
}"""

CONSENT_RE = re.compile(
    r"yes,?\s+i have read and consent to the terms( and conditions)?",
    re.I,
)

VERIFY_PASSWORD_RE = re.compile(r"verify(\s+new)?\s+password", re.I)

EMAIL_ADDRESS_RE = re.compile(r"email\s*address", re.I)
CREATE_SIGNIN_STEP_RE = re.compile(r"create\s+account(\s*/\s*sign\s+in)?|\bsign\s+in\b", re.I)
HEADER_SIGNIN_RE = re.compile(r"^sign\s+in$", re.I)
SIGN_IN_WITH_EMAIL_RE = re.compile(
    r"sign\s*in\s*with\s*(your\s+)?e-?mail|continue\s*with\s*e-?mail|use\s*e-?mail",
    re.I,
)

# Wait for Workday SPA/iframe widgets after the stepper mounts (Motorola blank shell).
AUTH_WIDGET_WAIT_MS = 12_000
AUTH_WIDGET_RELOAD_WAIT_MS = 8_000
AUTH_WIDGET_HEADER_WAIT_MS = 8_000
# After sign-in the stepper paints before either the form or the soft-fail
# interstitial. Wait this long for one of those, not for the step label.
WIZARD_SURFACE_WAIT_MS = 8_000
# After submitting standalone Sign In, wait this long to leave /login.
SIGN_IN_REDIRECT_WAIT_MS = 8_000



JS_FIELDS = """
() => {
  const nodes = [...document.querySelectorAll('input, textarea, select')];
  return nodes.map((el, i) => {
    const labelFrom = (node) => (node && (node.innerText || node.textContent) || '').trim();
    let label = '';
    if (el.labels && el.labels[0]) label = labelFrom(el.labels[0]);
    if (!label) {
      const wrap = el.closest('label');
      if (wrap) label = labelFrom(wrap);
    }
    if (!label) {
      const labelled = el.getAttribute('aria-labelledby');
      if (labelled) {
        label = labelled.split(/\\s+/).map(id => {
          const n = document.getElementById(id);
          return n ? (n.innerText || '') : '';
        }).join(' ').trim();
      }
    }
    if (!label) label = el.getAttribute('aria-label') || '';
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    const hidden = el.type === 'hidden' || style.display === 'none' || style.visibility === 'hidden';
    const options = el.tagName === 'SELECT' ? [...el.options].map(o => o.text.trim()).filter(Boolean) : [];
    return {
      index: i,
      tag: el.tagName.toLowerCase(),
      type: (el.type || '').toLowerCase(),
      name: el.name || '',
      id: el.id || '',
      placeholder: el.placeholder || '',
      label,
      hidden,
      options
    };
  });
}
"""


def fill_application(
    *,
    url: str,
    profile: Profile,
    resume: TailoredResume | None,
    resume_path: str | Path,
    profile_path: str,
    pool_path: str,
    queue_id: str,
    headed: bool = False,
    screenshot_path: str | Path | None = None,
    html: str | None = None,
    submit: bool = False,
    timeout_ms: int = 45000,
    tenant_map_path: str | Path | None = None,
    job: JobPosting | None = None,
    saved_answers: dict[str, str] | None = None,
    pre_submit: Callable[[dict], list[str]] | None = None,
) -> ReviewArtifact:
    """Fill the ATS form. submit=True is only legal from `confirm` (env flag).

    saved_answers maps question label -> reviewed LLM answer; when given, those are
    typed verbatim and nothing is drafted fresh. pre_submit sees the fresh fill just
    before the Submit click; any reason it returns leaves the form unsubmitted.
    """
    if submit:
        from apply_engine.guard import assert_can_submit

        assert_can_submit()
    else:
        os.environ.pop("APPLY_ENGINE_CONFIRM", None)

    ats = detect_ats(url)
    if ats == ATS_WORKDAY:
        from apply_engine.workday import require_password

        require_password()

    from playwright.sync_api import sync_playwright

    filled: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    notes: list[str] = []
    ats = detect_ats(url)
    submit_clicked = False
    screenshot = ""
    dom_snapshot: list = []
    step_shots: list = []
    step_snapshots: list = []
    readback_problems: list = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headed)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.set_default_timeout(timeout_ms)
        try:
            if html:
                page.set_content(html, wait_until="domcontentloaded")
            else:
                # Company careers pages that embed Greenhouse are slow, script-heavy, and
                # sometimes refuse headless Chromium; the embed form is the same form.
                embed = _greenhouse_embed_without_page(url)
                if embed:
                    notes.append(f"greenhouse entry: company page -> {embed}")
                page.goto(embed or url, wait_until="domcontentloaded")
            page.wait_for_timeout(1200)
            ats = detect_ats(url, page.content())
            _maybe_dismiss(page)
            page.wait_for_timeout(400)

            ashby_ready = True
            if ats == ATS_WORKDAY:
                from apply_engine.workday import require_password, workday_email

                wd_email = workday_email(profile)
                wd_password = require_password()
                tenant_path = Path(tenant_map_path) if tenant_map_path else None
                _clear_workday_login_wall(
                    page,
                    email=wd_email,
                    password=wd_password,
                    notes=notes,
                    skipped=skipped,
                    tenant_map_path=tenant_path,
                )
                _run_workday(
                    page,
                    url=url,
                    profile=profile,
                    resume=resume,
                    resume_path=str(resume_path),
                    filled=filled,
                    skipped=skipped,
                    notes=notes,
                    tenant_map_path=tenant_path,
                    screenshot_path=screenshot_path,
                    step_shots=step_shots,
                    step_snapshots=step_snapshots,
                    pool_path=pool_path,
                )
                # confirm / My Applications / mid-flow redirects can bounce to /private/login
                _clear_workday_login_wall(
                    page,
                    email=wd_email,
                    password=wd_password,
                    notes=notes,
                    skipped=skipped,
                    tenant_map_path=tenant_path,
                )
            elif ats in (ATS_ASHBY, ATS_GREENHOUSE, ATS_LEVER) and not html:
                if _enter_single_page_application(page, ats, notes):
                    _upload_resume(page, str(resume_path), filled, skipped, notes)
                    page.wait_for_timeout(2500)
                    fill_form(
                        page,
                        profile=profile,
                        pool=_load_pool_entries(pool_path),
                        job=job,
                        filled=filled,
                        skipped=skipped,
                        notes=notes,
                        saved_answers=saved_answers,
                    )
                elif not any("needs_user" in (n or "") for n in notes):
                    notes.append(f"needs_user: {ats} apply form not entered")
            elif ats == ATS_ASHBY:
                ashby_ready = _enter_ashby_application(page, notes)
                if ashby_ready:
                    _fill_standard_fields(
                        page,
                        profile=profile,
                        resume=resume,
                        resume_path=str(resume_path),
                        filled=filled,
                        skipped=skipped,
                        notes=notes,
                    )
                elif not any("needs_user" in (n or "") for n in notes):
                    notes.append("needs_user: ashby apply form not entered")
            else:
                _maybe_open_form(page)
                _maybe_dismiss(page)
                page.wait_for_timeout(600)
                _fill_standard_fields(
                    page,
                    profile=profile,
                    resume=resume,
                    resume_path=str(resume_path),
                    filled=filled,
                    skipped=skipped,
                    notes=notes,
                )

            if screenshot_path:
                Path(screenshot_path).parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(screenshot_path), full_page=True)
                screenshot = str(screenshot_path)

            # Snapshot rendered values at the same instant as the PNG, so the
            # filled log can be proved against what a reviewer actually sees.
            from apply_engine import readback as _readback

            dom_snapshot = _readback.capture(page)
            # A multi-step wizard hides earlier steps by the time we screenshot
            # Review, so a value counts as shown if any step screenshot shows it.
            visible_now = [r for r in dom_snapshot if r.get("visible")]
            for snap in step_snapshots:
                visible_now.extend(snap.get("rows") or [])
            readback_problems = _readback.reconcile(filled, visible_now or dom_snapshot)

            stop_before_submit: list[str] = []
            if submit and pre_submit is not None:
                _prune_skipped_if_filled(filled, skipped)
                stop_before_submit = pre_submit({
                    "filled": filled, "skipped": skipped, "notes": notes,
                    "extra": {"readback_problems": readback_problems},
                })
            if submit and stop_before_submit:
                notes.append("needs_user: confirm stopped before Submit: " + "; ".join(stop_before_submit[:6]))
            elif submit:
                if _captcha_or_cloudflare(page):
                    notes.append(
                        "needs_user: captcha/cloudflare blocking submit — do not fake-submit"
                    )
                else:
                    try:
                        submit_clicked = _click_submit(page)
                        notes.append("submit clicked via confirm")
                    except SubmitBlockedError as exc:
                        msg = str(exc)
                        if "no submit control" in msg.lower() or "disabled" in msg.lower():
                            notes.append(f"needs_user: {msg}")
                        else:
                            raise
            else:
                _assert_no_submit_clicked(page)
                notes.append("hard-stop: submit not clicked")
        finally:
            context.close()
            browser.close()

    _prune_skipped_if_filled(filled, skipped)

    if readback_problems:
        notes.append(
            "readback: filled log disagrees with rendered form on "
            + ", ".join(sorted({str(p.get("mapped_to")) for p in readback_problems}))
        )

    status = "submitted" if submit_clicked else "waiting_confirm"
    if status == "waiting_confirm" and any("needs_user" in (n or "") for n in notes):
        status = "needs_user"
    return ReviewArtifact(
        id=queue_id,
        status=status,
        url=url,
        ats=ats,
        resume_path=str(resume_path),
        profile_path=profile_path,
        pool_path=pool_path,
        filled=filled,
        skipped=skipped,
        screenshot=screenshot,
        submit_clicked=submit_clicked,
        notes=notes,
        extra={
            "finished_at": now_iso(),
            "dom_snapshot": dom_snapshot,
            "step_screenshots": step_shots,
            "step_snapshots": [
                {"step": x.get("step"), "screenshot": x.get("screenshot"), "controls": len(x.get("rows") or [])}
                for x in step_snapshots
            ],
            "readback_problems": readback_problems,
        },
    )


def _resume_already_attached(page: Any, resume_path: str) -> bool:
    """True when this file is already showing as uploaded on the page.

    Workday renders each attachment as a row with the file name and a
    "Successfully Uploaded!" marker; re-running the upload pass adds duplicates
    rather than replacing.
    """
    name = Path(resume_path).name
    if not name:
        return False
    for scope in _iter_dom_scopes(page):
        try:
            if scope.get_by_text(name, exact=False).count():
                return True
        except Exception:
            continue
    try:
        return bool(
            page.evaluate(
                "n => [...document.querySelectorAll('input[type=file]')]"
                ".some(i => i.files && i.files.length && i.files[0].name === n)",
                name,
            )
        )
    except Exception:
        return False


def _drop_other_resumes(page: Any, resume_path: str, notes: list) -> int:
    """Remove uploaded PDFs that are not the resume we intend to send.

    A saved Workday draft keeps earlier attachments. Each row's delete control
    is clicked only when its nearest container names exactly one PDF and that
    name is not the current file.
    """
    want = Path(resume_path).name.lower()
    removed = 0
    for _ in range(8):
        buttons = page.locator(
            "button, [role='button']"
        ).filter(has_text=re.compile(r"delete|remove", re.I))
        named = page.get_by_role("button", name=re.compile(r"delete|remove", re.I))
        locs = [named, buttons]
        clicked = False
        for loc in locs:
            try:
                count = loc.count()
            except Exception:
                continue
            for i in range(min(count, 30)):
                btn = loc.nth(i)
                try:
                    if not btn.is_visible():
                        continue
                    blob = btn.evaluate(
                        """el => {
                          let node = el.parentElement;
                          for (let i = 0; node && i < 8; i++) {
                            const text = node.innerText || '';
                            const pdfs = text.match(/[^\\n]{1,120}?\\.pdf/gi) || [];
                            if (pdfs.length === 1) return text;
                            node = node.parentElement;
                          }
                          return '';
                        }"""
                    )
                except Exception:
                    continue
                low = (blob or "").lower()
                if ".pdf" not in low or want in low:
                    continue
                try:
                    btn.click(timeout=2000)
                except Exception:
                    try:
                        box = btn.bounding_box()
                        if not box:
                            continue
                        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                    except Exception:
                        continue
                removed += 1
                clicked = True
                page.wait_for_timeout(400)
                break
            if clicked:
                break
        if not clicked:
            break
    if removed:
        notes.append(f"removed {removed} resume attachment(s) other than {Path(resume_path).name}")
    return removed


def _upload_resume(page: Any, resume_path: str, filled: list, skipped: list, notes: list) -> None:
    _drop_other_resumes(page, resume_path, notes)
    # Ashby SPA: wait briefly for file inputs (esp. after Apply CTA).
    files = page.locator("input[type=file]")
    try:
        count = files.count()
    except Exception:
        count = 0
    if count == 0:
        for _ in range(10):
            page.wait_for_timeout(300)
            try:
                count = files.count()
            except Exception:
                count = 0
            if count:
                break
    if count == 0:
        notes.append("no resume file input found")
        return

    # Workday keeps the same file input mounted across wizard steps, so running
    # this pass per step attached the tailored PDF five times on live Walmart.
    if _resume_already_attached(page, resume_path):
        notes.append("resume already attached — not re-uploading")
        return

    uploaded = False

    def _try_upload(loc: Any) -> bool:
        nonlocal uploaded
        label = _accessible_name(loc)
        low = (label or "").lower()
        if "cover" in low and "resume" not in low and "cv" not in low:
            skipped.append({"label": label or "cover letter file", "reason": "no tailored cover-letter file"})
            return False
        if "transcript" in low:
            return False
        try:
            loc.set_input_files(resume_path, timeout=8000)
            filled.append({"label": label or "resume", "mapped_to": "resume", "value": resume_path, "method": "file"})
            uploaded = True
            return True
        except Exception as exc:
            skipped.append({"label": label or "resume", "reason": f"file upload failed: {exc}"[:160]})
            return False

    preferred = page.locator(
        "#_systemfield_resume, input[name='_systemfield_resume'], input[type=file]#resume, "
        "input[type=file][name=resume], #resume-upload-input"
    )
    try:
        for i in range(min(preferred.count(), 2)):
            if _try_upload(preferred.nth(i)):
                break
    except Exception:
        pass
    if not uploaded:
        for i in range(count):
            if _try_upload(files.nth(i)):
                break
    if not uploaded:
        notes.append("resume upload did not stick")


CONTAINS_KEYS = {
    "work_authorized_us",
    "need_sponsorship",
    "sponsorship_type",
    "how_heard",
    "previous_employee",
    "export_license",
    "policy_ack",
    "gender",
    "race_ethnicity",
    "veteran",
    "disability",
    "cover_letter",
}

WD_AUTOMATION_IDS = {
    "first_name": ("legalName--firstName", "legalNameSection_firstName", "firstName"),
    "last_name": ("legalName--lastName", "legalNameSection_lastName", "lastName"),
    "email": ("email", "emailAddress"),
    "phone": ("phone-number",),
    "city": ("city", "addressSection_city"),
    "state": ("addressSection_countryRegion",),
    "postal_code": ("addressSection_postalCode", "postalCode"),
    "country": ("country", "country-input"),
    "school": ("schoolName", "school"),
    "degree": ("education-degree",),
    "field_of_study": ("fieldOfStudy", "field-of-study"),
    "linkedin": ("linkedin", "linkedinQuestion"),
    "github": ("github", "website"),
}

# Walmart's Workday puts NO data-automation-id on the input or button itself.
# The id lives on the wrapper div as `formField-<name>`, and the control is a
# descendant of it. Our flat id list (addressSection_postalCode, city, ...)
# matches nothing on that tenant, which is why Address Line 1, City, State and
# Postal Code came back blank on every live run while the fixture passed.
WD_FORM_FIELD_WRAPPERS = {
    "first_name": ("legalName--firstName", "legalNameSection--firstName"),
    "last_name": ("legalName--lastName", "legalNameSection--lastName"),
    "address_line1": ("addressLine1",),
    "city": ("city",),
    "state": ("countryRegion",),
    "postal_code": ("postalCode",),
    "country": ("country",),
    "how_heard": ("source",),
    "phone": ("phoneNumber",),
    "email": ("email",),
}

# Inside a wrapper, this is the control we want.
WD_WRAPPER_CONTROL = (
    "input:not([type=hidden])",
    "button",
    "textarea",
    "select",
)


def _find_in_form_field_wrapper(root: Any, key: str, accept: Any) -> Any | None:
    """Locate a control by its Workday formField wrapper id."""
    for suffix in WD_FORM_FIELD_WRAPPERS.get(key, ()):
        try:
            wrapper = root.locator(f'[data-automation-id="formField-{suffix}"]')
            if not wrapper.count():
                continue
        except Exception:
            continue
        for w in range(min(wrapper.count(), 3)):
            scope = wrapper.nth(w)
            for sel in WD_WRAPPER_CONTROL:
                try:
                    loc = scope.locator(sel)
                    for i in range(min(loc.count(), 4)):
                        cand = loc.nth(i)
                        if accept(cand):
                            return cand
                except Exception:
                    continue
    return None


WORKDAY_SKIP_STANDARD = {"state", "phone", "degree", "postal_code", "field_of_study"}


def _fill_standard_fields(
    page: Any,
    *,
    profile: Profile,
    resume: TailoredResume | None,
    resume_path: str,
    filled: list,
    skipped: list,
    notes: list,
    skip_keys: set[str] | None = None,
) -> None:
    skip_keys = skip_keys or set()
    _upload_resume(page, resume_path, filled, skipped, notes)
    claimed: set[str] = {row["mapped_to"] for row in filled}

    for key, aliases in FIELD_ALIASES:
        if key in {"resume", "cover_letter", "policy_ack"} or key in claimed or key in skip_keys:
            continue
        loc = _find_by_aliases(page, aliases, contains=key in CONTAINS_KEYS, key=key)
        if loc is None:
            continue
        if _is_password_locator(loc):
            continue
        value = profile_value(profile, key)
        if key == "gpa" and not value:
            skipped.append({"label": "GPA", "reason": "gpa omitted — never invent"})
            claimed.add(key)
            continue
        if value is None:
            if key in {"gender", "race_ethnicity", "veteran", "disability"}:
                info = _locator_type(loc)
                picked = pick_select_option(info.get("options") or [], "decline")
                if picked:
                    _write_locator(page, loc, picked)
                    if _record_widget_filled(
                        filled,
                        skipped,
                        loc,
                        label=aliases[0],
                        mapped_to=key,
                        intended=picked,
                        method="select",
                        key=key,
                    ):
                        claimed.add(key)
                        continue
            skipped.append({"label": aliases[0], "reason": "no profile value"})
            claimed.add(key)
            continue
        candidates = value_candidates(key, value, profile)
        intended = candidates[0] if candidates else value
        if is_url_profile_key(key):
            # Workday rejects a LinkedIn URL without the www host.
            url_forms = profile_url_forms(key, value) or [value]
            ok, method = False, "fail"
            for candidate in url_forms:
                ok, method = _write_url_locator(page, loc, candidate)
                if ok:
                    intended = candidate
                    break
        else:
            ok, method = _write_locator(page, loc, candidates)
        if _record_widget_filled(
            filled,
            skipped,
            loc,
            label=aliases[0],
            mapped_to=key,
            intended=intended,
            method=method if ok else "fail",
            key=key,
            intended_terms=candidates,
        ):
            claimed.add(key)

    if resume is not None:
        _fill_open_ended(page, profile, resume, filled, skipped, claimed, skip_keys=skip_keys)


def _scope_text(scope: Any) -> str:
    try:
        return scope.inner_text("body") or ""
    except Exception:
        return ""


def _workday_body_text(page: Any) -> str:
    """Visible text from the page and every child frame.

    The application shell often lives in a frame. A main-frame inner_text
    misses both the soft-fail copy and the validation banner.
    """
    return "\n".join(_scope_text(scope) for scope in _iter_dom_scopes(page))


def _workday_error_page(page: Any) -> bool:
    body = _workday_body_text(page)
    return bool(
        re.search(r"something went wrong", body, re.I)
        and re.search(r"refresh the page", body, re.I)
    )


def _required_prompt_unset(page: Any) -> bool:
    """True when a required question still shows Select One."""
    for scope in _iter_dom_scopes(page):
        fields = scope.locator("[data-automation-id*='formField']")
        try:
            count = fields.count()
        except Exception:
            continue
        for i in range(count):
            field = fields.nth(i)
            try:
                if not field.is_visible():
                    continue
                text = field.inner_text() or ""
            except Exception:
                continue
            # The asterisk is Workday's required marker. The word "required"
            # shows up inside optional legal copy and must not count.
            if "*" not in text:
                continue
            if re.search(r"select one", text, re.I):
                return True
    return False


def _workday_validation_blocked(page: Any) -> bool:
    """True when Workday is showing field errors and will ignore Next.

    An "Errors Found" banner can stay on screen after the dropdowns have been
    committed. Block only while a required prompt is still Select One, or an
    inline invalid message is showing.
    """
    body = _workday_body_text(page)
    if re.search(r"error:\s*invalid", body, re.I) or re.search(r"is not a valid", body, re.I):
        return True
    if re.search(r"must have a value", body, re.I):
        return True
    if re.search(r"errors found", body, re.I):
        return _required_prompt_unset(page) or _required_terms_unchecked(page)
    return False


def _required_terms_unchecked(page: Any) -> bool:
    from apply_engine.workday_widgets import TERMS_CONSENT_RE

    for scope in _iter_dom_scopes(page):
        boxes = scope.locator("input[type=checkbox]")
        try:
            count = boxes.count()
        except Exception:
            continue
        for i in range(count):
            box = boxes.nth(i)
            try:
                if not box.is_visible() or box.is_checked():
                    continue
                blob = " ".join([
                    box.get_attribute("aria-label") or "",
                    box.get_attribute("name") or "",
                    box.get_attribute("id") or "",
                ])
                if TERMS_CONSENT_RE.search(blob):
                    return True
            except Exception:
                continue
    return False


# Controls that exist on a real wizard step. The stepper label "My Information"
# is not one of them — the soft-fail page renders that label with no fields.
_APPLICATION_CONTROL_SELECTOR = (
    '[data-automation-id="legalName--firstName"], '
    '[data-automation-id="legalNameSection_firstName"], '
    'input[name="first_name"], '
    'input[type="file"], '
    '[data-automation-id="education-degree"], '
    '[data-automation-id="bottom-navigation-next-button"], '
    '[data-automation-id="phone-number"], '
    '[data-automation-id="addressSection_addressLine1"], '
    'input[name="linkedin"], input[name="school"]'
)


def _application_controls_visible(page: Any) -> bool:
    for scope in _iter_dom_scopes(page):
        loc = scope.locator(_APPLICATION_CONTROL_SELECTOR)
        try:
            n = min(loc.count(), 8)
        except Exception:
            n = 0
        for i in range(n):
            try:
                if loc.nth(i).is_visible():
                    return True
            except Exception:
                continue
        try:
            nxt = scope.get_by_role(
                "button",
                name=re.compile(r"^(next|save and continue|save & continue)$", re.I),
            )
            if nxt.count() and nxt.first.is_visible():
                return True
        except Exception:
            continue
    return False


def _await_workday_surface(page: Any) -> str:
    """'form' when a step has controls, 'error' on the soft-fail page, else 'timeout'."""
    timeout_ms = WIZARD_SURFACE_WAIT_MS
    waited = 0
    while True:
        if _workday_error_page(page):
            return "error"
        # Review has no inputs. The stepper's "Review" label is not a heading
        # on the pages we have seen; the step title is.
        if _on_review_page(page) or _application_controls_visible(page):
            return "form"
        if waited >= timeout_ms:
            return "timeout"
        page.wait_for_timeout(250)
        waited += 250


def _advance_to_application_fields(page: Any, notes: list) -> bool:
    """Wait until this step is fillable. Refresh through a soft-fail page once."""
    outcome = _await_workday_surface(page)
    if outcome == "form":
        return True
    if outcome == "error":
        notes.append("workday soft-fail page — refreshing")
        if _recover_workday_error(page, notes) and _await_workday_surface(page) == "form":
            notes.append("workday error page cleared after refresh")
            return True
        notes.append("needs_user: workday error page did not clear")
        return False
    return False


WORKDAY_BLOCKERS = (
    (re.compile(r"wrong email address or password|account might be locked|invalid (username|email) or password", re.I),
     "Workday rejected the sign-in (wrong password or locked account); reset the password on this tenant"),
    (re.compile(r"page you are looking for doesn.t exist|job (posting )?(is )?no longer available|position has been filled", re.I),
     "posting is closed or removed"),
    (re.compile(r"verify your (email|account)|verification (email|link)|check your email", re.I),
     "Workday wants email verification for the new account; click the link in the inbox, then re-run"),
)


def _workday_blocker(page: Any) -> str | None:
    try:
        body = page.inner_text("body", timeout=3000)
    except Exception:
        return None
    return next((msg for rx, msg in WORKDAY_BLOCKERS if rx.search(body)), None)


def _park_before_application_fields(filled: list, skipped: list, notes: list, page: Any = None) -> None:
    from apply_engine.workday import drop_unconfirmed_auth_filled

    blocker = _workday_blocker(page) if page is not None else None
    skipped.append({
        "label": "workday_auth",
        "reason": blocker or "did not reach application fields after Create Account/Sign In",
    })
    if not any("needs_user" in (n or "") for n in notes):
        notes.append(f"needs_user: {blocker or 'did not reach application fields after sign-in'}")
    filled[:] = drop_unconfirmed_auth_filled(filled)


def _recover_workday_error(page: Any, notes: list, *, attempts: int = 3) -> bool:
    """Refresh through Workday soft-fail pages. Returns True if form looks usable."""
    for i in range(attempts):
        if not _workday_error_page(page):
            return True
        notes.append(f"workday error page detected — refresh retry {i+1}/{attempts}")
        try:
            page.reload(wait_until="domcontentloaded", timeout=45000)
        except Exception as exc:
            notes.append(f"workday refresh failed: {exc}"[:160])
            return False
        page.wait_for_timeout(2000)
        _maybe_dismiss(page)
    return not _workday_error_page(page)



def _remember_posting_term(page: Any, notes: list) -> None:
    """Keep a short snippet when the job posting names summer, winter, or spring."""
    try:
        body = page.inner_text("body") or ""
    except Exception:
        return
    match = re.search(r".{0,80}\b(summer|winter|spring)\b.{0,80}", body, re.I)
    if not match:
        return
    snippet = " ".join(match.group(0).split())[:180]
    note = f"workday posting term: {snippet}"
    if note not in notes:
        notes.append(note)


def _enter_workday_application(page: Any, url: str, notes: list) -> bool:
    """Leave the public Careers JD and reach auth or My Information.

    Motorola 7b3a42: /apply/applyManually sometimes lands on a blank Careers shell
    (loading dots only). Prefer the job posting → Apply CTA, wait out SPA loads,
    reload blank shells, then fall back to apply URLs + header Sign In.
    """
    from apply_engine.workday import (
        is_standalone_sign_in_url,
        page_looks_like_job_listing,
        page_looks_like_workday_form,
        workday_apply_urls,
        workday_job_base,
    )

    def _body() -> str:
        try:
            return page.inner_text("body") or ""
        except Exception:
            return ""

    def _page_url() -> str:
        try:
            return page.url or ""
        except Exception:
            return ""

    def _ready() -> bool:
        if is_standalone_sign_in_url(_page_url()) or _on_sign_in_page(page):
            return True
        if _auth_form_present(page):
            return True
        if page_looks_like_workday_form(_body()):
            return True
        # Blank Create Account/Sign In shell (stepper/heading, widgets not yet painted)
        if _create_signin_step_active(page):
            return True
        try:
            if page.get_by_role("heading", name=re.compile(r"my information|create account|sign in", re.I)).count():
                h = page.get_by_role("heading", name=re.compile(r"my information|create account|sign in", re.I)).first
                if h.is_visible():
                    return True
        except Exception:
            pass
        return False

    def _is_blank_shell() -> bool:
        body = _body().strip().lower()
        # Logo/nav/footer only — no job text, no auth fields
        if _auth_form_present(page):
            return False
        if len(body) < 80:
            return True
        markers = ("apply", "job description", "create account", "sign in", "email", "password", "my information")
        return sum(1 for m in markers if m in body) == 0

    def _wait_ready(timeout_ms: int = 20000) -> bool:
        steps = max(1, timeout_ms // 500)
        for i in range(steps):
            _maybe_dismiss(page)
            if _ready():
                return True
            if i in (6, 12, 18) and _is_blank_shell():
                notes.append(f"workday entry: blank shell — reload ({i})")
                try:
                    page.reload(wait_until="domcontentloaded", timeout=45000)
                except Exception as exc:
                    notes.append(f"workday entry reload failed: {exc}"[:120])
            page.wait_for_timeout(500)
        return _ready()

    if _ready():
        if is_standalone_sign_in_url(_page_url()) or _on_sign_in_page(page):
            notes.append("workday entry: already on standalone Sign In")
            _wait_auth_widgets(page, AUTH_WIDGET_WAIT_MS)
        return True

    # 1) Job posting first (most reliable for Motorola)
    job_url = workday_job_base(url) or url
    try:
        notes.append(f"workday entry: goto job posting {job_url}")
        page.goto(job_url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(1500)
        _maybe_dismiss(page)
        _remember_posting_term(page, notes)
        # Wait for Apply to appear (SPA)
        for _ in range(20):
            if _click_workday_apply_cta(page, notes):
                break
            if _is_blank_shell():
                page.reload(wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(500)
        else:
            notes.append("workday entry: no Apply CTA on job posting yet")
        page.wait_for_timeout(1000)
        _maybe_dismiss(page)
        _click_apply_manually_modal(page, notes)
        if _wait_ready(20000):
            notes.append("workday entry: reached auth/form via job Apply CTA")
            return True
    except Exception as exc:
        notes.append(f"workday entry job posting failed: {exc}"[:160])

    # 2) Direct apply URLs with blank-shell recovery
    for apply_url in workday_apply_urls(url):
        try:
            notes.append(f"workday entry: goto {apply_url}")
            page.goto(apply_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2000)
            _maybe_dismiss(page)
            if _is_blank_shell():
                notes.append("workday entry: blank after apply URL — reload once")
                page.reload(wait_until="networkidle", timeout=45000)
                page.wait_for_timeout(2000)
            _click_apply_manually_modal(page, notes)
            if _wait_ready(20000):
                notes.append("workday entry: reached auth/form via apply URL")
                return True
        except Exception as exc:
            notes.append(f"workday entry goto failed: {exc}"[:160])

    # 3) Header Sign In (gets to auth even from blank careers shell)
    if _click_header_sign_in(page, notes):
        if _wait_ready(15000):
            notes.append("workday entry: reached auth via header Sign In")
            return True

    # 4) Last try: Apply CTA on whatever we have
    if _click_workday_apply_cta(page, notes):
        page.wait_for_timeout(1500)
        _maybe_dismiss(page)
        _click_apply_manually_modal(page, notes)
        if _wait_ready(15000):
            notes.append("workday entry: reached auth/form via Apply CTA")
            return True

    body = _body()
    if _is_blank_shell():
        notes.append("workday entry FAILED: blank Careers shell (SPA never painted)")
        return False
    if page_looks_like_job_listing(body, page.url):
        notes.append("workday entry FAILED: still on public job listing (Apply CTA)")
        return False
    if not _ready():
        notes.append("workday entry FAILED: no auth/form after apply attempts")
        return False
    return True


def _click_header_sign_in(page: Any, notes: list) -> bool:
    """Header/nav Sign In only. Never the in-form overlay Sign In (dd7478)."""
    # Do not divert away from a visible Create Account form.
    if _verify_password_visible(page) or len(_visible_password_inputs(page)) >= 2:
        notes.append("workday_auth: not clicking header Sign In — create form is showing")
        return False
    for scope in _iter_dom_scopes(page):
        if _verify_password_visible(scope) or len(_visible_password_inputs(scope)) >= 2:
            notes.append("workday_auth: not clicking header Sign In — create form is showing")
            return False

    locators = [
        page.locator("header").get_by_role("link", name=HEADER_SIGNIN_RE),
        page.locator("header").get_by_role("button", name=HEADER_SIGNIN_RE),
        page.locator("nav").get_by_role("link", name=HEADER_SIGNIN_RE),
        page.locator("nav").get_by_role("button", name=HEADER_SIGNIN_RE),
        page.locator('[role="banner"]').get_by_role("link", name=HEADER_SIGNIN_RE),
        page.locator('[role="banner"]').get_by_role("button", name=HEADER_SIGNIN_RE),
        page.get_by_role("link", name=HEADER_SIGNIN_RE),
        page.get_by_role("button", name=HEADER_SIGNIN_RE),
        page.locator(
            '#header-signin, [data-automation-id="utilityButtonSignIn"], '
            '[data-automation-id="signInLink"]'
        ),
        page.locator("a[href*='login'], a[href*='signin'], a[href*='SignIn']"),
    ]
    seen: list[Any] = []
    for loc in locators:
        try:
            n = loc.count()
        except Exception:
            n = 0
        for i in range(n):
            seen.append(loc.nth(i))
    for btn in seen:
        try:
            if not btn.is_visible():
                continue
        except Exception:
            continue
        try:
            inside_create = btn.evaluate(
                """el => {
                  const form = el.closest('form');
                  if (form && form.querySelector('input[type=password]')) return true;
                  if (el.id === 'open-signin' || el.id === 'overlay-signin') return true;
                  const overlay = el.closest('#signin-overlay');
                  return !!overlay;
                }"""
            )
        except Exception:
            inside_create = False
        if inside_create:
            continue
        try:
            guarded_click(
                btn,
                allow_submit=False,
                allow_auth=True,
                meta={"text": "Sign In", "role": "button"},
            )
            page.wait_for_timeout(400)
            notes.append("workday entry: clicked header Sign In")
            return True
        except Exception:
            try:
                btn.click(timeout=2000)
                page.wait_for_timeout(400)
                notes.append("workday entry: clicked header Sign In")
                return True
            except Exception:
                continue
    notes.append("workday_auth: header Sign In not found")
    return False


def _click_apply_manually_modal(page: Any, notes: list) -> bool:
    """Prefer Apply Manually over LinkedIn/Indeed partner buttons."""
    prefer = ("apply manually", "continue", "proceed")
    avoid = ("linkedin", "indeed", "google", "facebook", "autofill")
    candidates = page.get_by_role("button").all() + page.get_by_role("link").all()
    for loc in candidates[:40]:
        try:
            text = (loc.inner_text() or "").strip().lower()
            if not text:
                continue
            if any(a in text for a in avoid):
                continue
            if any(p in text for p in prefer):
                loc.click(timeout=2000)
                page.wait_for_timeout(800)
                notes.append(f"workday entry: clicked modal '{text[:40]}'")
                return True
        except Exception:
            continue
    return False


def _click_workday_apply_cta(page: Any, notes: list) -> bool:
    """Click the primary Apply control on a Careers JD."""
    # data-automation-id shortcuts used by some Workday tenants
    for sel in (
        "[data-automation-id='adventureButton']",
        "[data-automation-id='applyButton']",
        "a[data-automation-id='jobPostingApplyButton']",
        "button[data-uxi-element-id='apply']",
    ):
        loc = page.locator(sel)
        try:
            if loc.count() and loc.first.is_visible():
                loc.first.click(timeout=2000)
                notes.append(f"workday entry: clicked {sel}")
                page.wait_for_timeout(800)
                return True
        except Exception:
            pass

    candidates = page.get_by_role("button").all() + page.get_by_role("link").all()
    # Prefer exact Apply / Apply Now before longer "Apply for …"
    ranked: list[tuple[int, Any, str]] = []
    for loc in candidates[:60]:
        try:
            text = (loc.inner_text() or "").strip()
        except Exception:
            continue
        if not is_apply_nav(text):
            continue
        low = text.lower()
        rank = 0 if low in {"apply", "apply now", "apply manually"} else 1
        ranked.append((rank, loc, text))
    ranked.sort(key=lambda x: x[0])
    for _, loc, text in ranked:
        try:
            loc.click(timeout=2000)
            notes.append(f"workday entry: clicked Apply CTA '{text[:50]}'")
            page.wait_for_timeout(800)
            return True
        except Exception:
            continue
    notes.append("workday entry: no Apply CTA clicked")
    return False


def _work_history(pool_path: str | None, resume: TailoredResume | None) -> list:
    """Pool order, so work history follows the resume instead of JD rank."""
    if pool_path:
        try:
            from apply_engine.pool import load_pool

            return load_pool(pool_path)
        except Exception:
            pass
    if resume is None:
        return []
    return [*resume.experience, *resume.programs]


def _run_workday(
    page: Any,
    *,
    url: str,
    profile: Profile,
    resume: TailoredResume | None,
    resume_path: str,
    filled: list,
    skipped: list,
    notes: list,
    tenant_map_path: Path | None,
    screenshot_path: str | Path | None = None,
    step_shots: list | None = None,
    step_snapshots: list | None = None,
    pool_path: str | None = None,
) -> None:
    from apply_engine.workday import (
        drop_unconfirmed_auth_filled,
        is_blank_auth_shell,
        remember_account,
        require_password,
        workday_email,
    )

    password = require_password()
    email = workday_email(profile)
    if not _enter_workday_application(page, url, notes):
        skipped.append({"label": "workday_entry", "reason": "stuck on job listing / Apply CTA"})
        return
    _maybe_dismiss(page)
    if not _recover_workday_error(page, notes):
        notes.append("workday stuck on error page after entry")
        skipped.append({"label": "workday_entry", "reason": "error page after entry"})
        return
    if _captcha_or_2fa(page):
        notes.append("CAPTCHA or 2FA present — Workday cannot continue unattended")
        return

    if not _clear_workday_login_wall(
        page,
        email=email,
        password=password,
        notes=notes,
        skipped=skipped,
        tenant_map_path=tenant_map_path,
    ):
        filled[:] = drop_unconfirmed_auth_filled(filled)
        notes.append("workday auth failed — not continuing wizard (needs_user)")
        return

    already_in_app = _my_information_visible_anywhere(page) or _application_controls_visible(page)
    if already_in_app:
        notes.append("workday: already past Sign In — skipping create-account wizard")
        signed_in = True
    else:
        widgets_ready = _ensure_workday_auth_widgets(page, notes)
        if not widgets_ready:
            if _my_information_visible_anywhere(page):
                notes.append("workday: already on My Information — skipping auth")
                signed_in = True
            else:
                flags = _blank_auth_shell_flags(page)
                blank = is_blank_auth_shell(
                    step_active=bool(flags["step_active"]),
                    email_input_count=int(flags["email_input_count"]),
                    password_input_count=int(flags["password_input_count"]),
                )
                skipped.append(
                    {
                        "label": "workday_auth",
                        "reason": "blank Create Account/Sign In shell — no email/password widgets",
                    }
                )
                notes.append("no Workday auth form on this page")
                if blank:
                    notes.append(
                        "workday_auth: blank Create Account/Sign In shell after wait/reload/header Sign In"
                    )
                notes.append("workday auth failed — not continuing wizard (needs_user)")
                filled[:] = drop_unconfirmed_auth_filled(filled)
                return
        else:
            signed_in = _workday_auth(
                page,
                url=url,
                email=email,
                password=password,
                filled=filled,
                notes=notes,
                skipped=skipped,
                tenant_map_path=tenant_map_path,
            )
    if not signed_in:
        filled[:] = drop_unconfirmed_auth_filled(filled)
        notes.append("workday auth failed — not continuing wizard (needs_user)")
        return
    if not _advance_to_application_fields(page, notes):
        # One more Sign In attempt if still on auth. An error interstitial is
        # not a sign-in page; _advance already refreshed and recorded needs_user.
        if _on_sign_in_page(page):
            notes.append("workday_auth: still Sign In before MI — retry Sign In fill")
            _clear_workday_login_wall(
                page,
                email=email,
                password=password,
                notes=notes,
                skipped=skipped,
                tenant_map_path=tenant_map_path,
            )
            if _advance_to_application_fields(page, notes):
                pass
            else:
                _park_before_application_fields(filled, skipped, notes, page)
                return
        else:
            _park_before_application_fields(filled, skipped, notes, page)
            return
    # Only now record auth success against UI truth
    filled.append({"label": "Email Address", "mapped_to": "email", "value": email, "method": "workday-auth"})
    filled.append({"label": "password", "mapped_to": "workday_password", "value": "[redacted]", "method": "workday-auth"})
    if tenant_map_path:
        remember_account(tenant_map_path, url, email)
        notes.append(f"workday account recorded for {tenant_map_path.name} (email only)")

    revisited_experience = False
    for step in range(12):
        if _captcha_or_2fa(page):
            notes.append("CAPTCHA or 2FA present — stopping at current step")
            return
        if not _clear_workday_login_wall(
            page,
            email=email,
            password=password,
            notes=notes,
            skipped=skipped,
            tenant_map_path=tenant_map_path,
        ):
            _park_before_application_fields(filled, skipped, notes, page)
            return
        # The stepper can be on screen while the step body is still the
        # soft-fail interstitial. Wait for fields, and refresh if the error
        # text is what actually painted.
        if not _advance_to_application_fields(page, notes):
            if _on_sign_in_page(page) and _clear_workday_login_wall(
                page,
                email=email,
                password=password,
                notes=notes,
                skipped=skipped,
                tenant_map_path=tenant_map_path,
            ) and _advance_to_application_fields(page, notes):
                pass
            else:
                return
        _fill_standard_fields(
            page,
            profile=profile,
            resume=resume,
            resume_path=resume_path,
            filled=filled,
            skipped=skipped,
            notes=notes,
            skip_keys=WORKDAY_SKIP_STANDARD,
        )
        from apply_engine.workday_widgets import fill_workday_sticky_fields

        job = resume.job if resume is not None else None
        fill_workday_sticky_fields(
            page,
            profile,
            filled,
            skipped,
            notes,
            experience=_work_history(pool_path, resume),
            job_title=(job.title if job else "") or "",
            job_text=" ".join(
                part
                for part in (
                    job.description if job else "",
                    job.url if job else "",
                    url,
                    " ".join(
                        note.removeprefix("workday posting term: ")
                        for note in notes
                        if str(note).startswith("workday posting term: ")
                    ),
                )
                if part
            ),
        )
        # Evidence of this step *while its fields are still on screen*. The
        # final screenshot lands on Review, where nothing is left to verify.
        _capture_step(page, screenshot_path, step_shots, step, notes, step_snapshots)
        if _on_review_page(page):
            if (
                not revisited_experience
                and _review_missing_history(page)
                and _open_my_experience_step(page, notes)
            ):
                revisited_experience = True
                notes.append("review has no education or work history — opening My Experience")
                continue
            notes.append(f"workday review page at step {step}")
            return
        # Fill can outrun the interstitial: the error text shows up after the
        # pre-fill wait, and there is no Next button underneath it.
        if _workday_error_page(page):
            notes.append(f"workday soft-fail page at step {step} — refreshing")
            if not _recover_workday_error(page, notes) or not _advance_to_application_fields(page, notes):
                notes.append("needs_user: workday error page did not clear")
                return
            continue
        if _workday_validation_blocked(page):
            notes.append("needs_user: Workday validation errors on this step — not clicking Next")
            return
        if not _click_next(page):
            page.wait_for_timeout(750)
            if _workday_error_page(page):
                notes.append(f"workday soft-fail page at step {step} — refreshing")
                if not _recover_workday_error(page, notes) or not _advance_to_application_fields(page, notes):
                    notes.append("needs_user: workday error page did not clear")
                    return
                continue
            notes.append(f"workday wizard: no Next after step {step}")
            if not _application_controls_visible(page):
                notes.append("needs_user: wizard step had no application fields")
            return
        page.wait_for_timeout(700)
    notes.append("workday wizard: reached max steps without a clear review heading")


def _capture_step(
    page: Any,
    screenshot_path: str | Path | None,
    step_shots: list | None,
    step: int,
    notes: list,
    step_snapshots: list | None = None,
) -> None:
    """Screenshot a wizard step before Next scrolls its fields out of existence."""
    if not screenshot_path or step_shots is None:
        return
    try:
        label = "my-information" if _my_information_visible_anywhere(page) else f"step-{step}"
        dest = Path(screenshot_path).parent / f"step-{step}-{label}.png"
        dest.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(dest), full_page=True)
        step_shots.append(str(dest))
        # Snapshot the values this screenshot actually shows, so the filled log
        # can be proved against the step where each field was visible.
        from apply_engine import readback as _readback

        rows = [r for r in _readback.capture(page) if r.get("visible")]
        if step_snapshots is not None:
            step_snapshots.append({"step": step, "screenshot": str(dest), "rows": rows})
    except Exception as exc:  # noqa: BLE001
        notes.append(f"step screenshot failed at step {step}: {exc}")


def _workday_auth(
    page: Any,
    *,
    url: str,
    email: str,
    password: str,
    filled: list,
    skipped: list,
    notes: list,
    tenant_map_path: Path | None,
) -> bool:
    from apply_engine.workday import auth_click_allowed, emails_match, known_account_email, prefer_sign_in

    _maybe_dismiss(page)
    root = _auth_scope(page)
    if not _auth_widgets_ready(root):
        notes.append("no Workday auth form on this page")
        return False

    verify_visible = _verify_password_visible(root)
    pw_count = len(_visible_password_inputs(root))
    create_mode = verify_visible or pw_count >= 2
    known = known_account_email(tenant_map_path, url) if tenant_map_path else None
    standalone = _on_sign_in_page(page) and not create_mode
    want_sign_in = prefer_sign_in(
        known=bool(known),
        verify_password_visible=verify_visible,
        visible_password_count=pw_count,
        standalone_sign_in=standalone,
    )
    # Never click Sign In first on a Create Account page — that opens the overlay
    # with an empty email (Motorola dd7478). Never click Sign In when Verify New
    # Password is showing. Standalone /private/login is always Sign In.

    if standalone:
        notes.append("workday_auth: standalone Sign In form — filling Sign In")
        if not _fill_and_submit_sign_in(page, email, password, notes, skipped):
            return False
        _wait_left_sign_in_page(page)
        notes.append("workday auth submitted (sign-in)")
        return True

    email_locators = _visible_auth_email_inputs(root)
    if not email_locators:
        skipped.append({"label": "Email Address*", "reason": "auth email field not found"})
        notes.append("workday_auth: email field not found")
        return False
    for loc in email_locators:
        if _locator_is_honeypot(loc):
            continue
        _fill_react_input(loc, email)
    email_readback = _input_value(email_locators[-1])
    if not emails_match(email_readback, email):
        skipped.append(
            {
                "label": "Email Address*",
                "reason": "auth email fill/readback failed — UI email empty",
                "readback": email_readback,
            }
        )
        notes.append("workday_auth: email readback did not match")
        return False
    # Do NOT append to filled yet — only record after we reach My Information
    # (9372e5: filled claimed email/password while screenshot showed empty Sign In).

    _fill_auth_passwords(root, password)
    password_ok, verify_ok = _password_fields_ok(root, need_verify=create_mode)
    if not password_ok:
        skipped.append({"label": "password", "reason": "password field empty after fill"})
        notes.append("workday_auth: password fields not filled")
        return False

    consent_visible = _consent_checkbox_visible(root)
    consent_checked = False
    if create_mode and consent_visible:
        consent_checked = _check_consent(root)
        if not consent_checked:
            skipped.append({"label": "consent", "reason": "consent checkbox not checked"})
            notes.append("workday_auth: consent checkbox not checked")
            return False

    if not auth_click_allowed(
        email_readback=email_readback,
        expected_email=email,
        create_mode=create_mode,
        password_filled=password_ok,
        verify_filled=verify_ok if create_mode else True,
        consent_visible=consent_visible,
        consent_checked=consent_checked if consent_visible else True,
    ):
        skipped.append({"label": "workday_auth", "reason": "auth widgets not ready — refusing Create Account/Sign In"})
        notes.append("workday_auth: refusing click without email/password/consent")
        return False

    # A tenant we have applied to before already has an account; Create Account
    # can only fail there. Switch the form over before submitting anything.
    if known and create_mode:
        if _switch_to_sign_in_form(page, notes):
            create_mode = False
            want_sign_in = True
            page.wait_for_timeout(800)
            root = _auth_scope(page)
            if not _fill_and_submit_sign_in(page, email, password, notes, skipped):
                return False
            page.wait_for_timeout(1500)
            notes.append("workday auth submitted (sign-in, known tenant)")
            return True

    clicked = _click_auth_button(root, prefer_sign_in=want_sign_in, create_mode=create_mode)
    if not clicked:
        skipped.append({"label": "workday_auth", "reason": "Create Account/Sign In button not found"})
        notes.append("Workday auth button not found")
        return False
    page.wait_for_timeout(1200)
    _maybe_dismiss(page)

    # After Create Account, Workday often lands on an empty Sign In page (9372e5).
    if _on_sign_in_page(page) and not _wait_my_information(page):
        notes.append("workday_auth: landed on Sign In after submit — filling Sign In")
        if not _fill_and_submit_sign_in(page, email, password, notes, skipped):
            return False
        page.wait_for_timeout(1200)

    # Create Account against an account that already exists just errors and
    # parks. Every tenant we have applied to before is in this state on the
    # second visit, and the accounts file is not reliable enough to predict it
    # (Walmart: verify-password visible forced create_mode, so Sign In was
    # never preferred). Detect the refusal and switch forms instead.
    if create_mode and not _my_information_visible_anywhere(page):
        if _auth_error_visible(page):
            notes.append("workday_auth: Create Account refused — switching to Sign In")
            if _switch_to_sign_in_form(page, notes) and _fill_and_submit_sign_in(
                page, email, password, notes, skipped
            ):
                page.wait_for_timeout(1500)

    notes.append("workday auth submitted (create or sign-in)")
    return True


# Workday renders auth failures ("account already exists", bad password) here.
AUTH_ERROR_SELECTORS = (
    '[data-automation-id="errorMessage"]',
    '[data-automation-id="alertMessage"]',
    '[role="alert"]',
)


def _auth_error_visible(page: Any) -> bool:
    """True when Workday is showing an auth error rather than advancing."""
    for scope in _iter_dom_scopes(page):
        for sel in AUTH_ERROR_SELECTORS:
            try:
                loc = scope.locator(sel)
                for i in range(min(loc.count(), 5)):
                    node = loc.nth(i)
                    if node.is_visible() and (node.inner_text() or "").strip():
                        return True
            except Exception:
                continue
    return False


def _switch_to_sign_in_form(page: Any, notes: list) -> bool:
    """Flip the Create Account form over to Sign In.

    Walmart's page offers "Already have an account? Sign In"; other tenants use
    a header Sign In button. Both land on the same form.
    """
    selectors = (
        '[data-automation-id="signInLink"]',
        '[data-automation-id="utilityButtonSignIn"]',
        'button:has-text("Sign In")',
        'a:has-text("Sign In")',
    )
    for scope in _iter_dom_scopes(page):
        for sel in selectors:
            try:
                loc = scope.locator(sel)
                for i in range(min(loc.count(), 4)):
                    node = loc.nth(i)
                    if not node.is_visible():
                        continue
                    node.click(timeout=3000)
                    page.wait_for_timeout(1500)
                    # The sign-in form has one password box and no verify box.
                    if not _verify_password_visible(page):
                        notes.append(f"workday_auth: switched to Sign In via {sel}")
                        return True
            except Exception:
                continue
    if _click_header_sign_in(page, notes):
        return True
    notes.append("workday_auth: could not switch to the Sign In form")
    return False


def _auth_form_present(page: Any) -> bool:
    """True only when email OR password widgets exist — a stepper heading is not a form."""
    return _auth_widgets_ready_anywhere(page)


def _auth_widgets_ready(scope: Any) -> bool:
    try:
        return bool(_visible_auth_email_inputs(scope)) or bool(_visible_password_inputs(scope))
    except Exception:
        return False


def _auth_widgets_ready_anywhere(page: Any) -> bool:
    for scope in _iter_dom_scopes(page):
        if _auth_widgets_ready(scope):
            return True
    return False


def _auth_scope(page: Any) -> Any:
    for scope in _iter_dom_scopes(page):
        if _auth_widgets_ready(scope):
            return scope
    return page


def _iter_dom_scopes(page: Any):
    yield page
    frames = getattr(page, "frames", None) or []
    main = getattr(page, "main_frame", None)
    for frame in frames:
        if frame is page or frame is main:
            continue
        yield frame


def _blank_auth_shell_flags(page: Any) -> dict:
    email_count = 0
    password_count = 0
    for scope in _iter_dom_scopes(page):
        email_count += len(_visible_auth_email_inputs(scope))
        password_count += len(_visible_password_inputs(scope))
    step_active = _create_signin_step_active(page)
    return {
        "step_active": step_active,
        "email_input_count": email_count,
        "password_input_count": password_count,
    }


def _create_signin_heading_visible(scope: Any) -> bool:
    try:
        heading = scope.get_by_role("heading", name=re.compile(r"create account|sign in", re.I))
        return bool(heading.count() and heading.first.is_visible())
    except Exception:
        return False


def _create_signin_step_active(page: Any) -> bool:
    try:
        text = page.evaluate(
            """() => {
              const cur = document.querySelector('[aria-current="step"], [aria-current="true"]');
              if (cur) return ((cur.innerText || cur.textContent || '') + ' ' + (cur.getAttribute('aria-label') || '')).trim();
              return '';
            }"""
        )
        label = str(text or "")
        if CREATE_SIGNIN_STEP_RE.search(label) and "my information" not in label.lower():
            return True
    except Exception:
        pass
    try:
        loc = page.locator('[aria-current="step"], [aria-current="true"]')
        if loc.count() and loc.first.is_visible():
            label = (loc.first.inner_text() or "") + " " + (loc.first.get_attribute("aria-label") or "")
            if CREATE_SIGNIN_STEP_RE.search(label) and "my information" not in label.lower():
                return True
    except Exception:
        pass
    return _create_signin_heading_visible(page)


def _ensure_workday_auth_widgets(page: Any, notes: list) -> bool:
    """Wait / SSO email / reload once / header Sign In when the Create Account shell is blank."""
    from apply_engine.workday import is_blank_auth_shell, should_reload_blank_auth_shell

    if _auth_widgets_ready_anywhere(page):
        return True
    if _my_information_visible_anywhere(page):
        return False

    if _reveal_workday_email_password(page, notes):
        return True

    flags = _blank_auth_shell_flags(page)
    blank = is_blank_auth_shell(
        step_active=bool(flags["step_active"]),
        email_input_count=int(flags["email_input_count"]),
        password_input_count=int(flags["password_input_count"]),
    )
    if blank:
        notes.append("workday_auth: blank Create Account/Sign In shell — waiting for widgets")
    else:
        notes.append("workday_auth: waiting for auth widgets to paint")

    if _wait_auth_widgets(page, AUTH_WIDGET_WAIT_MS):
        notes.append("workday_auth: auth widgets appeared after wait")
        return True

    page_url = ""
    try:
        page_url = page.url or ""
    except Exception:
        page_url = ""

    flags = _blank_auth_shell_flags(page)
    blank = is_blank_auth_shell(
        step_active=bool(flags["step_active"]),
        email_input_count=int(flags["email_input_count"]),
        password_input_count=int(flags["password_input_count"]),
    )
    already_reloaded = False
    if should_reload_blank_auth_shell(is_blank=blank, page_url=page_url, already_reloaded=already_reloaded):
        notes.append("workday_auth: reloading once to recover blank Create Account/Sign In shell")
        try:
            page.reload(wait_until="domcontentloaded")
        except Exception:
            pass
        already_reloaded = True
        page.wait_for_timeout(400)
        _maybe_dismiss(page)
        if _wait_auth_widgets(page, AUTH_WIDGET_RELOAD_WAIT_MS):
            notes.append("workday_auth: auth widgets appeared after reload")
            return True
    else:
        notes.append("workday_auth: skip reload (not a live Workday document or not blank)")

    if _auth_widgets_ready_anywhere(page):
        return True
    if _click_header_sign_in(page, notes):
        notes.append("workday_auth: clicked header Sign In to recover blank shell")
        if _wait_auth_widgets(page, AUTH_WIDGET_HEADER_WAIT_MS):
            notes.append("workday_auth: auth widgets appeared after header Sign In")
            return True
        if _reveal_workday_email_password(page, notes):
            return True

    if not _auth_widgets_ready_anywhere(page):
        notes.append("workday_auth: blank Create Account/Sign In shell refused — no widgets")
        return False
    return True


def _wait_auth_widgets(page: Any, timeout_ms: int) -> bool:
    deadline = time.monotonic() + max(timeout_ms, 0) / 1000.0
    while time.monotonic() < deadline:
        if _auth_widgets_ready_anywhere(page):
            return True
        remaining = int((deadline - time.monotonic()) * 1000)
        if remaining <= 0:
            break
        try:
            page.wait_for_selector(
                'input[type="password"], input[type="email"], input[data-automation-id="email"], iframe',
                timeout=min(400, remaining),
            )
        except Exception:
            pass
        page.wait_for_timeout(200)
    return _auth_widgets_ready_anywhere(page)


def _sign_in_with_email_locator(scope: Any) -> Any | None:
    """NVIDIA-style SSO modal: Google / LinkedIn / Sign in with email, no fields yet."""
    try:
        loc = scope.get_by_role("button", name=SIGN_IN_WITH_EMAIL_RE)
        if loc.count():
            return loc
    except Exception:
        pass
    try:
        loc = scope.get_by_role("link", name=SIGN_IN_WITH_EMAIL_RE)
        if loc.count():
            return loc
    except Exception:
        pass
    try:
        loc = scope.locator("button, a, [role=button]").filter(has_text=SIGN_IN_WITH_EMAIL_RE)
        if loc.count():
            return loc
    except Exception:
        pass
    return None


def _sign_in_with_email_visible(page: Any) -> bool:
    for scope in _iter_dom_scopes(page):
        loc = _sign_in_with_email_locator(scope)
        if loc is None:
            continue
        try:
            for i in range(min(loc.count(), 4)):
                node = loc.nth(i)
                if node.is_visible():
                    return True
        except Exception:
            continue
    return False


def _click_sign_in_with_email(page: Any, notes: list) -> bool:
    for scope in _iter_dom_scopes(page):
        loc = _sign_in_with_email_locator(scope)
        if loc is None:
            continue
        try:
            n = min(loc.count(), 4)
        except Exception:
            continue
        for i in range(n):
            node = loc.nth(i)
            try:
                if not node.is_visible():
                    continue
                text = (node.inner_text() or "").strip()[:80]
            except Exception:
                text = "Sign in with email"
            try:
                guarded_click(
                    node,
                    allow_submit=False,
                    allow_auth=True,
                    meta={"text": text or "Sign in with email", "role": "button"},
                )
                page.wait_for_timeout(600)
                notes.append(f"workday_auth: clicked Sign in with email ({text!r})")
                return True
            except Exception:
                try:
                    node.click(timeout=2000)
                    page.wait_for_timeout(600)
                    notes.append(f"workday_auth: clicked Sign in with email ({text!r})")
                    return True
                except Exception:
                    continue
    return False


def _reveal_workday_email_password(page: Any, notes: list) -> bool:
    """If the auth modal is SSO-only, click Sign in with email then wait for fields."""
    from apply_engine.workday import sso_email_gate_visible

    if _auth_widgets_ready_anywhere(page):
        return True
    email_count = 0
    password_count = 0
    for scope in _iter_dom_scopes(page):
        email_count += len(_visible_auth_email_inputs(scope))
        password_count += len(_visible_password_inputs(scope))
    if not sso_email_gate_visible(
        email_input_count=email_count,
        password_input_count=password_count,
        sign_in_with_email_visible=_sign_in_with_email_visible(page),
    ):
        return False
    notes.append("workday_auth: SSO gate (Google/LinkedIn/Sign in with email) — expanding email form")
    if not _click_sign_in_with_email(page, notes):
        notes.append("workday_auth: Sign in with email control not clickable")
        return False
    if _wait_auth_widgets(page, AUTH_WIDGET_WAIT_MS):
        notes.append("workday_auth: email/password fields appeared after Sign in with email")
        return True
    notes.append("workday_auth: Sign in with email clicked but fields did not appear")
    return False


def _my_information_visible(scope: Any) -> bool:
    try:
        loc = scope.get_by_role("heading", name=re.compile(r"my information", re.I))
        if loc.count() and loc.first.is_visible():
            return True
    except Exception:
        pass
    loc = scope.locator(
        '[data-automation-id="legalName--firstName"], [data-automation-id="legalNameSection_firstName"], input[name="first_name"]'
    )
    try:
        return bool(loc.count() and loc.first.is_visible())
    except Exception:
        return False


def _my_information_visible_anywhere(page: Any) -> bool:
    for scope in _iter_dom_scopes(page):
        if _my_information_visible(scope):
            return True
    return False


def _locator_is_honeypot(loc: Any) -> bool:
    meta = _control_meta(loc)
    try:
        label = _accessible_name(loc)
    except Exception:
        label = ""
    return is_honeypot(
        label=label,
        name=str(meta.get("name") or ""),
        automation_id=str(meta.get("automation_id") or ""),
        width=meta.get("width"),
        height=meta.get("height"),
    )


def _locator_fingerprint(loc: Any) -> str:
    try:
        return str(
            loc.evaluate(
                "el => [el.getAttribute('data-automation-id') || '', el.id || '', el.name || '', el.type || ''].join('|')"
            )
            or ""
        )
    except Exception:
        return str(id(loc))


def _collect_visible_inputs(page: Any, locators: list) -> list[Any]:
    out: list[Any] = []
    seen: set[str] = set()
    for loc in locators:
        try:
            n = loc.count()
        except Exception:
            n = 0
        for i in range(n):
            el = loc.nth(i)
            try:
                if not el.is_visible():
                    continue
            except Exception:
                continue
            if _locator_is_honeypot(el):
                continue
            fp = _locator_fingerprint(el)
            if fp in seen:
                continue
            seen.add(fp)
            out.append(el)
    return out


def _visible_password_inputs(page: Any) -> list[Any]:
    return _collect_visible_inputs(
        page,
        [
            page.locator('input[data-automation-id="password"]'),
            page.locator("input[type=password]"),
        ],
    )


def _verify_password_visible(page: Any) -> bool:
    for scope in _iter_dom_scopes(page):
        try:
            loc = scope.get_by_label(VERIFY_PASSWORD_RE)
            if loc.count() and loc.first.is_visible():
                return True
        except Exception:
            pass
        try:
            loc = scope.get_by_text(VERIFY_PASSWORD_RE)
            if loc.count() and loc.first.is_visible():
                return True
        except Exception:
            continue
    return False


def _visible_auth_email_inputs(page: Any) -> list[Any]:
    return _collect_visible_inputs(
        page,
        [
            page.locator('input[data-automation-id="email"]'),
            page.locator('input[type="email"]'),
            page.get_by_label(EMAIL_ADDRESS_RE),
            page.get_by_label(re.compile(r"^e-?mail", re.I)),
        ],
    )


def _fill_react_input(locator: Any, value: str) -> None:
    try:
        locator.click(timeout=3000)
    except Exception:
        pass
    try:
        locator.fill("")
        locator.fill(value, timeout=4000)
    except Exception:
        pass
    try:
        locator.evaluate(REACT_SET_VALUE, value)
    except Exception:
        pass


def _input_value(locator: Any) -> str:
    try:
        return (locator.input_value() or "").strip()
    except Exception:
        try:
            return str(locator.evaluate("el => (el.value || '').trim()") or "")
        except Exception:
            return ""


def _fill_auth_passwords(page: Any, password: str) -> None:
    for loc in _visible_password_inputs(page):
        if _locator_is_honeypot(loc):
            continue
        _fill_react_input(loc, password)


def _password_fields_ok(page: Any, *, need_verify: bool) -> tuple[bool, bool]:
    values: list[str] = []
    for loc in _visible_password_inputs(page):
        values.append(_input_value(loc))
    password_filled = bool(values) and all(bool(v) for v in values)
    if not values:
        return False, False
    if need_verify:
        verify_filled = len(values) >= 2 and all(values)
        return password_filled, verify_filled
    return password_filled, True


def _consent_checkbox_visible(page: Any) -> bool:
    loc = _consent_locator(page)
    if loc is None:
        return False
    try:
        return loc.is_visible()
    except Exception:
        return False


def _consent_locator(page: Any) -> Any | None:
    try:
        loc = page.get_by_label(CONSENT_RE)
        if loc.count() and loc.first.is_visible():
            return loc.first
    except Exception:
        pass
    try:
        text = page.get_by_text(CONSENT_RE)
        if text.count():
            wrap = text.first.locator("xpath=ancestor::label[1]")
            box = wrap.locator('input[type="checkbox"]')
            if box.count() and box.first.is_visible():
                return box.first
    except Exception:
        pass
    try:
        boxes = page.locator('input[type="checkbox"]')
        for i in range(min(boxes.count(), 12)):
            el = boxes.nth(i)
            if not el.is_visible():
                continue
            label = (el.get_attribute("aria-label") or "") + " " + _accessible_name(el)
            if CONSENT_RE.search(label):
                return el
    except Exception:
        pass
    return None


def _check_consent(page: Any) -> bool:
    loc = _consent_locator(page)
    if loc is None:
        return False
    try:
        loc.check(timeout=3000)
    except Exception:
        try:
            loc.click(timeout=3000)
        except Exception:
            return False
    try:
        return bool(loc.is_checked())
    except Exception:
        return False


def _role_heading_visible(scope: Any, pattern: re.Pattern) -> bool:
    try:
        heading = scope.get_by_role("heading", name=pattern)
        return bool(heading.count() and heading.first.is_visible())
    except Exception:
        return False


def _auth_submit_visible(page: Any, name: str) -> bool:
    for scope in _iter_dom_scopes(page):
        for aid in AUTH_SUBMIT_AIDS.get(name, ()):
            try:
                loc = scope.locator(f'button[data-automation-id="{aid}"]')
                for i in range(min(loc.count(), 3)):
                    if loc.nth(i).is_visible():
                        return True
            except Exception:
                continue
        try:
            loc = scope.get_by_role("button", name=re.compile(rf"^{re.escape(name)}$", re.I))
            for i in range(min(loc.count(), 3)):
                if loc.nth(i).is_visible():
                    return True
        except Exception:
            continue
    return False


def _standalone_sign_in_flags(page: Any) -> dict:
    try:
        url = page.url or ""
    except Exception:
        url = ""
    heading_sign_in = False
    heading_create_account = False
    email_count = 0
    pw_count = 0
    for scope in _iter_dom_scopes(page):
        if _role_heading_visible(scope, re.compile(r"^sign in$", re.I)):
            heading_sign_in = True
        if _role_heading_visible(scope, re.compile(r"^create account", re.I)):
            heading_create_account = True
        email_count += len(_visible_auth_email_inputs(scope))
        pw_count += len(_visible_password_inputs(scope))
    return {
        "url": url,
        "heading_sign_in": heading_sign_in,
        "heading_create_account": heading_create_account,
        "verify_password_visible": _verify_password_visible(page),
        "visible_password_count": pw_count,
        "email_visible": email_count > 0,
        "sign_in_submit_visible": _auth_submit_visible(page, "Sign In"),
        "create_account_submit_visible": _auth_submit_visible(page, "Create Account"),
    }


def _on_sign_in_page(page: Any) -> bool:
    from apply_engine.workday import looks_like_standalone_sign_in

    return looks_like_standalone_sign_in(**_standalone_sign_in_flags(page))


def _wait_left_sign_in_page(page: Any, timeout_ms: int = SIGN_IN_REDIRECT_WAIT_MS) -> bool:
    from apply_engine.workday import is_standalone_sign_in_url

    deadline = time.monotonic() + max(timeout_ms, 0) / 1000.0
    while time.monotonic() < deadline:
        if _my_information_visible_anywhere(page) or _application_controls_visible(page) or _on_review_page(page):
            return True
        if not _on_sign_in_page(page):
            try:
                if not is_standalone_sign_in_url(page.url or ""):
                    return True
            except Exception:
                return True
            return True
        page.wait_for_timeout(250)
    return (
        not _on_sign_in_page(page)
        or _my_information_visible_anywhere(page)
        or _application_controls_visible(page)
    )


def _clear_workday_login_wall(
    page: Any,
    *,
    email: str,
    password: str,
    notes: list,
    skipped: list,
    tenant_map_path: Path | None = None,
) -> bool:
    """Fill standalone Workday Sign In when a login wall is showing.

    Returns True when we are not stuck on Sign In (never were, or signed in).
    Returns False if the wall is still up after attempting Sign In.
    Never invents a password; caller passes WORKDAY_DEFAULT_PASSWORD.
    """
    from apply_engine.workday import is_standalone_sign_in_url, known_account_email

    try:
        url = page.url or ""
    except Exception:
        url = ""
    on_login_url = is_standalone_sign_in_url(url)
    if not on_login_url and not _on_sign_in_page(page):
        return True
    if _verify_password_visible(page) or len(_visible_password_inputs(page)) >= 2:
        return True
    if not _auth_widgets_ready_anywhere(page):
        notes.append("workday_auth: Sign In wall — waiting for widgets")
        _wait_auth_widgets(page, AUTH_WIDGET_WAIT_MS)
    if not _auth_widgets_ready_anywhere(page):
        if _reveal_workday_email_password(page, notes):
            pass
    if not _auth_widgets_ready_anywhere(page):
        if on_login_url:
            notes.append("workday_auth: standalone Sign In URL but no email/password widgets")
            return False
        return True
    if known_account_email(tenant_map_path, url) if tenant_map_path else None:
        notes.append("workday_auth: known tenant — Sign In (not Create Account)")
    notes.append("workday_auth: filling standalone Sign In wall")
    if not _fill_and_submit_sign_in(page, email, password, notes, skipped):
        return False
    if _wait_left_sign_in_page(page):
        notes.append("workday_auth: left standalone Sign In")
        return True
    blocker = _workday_blocker(page)
    if blocker:
        notes.append(f"needs_user: {blocker}")
    else:
        notes.append("workday_auth: still on Sign In after submit")
    return False


def _fill_and_submit_sign_in(page: Any, email: str, password: str, notes: list, skipped: list) -> bool:
    from apply_engine.workday import emails_match

    _maybe_dismiss(page)
    if not _auth_widgets_ready_anywhere(page):
        _reveal_workday_email_password(page, notes)
    root = _auth_scope(page)
    email_locs = _visible_auth_email_inputs(root)
    if not email_locs:
        skipped.append({"label": "Email Address*", "reason": "Sign In email field not found"})
        notes.append("workday_auth: Sign In email field missing")
        return False
    for loc in email_locs:
        if _locator_is_honeypot(loc):
            continue
        _fill_react_input(loc, email)
    email_readback = _input_value(email_locs[-1])
    if not emails_match(email_readback, email):
        skipped.append({
            "label": "Email Address*",
            "reason": "Sign In email readback failed — UI still empty",
            "readback": email_readback,
        })
        notes.append(f"workday_auth: Sign In email readback {email_readback!r}")
        return False
    _fill_auth_passwords(root, password)
    password_ok, _ = _password_fields_ok(root, need_verify=False)
    if not password_ok:
        skipped.append({"label": "password", "reason": "Sign In password empty after fill"})
        return False
    email_readback = _input_value(email_locs[-1])
    if not emails_match(email_readback, email):
        skipped.append({"label": "Email Address*", "reason": "Sign In email cleared before click", "readback": email_readback})
        return False
    if not _click_auth_button(page, prefer_sign_in=True, create_mode=False):
        skipped.append({"label": "workday_auth", "reason": "Sign In button not found"})
        return False
    notes.append("workday_auth: Sign In submitted with email readback ok")
    return True



def _wait_my_information(page: Any) -> bool:
    try:
        page.get_by_role("heading", name=re.compile(r"my information", re.I)).first.wait_for(
            state="visible", timeout=8000
        )
        return True
    except Exception:
        pass
    loc = page.locator(
        '[data-automation-id="legalName--firstName"], [data-automation-id="legalNameSection_firstName"], input[name="first_name"]'
    )
    try:
        if loc.count() and loc.first.is_visible():
            return True
    except Exception:
        pass
    return False


def _visible_auth_form(page: Any) -> Any | None:
    forms = page.locator("form").filter(has=page.locator('input[type="password"]'))
    try:
        n = forms.count()
    except Exception:
        n = 0
    for i in range(n):
        form = forms.nth(i)
        try:
            if form.is_visible():
                return form
        except Exception:
            continue
    return None


def _click_through_filter(page: Any, locator: Any, *, meta: dict | None = None,
                          allow_auth: bool = False, allow_submit: bool = False) -> bool:
    """Click a Workday control that sits under a click_filter overlay.

    Workday covers its auth buttons with
    `<div data-automation-id="click_filter">`. elementFromPoint over the Sign In
    button returns that div, so an ordinary Playwright click never lands and
    times out after the actionability wait. Measured against live Walmart:

        normal click            -> timeout, still on /login
        el.click() in JS        -> silently ignored (untrusted event)
        click the filter div    -> signed in
        click(force=True)       -> signed in

    So: try the honest click, then the overlay, then force. The submit guard
    runs on the real control every time -- the overlay never bypasses it.
    """
    meta = meta or {}
    try:
        guarded_click(locator, allow_submit=allow_submit, allow_auth=allow_auth, meta=meta)
        return True
    except SubmitBlockedError:
        raise
    except Exception:
        pass

    # The guard has to pass before we go looking for a way around the overlay.
    if not allow_submit:
        info = {
            "type_attr": meta.get("type_attr", ""),
            "text": meta.get("text", ""),
            "aria": meta.get("aria", ""),
            "name": meta.get("name", ""),
            "role": meta.get("role", ""),
        }
        if is_submit_control(**info) and not (allow_auth and is_auth_control(info["text"], info["aria"])):
            raise SubmitBlockedError(f"blocked submit click on {info!r}")

    for scope in _iter_dom_scopes(page):
        try:
            shield = scope.locator('[data-automation-id="click_filter"]')
            for i in range(min(shield.count(), 3)):
                node = shield.nth(i)
                if node.is_visible():
                    node.click(timeout=4000)
                    return True
        except Exception:
            continue
    try:
        locator.click(force=True, timeout=4000)
        return True
    except Exception:
        return False


# Workday names its auth submit buttons precisely. Matching on the visible text
# instead is ambiguous: "Create Account" is also the stepper label
# ("Create Account/Sign In") and the link that switches the form over, so a
# role+name click can report success having pressed a link that submits nothing
# (live Walmart: the form sat filled, unsubmitted, and auth claimed success).
AUTH_SUBMIT_AIDS = {
    "Create Account": ("createAccountSubmitButton",),
    "Sign In": ("signInSubmitButton",),
}


def _click_auth_button(page: Any, *, prefer_sign_in: bool, create_mode: bool = False) -> bool:
    if create_mode:
        names = ("Create Account",)
    elif prefer_sign_in:
        names = ("Sign In",)
    else:
        names = ("Create Account",)

    # Exact automation id first.
    for name in names:
        for aid in AUTH_SUBMIT_AIDS.get(name, ()):
            for scope in _iter_dom_scopes(page):
                try:
                    loc = scope.locator(f'button[data-automation-id="{aid}"]')
                    for i in range(min(loc.count(), 3)):
                        btn = loc.nth(i)
                        if not btn.is_visible():
                            continue
                        if _click_through_filter(
                            page,
                            btn,
                            meta={"text": name, "type_attr": "submit", "role": "button"},
                            allow_auth=True,
                        ):
                            return True
                except SubmitBlockedError:
                    raise
                except Exception:
                    continue

    form = _visible_auth_form(page)
    for name in names:
        scopes = []
        if form is not None:
            scopes.append(form)
        scopes.append(page)
        for scope in scopes:
            loc = scope.get_by_role("button", name=re.compile(rf"^{re.escape(name)}$", re.I))
            try:
                n = loc.count()
            except Exception:
                n = 0
            for i in range(n):
                btn = loc.nth(i)
                try:
                    if not btn.is_visible():
                        continue
                except Exception:
                    continue
                if _click_through_filter(
                    page,
                    btn,
                    meta={"text": name, "type_attr": "submit", "role": "button"},
                    allow_auth=True,
                ):
                    return True
                continue
    return False


def _click_next(page: Any) -> bool:
    loc = page.locator('[data-automation-id="bottom-navigation-next-button"]')
    try:
        if loc.count() and loc.first.is_visible():
            # Same click_filter overlay as the auth buttons can sit over Next.
            if _click_through_filter(
                page,
                loc.first,
                meta={"text": "Next", "type_attr": "button", "role": "button"},
            ):
                return True
    except SubmitBlockedError:
        raise
    except Exception:
        pass
    named = page.get_by_role(
        "button",
        name=re.compile(r"^(next|continue|save and continue|save & continue)$", re.I),
    )
    try:
        count = named.count()
    except Exception:
        count = 0
    for i in range(count - 1, -1, -1):
        btn = named.nth(i)
        try:
            if not btn.is_visible():
                continue
            btn.click(timeout=3000)
            return True
        except Exception:
            continue
    for btn in page.get_by_role("button").all()[:80]:
        try:
            text = (btn.inner_text() or "").strip()
        except Exception:
            continue
        if is_submit_control(text=text):
            continue
        if is_auth_control(text):
            continue
        if is_next_control(text):
            try:
                btn.click(timeout=3000)
                return True
            except Exception:
                return False
    return False


def _review_missing_history(page: Any) -> bool:
    try:
        body = (page.inner_text("body") or "").lower()
    except Exception:
        return False
    return "no education" in body or "no work experience" in body


def _open_my_experience_step(page: Any, notes: list) -> bool:
    """Saved drafts reopen on Review. The experience step is already visited, so it is clickable."""
    pattern = re.compile(r"my experience", re.I)
    for role in ("button", "link"):
        loc = page.get_by_role(role, name=pattern)
        try:
            count = min(loc.count(), 4)
        except Exception:
            count = 0
        for i in range(count):
            el = loc.nth(i)
            try:
                if not el.is_visible():
                    continue
                el.click(timeout=3000)
                page.wait_for_timeout(800)
                if not _on_review_page(page):
                    return True
            except Exception:
                continue
    notes.append("could not open My Experience from the review stepper")
    return False


def _on_review_page(page: Any) -> bool:
    loc = page.get_by_role("heading", name=re.compile(r"review", re.I))
    try:
        if loc.count() and loc.first.is_visible():
            return True
    except Exception:
        pass
    try:
        vis = page.get_by_text("Review your application")
        if vis.count() and vis.first.is_visible():
            return True
    except Exception:
        pass
    return False


def _captcha_or_2fa(page: Any) -> bool:
    try:
        body = (page.inner_text("body") or "").lower()
    except Exception:
        return False
    needles = ("recaptcha", "verify you are human", "two-factor", "two factor", "enter the code we sent", "authenticator")
    return any(n in body for n in needles)


def _captcha_or_cloudflare(page: Any) -> bool:
    """True when a human challenge is blocking submit (do not fake-click)."""
    if _captcha_or_2fa(page):
        return True
    try:
        body = (page.inner_text("body") or "").lower()
    except Exception:
        body = ""
    needles = (
        "cf-turnstile",
        "cloudflare",
        "checking your browser",
        "just a moment",
        "attention required",
        "verify you are human",
        "hcaptcha",
    )
    if any(n in body for n in needles):
        return True
    try:
        if page.locator("iframe[src*='recaptcha'], iframe[src*='hcaptcha'], iframe[src*='turnstile'], .cf-turnstile, #cf-challenge").count():
            # Visible challenge widgets only — hidden g-recaptcha-response alone is OK.
            for sel in (
                "iframe[src*='recaptcha']",
                "iframe[src*='hcaptcha']",
                "iframe[src*='turnstile']",
                ".cf-turnstile",
                "#cf-challenge",
            ):
                loc = page.locator(sel)
                for i in range(min(loc.count(), 3)):
                    try:
                        if loc.nth(i).is_visible():
                            return True
                    except Exception:
                        continue
    except Exception:
        pass
    return False


def _is_password_locator(loc: Any) -> bool:
    try:
        return str(loc.evaluate("el => (el.type || '').toLowerCase()")) == "password"
    except Exception:
        return False


def _locator_type(loc: Any) -> dict:
    try:
        return loc.evaluate(
            """el => ({
                tag: el.tagName.toLowerCase(),
                type: (el.type || '').toLowerCase(),
                options: el.tagName === 'SELECT' ? [...el.options].map(o => o.text.trim()) : []
            })"""
        )
    except Exception:
        return {"tag": "input", "type": "text", "options": []}



def _application_form_scope(page: Any) -> Any:
    """Prefer the visible application form so hidden/how-heard widgets are not filled."""
    selectors = (
        "form#application-form",
        "form#application",
        "form[id*='application' i]",
        "form[action*='application' i]",
        "#application-form",
        "[data-testid='application-form']",
        "form.application-form",
        "main form",
        "form",
    )
    for sel in selectors:
        loc = page.locator(sel)
        try:
            n = min(loc.count(), 6)
        except Exception:
            continue
        for i in range(n):
            cand = loc.nth(i)
            try:
                if cand.is_visible():
                    return cand
            except Exception:
                continue
    return page


def _control_meta(loc: Any) -> dict:
    try:
        return loc.evaluate(
            """el => ({
                tag: (el.tagName || '').toLowerCase(),
                type: (el.type || '').toLowerCase(),
                role: (el.getAttribute('role') || '').toLowerCase(),
                hidden: !!(el.hidden || el.type === 'hidden'
                           || (el.getAttribute('aria-hidden') === 'true')),
                visible: !!(el.offsetParent !== null || el.getClientRects().length),
                name: el.getAttribute('name') || '',
                automation_id: el.getAttribute('data-automation-id') || '',
                width: Math.round(el.getBoundingClientRect().width),
                height: Math.round(el.getBoundingClientRect().height)
            })"""
        )
    except Exception:
        return {
            "tag": "input", "type": "text", "role": "", "hidden": False, "visible": True,
            "name": "", "automation_id": "", "width": None, "height": None,
        }


def _is_fillable_url_control(loc: Any) -> bool:
    meta = _control_meta(loc)
    if meta.get("hidden"):
        return False
    try:
        if hasattr(loc, "is_visible") and not loc.is_visible():
            return False
    except Exception:
        pass
    return is_url_capable_control(meta.get("tag") or "", meta.get("type") or "", meta.get("role") or "")


def _write_url_locator(page: Any, loc: Any, value: str) -> tuple[bool, str]:
    """Clear stale value, type the full URL, blur — avoid phone/option-id bleed stickiness."""
    meta = _control_meta(loc)
    if not is_url_capable_control(meta.get("tag") or "", meta.get("type") or "", meta.get("role") or ""):
        return False, "skip-non-url-control"
    try:
        loc.click(timeout=3000)
    except Exception:
        pass
    try:
        loc.fill("", timeout=3000)
    except Exception:
        try:
            loc.evaluate("(el) => { el.value = ''; el.dispatchEvent(new Event('input', {bubbles:true})); }")
        except Exception:
            pass
    try:
        loc.fill(value, timeout=5000)
        try:
            loc.evaluate(
                """el => {
                  el.dispatchEvent(new Event('input', { bubbles: true }));
                  el.dispatchEvent(new Event('change', { bubbles: true }));
                  el.blur();
                }"""
            )
        except Exception:
            pass
        return True, "url-fill"
    except Exception:
        try:
            loc.click(timeout=2000)
            loc.fill(value, timeout=5000)
            return True, "url-fill"
        except Exception:
            return False, "fail"


def _find_by_aliases(page: Any, aliases: tuple[str, ...], contains: bool = False, key: str = "") -> Any | None:
    root = _application_form_scope(page)
    url_key = is_url_profile_key(key)

    def _accept(loc: Any) -> bool:
        if loc is None:
            return False
        try:
            aname = _accessible_name(loc)
        except Exception:
            aname = ""
        if is_noise_field(aname):
            return False
        # Bot traps look like ordinary fields to a label matcher. Walmart's
        # Workday auth ships one named `website` that maps cleanly to the
        # profile's website key; filling it flags the application as a bot.
        meta_hp = _control_meta(loc)
        if is_honeypot(
            label=aname,
            name=str(meta_hp.get("name") or ""),
            automation_id=str(meta_hp.get("automation_id") or ""),
            width=meta_hp.get("width"),
            height=meta_hp.get("height"),
        ):
            return False
        if key == "location" and aname:
            from apply_engine.util import normalize_label

            if normalize_label(aname) in {"locations", "departments", "please choose the location(s)", "please choose the department(s)"}:
                return False
        if url_key:
            return _is_fillable_url_control(loc)
        # Prefer visible controls when possible; fall back to first match.
        try:
            if hasattr(loc, "is_visible") and not loc.is_visible():
                meta = _control_meta(loc)
                if meta.get("hidden") or meta.get("type") == "hidden":
                    return False
        except Exception:
            pass
        return True

    if key:
        for aid in WD_AUTOMATION_IDS.get(key, ()):
            loc = root.locator(f'[data-automation-id="{aid}"]')
            try:
                n = loc.count()
            except Exception:
                n = 0
            for i in range(min(n, 8)):
                cand = loc.nth(i)
                if _accept(cand):
                    return cand
        wrapped = _find_in_form_field_wrapper(root, key, _accept)
        if wrapped is not None:
            return wrapped
    if key == "full_name":
        loc = root.locator("#_systemfield_name, input[name='_systemfield_name']")
        try:
            if loc.count() and _accept(loc.first):
                return loc.first
        except Exception:
            pass
    for alias in aliases:
        if contains:
            pattern = re.compile(re.escape(alias), re.I)
        else:
            pattern = re.compile(
                rf"^{re.escape(alias)}(\s*\*?|:.*|\s+profile|\s+url|\s+address|\s+number)?$",
                re.I,
            )
        try:
            loc = root.get_by_label(pattern)
            n = loc.count()
        except Exception:
            n = 0
        for i in range(min(n, 12)):
            cand = loc.nth(i)
            if _accept(cand):
                return cand
        slug = alias.replace(" ", "_")
        loc = root.locator(
            f"input[name='{slug}'], textarea[name='{slug}'], select[name='{slug}'], "
            f"input#{slug}, textarea#{slug}, select#{slug}"
        )
        try:
            n = loc.count()
        except Exception:
            n = 0
        for i in range(min(n, 8)):
            cand = loc.nth(i)
            if _accept(cand):
                return cand
    return None



def _prune_skipped_if_filled(filled: list, skipped: list) -> None:
    """Drop skip rows later filled successfully (standard-pass miss → open-ended retry)."""
    from apply_engine.util import normalize_label

    filled_keys = {str(r.get("mapped_to") or "") for r in filled if r.get("mapped_to")}
    filled_labels = {normalize_label(str(r.get("label") or "")) for r in filled}
    keep: list = []
    for row in skipped:
        label = str(row.get("label") or "")
        mapped = str(row.get("mapped_to") or "")
        if mapped and mapped in filled_keys:
            continue
        if normalize_label(label) in filled_labels:
            continue
        # Alias label "sponsorship" vs DOM "Do you require work authorization?"
        if any(
            normalize_label(label) in normalize_label(str(fr.get("label") or ""))
            or normalize_label(str(fr.get("label") or "")) in normalize_label(label)
            for fr in filled
            if fr.get("mapped_to") in {
                "need_sponsorship",
                "sponsorship_type",
                "how_heard",
                "policy_ack",
                "state",
                "location",
                "previous_employee",
                "export_license",
            }
        ):
            # Only prune when the skip looks like the same question family.
            low = normalize_label(label)
            if any(
                tok in low
                for tok in (
                    "sponsor",
                    "authorization",
                    "how did you hear",
                    "acknowledge",
                    "artificial intelligence",
                    "outside assistance",
                    "privacy",
                    "reside",
                    "location",
                    "alphabet",
                    "export license",
                    "opacity",
                    "color",
                    "font",
                )
            ):
                continue
        keep.append(row)
    skipped[:] = keep


def _record_widget_filled(
    filled: list,
    skipped: list,
    loc: Any,
    *,
    label: str,
    mapped_to: str,
    intended: str,
    method: str,
    key: str = "",
    intended_terms: list[str] | None = None,
) -> bool:
    """Count a field as filled only if the widget value after settle matches. Log that readback."""
    from apply_engine.fields import looks_like_phone_or_id_bleed
    from apply_engine.workday_widgets import phone_digits_match, readback_committed, widget_readback

    observed = widget_readback(loc)
    terms = [t for t in (intended_terms or [intended]) if t]
    stuck = False
    if key == "phone":
        stuck = phone_digits_match(observed, intended)
    elif is_url_profile_key(key):
        stuck = url_readback_matches(observed, intended)
    else:
        for term in terms or [intended]:
            if select_readback_matches(observed, term, key=key):
                stuck = True
                break
        if not stuck:
            stuck = readback_committed(observed, terms or ([intended] if intended else []))
    if stuck:
        filled.append({"label": label, "mapped_to": mapped_to, "value": observed, "method": method})
        return True
    reason = f"readback {observed!r} did not stick (intended {intended!r})"
    if is_url_profile_key(key) and looks_like_phone_or_id_bleed(observed):
        reason = (
            f"url readback looks like phone/option-id bleed {observed!r} "
            f"(intended {intended!r}) — wrong control or sticky fail"
        )
    skipped.append(
        {
            "label": label,
            "reason": reason,
            "readback": observed,
        }
    )
    return False


def _write_locator(page: Any, loc: Any, value: str | list[str]) -> tuple[bool, str]:
    values = [v for v in (value if isinstance(value, list) else [value]) if str(v or "").strip()]
    if not values:
        return False, "fail"
    try:
        info = loc.evaluate(
            """el => ({
                tag: el.tagName.toLowerCase(),
                type: (el.type || '').toLowerCase(),
                options: el.tagName === 'SELECT' ? [...el.options].map(o => o.text.trim()) : []
            })"""
        )
    except Exception:
        info = {"tag": "input", "type": "text", "options": []}
    try:
        if info.get("type") == "password":
            return False, "skip-password"
        if info.get("tag") == "select" or info.get("options"):
            options = info.get("options") or []
            for cand in values:
                picked = pick_select_option(options, cand)
                if picked:
                    try:
                        loc.select_option(label=picked, timeout=5000)
                        return True, "select"
                    except Exception:
                        try:
                            loc.select_option(value=picked, timeout=5000)
                            return True, "select"
                        except Exception:
                            continue
        # Prefer first candidate for free-text fills.
        primary = values[0]
        loc.fill(primary, timeout=5000)
        try:
            loc.evaluate(
                """el => {
                  el.dispatchEvent(new Event('input', { bubbles: true }));
                  el.dispatchEvent(new Event('change', { bubbles: true }));
                  el.blur();
                }"""
            )
        except Exception:
            pass
        return True, "fill"
    except Exception:
        try:
            loc.click(timeout=2000)
            loc.fill(values[0], timeout=5000)
            return True, "fill"
        except Exception:
            return False, "fail"


def _fill_open_ended(
    page: Any,
    profile: Profile,
    resume: TailoredResume,
    filled: list,
    skipped: list,
    claimed: set[str],
    skip_keys: set[str] | None = None,
) -> None:
    skip_keys = skip_keys or set()
    fields = page.evaluate(JS_FIELDS)
    for field in fields:
        ftype = field.get("type") or ""
        if ftype in {"hidden", "file", "submit", "button", "checkbox", "radio"}:
            continue
        label = field.get("label") or field.get("placeholder") or field.get("name") or ""
        name = field.get("name") or ""
        eid = field.get("id") or ""
        placeholder = field.get("placeholder") or ""
        if is_noise_field(label, name, eid, placeholder) or field.get("hidden"):
            continue
        mapped = map_field(label, name, eid, placeholder)
        if mapped and mapped in skip_keys:
            continue
        if mapped and mapped in claimed and mapped != "policy_ack":
            continue
        # Grounded mapped questions (Waymo sponsorship / how-heard / AI ack / state, etc.).
        if mapped and mapped not in {"resume", "cover_letter"} and mapped != "gpa":
            value = profile_value(profile, mapped)
            if value is None:
                # Do not invent essays / unknown enums — leave for optional skip only when required-looking.
                if mapped in {
                    "need_sponsorship",
                    "sponsorship_type",
                    "how_heard",
                    "policy_ack",
                    "previous_employee",
                    "export_license",
                    "state",
                    "location",
                    "full_name",
                    "graduation_month",
                    "graduation_year",
                }:
                    skipped.append({"label": label or mapped, "reason": "no profile value"})
                continue
            loc = _locator_for_field(page, field)
            if not loc:
                continue
            candidates = value_candidates(mapped, value, profile)
            ok, method = _write_locator(page, loc, candidates)
            if _record_widget_filled(
                filled,
                skipped,
                loc,
                label=label or mapped,
                mapped_to=mapped,
                intended=candidates[0] if candidates else value,
                method=method if ok else "fail",
                key=mapped,
                intended_terms=candidates,
            ):
                # Privacy + AI ack both map to policy_ack — allow multiple widgets.
                if mapped != "policy_ack":
                    claimed.add(mapped)
            continue
        if mapped == "cover_letter" or looks_open_ended(label):
            low_label = (label or field.get("name") or "").lower()
            # Hidden reCAPTCHA textarea is filled by Google on submit — do not skip/block.
            if "recaptcha" in low_label or "g-recaptcha" in low_label:
                continue
            text = answer_open_ended(label or "cover letter", profile, resume)
            loc = _locator_for_field(page, field)
            if not loc:
                continue
            if not text:
                skipped.append({"label": label, "reason": "no grounded answer"})
                continue
            ok, method = _write_locator(page, loc, text)
            if ok:
                from apply_engine.workday_widgets import widget_readback

                observed = widget_readback(loc) or ""
                if observed.strip():
                    filled.append(
                        {
                            "label": label,
                            "mapped_to": mapped or "open_ended",
                            "value": observed[:80],
                            "method": method,
                        }
                    )
                else:
                    skipped.append({"label": label, "reason": "open-ended readback empty"})
            continue
        if not mapped:
            low = (label or field.get("name") or "").lower()
            if "recaptcha" in low or low in {"search"}:
                continue
            clean = (label or "").strip().rstrip("*").strip()
            if AUTH_FIELD_LABELS.match(clean):
                continue  # create-account auth — handled by _workday_auth
            skipped.append({"label": label or field.get("name") or "unknown", "reason": "unmapped"})


def _locator_for_field(page: Any, field: dict) -> Any | None:
    # Prefer [id="..."] — Ashby/UUID ids often start with a digit and break #id CSS.
    if field.get("id"):
        fid = str(field["id"])
        loc = page.locator('[id="' + fid.replace("\\", "\\\\").replace('"', '\\"') + '"]')
        try:
            if loc.count():
                return loc.first
        except Exception:
            pass
    if field.get("name"):
        name = str(field["name"]).replace("'", "\\'")
        loc = page.locator(f"[name='{name}']")
        try:
            if loc.count():
                return loc.first
        except Exception:
            pass
    return None


def _accessible_name(loc: Any) -> str:
    try:
        return str(
            loc.evaluate(
                """el => {
                  if (el.labels && el.labels[0]) return el.labels[0].innerText.trim();
                  return el.getAttribute('aria-label') || el.name || el.id || '';
                }"""
            )
            or ""
        )
    except Exception:
        return ""



def _ashby_job_missing(page: Any) -> bool:
    try:
        body = (page.inner_text("body") or "").strip().lower()
    except Exception:
        return False
    if "job not found" in body:
        return True
    if "the job you requested was not found" in body:
        return True
    return False


def _ashby_form_ready(page: Any) -> bool:
    """True when the apply form is interactable (not a hidden JD shell stub)."""
    try:
        url = (page.url or "").lower()
    except Exception:
        url = ""

    def _any_visible(sel: str) -> bool:
        loc = page.locator(sel)
        try:
            n = loc.count()
        except Exception:
            return False
        for i in range(min(n, 6)):
            try:
                if loc.nth(i).is_visible():
                    return True
            except Exception:
                continue
        return False

    if "/application" in url and (
        _any_visible("#_systemfield_name, #_systemfield_email, #_systemfield_resume")
        or _any_visible("input[type=file]")
    ):
        return True
    if _any_visible("#_systemfield_name, #_systemfield_email, #_systemfield_resume"):
        return True
    if _any_visible("input[type=file]") and _any_visible(
        "input[type=email], input[type=text], #_systemfield_name"
    ):
        return True
    return False


def _click_ashby_apply_cta(page: Any, notes: list) -> bool:
    """Click Ashby JD Apply CTA (not LinkedIn/Indeed partner buttons)."""
    patterns = (
        re.compile(r"^apply for this job$", re.I),
        re.compile(r"^apply now$", re.I),
        re.compile(r"^apply$", re.I),
        re.compile(r"^start application$", re.I),
        re.compile(r"^begin application$", re.I),
    )
    for role in ("button", "link"):
        try:
            candidates = page.get_by_role(role).all()
        except Exception:
            candidates = []
        for loc in candidates[:80]:
            try:
                text = (loc.inner_text() or "").strip()
            except Exception:
                continue
            if not text or not is_apply_nav(text):
                # Also accept exact Ashby casing variants already covered by is_apply_nav.
                if not any(p.match(text) for p in patterns):
                    continue
            if is_submit_control(text=text):
                continue
            try:
                if not loc.is_visible():
                    continue
                loc.scroll_into_view_if_needed(timeout=2000)
                loc.click(timeout=2500)
                notes.append(f"ashby entry: clicked Apply CTA {text!r}")
                page.wait_for_timeout(800)
                return True
            except Exception:
                continue
    return False


def _enter_ashby_application(page: Any, notes: list) -> bool:
    """Reach the Ashby application form from a JD / board shell.

    Persona 1am: job UUID 404s as "Job not found" with no widgets — park needs_user.
    Decagon: JD shows Overview until "Apply for this Job" → /application SPA.
    """
    _maybe_dismiss(page)
    if _ashby_job_missing(page):
        notes.append("needs_user: ashby job not found (posting closed or bad URL)")
        return False
    if _ashby_form_ready(page):
        notes.append("ashby entry: application form already present")
        return True

    # Prefer explicit Apply CTA; fall back to generic open.
    if not _click_ashby_apply_cta(page, notes):
        _maybe_open_form(page)
        notes.append("ashby entry: fell back to generic apply-nav click")

    for i in range(24):
        _maybe_dismiss(page)
        if _ashby_job_missing(page):
            notes.append("needs_user: ashby job not found after Apply CTA")
            return False
        if _ashby_form_ready(page):
            notes.append("ashby entry: reached application form")
            return True
        if i in (8, 16):
            # SPA lag — retry Apply once, then soft reload.
            if not _ashby_form_ready(page):
                _click_ashby_apply_cta(page, notes)
            if i == 16 and not _ashby_form_ready(page):
                try:
                    page.reload(wait_until="domcontentloaded", timeout=45000)
                    notes.append("ashby entry: reload after slow SPA")
                    page.wait_for_timeout(1000)
                    _maybe_dismiss(page)
                    if _ashby_job_missing(page):
                        notes.append("needs_user: ashby job not found after reload")
                        return False
                    _click_ashby_apply_cta(page, notes)
                except Exception as exc:
                    notes.append(f"ashby entry reload failed: {exc}"[:160])
        page.wait_for_timeout(400)

    if _ashby_job_missing(page):
        notes.append("needs_user: ashby job not found")
        return False
    if _ashby_form_ready(page):
        return True
    try:
        body = page.inner_text("body", timeout=2000)
    except Exception:
        body = ""
    closed = re.search(r"application submission is unavailable[^.\n]*|no longer accepting applications|"
                       r"this (job|position|posting) (is|has been) (closed|filled)", body, re.I)
    if closed:
        notes.append(f"needs_user: ashby posting not taking applications: {closed.group(0)}")
        return False
    notes.append("needs_user: ashby application form not ready (no resume/name widgets)")
    return False


def _load_pool_entries(pool_path: str) -> list:
    from apply_engine.pool import load_pool

    try:
        return load_pool(pool_path) if pool_path else []
    except Exception:
        return []


def _application_inputs_visible(page: Any) -> bool:
    try:
        return bool(
            page.evaluate(
                """() => [...document.querySelectorAll('input[type=email], input[type=file], #first_name, input[name=name], #_systemfield_name')]
                   .some(e => { const r = e.getBoundingClientRect(); return (r.width > 1 && r.height > 1) || e.type === 'file'; })"""
            )
        )
    except Exception:
        return False


def _enter_single_page_application(page: Any, ats: str, notes: list) -> bool:
    """Get from a posting URL to the page that holds the application form."""
    if ats == ATS_ASHBY:
        return _enter_ashby_application(page, notes)
    url = page.url or ""
    if ats == ATS_LEVER:
        m = re.match(r"(https?://jobs\.(?:eu\.)?lever\.co/[^/?#]+/[0-9a-f-]{36})(/apply)?", url)
        if m and not m.group(2):
            page.goto(m.group(1) + "/apply", wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            notes.append("lever entry: opened /apply")
    if ats == ATS_GREENHOUSE and "greenhouse.io" not in urlparse_host(url):
        board_url = _greenhouse_board_url(page, url)
        if board_url:
            page.goto(board_url, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            notes.append(f"greenhouse entry: company page -> {board_url}")
    _maybe_dismiss(page)
    for _ in range(12):
        if _application_inputs_visible(page):
            return True
        page.wait_for_timeout(500)
    _maybe_open_form(page)
    page.wait_for_timeout(1500)
    if _application_inputs_visible(page):
        return True
    notes.append(f"needs_user: {ats} application form not found on {page.url}")
    return False


def _greenhouse_embed_without_page(url: str) -> str | None:
    m = re.search(r"gh_jid=(\d+)", url)
    if not m or "greenhouse.io" in urlparse_host(url) or detect_ats(url) != ATS_GREENHOUSE:
        return None
    from apply_engine.jd import greenhouse_board_token

    token = greenhouse_board_token(url, m.group(1))
    return f"https://job-boards.greenhouse.io/embed/job_app?for={token}&token={m.group(1)}" if token else None


def _greenhouse_board_url(page: Any, url: str) -> str | None:
    """Hosted Greenhouse form for a gh_jid posting on a company's own careers site."""
    m = re.search(r"gh_jid=(\d+)", url)
    try:
        frame_src = page.evaluate(
            "() => { const f = document.querySelector('iframe#grnhse_iframe, iframe[src*=\"greenhouse.io\"]'); return f ? f.src : ''; }"
        )
    except Exception:
        frame_src = ""
    if frame_src:
        return frame_src
    if not m:
        return None
    from apply_engine.jd import greenhouse_board_token

    jid = m.group(1)
    try:
        html = page.content()
    except Exception:
        html = ""
    token = greenhouse_board_token(url, jid, html)
    # The board URL bounces back to the company site when it sets a custom
    # job-board URL; the embed form never redirects.
    return f"https://job-boards.greenhouse.io/embed/job_app?for={token}&token={jid}" if token else None


def urlparse_host(url: str) -> str:
    from urllib.parse import urlparse

    return (urlparse(url).hostname or "").lower()


def _maybe_open_form(page: Any) -> None:
    # Prefer Workday-specific entry when URL is already known via notes-less path.
    if _click_workday_apply_cta(page, notes=[]):
        _click_apply_manually_modal(page, notes=[])
        return
    candidates = page.get_by_role("button").all() + page.get_by_role("link").all()
    for loc in candidates[:60]:
        try:
            text = (loc.inner_text() or "").strip()
        except Exception:
            continue
        if is_submit_control(text=text):
            continue
        if is_apply_nav(text):
            try:
                loc.click(timeout=1500)
                page.wait_for_timeout(800)
                return
            except Exception:
                continue


def _maybe_dismiss(page: Any) -> None:
    for name in ("Accept Cookies", "Accept all cookies", "Accept All", "Accept", "Accept all", "I agree", "Got it"):
        loc = page.get_by_role("button", name=re.compile(rf"^{re.escape(name)}$", re.I))
        try:
            if loc.count() and loc.first.is_visible():
                loc.first.click(timeout=800)
        except Exception:
            pass


def _iter_submit_candidates(page: Any) -> list[Any]:
    """Collect likely Submit / Submit application controls (Ashby often omits type=submit)."""
    found: list[Any] = []
    selectors = (
        "button[type=submit], input[type=submit]",
        "button._submitButton_5yu8i_411, button[class*='submitButton'], "
        "button.ashby-application-form-submit-button, [class*='ashby'][class*='submit']",
    )
    for sel in selectors:
        loc = page.locator(sel)
        try:
            n = loc.count()
        except Exception:
            n = 0
        for i in range(n):
            found.append(loc.nth(i))
    try:
        for btn in page.get_by_role("button").all():
            found.append(btn)
    except Exception:
        pass
    try:
        named = page.get_by_role("button", name=re.compile(r"submit", re.I))
        for i in range(named.count()):
            found.append(named.nth(i))
    except Exception:
        pass
    return found


def _submit_control_text(btn: Any) -> str:
    try:
        return (btn.inner_text() or btn.input_value() or btn.get_attribute("aria-label") or "").strip()
    except Exception:
        try:
            return (btn.inner_text() or "").strip()
        except Exception:
            return ""


def _wait_submit_enabled(page: Any, btn: Any, *, timeout_ms: int = 8000) -> bool:
    steps = max(1, timeout_ms // 250)
    for _ in range(steps):
        try:
            if btn.is_visible() and btn.is_enabled():
                disabled = False
                try:
                    aria = (btn.get_attribute("aria-disabled") or "").lower()
                    disabled = bool(btn.get_attribute("disabled")) or aria == "true"
                except Exception:
                    disabled = False
                if not disabled:
                    return True
        except Exception:
            pass
        try:
            page.wait_for_timeout(250)
        except Exception:
            time.sleep(0.25)
    return False


def _click_submit(page: Any) -> bool:
    from apply_engine.guard import assert_can_submit

    assert_can_submit()
    if _captcha_or_cloudflare(page):
        raise SubmitBlockedError("confirm: captcha/cloudflare blocking submit")

    deadline = time.time() + 12
    last_disabled = False
    while time.time() < deadline:
        for btn in _iter_submit_candidates(page):
            text = _submit_control_text(btn)
            try:
                type_attr = ""
                try:
                    type_attr = (btn.get_attribute("type") or "").lower()
                except Exception:
                    type_attr = ""
                if not is_submit_control(type_attr=type_attr, text=text, role="button"):
                    if type_attr != "submit" and not SUBMIT_TEXT.search(text or ""):
                        continue
                if is_auth_control(text):
                    continue
                try:
                    if not btn.is_visible():
                        continue
                except Exception:
                    continue
                try:
                    btn.scroll_into_view_if_needed(timeout=3000)
                except Exception:
                    pass
                page.wait_for_timeout(200)
                if not _wait_submit_enabled(page, btn, timeout_ms=6000):
                    last_disabled = True
                    continue
                guarded_click(
                    btn,
                    allow_submit=True,
                    meta={"type_attr": type_attr or "button", "text": text or "Submit", "role": "button"},
                )
                page.wait_for_timeout(1000)
                return True
            except SubmitBlockedError:
                raise
            except Exception:
                continue
        page.wait_for_timeout(400)

    if last_disabled:
        raise SubmitBlockedError("confirm: submit control stayed disabled")
    raise SubmitBlockedError("confirm: no submit control found")


def _assert_no_submit_clicked(page: Any) -> None:
    try:
        submitted = page.evaluate("() => window.__submitted === true")
    except Exception:
        submitted = False
    if submitted:
        raise SubmitBlockedError("form submitted during fill — this is a bug")
