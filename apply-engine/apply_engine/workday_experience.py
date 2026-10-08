"""Workday My Experience Add panels for Education and Work Experience.

Clicks Add under that section only. Languages, Websites, and projects stay
untouched. Start and end dates come from the pool or the profile graduation;
a missing date is left blank rather than invented.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from apply_engine.models import PoolEntry, Profile
from apply_engine.pool import dated_work
from apply_engine.workday_widgets import (
    SELECT_ONE,
    _click_option_substring,
    _close_prompt,
    _settle,
    degree_fallback_terms,
    select_prompt,
    widget_readback,
)

_MONTHS = (
    ("january", "01", "January", ("jan",)),
    ("february", "02", "February", ("feb",)),
    ("march", "03", "March", ("mar",)),
    ("april", "04", "April", ("apr",)),
    ("may", "05", "May", ("may",)),
    ("june", "06", "June", ("jun",)),
    ("july", "07", "July", ("jul",)),
    ("august", "08", "August", ("aug",)),
    ("september", "09", "September", ("sept", "sep")),
    ("october", "10", "October", ("oct",)),
    ("november", "11", "November", ("nov",)),
    ("december", "12", "December", ("dec",)),
)

SCHOOL_RE = re.compile(r"school|university|college", re.I)
JOB_TITLE_RE = re.compile(r"job title|\bposition\b", re.I)
COMPANY_RE = re.compile(r"\bcompany\b", re.I)
LOCATION_RE = re.compile(r"\blocation\b", re.I)
START_RE = re.compile(r"start date|first year|\bfrom\b", re.I)
END_RE = re.compile(r"end date|last year|graduation|expected|\bto\b", re.I)
GPA_RE = re.compile(r"\bgpa\b|grade average|overall result", re.I)
DESC_RE = re.compile(r"description|responsibilit", re.I)
WORK_CURRENT_RE = re.compile(r"currently work|current role", re.I)
EDU_CURRENT_RE = re.compile(r"currently attend|currently enrolled", re.I)

_RANGE_JS = r"""
(title) => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const wanted = norm(title);
  const names = ['work experience','education','languages','websites','skills','certifications','resume/cv','resume'];
  const ownText = (el) => {
    const own = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('');
    const direct = norm(own);
    if (direct) return direct;
    if (!el.children || el.children.length === 0) return norm(el.textContent);
    return '';
  };
  const visible = (el) => !!(el.getClientRects && el.getClientRects().length);
  const top = (el) => el.getBoundingClientRect().top;
  const headings = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6,legend,span,div,p')].filter((el) => {
    const t = ownText(el);
    return t && names.some((n) => t === n || t.startsWith(n + ' ')) && visible(el);
  });
  const heading = headings.find((el) => {
    const t = ownText(el);
    return t === wanted || t.startsWith(wanted + ' ');
  });
  if (!heading) return null;
  const y = top(heading);
  const below = headings.filter((el) => el !== heading && top(el) > y + 2).sort((a, b) => top(a) - top(b));
  return { y, y2: below.length ? top(below[0]) : 1e9 };
}
"""

_ADD_JS = r"""
(title) => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const wanted = norm(title);
  const names = ['work experience','education','languages','websites','skills','certifications','resume/cv','resume'];
  const ownText = (el) => {
    const own = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('');
    const direct = norm(own);
    if (direct) return direct;
    if (!el.children || el.children.length === 0) return norm(el.textContent);
    return '';
  };
  const visible = (el) => !!(el.getClientRects && el.getClientRects().length);
  const top = (el) => el.getBoundingClientRect().top;
  const headings = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6,legend,span,div,p')].filter((el) => {
    const t = ownText(el);
    return t && names.some((n) => t === n || t.startsWith(n + ' ')) && visible(el);
  });
  const heading = headings.find((el) => {
    const t = ownText(el);
    return t === wanted || t.startsWith(wanted + ' ');
  });
  if (!heading) return null;
  const y = top(heading);
  const below = headings.filter((el) => el !== heading && top(el) > y + 2).sort((a, b) => top(a) - top(b));
  const y2 = below.length ? top(below[0]) : 1e9;
  const buttons = [...document.querySelectorAll('button, [role="button"]')].filter((b) => {
    const label = norm(b.innerText || b.getAttribute('aria-label') || '');
    if (!/^add(\b|$)/.test(label)) return false;
    const by = top(b);
    return by > y + 1 && by < y2 && visible(b);
  }).sort((a, b) => top(a) - top(b));
  return buttons[0] || null;
}
"""


def parse_when(text: str) -> dict[str, str | bool]:
    """Parse 'March 2026', 'Sept. 2026', '2028', or 'Present'. Never invents a month."""
    raw = (text or "").strip()
    if not raw:
        return {}
    if re.search(r"\b(present|current|now)\b", raw, re.I):
        return {"current": True}
    match = re.search(r"([A-Za-z]+)\.?\s+((?:19|20)\d{2})", raw)
    if match:
        token = match.group(1).lower()
        year = match.group(2)
        for name, num, pretty, aliases in _MONTHS:
            if token == name or token in aliases:
                return {"month_num": num, "month_name": pretty, "year": year}
        return {"year": year}
    year_only = re.search(r"\b((?:19|20)\d{2})\b", raw)
    if year_only:
        return {"year": year_only.group(1)}
    return {}


def _prefixes(page: Any, suffix: str) -> list[str]:
    try:
        ids = page.eval_on_selector_all(
            f'[id$="--{suffix}"]',
            "els => els.map(el => el.id)",
        )
    except Exception:
        return []
    out: list[str] = []
    for element_id in ids or []:
        prefix = str(element_id).split("--", 1)[0]
        if prefix and prefix not in out:
            out.append(prefix)
    return out


def _education_prefix(page: Any) -> str:
    """The education row that already has a school. A later blank panel is not it."""
    found = _prefixes(page, "schoolName")
    for prefix in found:
        if _input_value(page, f"{prefix}--schoolName").strip():
            return prefix
    if found:
        return found[0]
    for suffix in ("degree", "gradeAverage"):
        found = _prefixes(page, suffix)
        if found:
            return found[0]
    return ""


def _blank_work_prefix(page: Any) -> str:
    for prefix in _prefixes(page, "jobTitle"):
        if not _input_value(page, f"{prefix}--jobTitle").strip():
            return prefix
    return ""


def _company_taken(page: Any, company: str) -> bool:
    want = company.strip().lower()
    if not want:
        return False
    for prefix in _prefixes(page, "companyName"):
        if want in _input_value(page, f"{prefix}--companyName").lower():
            return True
    return False


def _opened_work_ids(page: Any, notes: list) -> bool:
    before = set(_prefixes(page, "jobTitle"))
    if not _click_add(page, "Work Experience"):
        return False
    return _wait_new_prefix(page, before, notes) != ""


def _fill_education_span(
    page: Any,
    prefix: str,
    text: str,
    filled: list,
    which: str,
    mapped: str,
    label: str,
) -> None:
    """Fill a start or end only when that date is on the profile and the control exists."""
    when = parse_when(text or "")
    if not when or when.get("current"):
        return
    if _write_span(page, prefix, which, when):
        filled.append({
            "label": label,
            "mapped_to": mapped,
            "value": text.strip(),
            "method": "workday-add-panel",
        })


def _fill_education_ids(
    page: Any,
    prefix: str,
    profile: Profile,
    filled: list,
    skipped: list,
) -> None:
    _dismiss_popup(page)
    school = (profile.school or "").strip()
    current = _input_value(page, f"{prefix}--schoolName")
    if school and school.lower() not in current.lower():
        wrote = _write_id(page, f"{prefix}--schoolName", school)
        if _committed(wrote, _school_terms(school)):
            filled.append({"label": "School", "mapped_to": "school", "value": wrote, "method": "workday-add-panel"})
    gpa = (profile.gpa or "").strip()
    if gpa and gpa.lower() not in _input_value(page, f"{prefix}--gradeAverage").lower():
        wrote = _write_id(page, f"{prefix}--gradeAverage", gpa)
        if wrote and gpa.lower() in wrote.lower():
            filled.append({"label": "GPA", "mapped_to": "gpa", "value": wrote, "method": "workday-add-panel"})
    _fill_education_span(
        page,
        prefix,
        profile.education_start,
        filled,
        "firstYearAttended",
        "education_start",
        "Education start",
    )
    when = parse_when(profile.graduation or "")
    if when.get("year"):
        if _write_span(page, prefix, "lastYearAttended", when):
            filled.append({
                "label": "Graduation",
                "mapped_to": "graduation",
                "value": (profile.graduation or str(when["year"])).strip(),
                "method": "workday-add-panel",
            })
    degree = (profile.degree or "").strip()
    button = page.locator(f'[id="{prefix}--degree"]')
    try:
        if degree and button.count() and button.first.is_visible():
            control = button.first
            readback = select_prompt(
                page,
                control,
                degree_fallback_terms(degree),
                readback_fn=lambda c=control: widget_readback(c),
                close_outside=True,
            )
            if _committed(readback, degree_fallback_terms(degree)):
                filled.append({"label": "Degree", "mapped_to": "degree", "value": readback, "method": "workday-add-panel"})
            else:
                skipped.append({"label": "Degree", "reason": f"readback {readback!r}", "readback": readback})
    except Exception as exc:
        skipped.append({"label": "Degree", "reason": str(exc)[:120]})
    _dismiss_popup(page)


def _fill_work_ids(page: Any, rows: list[PoolEntry], filled: list, skipped: list, notes: list) -> None:
    for row in rows:
        existing = _prefix_for_row(page, row)
        if existing:
            _repair_dates(page, existing, row, skipped)
            continue
        prefix = _blank_work_prefix(page)
        if not prefix:
            before = set(_prefixes(page, "jobTitle"))
            if not _click_add(page, "Work Experience"):
                notes.append("work experience Add button not found")
                return
            prefix = _wait_new_prefix(page, before, notes)
        if not prefix:
            notes.append("work experience Add did not open a form")
            _note_open_fields(page, notes)
            return
        _fill_work_prefix(page, prefix, row, filled, skipped)
        commit_open_panel(page)


def _fill_work_prefix(page: Any, prefix: str, row: PoolEntry, filled: list, skipped: list) -> None:
    _dismiss_popup(page)
    title = _write_id(page, f"{prefix}--jobTitle", row.role)
    company = _write_id(page, f"{prefix}--companyName", row.company)
    if row.location:
        _write_id(page, f"{prefix}--location", row.location)
    start = parse_when(row.start)
    end = parse_when(row.end)
    if start and not start.get("current"):
        if not _write_span(page, prefix, "startDate", start):
            skipped.append({"label": f"Start date ({row.company})", "reason": "start date widget did not take the pool date"})
    if end.get("current"):
        if not _check_id(page, f"{prefix}--currentlyWorkHere"):
            skipped.append({
                "label": f"End date ({row.company})",
                "reason": "end is Present and no currently-work checkbox was found",
            })
    elif end and not _write_span(page, prefix, "endDate", end):
        skipped.append({"label": f"End date ({row.company})", "reason": "end date widget did not take the pool date"})
    blurb = " ".join(b.strip() for b in row.bullets if b.strip())
    if blurb:
        _write_id(page, f"{prefix}--roleDescription", blurb[:600])
    if _committed(title, [row.role]) and _committed(company, [row.company]):
        span = row.end.strip() or row.start.strip()
        filled.append({
            "label": "Work Experience",
            "mapped_to": "work_experience",
            "value": f"{row.company} — {row.role} ({row.start} – {span})",
            "method": "workday-add-panel",
        })
    else:
        skipped.append({
            "label": "Work Experience",
            "reason": f"{row.company}: title {title!r}, company {company!r}",
        })


def _span_container(page: Any, prefix: str, which: str) -> Any | None:
    month_id = f"{prefix}--{which}-dateSectionMonth-input"
    try:
        node_id = page.evaluate(
            """({monthId, prefix, which}) => {
              const el = document.getElementById(monthId)
                || document.querySelector(`[id^="${prefix}--${which}"][id*="dateSectionMonth"]`);
              if (!el) return '';
              let node = el;
              for (let i = 0; i < 12 && node; i++) {
                const aid = (node.getAttribute && node.getAttribute('data-automation-id')) || '';
                if (aid.includes('formField') || (node.querySelector && node.querySelector('[data-automation-id="dateSectionYear-display"]'))) {
                  if (!node.id) node.id = 'apply-engine-date-' + Math.random().toString(36).slice(2);
                  return node.id;
                }
                node = node.parentElement;
              }
              if (!el.id) el.id = monthId;
              return el.id || '';
            }""",
            {"monthId": month_id, "prefix": prefix, "which": which},
        )
    except Exception:
        return None
    if not node_id:
        return None
    loc = page.locator(f'[id="{node_id}"]')
    try:
        if loc.count():
            return loc.first
    except Exception:
        return None
    return None


def _write_span(page: Any, prefix: str, which: str, when: dict) -> bool:
    month = str(when.get("month_num") or "")
    year = str(when.get("year") or "")
    if not year:
        return False
    field = _span_container(page, prefix, which)
    if field is not None:
        from apply_engine.workday_widgets import _write_date_parts

        if _write_date_parts(page, field, when) or _span_ok(page, prefix, which, when):
            return True
    month_id = f"{prefix}--{which}-dateSectionMonth-input"
    year_id = f"{prefix}--{which}-dateSectionYear-input"
    # Month first, then year, then month again if the year's leading 2
    # landed in the month spinbutton.
    month_ok = True
    if month and _exists(page, month_id) and not _date_value_ok(_input_value(page, month_id), month):
        month_ok = _type_into_id(page, month_id, month)
        if not month_ok and month.startswith("0"):
            month_ok = _type_into_id(page, month_id, str(int(month)))
    year_ok = True
    if _exists(page, year_id) and year not in _input_value(page, year_id):
        year_ok = _type_into_id(page, year_id, year)
    if month and _exists(page, month_id) and not _date_value_ok(_input_value(page, month_id), month):
        month_ok = _type_into_id(page, month_id, month)
        if not month_ok and month.startswith("0"):
            month_ok = _type_into_id(page, month_id, str(int(month)))
    return bool(month_ok and year_ok and (not month or _span_ok(page, prefix, which, when) or _date_value_ok(_input_value(page, month_id), month)))


def _wait_new_prefix(page: Any, before: set[str], notes: list) -> str:
    _ = notes
    for _try in range(8):
        _wait(page, 250)
        for prefix in _prefixes(page, "jobTitle"):
            if prefix not in before and not _input_value(page, f"{prefix}--jobTitle").strip():
                return prefix
        blank = _blank_work_prefix(page)
        if blank and blank not in before:
            return blank
    return _blank_work_prefix(page)


def _exists(page: Any, element_id: str) -> bool:
    try:
        return page.locator(f'[id="{element_id}"]').count() > 0
    except Exception:
        return False


def _input_value(page: Any, element_id: str) -> str:
    loc = page.locator(f'[id="{element_id}"]')
    try:
        if not loc.count():
            return ""
        return loc.first.input_value() or ""
    except Exception:
        return ""


def _write_id(page: Any, element_id: str, value: str) -> str:
    loc = page.locator(f'[id="{element_id}"]')
    try:
        if not loc.count() or not value.strip():
            return ""
        loc.first.fill(value, timeout=3000)
        return loc.first.input_value() or ""
    except Exception:
        return _type_into_id(page, element_id, value) and _input_value(page, element_id) or ""


def _type_into_id(page: Any, element_id: str, value: str) -> bool:
    """Type into one date segment, then blur it before the next segment.

    A year typed while the month segment still has focus is how every month
    collapsed to February: the leading 2 of 2026 landed in the month box.
    """
    loc = page.locator(f'[id="{element_id}"]')
    try:
        if not loc.count():
            return False
        el = loc.first
        el.evaluate("node => { node.focus(); if (node.select) node.select(); }")
        _wait(page, 40)
        active = page.evaluate("() => (document.activeElement && document.activeElement.id) || ''")
        if active != element_id:
            el.click(force=True, timeout=1500)
            el.evaluate("node => { node.focus(); if (node.select) node.select(); }")
            active = page.evaluate("() => (document.activeElement && document.activeElement.id) || ''")
            if active != element_id:
                # Typing a year while the month segment still has focus is how
                # every month collapsed to February (leading 2 of 2024).
                return False
        page.keyboard.press("Backspace")
        page.keyboard.type(value, delay=90)
        _wait(page, 120)
        el.evaluate("node => node.blur()")
        _wait(page, 80)
        return _date_value_ok(el.input_value() or "", value)
    except Exception:
        return False


def _date_value_ok(got: str, value: str) -> bool:
    if value in (got or ""):
        return True
    if value.isdigit() and str(int(value)) == (got or "").strip():
        return True
    return False


def _check_id(page: Any, element_id: str) -> bool:
    loc = page.locator(f'[id="{element_id}"]')
    try:
        if not loc.count():
            return False
        box = loc.first
        if not box.is_checked():
            box.check(force=True, timeout=2000)
        return bool(box.is_checked())
    except Exception:
        return False


def _dismiss_popup(page: Any) -> None:
    try:
        page.keyboard.press("Escape")
    except Exception:
        return
    _settle(page, 100)


def _wait(page: Any, ms: int) -> None:
    try:
        page.wait_for_timeout(ms)
    except Exception:
        return


def _remove_blank_education_rows(page: Any, notes: list) -> None:
    """Drop extra education panels that have no school. They block Next."""
    for _ in range(4):
        try:
            target = page.evaluate(
                """() => {
                  const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                  const schools = [...document.querySelectorAll('input[id$="--schoolName"]')];
                  for (const input of schools) {
                    if (clean(input.value)) continue;
                    let node = input;
                    let button = null;
                    for (let i = 0; node && i < 12; i++) {
                      const buttons = [...node.querySelectorAll('button, [role="button"]')];
                      button = buttons.find(el => /delete|remove/i.test(
                        (el.getAttribute('aria-label') || '') + ' ' +
                        (el.getAttribute('data-automation-id') || '') + ' ' +
                        (el.innerText || '')
                      ));
                      const here = node.querySelectorAll('input[id$="--schoolName"]').length;
                      if (button && here === 1) break;
                      button = null;
                      node = node.parentElement;
                    }
                    if (!button) continue;
                    button.scrollIntoView({block: 'center'});
                    const r = button.getBoundingClientRect();
                    if (r.width < 2 || r.height < 2) continue;
                    return {
                      x: r.x + r.width / 2,
                      y: r.y + r.height / 2,
                      id: input.id,
                      label: clean(button.getAttribute('aria-label') || button.innerText || ''),
                    };
                  }
                  return null;
                }"""
            )
        except Exception:
            return
        if not target:
            return
        try:
            page.mouse.click(target["x"], target["y"])
        except Exception:
            return
        page.wait_for_timeout(400)
        confirm = page.get_by_role("button", name=re.compile(r"^delete$", re.I))
        try:
            if confirm.count() and confirm.last.is_visible():
                confirm.last.click(timeout=2000)
                page.wait_for_timeout(400)
        except Exception:
            pass
        notes.append(f"removed blank education row {target.get('id', '')}")


def fill_education_panel(page: Any, profile: Profile, filled: list, skipped: list, notes: list) -> None:
    school = (profile.school or "").strip()
    if not school:
        return
    _remove_blank_education_rows(page, notes)
    prefix = _education_prefix(page)
    if not prefix:
        _click_add(page, "Education")
        _wait(page, 500)
        prefix = _education_prefix(page)
    if prefix:
        _fill_education_ids(page, prefix, profile, filled, skipped)
        return
    if _value_present(page, "Education", school):
        return
    if not _open_blank(page, "Education", SCHOOL_RE, notes):
        return
    terms = _school_terms(school)
    school_field = _last_unset(page, "Education", SCHOOL_RE)
    got = _set_prompt_or_text(page, school_field, school, terms)
    if _committed(got, terms):
        filled.append({"label": "School", "mapped_to": "school", "value": got, "method": "workday-add-panel"})
    elif school_field is not None:
        skipped.append({"label": "School", "reason": f"readback {got!r}", "readback": got})

    gpa = (profile.gpa or "").strip()
    if gpa:
        gpa_field = _last_unset(page, "Education", GPA_RE)
        wrote = _fill_plain(gpa_field, gpa)
        if wrote and gpa.lower() in wrote.lower():
            filled.append({"label": "GPA", "mapped_to": "gpa", "value": wrote, "method": "workday-add-panel"})

    started = parse_when(profile.education_start or "")
    if started and not started.get("current"):
        start_field = _last_unset(page, "Education", START_RE)
        if _fill_date_field(start_field, started):
            filled.append({
                "label": "Education start",
                "mapped_to": "education_start",
                "value": profile.education_start.strip(),
                "method": "workday-add-panel",
            })
    when = parse_when(profile.graduation or "")
    if when and not when.get("current"):
        end_field = _last_unset(page, "Education", END_RE)
        if _fill_date_field(end_field, when):
            label = profile.graduation.strip()
            filled.append({"label": "Graduation", "mapped_to": "graduation", "value": label, "method": "workday-add-panel"})
        elif end_field is not None:
            skipped.append({"label": "Graduation", "reason": "end date widget did not take the profile graduation"})
    if _graduation_in_future(when) and _check_box(page, "Education", EDU_CURRENT_RE):
        filled.append({
            "label": "Currently attend",
            "mapped_to": "graduation",
            "value": "Yes",
            "method": "workday-add-panel",
        })


def commit_open_panel(page: Any) -> None:
    """Save a modal Add panel. Inline sections have nothing to commit."""
    dialog = _dialog(page)
    if dialog is None:
        return
    button = dialog.get_by_role("button", name=re.compile(r"^(add|save|done)$", re.I))
    try:
        if button.count() and button.first.is_visible():
            button.first.click(timeout=3000)
            page.wait_for_timeout(400)
    except Exception:
        return


def fill_work_panels(page: Any, entries: list[PoolEntry], filled: list, skipped: list, notes: list) -> None:
    rows = dated_work(entries)
    if not rows:
        return
    if _prefixes(page, "jobTitle"):
        _fill_work_ids(page, rows, filled, skipped, notes)
        return
    missing = [row for row in rows if not _work_already_listed(page, row)]
    if not missing:
        for row in rows:
            existing = _prefix_for_row(page, row)
            if existing:
                _repair_dates(page, existing, row, skipped)
        return
    if _opened_work_ids(page, notes):
        _fill_work_ids(page, rows, filled, skipped, notes)
        return
    for row in missing:
        if not _open_blank(page, "Work Experience", JOB_TITLE_RE, notes):
            return
        _fill_job(page, row, filled, skipped)
        commit_open_panel(page)


def _fill_job(page: Any, row: PoolEntry, filled: list, skipped: list) -> None:
    title_field = _last_unset(page, "Work Experience", JOB_TITLE_RE)
    company_field = _last_unset(page, "Work Experience", COMPANY_RE)
    location_field = _last_unset(page, "Work Experience", LOCATION_RE)
    start_field = _last_unset(page, "Work Experience", START_RE)
    end_field = _last_unset(page, "Work Experience", END_RE)
    desc_field = _last_unset(page, "Work Experience", DESC_RE)

    title_got = _set_prompt_or_text(page, title_field, row.role, [row.role])
    company_got = _set_prompt_or_text(page, company_field, row.company, [row.company])
    if row.location:
        _fill_plain(location_field, row.location)

    start = parse_when(row.start)
    end = parse_when(row.end)
    if start and not start.get("current"):
        if not _fill_date_field(start_field, start):
            skipped.append({"label": f"Start date ({row.company})", "reason": "start date widget did not take the pool date"})
    if end.get("current"):
        if not _check_box(page, "Work Experience", WORK_CURRENT_RE):
            skipped.append({
                "label": f"End date ({row.company})",
                "reason": "end is Present and no currently-work checkbox was found",
            })
    elif end:
        if not _fill_date_field(end_field, end):
            skipped.append({"label": f"End date ({row.company})", "reason": "end date widget did not take the pool date"})

    blurb = " ".join(b.strip() for b in row.bullets if b.strip())
    if blurb:
        _fill_plain(desc_field, blurb[:600])

    if _committed(title_got, [row.role]) and _committed(company_got, [row.company]):
        span = row.end.strip() or row.start.strip()
        filled.append({
            "label": "Work Experience",
            "mapped_to": "work_experience",
            "value": f"{row.company} — {row.role} ({row.start} – {span})",
            "method": "workday-add-panel",
        })
    else:
        skipped.append({
            "label": "Work Experience",
            "reason": f"{row.company}: title {title_got!r}, company {company_got!r}",
        })


def _school_terms(school: str) -> list[str]:
    terms = [school]
    stripped = re.sub(r"^the\s+", "", school, flags=re.I).strip()
    if stripped and stripped.lower() != school.lower():
        terms.append(stripped)
    return terms


def _graduation_in_future(when: dict) -> bool:
    year_s = str(when.get("year") or "")
    if not year_s.isdigit():
        return False
    month = int(str(when.get("month_num") or "12"))
    today = date.today()
    return (int(year_s), month) > (today.year, today.month)


def _committed(value: str, terms: list[str]) -> bool:
    got = (value or "").strip().lower()
    if not got or got in SELECT_ONE:
        return False
    for term in terms:
        want = term.strip().lower()
        if want and (want in got or got in want):
            return True
    return False


def _open_blank(page: Any, section: str, label_re: re.Pattern, notes: list) -> bool:
    if _last_unset(page, section, label_re) is not None:
        return True
    if not _click_add(page, section):
        return False
    try:
        page.wait_for_timeout(500)
    except Exception:
        pass
    if _last_unset(page, section, label_re) is not None:
        return True
    notes.append(f"{section} Add did not open a form")
    _note_open_fields(page, notes)
    return False


def _prefix_for_company(page: Any, company: str) -> str:
    want = company.strip().lower()
    if not want:
        return ""
    for prefix in _prefixes(page, "companyName"):
        if want in _input_value(page, f"{prefix}--companyName").lower():
            return prefix
    return ""


def _prefix_for_row(page: Any, row: PoolEntry) -> str:
    """Match an open work row by company and title so a re-fill does not duplicate it."""
    company = (row.company or "").strip().lower()
    role = (row.role or "").strip().lower()
    prefixes = list(dict.fromkeys(_prefixes(page, "jobTitle") + _prefixes(page, "companyName")))
    for prefix in prefixes:
        got_title = _input_value(page, f"{prefix}--jobTitle").strip().lower()
        got_co = _input_value(page, f"{prefix}--companyName").strip().lower()
        title_hit = bool(role) and role in got_title
        co_hit = bool(company) and company in got_co
        if title_hit and co_hit:
            return prefix
        if co_hit and (not got_title or not role):
            return prefix
        if title_hit and (not got_co or not company):
            return prefix
    return _prefix_for_company(page, row.company)


def _work_already_listed(page: Any, row: PoolEntry) -> bool:
    if _prefix_for_row(page, row):
        return True
    company = (row.company or "").strip()
    role = (row.role or "").strip()
    if company and _value_present(page, "Work Experience", company):
        if not role or _value_present(page, "Work Experience", role):
            return True
    return False


def _repair_dates(page: Any, prefix: str, row: PoolEntry, skipped: list) -> None:
    start = parse_when(row.start)
    end = parse_when(row.end)
    if start and not start.get("current") and not _span_ok(page, prefix, "startDate", start):
        if not _write_span(page, prefix, "startDate", start):
            skipped.append({"label": f"Start date ({row.company})", "reason": "start date widget did not take the pool date"})
    if end.get("current"):
        _check_id(page, f"{prefix}--currentlyWorkHere")
    elif end and not _span_ok(page, prefix, "endDate", end):
        if not _write_span(page, prefix, "endDate", end):
            skipped.append({"label": f"End date ({row.company})", "reason": "end date widget did not take the pool date"})


def _span_ok(page: Any, prefix: str, which: str, when: dict) -> bool:
    year = str(when.get("year") or "")
    month = str(when.get("month_num") or "")
    got_year = _input_value(page, f"{prefix}--{which}-dateSectionYear-input")
    got_month = _input_value(page, f"{prefix}--{which}-dateSectionMonth-input")
    field = _span_container(page, prefix, which)
    if field is not None:
        from apply_engine.workday_widgets import _read_date_display

        display = _read_date_display(field)
        if display is not None:
            shown_month, _shown_day, shown_year = display
            if month and not _date_value_ok(shown_month, month):
                return False
            if year and not _date_value_ok(shown_year, year):
                return False
            return True
    if year and year not in got_year:
        return False
    if month and not _date_value_ok(got_month, month):
        return False
    return True


def _click_add(page: Any, section: str) -> bool:
    if _click_add_js(page, section):
        return True
    pattern = re.compile(r"^add\b", re.I)
    candidates: list[Any] = []
    for role in ("button", "link"):
        loc = page.get_by_role(role, name=pattern)
        try:
            count = min(loc.count(), 6)
        except Exception:
            count = 0
        for i in range(count):
            el = loc.nth(i)
            try:
                if el.is_visible():
                    candidates.append(el)
            except Exception:
                continue
    if not candidates:
        return False
    index = 0 if section.lower().startswith("work") else min(1, len(candidates) - 1)
    try:
        candidates[index].click(timeout=3000)
        return True
    except Exception:
        return False


def _click_add_js(page: Any, section: str) -> bool:
    try:
        handle = page.evaluate_handle(_ADD_JS, section)
    except Exception:
        return False
    try:
        element = handle.as_element()
        if element is None:
            return False
        element.click(timeout=3000)
        return True
    except Exception:
        return False
    finally:
        try:
            handle.dispose()
        except Exception:
            pass


def _value_present(page: Any, section: str, needle: str) -> bool:
    want = needle.strip().lower()
    if not want:
        return False
    for field in _section_fields(page, section):
        inputs = field.locator("input:not([type=hidden]), textarea")
        try:
            count = min(inputs.count(), 4)
        except Exception:
            count = 0
        for i in range(count):
            try:
                val = (inputs.nth(i).input_value() or "").strip().lower()
            except Exception:
                continue
            if want in val:
                return True
    try:
        blob = str(page.evaluate(_section_text_js(), section) or "")
    except Exception:
        blob = ""
    return want in blob.lower()


def _section_text_js() -> str:
    return r"""
(title) => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const wanted = norm(title);
  const names = ['work experience','education','languages','websites','skills','certifications','resume/cv','resume'];
  const ownText = (el) => {
    const own = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('');
    const direct = norm(own);
    if (direct) return direct;
    if (!el.children || el.children.length === 0) return norm(el.textContent);
    return '';
  };
  const visible = (el) => !!(el.getClientRects && el.getClientRects().length);
  const top = (el) => el.getBoundingClientRect().top;
  const headings = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6,legend,span,div,p')].filter((el) => {
    const t = ownText(el);
    return t && names.some((n) => t === n || t.startsWith(n + ' ')) && visible(el);
  });
  const heading = headings.find((el) => {
    const t = ownText(el);
    return t === wanted || t.startsWith(wanted + ' ');
  });
  if (!heading) return '';
  const y = top(heading);
  const below = headings.filter((el) => el !== heading && top(el) > y + 2).sort((a, b) => top(a) - top(b));
  const y2 = below.length ? top(below[0]) : 1e9;
  const parts = [];
  for (const el of document.querySelectorAll('input, textarea, button, select')) {
    const box = el.getBoundingClientRect();
    if (!box.width && !box.height) continue;
    if (box.top < y || box.top >= y2) continue;
    if (el.value) parts.push(el.value);
    else parts.push(el.innerText || '');
  }
  return parts.join('\n');
}
"""


def _section_fields(page: Any, section: str) -> list[Any]:
    dialog = _dialog(page)
    if dialog is not None:
        loc = dialog.locator("[data-automation-id^='formField-']")
        bounds = None
    else:
        loc = page.locator("[data-automation-id^='formField-']")
        bounds = _bounds(page, section)
        if bounds is None:
            return []
    out: list[Any] = []
    try:
        count = min(loc.count(), 40)
    except Exception:
        return []
    for i in range(count):
        field = loc.nth(i)
        try:
            if not field.is_visible():
                continue
            if field.locator("[data-automation-id^='formField-']").count():
                continue
            if bounds is not None:
                box = field.bounding_box()
                if not box or not (bounds[0] - 1 <= box["y"] < bounds[1]):
                    continue
            out.append(field)
        except Exception:
            continue
    return out


def _bounds(page: Any, section: str) -> tuple[float, float] | None:
    try:
        raw = page.evaluate(_RANGE_JS, section)
    except Exception:
        return None
    if not raw:
        return None
    return float(raw["y"]), float(raw["y2"])


def _dialog(page: Any) -> Any | None:
    for sel in ("[role=dialog]", "[data-automation-id='popUpDialog']"):
        loc = page.locator(sel)
        try:
            if loc.count() and loc.last.is_visible():
                return loc.last
        except Exception:
            continue
    return None


def _last_unset(page: Any, section: str, label_re: re.Pattern) -> Any | None:
    match = None
    for field in _section_fields(page, section):
        if not label_re.search(_label(field)):
            continue
        if _field_is_unset(field):
            match = field
    return match


def _label(field: Any) -> str:
    try:
        return " ".join((field.inner_text() or "").split())[:80]
    except Exception:
        return ""


def _field_is_unset(field: Any) -> bool:
    saw = False
    try:
        inputs = field.locator(
            "input:not([type=hidden]):not([type=checkbox]):not([type=radio]), textarea"
        )
        for i in range(min(inputs.count(), 4)):
            el = inputs.nth(i)
            if not el.is_visible():
                continue
            saw = True
            if (el.input_value() or "").strip():
                return False
        selects = field.locator("select")
        for i in range(min(selects.count(), 3)):
            el = selects.nth(i)
            if not el.is_visible():
                continue
            saw = True
            if widget_readback(el).strip().lower() not in SELECT_ONE:
                return False
        buttons = field.locator("button, [role=combobox]")
        for i in range(min(buttons.count(), 3)):
            el = buttons.nth(i)
            if not el.is_visible():
                continue
            saw = True
            text = widget_readback(el).strip().lower()
            if text and text not in SELECT_ONE:
                return False
    except Exception:
        return False
    return saw


def _set_prompt_or_text(page: Any, field: Any | None, value: str, terms: list[str]) -> str:
    if field is None or not value.strip():
        return ""
    control = _primary_control(field)
    if control is None:
        return ""
    try:
        tag = str(control.evaluate("el => (el.tagName || '').toLowerCase()"))
    except Exception:
        tag = ""
    if tag in {"button", "select"} or _role(control) == "combobox":
        return select_prompt(
            page,
            control,
            terms or [value],
            readback_fn=lambda c=control: widget_readback(c),
            close_outside=True,
        )
    try:
        control.fill(value, timeout=3000)
    except Exception:
        return ""
    _settle(page, 200)
    _click_option_substring(page, terms or [value])
    _close_prompt(page, control, click_outside=False)
    return widget_readback(control)


def _fill_plain(field: Any | None, value: str) -> str:
    if field is None or not value.strip():
        return ""
    control = _primary_control(field)
    if control is None:
        return ""
    try:
        tag = str(control.evaluate("el => (el.tagName || '').toLowerCase()"))
    except Exception:
        return ""
    if tag not in {"input", "textarea"}:
        return ""
    try:
        control.fill(value, timeout=3000)
        return widget_readback(control)
    except Exception:
        return ""


def _fill_date_field(field: Any | None, when: dict) -> bool:
    if field is None or when.get("current"):
        return False
    month_num = str(when.get("month_num") or "")
    month_name = str(when.get("month_name") or "")
    year = str(when.get("year") or "")
    if not year:
        return False
    try:
        page = field.page
    except Exception:
        page = None
    if page is not None:
        from apply_engine.workday_widgets import _write_date_parts

        if _write_date_parts(page, field, when):
            return True
    controls = _date_controls(field)
    if not controls:
        return False
    if len(controls) == 1:
        # Never concatenate MMYYYY. A year typed into the month slot becomes 02.
        if month_num:
            _write_month(controls[0], month_num, month_name)
            try:
                controls[0].press("Tab")
            except Exception:
                pass
        _write_year(controls[0], year)
        return _date_stuck(_date_controls(field) or controls, month_num, year)
    # Month / day / year: the day slot stays blank. We only know month and year.
    year_at = -1 if len(controls) >= 3 else 1
    if month_num:
        _write_month(controls[0], month_num, month_name)
        _write_year(controls[year_at], year)
    else:
        _write_year(controls[year_at], year)
    return _date_stuck(controls, month_num, year)


def _date_controls(field: Any) -> list[Any]:
    loc = field.locator(
        "input:not([type=hidden]):not([type=checkbox]):not([type=radio]), select, [role=spinbutton]"
    )
    out: list[Any] = []
    try:
        count = min(loc.count(), 4)
    except Exception:
        return []
    for i in range(count):
        el = loc.nth(i)
        try:
            if el.is_visible():
                out.append(el)
        except Exception:
            continue
    return out


def _write_month(control: Any, num: str, name: str) -> None:
    if _is_select(control):
        for label in (name, num, str(int(num)) if num.isdigit() else ""):
            if not label:
                continue
            if _select_label(control, label):
                return
        return
    _type_into(control, num)


def _write_year(control: Any, year: str) -> None:
    if _is_select(control):
        _select_label(control, year)
        return
    _type_into(control, year)


def _date_stuck(controls: list[Any], month_num: str, year: str) -> bool:
    blob = " ".join(widget_readback(c) for c in controls).lower()
    if year and year not in blob:
        return False
    if month_num and month_num not in blob and str(int(month_num)) not in blob.split():
        # Month dropdowns read back "March", not "03".
        pretty = ""
        for _name, num, label, _aliases in _MONTHS:
            if num == month_num:
                pretty = label.lower()
                break
        if pretty and pretty not in blob:
            return False
    return True


def _type_into(control: Any, value: str) -> None:
    try:
        control.fill(value, timeout=2000)
    except Exception:
        try:
            control.click(timeout=1500)
            control.type(value, delay=20, timeout=2000)
        except Exception:
            return


def _is_select(control: Any) -> bool:
    try:
        return str(control.evaluate("el => (el.tagName || '').toLowerCase()")) == "select"
    except Exception:
        return False


def _select_label(control: Any, label: str) -> bool:
    try:
        control.select_option(label=label, timeout=1500)
        return True
    except Exception:
        try:
            control.select_option(value=label, timeout=1000)
            return True
        except Exception:
            return False


def _check_box(page: Any, section: str, pattern: re.Pattern) -> bool:
    boxes = _checkboxes(page, section)
    target = None
    for box in boxes:
        if pattern.search(_checkbox_label(box)):
            target = box
    if target is None:
        return False
    try:
        if not target.is_checked():
            target.check(timeout=3000)
        return bool(target.is_checked())
    except Exception:
        return False


def _checkboxes(page: Any, section: str) -> list[Any]:
    dialog = _dialog(page)
    loc = (dialog or page).locator("input[type=checkbox]")
    bounds = None if dialog is not None else _bounds(page, section)
    if dialog is None and bounds is None:
        return []
    out: list[Any] = []
    try:
        count = min(loc.count(), 12)
    except Exception:
        return []
    for i in range(count):
        box = loc.nth(i)
        try:
            if not box.is_visible():
                continue
            if bounds is not None:
                rect = box.bounding_box()
                if not rect or not (bounds[0] - 1 <= rect["y"] < bounds[1]):
                    continue
            out.append(box)
        except Exception:
            continue
    return out


def _checkbox_label(box: Any) -> str:
    try:
        return str(
            box.evaluate(
                """el => {
                  const own = el.getAttribute('aria-label') || '';
                  if (own) return own;
                  if (el.id) {
                    const lab = el.ownerDocument.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                    if (lab) return lab.innerText || '';
                  }
                  const wrap = el.closest('label');
                  return (wrap && wrap.innerText) || '';
                }"""
            )
            or ""
        )
    except Exception:
        return ""


def _primary_control(field: Any) -> Any | None:
    for sel in (
        "textarea",
        "input:not([type=hidden]):not([type=checkbox]):not([type=radio])",
        "select",
        "button",
        "[role=combobox]",
    ):
        loc = field.locator(sel)
        try:
            count = min(loc.count(), 4)
        except Exception:
            continue
        for i in range(count):
            el = loc.nth(i)
            try:
                if el.is_visible():
                    return el
            except Exception:
                continue
    return None


def _role(control: Any) -> str:
    try:
        return str(control.get_attribute("role") or "").lower()
    except Exception:
        return ""


def _note_open_fields(page: Any, notes: list) -> None:
    try:
        blob = page.evaluate(
            """() => [...document.querySelectorAll("[data-automation-id^='formField-']")]
              .filter(el => el.getClientRects().length && !el.querySelector("[data-automation-id^='formField-']"))
              .slice(0, 16)
              .map(el => (el.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 60))
              .filter(Boolean)
              .join(' | ')"""
        )
    except Exception:
        return
    if blob:
        notes.append(f"experience panel fields: {str(blob)[:400]}")
