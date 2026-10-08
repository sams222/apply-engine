"""Workday PromptSelect / formField helpers.

Patterns distilled from public Workday copilots and ATS autofill (open prompt,
type filter, click option, ESC / click-outside, widget-only readback).
Reimplemented here — never copy their source.

UI-readback policy: a field counts as filled ONLY if the widget value after
settle matches. Read the control container (button / input / selected option),
never page.inner_text. City "New York" on the page must not make State succeed
while the State widget still says Illinois.
"""

from __future__ import annotations

import os
import re
from datetime import date
from typing import Any, Callable, Iterable

from apply_engine.models import Profile
from apply_engine.util import normalize_label

SELECT_ONE = {"", "select one", "select", "select an option", "choose one"}

# Approximate term dates. Fall runs late August through mid-December. Spring
# runs late January through mid-May. Summer sits in the gap after spring and
# before fall. A spring or fall internship starts with that semester so it
# covers the term. An intern posting that names no term is treated as summer.
_SEASON_START = {
    "summer": (6, 1),
    "fall": (8, 25),
    "winter": (1, 4),
    "spring": (1, 25),
}

STATE_CANON = {
    "ny": "new york",
    "n y": "new york",
    "new york": "new york",
    "new york ny": "new york",
    "il": "illinois",
    "illinois": "illinois",
    "ca": "california",
    "california": "california",
}

# "United States" is a prefix of "United States Minor Outlying Islands".
# That longer label is a different country, and its state list is territories.
_US_COUNTRY_LABELS = frozenset({
    "united states",
    "united states of america",
    "usa",
    "us",
    "u s",
    "u s a",
})
_DATE_EMPTY_RE = re.compile(
    r"must have a value|current value is MM/DD/YYYY|is required and must have a value",
    re.I,
)

# Science and arts stay on separate lists. A shared list let "BA" win for a
# science degree, because those two letters sit inside the word "Bachelor".
_SCIENCE_FALLBACKS = ("Bachelor of Science", "B.S.", "BS", "Bachelor", "Bachelors")
_ARTS_FALLBACKS = ("Bachelor of Arts", "B.A.", "BA", "Bachelor", "Bachelors")
_GENERIC_FALLBACKS = ("Bachelor", "B.S.", "BS", "B.A.", "BA", "Bachelors")
_SCIENCE_DEGREE_RE = re.compile(r"\bscience\b|\bb\.?\s*s\.?\b|\bbs\b", re.I)
_ARTS_DEGREE_RE = re.compile(r"\barts\b|\bb\.?\s*a\.?\b", re.I)
_DEGREE_ABBREV = {"bs": "bs", "bsc": "bs", "ba": "ba", "ms": "ms", "ma": "ma", "phd": "phd"}

POSTAL_ERROR_RE = re.compile(
    r"(postal code|zip code).*(invalid|not valid|error|does not match)|not valid for the selected state",
    re.I,
)

STATE_META_RE = re.compile(r"state|province|region", re.I)
PHONE_CODE_OPTION_RE = re.compile(
    r"^\+\d{1,4}$|united states.*\(\+\d|country phone code|\(\+\d{1,4}\)\s*$",
    re.I,
)
OPTION_SELECTOR = (
    '[data-automation-id="promptOption"], '
    '[data-automation-id="listItem"], '
    '[role="option"], '
    '[role="listitem"]'
)
SEARCH_BOX_SELECTOR = (
    'input[data-automation-id="searchBox"]:visible, '
    '[role="listbox"]:visible input:visible'
)
EMPLOYEE_FOLLOWUP_AIDS = ("employee-id", "employeeId", "workerId", "manager")

ReadbackFn = Callable[[], str]


def phone_digits(value: str) -> str:
    return re.sub(r"\D+", "", value or "")


def phone_last10(value: str) -> str:
    digits = phone_digits(value)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits[-10:] if len(digits) >= 10 else digits


def phone_digits_match(input_value: str, profile_phone: str) -> bool:
    """True when the phone input's digits match the profile's last 10 (or all if shorter)."""
    got = phone_digits(input_value)
    want = phone_digits(profile_phone)
    if not got or not want:
        return False
    n = min(10, len(got), len(want))
    if n < 7:
        return got == want
    return got[-n:] == want[-n:]


def is_country_phone_code_field(
    label: str = "",
    name: str = "",
    element_id: str = "",
    placeholder: str = "",
    automation_id: str = "",
) -> bool:
    blob = normalize_label(
        " ".join([label, name.replace("_", " "), element_id.replace("_", " "), placeholder, automation_id])
    )
    compact = blob.replace(" ", "")
    if "countryphonecode" in compact or "country-phone-code" in (automation_id or "").lower():
        return True
    if "country phone code" in blob or blob in {"country code", "phone code", "dialing code"}:
        return True
    return False


def looks_like_country_phone_code_option(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if PHONE_CODE_OPTION_RE.search(t):
        return True
    return bool(re.fullmatch(r"\+\d{1,4}", t))


def is_state_control_meta(
    aria_label: str = "",
    automation_id: str = "",
    name: str = "",
    element_id: str = "",
    placeholder: str = "",
) -> bool:
    """True for State/Province/Region widgets; never City or Country Phone Code."""
    if is_country_phone_code_field(
        label=aria_label,
        name=name,
        element_id=element_id,
        placeholder=placeholder,
        automation_id=automation_id,
    ):
        return False
    blob = " ".join([aria_label, automation_id, name, element_id, placeholder])
    low = blob.lower().replace("_", " ").replace("-", " ")
    compact = re.sub(r"[^a-z0-9]+", "", low)
    if "phone" in low or "dial" in low:
        return False
    if re.search(r"\bcity\b", low) and not STATE_META_RE.search(blob):
        return False
    if "countryregion" in compact or "stateprovince" in compact:
        return True
    return bool(STATE_META_RE.search(blob))


def is_plausible_state_option_list(opts: Iterable[str]) -> bool:
    """Country Phone Code (+1) must not be mistaken for State — require >1 real options."""
    texts = [str(o).strip() for o in opts if str(o or "").strip()]
    if len(texts) <= 1:
        return False
    if all(looks_like_country_phone_code_option(t) for t in texts):
        return False
    return True


def canonicalize_state(text: str) -> str:
    t = re.sub(r"[^a-z]+", " ", (text or "").lower()).strip()
    return STATE_CANON.get(t, t)


def united_states_label(text: str) -> bool:
    """True only for the United States, not a territory that starts with those words."""
    low = re.sub(r"[^a-z]+", " ", (text or "").lower()).strip()
    return low in _US_COUNTRY_LABELS


def date_field_rejected(text: str) -> bool:
    """Workday still showing the empty-date error, even if input.value looks set."""
    return bool(_DATE_EMPTY_RE.search(text or ""))


def parse_state_widget_text(widget_text: str) -> str:
    """Displayed value of a state/province control (never page body / City)."""
    t = (widget_text or "").strip()
    if not t:
        return ""
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    if not lines:
        return ""
    if len(lines) > 1 and re.fullmatch(r"state\*?|province|region|country region", lines[0], re.I):
        return lines[-1]
    return lines[-1] if len(lines) > 1 else lines[0]


def evaluate_state_widget_readback(
    widget_text: str,
    expected_state: str,
    *,
    page_body: str = "",
    postal_error: bool = False,
) -> dict[str, Any]:
    """Decide if State stuck. `page_body` is ignored for the match (City trap)."""
    _ = page_body  # explicit: do not use body text (City can equal the intended state)
    displayed = parse_state_widget_text(widget_text)
    widget = canonicalize_state(displayed)
    expected = canonicalize_state(expected_state)
    raw = displayed.strip().lower()

    if postal_error:
        return {
            "ok": False,
            "field": "State*",
            "reason": "postal error text present",
            "readback": displayed,
        }
    if raw in SELECT_ONE or widget in SELECT_ONE:
        return {
            "ok": False,
            "field": "State*",
            "reason": "State widget still Select One",
            "readback": displayed,
        }
    if "illinois" in widget and expected != "illinois":
        return {
            "ok": False,
            "field": "State*",
            "reason": "Illinois remains on State widget",
            "readback": displayed,
        }
    if not expected:
        return {"ok": False, "field": "State*", "reason": "no expected state", "readback": displayed}
    if widget != expected:
        return {
            "ok": False,
            "field": "State*",
            "reason": f"widget {displayed!r} != {expected_state}",
            "readback": displayed,
        }
    return {"ok": True, "field": "state", "readback": displayed, "reason": ""}


def evaluate_prompt_readback(widget_text: str) -> bool:
    raw = parse_state_widget_text(widget_text)
    return canonicalize_state(raw) not in SELECT_ONE and raw.strip().lower() not in SELECT_ONE


def _phrase_in(haystack: str, needle: str) -> bool:
    """Whole-word phrase match. "ba" is not a hit inside "bachelor"."""
    if not needle:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack) is not None


def _degree_abbrev(text: str) -> str:
    compact = re.sub(r"[^a-z]", "", (text or "").lower())
    return _DEGREE_ABBREV.get(compact, "")


def pick_option_substring(options: Iterable[str], terms: Iterable[str]) -> str | None:
    """Pick the first visible option whose text matches a term (exact, phrase, or state canon)."""
    cleaned = [str(o).strip() for o in options if str(o or "").strip()]
    term_list = [str(t).strip() for t in terms if str(t or "").strip()]
    for term in term_list:
        want = term.lower()
        for text in cleaned:
            if text.lower() == want:
                return text
        for text in cleaned:
            low = text.lower()
            if _phrase_in(low, want) or _phrase_in(want, low):
                return text
        abbrev = _degree_abbrev(term)
        if abbrev:
            for text in cleaned:
                if _degree_abbrev(text) == abbrev:
                    return text
        want_canon = canonicalize_state(term)
        if want_canon:
            for text in cleaned:
                if canonicalize_state(text) == want_canon:
                    return text
    return None


def season_start(title: str, extra: str = "", today: date | None = None) -> dict[str, str] | None:
    """Approximate start for a summer, fall, winter, or spring posting.

    The title wins over the description. An intern role with no named term
    starts June 1, in the gap between spring and fall.
    """
    for blob in (title or "", extra or ""):
        season = _named_season(blob)
        if not season:
            continue
        month, day = _SEASON_START[season]
        year = _year_for_season(blob, season, today or date.today(), title=title or "")
        return {
            "season": season,
            "month_num": f"{month:02d}",
            "day": f"{day:02d}",
            "year": year,
        }
    return None


def _named_season(text: str) -> str | None:
    blob = text or ""
    for name in ("summer", "fall", "winter", "spring"):
        if re.search(rf"\b{name}\b", blob, re.I):
            return name
    if re.search(r"\bintern", blob, re.I):
        return "summer"
    return None


def _year_for_season(text: str, season: str, today: date, title: str = "") -> str:
    nearby = re.search(
        rf"\b{season}\b.{{0,40}}((?:19|20)\d{{2}})|((?:19|20)\d{{2}}).{{0,40}}\b{season}\b",
        text or "",
        re.I,
    )
    if nearby:
        return nearby.group(1) or nearby.group(2)
    for blob in (text or "", title or ""):
        if not blob or (blob != title and len(blob) >= 240):
            continue
        any_year = re.search(r"\b((?:19|20)\d{2})\b", blob)
        if any_year:
            return any_year.group(1)
    month, day = _SEASON_START[season]
    year = today.year
    if date(year, month, day) < today:
        year += 1
    return str(year)


def choice_readback(locator: Any) -> str:
    """Visible choice on a select or button. Hidden menu rows are not a choice."""
    try:
        return str(
            locator.evaluate(
                r"""el => {
                  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
                  if (!el) return '';
                  if (el.tagName === 'SELECT') {
                    const o = el.options[el.selectedIndex];
                    return clean((o && o.text) || '');
                  }
                  const hiddenMenu = (node) => {
                    if (!node || node.nodeType !== 1) return false;
                    const aid = node.getAttribute('data-automation-id') || '';
                    const role = node.getAttribute('role') || '';
                    return aid === 'activeListContainer' || aid === 'promptOption' || aid === 'menuItem'
                      || aid === 'inputAlert' || role === 'listbox' || role === 'option'
                      || /^error/i.test(node.id || '');
                  };
                  const parts = [];
                  const walk = (node) => {
                    if (!node) return;
                    if (node.nodeType === 3) { parts.push(node.textContent || ''); return; }
                    if (node.nodeType !== 1 || hiddenMenu(node)) return;
                    const style = window.getComputedStyle(node);
                    if (style.display === 'none' || style.visibility === 'hidden') return;
                    for (const child of node.childNodes) walk(child);
                  };
                  walk(el);
                  const text = clean(parts.join(' '));
                  if (/^error\b/i.test(text)) return '';
                  return text.replace(/\s+error\s+-\s+.*/i, '').trim();
                }"""
            )
            or ""
        )
    except Exception:
        return widget_readback(locator)


def readback_committed(widget_text: str, terms: Iterable[str]) -> bool:
    """True when the control container itself shows a committed choice from `terms`."""
    displayed = parse_state_widget_text(widget_text)
    if re.match(r"error\b", displayed.strip(), re.I):
        return False
    if displayed.strip().lower() in SELECT_ONE:
        return False
    if not (displayed or "").strip():
        return False
    return pick_option_substring([displayed], terms) is not None


def degree_fallback_terms(degree: str | None) -> list[str]:
    """Abbreviations for this degree. A science degree never probes BA."""
    raw = (degree or "").strip()
    low = raw.lower()
    if _SCIENCE_DEGREE_RE.search(low) and not _ARTS_DEGREE_RE.search(low):
        fallbacks = _SCIENCE_FALLBACKS
    elif _ARTS_DEGREE_RE.search(low) and not _SCIENCE_DEGREE_RE.search(low):
        fallbacks = _ARTS_FALLBACKS
    else:
        fallbacks = _GENERIC_FALLBACKS
    out: list[str] = []
    seen: set[str] = set()

    def add(item: str) -> None:
        item = (item or "").strip()
        if not item:
            return
        key = item.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(item)

    add(raw)
    for fb in fallbacks:
        add(fb)
    return out


def state_search_terms(profile: Profile) -> list[str]:
    raw = (profile.state or "").strip()
    pretty = state_search_label(profile)
    terms: list[str] = []
    for item in (pretty, raw, canonicalize_state(raw).title() if canonicalize_state(raw) else ""):
        if item and item not in terms:
            terms.append(item)
    return terms


def state_search_label(profile: Profile) -> str:
    raw = (profile.state or "").strip()
    canon = canonicalize_state(raw)
    pretty = {
        "new york": "New York",
        "illinois": "Illinois",
        "california": "California",
    }
    return pretty.get(canon, raw or canon)


def field_of_study_value(profile: Profile) -> str | None:
    if str(profile.field_of_study or "").strip():
        return str(profile.field_of_study).strip()
    deg = (profile.degree or "").lower()
    if "computer science" in deg:
        return "Computer Science"
    return None


def degree_search_term(profile: Profile) -> str | None:
    deg = (profile.degree or "").strip()
    return deg or None


def is_employee_followup_aid(automation_id: str) -> bool:
    aid = (automation_id or "").lower()
    return any(token.lower() in aid for token in EMPLOYEE_FOLLOWUP_AIDS)


def widget_readback(locator: Any) -> str:
    """Own text/value of this control only — not the page, not a sibling City field.

    Workday's searchable prompts (State, Country, Degree) do not put the chosen
    value in the button. It lands in a sibling
    `ul[data-automation-id='selectedItemList'] li` inside the field wrapper,
    which is why live Walmart read back '' for State while the form clearly
    showed a selection. Check the button first, then that list, then the input.
    """
    try:
        return str(
            locator.evaluate(
                r"""el => {
                  if (!el) return '';
                  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
                  if (el.tagName === 'SELECT') {
                    const o = el.options[el.selectedIndex];
                    return clean((o && o.text) || '');
                  }
                  const inMulti = !!el.closest("[data-automation-id='multiSelectContainer']")
                    || !!el.closest("[data-automation-id='multiselectInputContainer']")
                    || !!(el.getAttribute && /selectinput|multiselect/i.test(el.getAttribute('data-uxi-widget-type') || ''));
                  if ((el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') && !inMulti) {
                    if (clean(el.value)) return clean(el.value);
                  } else if (!inMulti) {
                    const own = clean(el.innerText || el.textContent || '');
                    if (own && !/^select one$/i.test(own)) return own;
                  }
                  // Searchable prompt: the commitment lives in selectedItemList,
                  // on an ancestor field wrapper rather than on the control.
                  // Scope to this field's own wrapper -- Workday also uses
                  // selectedItemList for the page footer's privacy-policy
                  // moniker, which would otherwise read back as our answer.
                  const wrapper = el.closest("[data-automation-id^='formField']")
                    || el.closest("[data-automation-id='multiSelectContainer']");
                  let node = wrapper || el;
                  const chipNoise = /^(expanded|minimized|search|\d* ?items selected|partial list\b.*|all)$/i;
                  const chipText = (node) => {
                    if (!node || !node.querySelector) return '';
                    const note = node.querySelector("[data-automation-id='promptAriaInstruction']");
                    const noteText = note ? clean(note.textContent) : '';
                    const charm = node.querySelector("[data-automation-id='DELETE_charm']");
                    const selectedCount = /^([1-9]\d*) items selected/i.test(noteText);
                    const bits = node.querySelectorAll(
                      "[data-automation-id='selectedItemList'] li, [data-automation-id='selectedItem']"
                    );
                    for (const bit of bits) {
                      const picked = clean(bit.innerText || bit.textContent || '').replace(/^\s*[x\u00d7]\s*/i, '').trim();
                      if (picked && !chipNoise.test(picked)) return picked;
                    }
                    // The open menu copies the highlighted major into the field
                    // label. That is not a chip. A chip has a remove button or
                    // "1 item selected".
                    if (!charm && !selectedCount) return '';
                    const label = node.querySelector("[data-automation-id='promptSelectionLabel']");
                    const labeled = label ? clean(label.innerText || label.textContent || '').replace(/^\s*[x\u00d7]\s*/i, '').trim() : '';
                    if (labeled && !chipNoise.test(labeled)) return labeled;
                    if ((node.getAttribute && node.getAttribute('data-automation-id')) !== 'multiSelectContainer') return '';
                    const lines = (node.innerText || '').split(/\n/).map(clean).filter(Boolean);
                    for (const line of lines) {
                      const picked = line.replace(/^\s*[x\u00d7]\s*/i, '').trim();
                      if (picked && !chipNoise.test(picked)) return picked;
                    }
                    return '';
                  };
                  const box = el.closest("[data-automation-id='multiSelectContainer']");
                  const fromBox = chipText(box);
                  if (fromBox) return fromBox;
                  for (let i = 0; node && i < 3; i++) {
                    if (node.getAttribute && node.getAttribute('data-automation-id') === 'responsiveMonikerInput') break;
                    const picked = chipText(node);
                    if (picked) return picked;
                    node = node.parentElement;
                  }
                  if (inMulti) return '';
                  if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') return clean(el.value);
                  return clean(el.innerText || el.textContent || '');
                }"""
            )
            or ""
        )
    except Exception:
        try:
            return (locator.input_value() or "").strip()
        except Exception:
            try:
                return (locator.inner_text() or "").strip()
            except Exception:
                return ""


def read_state_widget(page: Any) -> str:
    """Read ONLY the state/province button or input. Never City, phone, or page.inner_text."""
    loc = find_state_control(page)
    if loc is None:
        return ""
    return parse_state_widget_text(widget_readback(loc))


def form_field_control(page: Any, *suffixes: str) -> Any | None:
    """Control inside a Workday `formField-<suffix>` wrapper.

    Walmart's tenant leaves data-automation-id empty on the input/button and
    puts it only on the wrapper div, so a flat id lookup finds nothing.
    """
    for suffix in suffixes:
        try:
            wrapper = page.locator(f'[data-automation-id="formField-{suffix}"]')
            if not wrapper.count():
                continue
        except Exception:
            continue
        for w in range(min(wrapper.count(), 3)):
            scope = wrapper.nth(w)
            for sel in ("input:not([type=hidden])", "button", "select", "textarea"):
                try:
                    loc = scope.locator(sel)
                    for i in range(min(loc.count(), 4)):
                        cand = loc.nth(i)
                        if cand.is_visible():
                            return cand
                except Exception:
                    continue
    return None


def form_field_text(page: Any, suffix: str) -> str:
    """Rendered text of a formField wrapper, label included."""
    try:
        loc = page.locator(f'[data-automation-id="formField-{suffix}"]')
        if loc.count() and loc.first.is_visible():
            return str(loc.first.inner_text() or "").strip()
    except Exception:
        pass
    return ""


def find_state_control(page: Any) -> Any | None:
    wrapped = form_field_control(page, "countryRegion", "stateProvince")
    if wrapped is not None:
        return wrapped
    for aid in (
        "addressSection_countryRegion",
        "addressSection_stateProvince",
        "countryRegion",
        "stateProvince",
        "state",
    ):
        loc = page.locator(f'[data-automation-id="{aid}"]')
        try:
            if loc.count() and loc.first.is_visible() and is_state_control_meta(automation_id=aid):
                return loc.first
        except Exception:
            continue
    candidates = page.locator(
        "button[data-automation-id], input[data-automation-id], select[data-automation-id], "
        "[role=combobox], button[aria-label], input[aria-label]"
    )
    try:
        n = min(candidates.count(), 80)
    except Exception:
        n = 0
    for i in range(n):
        el = candidates.nth(i)
        try:
            if not el.is_visible():
                continue
            meta = el.evaluate(
                """el => ({
                  automationId: el.getAttribute('data-automation-id') || '',
                  aria: el.getAttribute('aria-label') || '',
                  name: el.name || '',
                  id: el.id || '',
                  placeholder: el.placeholder || ''
                })"""
            )
        except Exception:
            continue
        if is_state_control_meta(
            aria_label=meta.get("aria") or "",
            automation_id=meta.get("automationId") or "",
            name=meta.get("name") or "",
            element_id=meta.get("id") or "",
            placeholder=meta.get("placeholder") or "",
        ):
            return el
    return None


def postal_error_visible(page: Any) -> bool:
    try:
        loc = page.get_by_text(POSTAL_ERROR_RE)
        n = loc.count()
        for i in range(n):
            el = loc.nth(i)
            if el.is_visible():
                return True
    except Exception:
        pass
    try:
        err = page.locator('[data-automation-id="error"], #postal-error')
        for i in range(err.count()):
            el = err.nth(i)
            if el.is_visible() and POSTAL_ERROR_RE.search(el.inner_text() or ""):
                return True
    except Exception:
        pass
    return False


def select_prompt(
    page: Any,
    control: Any,
    terms: list[str],
    *,
    readback_fn: ReadbackFn,
    close_outside: bool = False,
    option_gate: Callable[[list[str]], bool] | None = None,
) -> str:
    """4-strategy custom-select. Each strategy verifies stickiness via readback_fn.

    Order: native → type-to-filter → click-scan → keyboard.
    Click-scan / type-to-filter follow Workday PromptSelect: JS-click → wait
    promptOption|role=option|listItem → substring pick → else searchBox → ESC.
    """
    terms = [str(t).strip() for t in terms if str(t or "").strip()]
    if not terms:
        return readback_fn()
    current = readback_fn()
    if readback_committed(current, terms):
        return current

    strategies = (
        _strategy_native,
        _strategy_type_to_filter,
        _strategy_click_scan,
        _strategy_keyboard,
    )
    for strat in strategies:
        try:
            strat(page, control, terms, option_gate=option_gate)
        except Exception:
            pass
        got = readback_fn()
        if readback_committed(got, terms):
            # Escape deletes a choice Workday has not finished committing.
            return got
        _close_prompt(page, control, click_outside=close_outside)
    _close_prompt(page, control, click_outside=close_outside)
    return readback_fn()


def fill_searchable_prompt(page: Any, locator: Any, desired: str) -> str:
    """Back-compat wrapper around select_prompt."""
    return select_prompt(page, locator, [desired], readback_fn=lambda: widget_readback(locator))


def _strategy_native(
    page: Any,
    control: Any,
    terms: list[str],
    *,
    option_gate: Callable[[list[str]], bool] | None = None,
) -> None:
    try:
        tag = str(control.evaluate("el => (el.tagName || '').toLowerCase()"))
    except Exception:
        return
    if tag != "select":
        return
    try:
        options = list(control.evaluate("el => [...el.options].map(o => (o.text || '').trim())") or [])
    except Exception:
        options = []
    if option_gate and not option_gate(options):
        return
    picked = pick_option_substring(options, terms)
    if not picked:
        return
    try:
        control.select_option(label=picked, timeout=4000)
    except Exception:
        try:
            control.select_option(value=picked, timeout=2000)
        except Exception:
            return


def _unfiltered_list_blocked(
    page: Any,
    option_gate: Callable[[list[str]], bool] | None,
) -> bool:
    """Reject Country Phone Code (+1) lists. Do not apply after type-to-filter (len==1 is expected)."""
    if option_gate is None:
        return False
    _wait_options(page)
    texts = _visible_option_texts(page)
    if not texts:
        return False
    return not option_gate(texts)


def _strategy_type_to_filter(
    page: Any,
    control: Any,
    terms: list[str],
    *,
    option_gate: Callable[[list[str]], bool] | None = None,
) -> None:
    _open_prompt(page, control)
    if _unfiltered_list_blocked(page, option_gate):
        return
    _type_and_pick(page, control, terms)


def _strategy_click_scan(
    page: Any,
    control: Any,
    terms: list[str],
    *,
    option_gate: Callable[[list[str]], bool] | None = None,
) -> None:
    _open_prompt(page, control)
    _wait_options(page)
    if _unfiltered_list_blocked(page, option_gate):
        return
    if _click_option_substring(page, terms):
        return
    _type_and_pick(page, control, terms)


def _strategy_keyboard(
    page: Any,
    control: Any,
    terms: list[str],
    *,
    option_gate: Callable[[list[str]], bool] | None = None,
) -> None:
    """Type the first term, then click a matching row. Enter commits the highlight."""
    _ = option_gate
    try:
        control.click(timeout=3000)
    except Exception:
        _js_click(control)
    _settle(page, 120)
    try:
        page.keyboard.type(terms[0], delay=20)
    except Exception:
        return
    _settle(page, 200)
    _click_option_substring(page, terms)


def _open_list_options(page: Any) -> list[str]:
    """Option labels in the menu that is open now, not a leftover list elsewhere."""
    try:
        texts = page.evaluate(
            """() => {
              const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
              const lists = [...document.querySelectorAll('[data-automation-id="activeListContainer"]')]
                .filter(el => el.getBoundingClientRect().height > 20);
              const root = lists.length ? lists[lists.length - 1] : null;
              if (!root) return [];
              const rows = [...root.querySelectorAll(
                '[data-automation-id="promptOption"], [data-automation-id="menuItem"], [role="option"]'
              )];
              const out = [];
              for (const row of rows) {
                const text = clean(row.innerText);
                if (text && !out.includes(text)) out.push(text);
              }
              return out.slice(0, 20);
            }"""
        )
    except Exception:
        return []
    return [str(item) for item in texts or []]


def _commit_listed_choice(page: Any, control: Any, terms: list[str], *, force: bool = False) -> tuple[str, list[str]]:
    """Open one dropdown and mouse-click the matching row. Do not Escape a committed choice."""
    current = choice_readback(control)
    if not force and readback_committed(current, terms):
        return current, []
    try:
        tag = str(control.evaluate("el => (el.tagName || '').toLowerCase()"))
    except Exception:
        tag = ""
    if tag == "select":
        _strategy_native(page, control, terms)
        got = choice_readback(control)
        if readback_committed(got, terms):
            return got, []
    _open_choice_list(page, control)
    texts = _options_near_control(page, control) or _visible_option_texts(page)
    picked = pick_option_substring(texts, terms)
    clicked = False
    if picked:
        clicked = _mouse_click_visible_option(page, picked) or _click_exact_text(page, picked)
    if not clicked:
        for term in terms:
            if _click_exact_text(page, term):
                clicked = True
                break
    if clicked:
        _settle(page, 300)
    got = choice_readback(control)
    if readback_committed(got, terms):
        return got, texts
    if _prompt_panel_open(page) or _visible_option_texts(page):
        _close_prompt(page, control, click_outside=False)
    return choice_readback(control), texts


def _click_exact_text(page: Any, text: str) -> bool:
    """Click a visible node whose own text is exactly `text`, preferring the shortest row."""
    try:
        point = page.evaluate(
            """(text) => {
              const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
              const hits = [];
              for (const node of document.querySelectorAll('div, span, li, p, button, [role="option"]')) {
                const own = clean([...node.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(''));
                const full = clean(node.innerText);
                if (own !== text && full !== text) continue;
                node.scrollIntoView({block: 'nearest', inline: 'nearest'});
                const r = node.getBoundingClientRect();
                if (r.width < 8 || r.height < 8 || r.height > 48) continue;
                if (r.bottom < 0 || r.top > window.innerHeight || r.right < 0 || r.left > window.innerWidth) continue;
                hits.push({h: r.height * r.width, x: r.x + Math.min(16, r.width / 2), y: r.y + r.height / 2});
              }
              hits.sort((a, b) => a.h - b.h);
              return hits.length ? {x: hits[0].x, y: hits[0].y} : null;
            }""",
            text,
        )
    except Exception:
        point = None
    if not point:
        return False
    try:
        page.mouse.click(point["x"], point["y"])
        return True
    except Exception:
        return False


def _options_near_control(page: Any, control: Any) -> list[str]:
    """Options in the listbox closest to this control, not a leftover menu."""
    try:
        texts = control.evaluate(
            """el => {
              const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
              const cr = el.getBoundingClientRect();
              const lists = [...document.querySelectorAll('[role="listbox"], [data-automation-id="activeListContainer"]')]
                .filter(list => list.getBoundingClientRect().height > 20);
              lists.sort((a, b) => {
                const da = Math.abs(a.getBoundingClientRect().top - cr.bottom);
                const db = Math.abs(b.getBoundingClientRect().top - cr.bottom);
                return da - db;
              });
              const root = lists[0];
              if (!root) return [];
              const out = [];
              for (const node of root.querySelectorAll('[role="option"], [data-automation-id="promptOption"]')) {
                const text = clean(node.getAttribute('data-automation-label') || node.innerText);
                if (!text || text.length > 80 || out.includes(text)) continue;
                out.push(text);
              }
              return out.slice(0, 20);
            }"""
        )
    except Exception:
        return []
    return [str(item) for item in texts or []]


def _open_choice_list(page: Any, control: Any) -> None:
    """Open a Select One list. These are role=option menus, not the search prompt."""
    try:
        point = control.evaluate(
            """el => {
              const root = el.closest("[data-automation-id*='formField']") || el;
              const widget = root.querySelector("[data-automation-id='selectWidget'], [aria-haspopup='listbox'], [data-automation-id='promptIcon']") || el;
              const r = widget.getBoundingClientRect();
              if (r.width < 2 || r.height < 2) return null;
              return {x: r.x + Math.min(24, r.width / 2), y: r.y + r.height / 2};
            }"""
        )
    except Exception:
        point = None
    if point:
        try:
            page.mouse.click(point["x"], point["y"])
        except Exception:
            _mouse_click_locator(page, control)
    else:
        _mouse_click_locator(page, control)
    _settle(page, 500)
    if _visible_option_texts(page) or _prompt_panel_open(page):
        return
    try:
        control.focus()
        page.keyboard.press("ArrowDown")
    except Exception:
        pass
    _settle(page, 200)


def _mouse_click_visible_option(page: Any, text: str) -> bool:
    """Trusted click on a visible option row whose text is exactly `text`."""
    try:
        point = page.evaluate(
            """(text) => {
              const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
              const nodes = [...document.querySelectorAll('[role="option"], [data-automation-id="promptOption"]')];
              for (const node of nodes) {
                const label = clean(node.getAttribute('data-automation-label') || node.innerText);
                if (label !== text) continue;
                node.scrollIntoView({block: 'nearest', inline: 'nearest'});
                const r = node.getBoundingClientRect();
                if (r.width < 2 || r.height < 2) continue;
                if (r.bottom < 0 || r.top > window.innerHeight) continue;
                const x = r.x + Math.min(24, Math.max(8, r.width / 2));
                const y = r.y + r.height / 2;
                const top = document.elementFromPoint(x, y);
                if (!top) continue;
                const row = node.parentElement || node;
                if (!row.contains(top) && !node.contains(top)) continue;
                return {x, y};
              }
              return null;
            }""",
            text,
        )
    except Exception:
        point = None
    if not point:
        return False
    try:
        page.mouse.click(point["x"], point["y"])
        return True
    except Exception:
        return False


def _field_row_texts(control: Any) -> list[str]:
    try:
        texts = control.evaluate(
            """el => {
              const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
              const root = el.closest("[data-automation-id*='formField']") || el.parentElement;
              if (!root) return [];
              const out = [];
              for (const node of root.querySelectorAll('li, [role="option"], [data-automation-id="promptOption"], [data-automation-id="menuItem"]')) {
                const text = clean(node.innerText);
                const r = node.getBoundingClientRect();
                if (!text || r.height < 8 || r.height > 80 || out.includes(text)) continue;
                out.push(text);
              }
              return out.slice(0, 20);
            }"""
        )
    except Exception:
        return []
    return [str(item) for item in texts or []]


def _click_exact_row(page: Any, control: Any, text: str) -> bool:
    try:
        point = control.evaluate(
            """(el, text) => {
              const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
              const root = el.closest("[data-automation-id*='formField']") || el.parentElement;
              if (!root) return null;
              for (const node of root.querySelectorAll('li, [role="option"], [data-automation-id="promptOption"], [data-automation-id="menuItem"]')) {
                if (clean(node.innerText) !== text) continue;
                const r = node.getBoundingClientRect();
                if (r.height < 8 || r.height > 80 || r.width < 8) continue;
                return {x: r.x + Math.min(24, r.width / 2), y: r.y + r.height / 2};
              }
              return null;
            }""",
            text,
        )
    except Exception:
        point = None
    if not point:
        return False
    try:
        page.mouse.click(point["x"], point["y"])
        return True
    except Exception:
        return False


def _open_prompt(page: Any, control: Any) -> None:
    if _prompt_panel_open(page):
        return
    if not _mouse_click_locator(page, control):
        if not _js_click(control):
            try:
                control.click(timeout=3000)
            except Exception:
                pass
    _settle(page, 150)


def _js_click(locator: Any) -> bool:
    try:
        locator.evaluate("el => el.click()")
        return True
    except Exception:
        return False


def _mouse_click_locator(page: Any, locator: Any) -> bool:
    """Trusted click at the element's center.

    Workday's prompt rows ignore element.click() (untrusted) and time out a
    normal Playwright click, but a mouse click on the row lands. The last
    listbox option is often below the fold — scroll it into view first.
    """
    try:
        locator.scroll_into_view_if_needed(timeout=1500)
    except Exception:
        pass
    try:
        box = locator.bounding_box()
    except Exception:
        return False
    if not box or box.get("width", 0) < 2 or box.get("height", 0) < 2:
        return False
    try:
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        return True
    except Exception:
        return False


def _type_and_pick(page: Any, control: Any, terms: list[str]) -> bool:
    """Probe the filter box with each term until one surfaces a real option.

    Typing only terms[0] loses the long-form degrees: a profile that says
    "Bachelor of Science in Computer Science" filters a list offering
    "Bachelor of Science (B.S.)" down to nothing, and the short fallbacks
    ("Bachelor", "B.S.") never get typed. Probe in order, stop at the first
    term that yields a match.
    """
    probes: list[str] = []
    for term in terms:
        term = (term or "").strip()
        if term and term.lower() not in {p.lower() for p in probes}:
            probes.append(term)
    for probe in probes:
        if not _type_into_filter(page, control, probe):
            return False
        _wait_options(page)
        if _click_option_substring(page, terms):
            return True
        # Aero's Field of Study says "press enter to search" and shows nothing
        # until Enter. Only do that when the list is still empty, so Enter
        # does not commit a highlighted wrong row.
        if not _visible_option_texts(page):
            try:
                page.keyboard.press("Enter")
            except Exception:
                return False
            _wait_options(page)
            if _click_option_substring(page, terms):
                return True
    return False


def _type_into_filter(page: Any, control: Any, term: str) -> bool:
    try:
        tag = str(control.evaluate("el => (el.tagName || '').toLowerCase()"))
    except Exception:
        tag = ""
    if tag in {"input", "textarea"}:
        try:
            control.fill("")
            control.type(term, delay=20, timeout=4000)
            return True
        except Exception:
            return False
    search = page.locator(SEARCH_BOX_SELECTOR)
    try:
        n = search.count()
        for i in range(n):
            box = search.nth(i)
            if not box.is_visible():
                continue
            box.fill("")
            box.type(term, delay=20, timeout=4000)
            return True
    except Exception:
        return False
    return False


def _wait_options(page: Any) -> bool:
    try:
        page.wait_for_selector(OPTION_SELECTOR, timeout=3500, state="visible")
        return True
    except Exception:
        return False


def _visible_option_texts(page: Any) -> list[str]:
    loc = page.locator(OPTION_SELECTOR)
    texts: list[str] = []
    try:
        n = min(loc.count(), 80)
    except Exception:
        n = 0
    for i in range(n):
        opt = loc.nth(i)
        try:
            if not opt.is_visible():
                continue
            text = (opt.inner_text() or "").strip()
        except Exception:
            continue
        if text:
            texts.append(text)
    return texts


def _click_option_substring(page: Any, terms: list[str]) -> bool:
    loc = page.locator(OPTION_SELECTOR)
    collected: list[tuple[Any, str]] = []
    try:
        n = min(loc.count(), 80)
    except Exception:
        n = 0
    for i in range(n):
        opt = loc.nth(i)
        try:
            if not opt.is_visible():
                continue
            text = (opt.inner_text() or "").strip()
        except Exception:
            continue
        if text:
            collected.append((opt, text))
    picked = pick_option_substring([t for _, t in collected], terms)
    if not picked:
        return False
    for opt, text in collected:
        if text != picked:
            continue
        try:
            opt.scroll_into_view_if_needed(timeout=1500)
        except Exception:
            pass
        if _mouse_click_locator(page, opt):
            return True
        if _mouse_click_prompt_text(page, picked):
            return True
        try:
            opt.click(timeout=1500)
            return True
        except Exception:
            if _js_click(opt):
                return True
    return False


def _close_prompt(page: Any, control: Any, *, click_outside: bool) -> None:
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    if click_outside:
        _click_outside(page, control)
    _settle(page, 120)
    if click_outside and _prompt_panel_open(page):
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        _click_outside(page, control)
        _settle(page, 80)


def _click_outside(page: Any, control: Any) -> None:
    try:
        box = control.bounding_box()
        if box:
            page.mouse.click(max(2, box["x"] - 24), max(2, box["y"] - 24))
            return
    except Exception:
        pass
    try:
        page.mouse.click(4, 2)
    except Exception:
        pass


def _prompt_panel_open(page: Any) -> bool:
    try:
        lists = page.locator('[data-automation-id="activeListContainer"]')
        for i in range(min(lists.count(), 20)):
            if lists.nth(i).is_visible():
                return True
    except Exception:
        pass
    return False


def _settle(page: Any, ms: int = 150) -> None:
    try:
        page.wait_for_timeout(ms)
    except Exception:
        pass


def fill_workday_sticky_fields(
    page: Any,
    profile: Profile,
    filled: list,
    skipped: list,
    notes: list,
    experience: list | None = None,
    job_title: str = "",
    job_text: str = "",
) -> None:
    """Section-aware sticky fills. Failures are recorded; never claimed as success."""
    # Country FIRST. Workday derives the address layout, the State option list,
    # and the Country Phone Code from it. Live Walmart defaulted to
    # "New Caledonia", so State had no US options to match, postal stayed
    # blank, and the phone code sat at +687 -- every downstream field failed
    # because this one was set eleventh instead of first.
    _fill_country_first(page, profile, filled, skipped, notes)
    _fill_phone_number_only(page, profile, filled, skipped)
    _fill_phone_device_type(page, filled, skipped)
    _fill_state_then_postal(page, profile, filled, skipped, notes)
    _fill_how_heard(page, profile, filled, skipped, notes)
    _fill_previous_employee_no(page, profile, filled, skipped)
    if _on_my_experience(page):
        from apply_engine.workday_experience import commit_open_panel, fill_education_panel, fill_work_panels

        fill_education_panel(page, profile, filled, skipped, notes)
        commit_open_panel(page)
        fill_work_panels(page, experience or [], filled, skipped, notes)
        # Work filling presses Escape to close its own menus. That key also
        # removes a Field of Study chip, so the major is committed last.
        _fill_degree_and_fos(page, profile, filled, skipped)
    _fill_application_questions(page, profile, filled, skipped)
    _fill_question_radios(page, profile, filled, skipped)
    _fill_disability_self_id_block(page, profile, filled, skipped)
    _fill_proposed_start_date(page, job_title, job_text, filled, skipped)
    _fill_college_end_date(page, profile, filled, skipped)
    _fill_no_relatives(page, profile, filled, skipped)
    _clear_ungrounded_essays(page)
    _check_terms_consent(page, filled, skipped)



COUNTRY_AIDS = (
    "country",
    "country-input",
    "addressSection_country",
    "countryDropdown",
)

# Workday spells the US several ways depending on tenant and field.
US_TERMS = (
    "United States of America",
    "United States",
    "USA",
    "US",
)


def country_search_terms(profile: Profile) -> list[str]:
    """Probe terms for the Country control, longest first."""
    raw = (profile.country or "").strip()
    terms: list[str] = []
    if raw:
        terms.append(raw)
    low = raw.lower().replace(".", "")
    if not raw or low in {"us", "usa", "united states", "united states of america", "america"}:
        for term in US_TERMS:
            if term.lower() not in {t.lower() for t in terms}:
                terms.append(term)
    return terms


def find_country_control(page: Any) -> Any | None:
    """The Country control, never the Country Phone Code control."""
    wrapped = form_field_control(page, "country")
    if wrapped is not None:
        return wrapped
    for aid in COUNTRY_AIDS:
        loc = page.locator(f'[data-automation-id="{aid}"]')
        try:
            if not loc.count():
                continue
            for i in range(min(loc.count(), 6)):
                cand = loc.nth(i)
                if not cand.is_visible():
                    continue
                blob = " ".join([
                    str(cand.get_attribute("data-automation-id") or ""),
                    str(cand.get_attribute("aria-label") or ""),
                ]).lower()
                if "phone" in blob:
                    continue
                return cand
        except Exception:
            continue
    return None


def _select_united_states(page: Any, control: Any) -> str:
    """Click the United States row. Never the territory that starts with those words."""
    if _prompt_panel_open(page):
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        _settle(page, 200)
    _open_prompt(page, control)
    _settle(page, 400)
    _type_country_search(page, "United States of America")
    _settle(page, 700)
    if not _click_united_states_option(page):
        _close_prompt(page, control, click_outside=True)
    _settle(page, 400)
    return widget_readback(control)


def _type_country_search(page: Any, text: str) -> bool:
    selectors = (
        'input[data-automation-id="searchBox"]',
        '[data-automation-id="promptSearchBox"] input',
        '[role="listbox"] input',
    )
    for sel in selectors:
        loc = page.locator(sel)
        try:
            count = min(loc.count(), 6)
        except Exception:
            continue
        for i in range(count):
            box = loc.nth(i)
            try:
                if not box.is_visible():
                    continue
                box.click(timeout=2000)
                box.fill("")
                box.type(text, delay=25, timeout=4000)
                return True
            except Exception:
                continue
    try:
        page.keyboard.type(text, delay=25)
        return True
    except Exception:
        return False


def _click_united_states_option(page: Any) -> bool:
    try:
        point = page.evaluate(
            """() => {
              const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
              const ok = new Set(['united states of america', 'united states', 'usa', 'us']);
              const nodes = [...document.querySelectorAll(
                '[data-automation-id="promptOption"], [role="option"]'
              )];
              const hits = [];
              for (const node of nodes) {
                const label = clean(node.getAttribute('data-automation-label') || '');
                const first = clean((node.innerText || '').split('\\n')[0]);
                const text = ok.has(label) ? label : (ok.has(first) ? first : '');
                if (!text) continue;
                if (/minor|virgin|island/.test(clean(node.innerText || ''))) continue;
                node.scrollIntoView({block: 'center', inline: 'nearest'});
                const r = node.getBoundingClientRect();
                if (r.width < 2 || r.height < 2) continue;
                if (r.bottom < 0 || r.top > window.innerHeight) continue;
                hits.push({len: text.length, x: r.x + Math.min(24, r.width / 2), y: r.y + r.height / 2});
              }
              hits.sort((a, b) => b.len - a.len);
              return hits.length ? {x: hits[0].x, y: hits[0].y} : null;
            }"""
        )
    except Exception:
        point = None
    if not point:
        return False
    try:
        page.mouse.click(point["x"], point["y"])
        return True
    except Exception:
        return False


def _fill_country_first(page: Any, profile: Profile, filled: list, skipped: list, notes: list) -> None:
    """Set Country before anything that depends on it, then let the form re-render."""
    terms = country_search_terms(profile)
    if not terms:
        return
    control = find_country_control(page)
    if control is None:
        return
    # "United States" is a prefix of "United States Minor Outlying Islands".
    # A prefix match there selects a territory list, and New York becomes Navassa.
    wrapper_text = form_field_text(page, "country")
    current = widget_readback(control)
    shown = parse_state_widget_text(wrapper_text or "") or parse_state_widget_text(current)
    wants_us = any(united_states_label(term) for term in terms)
    if wants_us and united_states_label(shown):
        filled.append({"label": "Country", "mapped_to": "country",
                       "value": shown,
                       "method": "workday-country-default-ok"})
        return
    if not wants_us and readback_committed(current, terms):
        filled.append({"label": "Country", "mapped_to": "country", "value": current,
                       "method": "workday-country-already-set"})
        return
    if wants_us:
        readback = _select_united_states(page, control)
    else:
        readback = select_prompt(
            page, control, terms,
            readback_fn=lambda c=control: widget_readback(c),
            close_outside=True,
        )
    if wants_us:
        committed = united_states_label(parse_state_widget_text(readback))
    else:
        committed = readback_committed(readback, terms)
    if not committed:
        skipped.append({"label": "Country*", "reason": f"readback {readback!r} not a US match",
                        "readback": readback})
        notes.append(f"Country* failed: widget={readback!r} — State/postal/phone code will not match")
        return
    filled.append({"label": "Country", "mapped_to": "country", "value": readback,
                   "method": "workday-prompt-readback"})
    notes.append(f"Country set to {readback!r} before dependent fields")
    # Changing Country re-renders the address and phone sections.
    _settle(page, 1200)


HOW_HEARD_AIDS = (
    "source",
    "sourceSection_source",
    "howDidYouHearAboutUs",
    "source-input",
)


def find_how_heard_control(page: Any) -> Any | None:
    for aid in HOW_HEARD_AIDS:
        loc = page.locator(f'[data-automation-id="{aid}"]')
        try:
            if loc.count() and loc.first.is_visible():
                return loc.first
        except Exception:
            continue
    # Fall back to the labelled prompt, which Walmart marks required.
    try:
        loc = page.get_by_label("How Did You Hear About Us?", exact=False)
        if loc.count() and loc.first.is_visible():
            return loc.first
    except Exception:
        pass
    return None


def _how_heard_terms(profile: Profile) -> list[str]:
    from apply_engine.fields import HOW_HEARD_CAREER_TERMS, HOW_HEARD_PRIMARY, value_candidates

    primary = (profile.how_heard or "").strip() or HOW_HEARD_PRIMARY
    return value_candidates("how_heard", primary, profile) or list(HOW_HEARD_CAREER_TERMS)


def _multiselect_chips(control: Any) -> list[str]:
    try:
        chips = control.evaluate(
            """e => {
              const f = e.closest("[data-automation-id*='formField']") || e.parentElement;
              return Array.from(f.querySelectorAll(
                "[data-automation-id='selectedItem'], [data-automation-id='selectedItemList'] li"
              )).map(x => (x.innerText || '').trim()).filter(Boolean);
            }"""
        )
    except Exception:
        return []
    return [str(c) for c in chips or [] if str(c).strip()]


def _is_multiselect_control(control: Any) -> bool:
    try:
        return bool(
            control.evaluate(
                """e => {
                  const f = e.closest("[data-automation-id*='formField']") || e.parentElement;
                  return !!(
                    f.querySelector("[data-automation-id='multiselectInputContainer'], [data-uxi-widget-type='multiselect'], [data-automation-id='multiSelectContainer']")
                    || (e.getAttribute && /selectinput|multiselect/i.test(e.getAttribute('data-uxi-widget-type') || ''))
                  );
                }"""
            )
        )
    except Exception:
        return False


HOW_HEARD_OPTION_SEL = "[data-automation-id='promptOption'], [data-automation-id='menuItem']"


def _visible_how_heard_options(page: Any) -> list[tuple[Any, str]]:
    loc = page.locator(HOW_HEARD_OPTION_SEL)
    seen: set[str] = set()
    out: list[tuple[Any, str]] = []
    try:
        n = loc.count()
    except Exception:
        return []
    for i in range(n):
        opt = loc.nth(i)
        try:
            if not opt.is_visible():
                continue
            text = (opt.inner_text() or "").strip()
        except Exception:
            continue
        if text and text not in seen and "(+1)" not in text:
            seen.add(text)
            out.append((opt, text))
    return out


def _how_heard_leaf_score(text: str) -> int:
    """Leaves under a Corporate Careers Website folder: microsite/.jobs beat named boards."""
    low = (text or "").strip().lower()
    if re.search(r"microsite|\.jobs\b|jobs microsite", low):
        return 5
    from apply_engine.questions import _how_heard_score

    return _how_heard_score(text)


def _pick_how_heard_option(opts: list[tuple[Any, str]], terms: list[str]) -> tuple[Any, str] | None:
    for term in terms:
        low = term.lower()
        for opt, text in opts:
            if low in text.lower():
                return opt, text
    ranked = sorted(opts, key=lambda row: -_how_heard_leaf_score(row[1]))
    if ranked and _how_heard_leaf_score(ranked[0][1]) > 0:
        return ranked[0]
    return None


def _walk_how_heard_multiselect(page: Any, control: Any, terms: list[str], notes: list) -> list[str]:
    """Hierarchical Workday multiselect: open, walk a category, click a leaf, verify chip."""
    log: list = []
    forced = [x.strip() for x in os.environ.get("WD_HOW_HEARD_PATH", "").split(">") if x.strip()]

    def click_opt(opt: Any) -> bool:
        try:
            opt.scroll_into_view_if_needed(timeout=1500)
        except Exception:
            pass
        if _mouse_click_locator(page, opt):
            return True
        try:
            opt.click(timeout=3000)
            return True
        except Exception:
            return False

    try:
        control.scroll_into_view_if_needed()
        control.click(timeout=3000)
        _settle(page, 800)
        top = _visible_how_heard_options(page)
        log.append(("top", [t for _, t in top]))
        if forced:
            for step in forced:
                o = page.locator(HOW_HEARD_OPTION_SEL).filter(
                    has_text=re.compile(r"^\s*" + re.escape(step) + r"\s*$")
                ).first
                click_opt(o)
                _settle(page, 800)
                log.append(("forced", step))
            page.keyboard.press("Escape")
            _settle(page, 300)
            notes.append(f"how_heard multiselect walk: {log}")
            return _multiselect_chips(control)
        hit = _pick_how_heard_option(top, terms)
        if hit is None:
            cats = sorted(top, key=lambda x: 0 if re.search(r"direct|website|career|company|online", x[1], re.I) else 1)
            for _o, cat in cats:
                o = page.locator(HOW_HEARD_OPTION_SEL).filter(
                    has_text=re.compile(r"^\s*" + re.escape(cat) + r"\s*$")
                ).first
                try:
                    vis = o.is_visible()
                except Exception:
                    vis = False
                if not vis:
                    page.keyboard.press("Escape")
                    _settle(page, 400)
                    control.click(timeout=3000)
                    _settle(page, 800)
                if not click_opt(o):
                    log.append((cat, "click failed"))
                    continue
                _settle(page, 800)
                kids = _visible_how_heard_options(page)
                log.append((cat, [k for _, k in kids]))
                hit = _pick_how_heard_option(kids, terms)
                if hit:
                    break
                back = page.locator("[data-automation-id='backButton'], [aria-label*='Back' i]")
                if back.count():
                    back.first.click(timeout=2000)
                    _settle(page, 600)
        if hit:
            o, t = hit
            click_opt(o)
            _settle(page, 800)
            log.append(("clicked", t))
            if not _multiselect_chips(control):
                kids = _visible_how_heard_options(page)
                kids = [(k, label) for k, label in kids if label.strip().lower() != t.strip().lower()]
                leaf = _pick_how_heard_option(kids, terms) if kids else None
                if leaf:
                    lo, lt = leaf
                    click_opt(lo)
                    _settle(page, 800)
                    log.append(("leaf", lt))
                    o, t = lo, lt
            if not _multiselect_chips(control):
                cb = o.locator("input[type=checkbox], [role=checkbox]")
                if cb.count():
                    cb.first.click(force=True)
                    _settle(page, 500)
        page.keyboard.press("Escape")
        _settle(page, 300)
    except Exception as exc:
        log.append(("err", f"{exc}"[:120]))
    notes.append(f"how_heard multiselect walk: {log}")
    return _multiselect_chips(control)


def _fill_how_heard(page: Any, profile: Profile, filled: list, skipped: list, notes: list) -> None:
    """How Did You Hear About Us? Tenants spell Company Website differently; some use a hierarchical multiselect."""
    terms = _how_heard_terms(profile)
    control = find_how_heard_control(page)
    if control is None:
        return
    if not terms:
        skipped.append({"label": "How Did You Hear About Us?*", "reason": "no profile value — never invent"})
        return
    if _is_multiselect_control(control):
        chips = _multiselect_chips(control)
        if not chips:
            chips = _walk_how_heard_multiselect(page, control, terms, notes)
        if chips:
            filled.append({
                "label": "How Did You Hear About Us?",
                "mapped_to": "how_heard",
                "value": "; ".join(chips),
                "method": "wd-howheard-multiselect",
            })
        else:
            skipped.append({"label": "How Did You Hear About Us?*", "reason": "multiselect: no chip committed"})
        return
    current = widget_readback(control)
    if readback_committed(current, terms):
        filled.append({"label": "How Did You Hear About Us?", "mapped_to": "how_heard",
                       "value": current, "method": "workday-already-set"})
        return
    for term in terms:
        readback = select_prompt(
            page, control, [term],
            readback_fn=lambda c=control: widget_readback(c),
            close_outside=True,
        )
        if readback_committed(readback, [term]):
            filled.append({"label": "How Did You Hear About Us?", "mapped_to": "how_heard",
                           "value": readback, "method": "wd-howheard-synonym"})
            return
    skipped.append({
        "label": "How Did You Hear About Us?*",
        "reason": f"no synonym stuck; tried {terms[:8]!r}",
        "readback": widget_readback(control),
    })


PHONE_DEVICE_AIDS = (
    "phoneDeviceType",
    "phone-device-type",
    "deviceType",
    "phoneType",
    "phone-type",
)
PHONE_DEVICE_TERMS = (
    "Personal Mobile",
    "Personal Cell",
    "Personal Phone",
    "Mobile Phone",
    "Mobile",
    "Cell Phone",
    "Cellular",
    "Cell",
)
PHONE_DEVICE_AVOID_RE = re.compile(r"\bbusiness\b|\bwork\b|\bland\s*line\b|\bfax\b", re.I)


def _phone_device_committed(text: str) -> bool:
    raw = (text or "").strip()
    if not raw or PHONE_DEVICE_AVOID_RE.search(raw):
        return False
    return readback_committed(raw, PHONE_DEVICE_TERMS)


def _fill_phone_device_type(page: Any, filled: list, skipped: list) -> None:
    """Required Workday Phone Device Type (Kyndryl) — Mobile, never leave Select One."""
    control = form_field_control(page, *PHONE_DEVICE_AIDS)
    if control is None:
        for aid in PHONE_DEVICE_AIDS:
            loc = page.locator(f'[data-automation-id="{aid}"]')
            try:
                if loc.count() and loc.first.is_visible():
                    control = loc.first
                    break
            except Exception:
                continue
    if control is None:
        for field in _iter_leaf_form_fields(page):
            try:
                text = field.inner_text() or ""
            except Exception:
                continue
            if not re.search(r"phone device type|device type", text, re.I):
                continue
            widget = _visible_prompt(field)
            if widget is not None:
                control = widget
                break
    if control is None:
        return
    current = choice_readback(control)
    if _phone_device_committed(current):
        filled.append({
            "label": "Phone Device Type",
            "mapped_to": "phone_device_type",
            "value": current,
            "method": "workday-phone-device",
        })
        return
    readback, options = _commit_listed_choice(
        page,
        control,
        list(PHONE_DEVICE_TERMS),
        force=bool(PHONE_DEVICE_AVOID_RE.search(current or "")),
    )
    if _phone_device_committed(readback):
        filled.append({
            "label": "Phone Device Type",
            "mapped_to": "phone_device_type",
            "value": readback,
            "method": "workday-phone-device",
        })
        return
    skipped.append({
        "label": "Phone Device Type*",
        "reason": f"readback {readback!r} did not match Mobile (options {options[:6]!r})",
        "readback": readback,
    })


def _fill_phone_number_only(page: Any, profile: Profile, filled: list, skipped: list) -> None:
    code = page.locator(
        '[data-automation-id="country-phone-code"], [data-automation-id="countryPhoneCode"]'
    )
    try:
        if code.count() and code.first.is_visible():
            skipped.append({"label": "Country Phone Code", "reason": "never fill country-phone-code"})
    except Exception:
        pass
    target = form_field_control(page, "phoneNumber")
    if target is None:
        loc = page.locator('[data-automation-id="phone-number"]')
        if not loc.count() or not loc.first.is_visible():
            return
        target = loc.first
    phone = profile.phone or ""
    try:
        target.click(timeout=3000)
        target.fill("")
        target.fill(phone, timeout=4000)
        value = widget_readback(target)
    except Exception as exc:
        skipped.append({"label": "phone-number", "reason": f"write failed: {exc}"[:120]})
        return
    if phone_digits_match(value, phone):
        filled.append({"label": "phone-number", "mapped_to": "phone", "value": value, "method": "workday-phone"})
    else:
        skipped.append(
            {
                "label": "phone-number",
                "reason": f"digits {phone_digits(value)!r} != profile last-10 {phone_last10(phone)}",
                "readback": value,
            }
        )


def _fill_state_then_postal(page: Any, profile: Profile, filled: list, skipped: list, notes: list) -> None:
    terms = state_search_terms(profile)
    if not terms:
        return
    loc = find_state_control(page)
    if loc is None:
        return
    readback = select_prompt(
        page,
        loc,
        terms,
        readback_fn=lambda: read_state_widget(page),
        option_gate=is_plausible_state_option_list,
    )
    # Always re-read the state widget — never page.inner_text / City.
    readback = read_state_widget(page)
    err = postal_error_visible(page)
    verdict = evaluate_state_widget_readback(
        readback,
        profile.state or terms[0],
        page_body="",
        postal_error=err,
    )
    if not verdict["ok"]:
        skipped.append({"label": "State*", "reason": verdict["reason"], "readback": readback})
        notes.append(f"State* failed: {verdict['reason']} (widget={readback!r})")
        return
    filled.append({"label": "State", "mapped_to": "state", "value": readback, "method": "workday-prompt-readback"})
    postal = (profile.postal_code or "").strip()
    if not postal:
        return
    ptarget = form_field_control(page, "postalCode")
    if ptarget is None:
        ploc = page.locator(
            '[data-automation-id="addressSection_postalCode"], [data-automation-id="postalCode"], input[name="postal"]'
        )
        if not ploc.count():
            return
        ptarget = ploc.first
    try:
        ptarget.fill("")
        ptarget.fill(postal, timeout=4000)
    except Exception as exc:
        skipped.append({"label": "postal", "reason": f"write failed: {exc}"[:120]})
        return
    zip_readback = widget_readback(ptarget)
    if postal_error_visible(page):
        skipped.append({"label": "State*", "reason": "postal error text present after zip", "readback": readback})
        notes.append("State* failed: postal error after writing zip")
        return
    if zip_readback.strip() != postal and phone_digits(zip_readback) != phone_digits(postal):
        skipped.append({"label": "postal", "reason": f"readback {zip_readback!r} != {postal!r}", "readback": zip_readback})
        return
    filled.append(
        {"label": "postal", "mapped_to": "postal_code", "value": zip_readback, "method": "workday-postal-after-state"}
    )


PREV_EMPLOYEE_RE = re.compile(
    r"previously (worked|employed)|previous employee|"
    r"previously worked for|"
    r"(?:former|current) (?!or former government)(?!government).{0,40}employee|"
    r"ever been an? (?!government).{0,40}employee|"
    r"worked (for|at) .{0,30}before",
    re.I,
)


def _click_styled_radio(radio: Any) -> bool:
    """Workday radios often ignore input.check(); the visible label click sticks."""
    try:
        if radio.is_checked():
            return True
    except Exception:
        pass
    try:
        radio.evaluate(
            """el => {
              const lab = (el.labels && el.labels[0]) || el.closest('label');
              (lab || el).click();
            }"""
        )
        try:
            _settle(radio.page, 80)
        except Exception:
            pass
    except Exception:
        pass
    try:
        if radio.is_checked():
            return True
    except Exception:
        pass
    try:
        radio.check(timeout=2000, force=True)
        return bool(radio.is_checked())
    except Exception:
        return False


def _fill_previous_employee_no(page: Any, profile: Profile, filled: list, skipped: list) -> None:
    if profile.previous_employee:
        skipped.append({"label": "previous_employee", "reason": "profile says yes — not auto-filled"})
        return
    field = page.locator("[data-automation-id*='formField']").filter(has_text=PREV_EMPLOYEE_RE)
    if not field.count():
        field = page.locator('[data-automation-id*="previouslyWorked"], [data-automation-id*="previousEmployee"]')
    if not field.count():
        return
    try:
        if not field.first.is_visible():
            return
    except Exception:
        return
    radios = field.get_by_role("radio")
    picked = False
    for i in range(radios.count()):
        radio = radios.nth(i)
        try:
            name = (radio.get_attribute("value") or radio.get_attribute("aria-label") or "").strip()
            label = radio.evaluate(
                "el => (el.labels && el.labels[0] && el.labels[0].innerText || el.getAttribute('aria-label') || el.value || '').trim()"
            )
            blob = f"{name} {label}"
            if re.fullmatch(r"\s*no\s*", blob, re.I) or re.search(r"\bno\b", blob, re.I):
                if not _click_styled_radio(radio):
                    continue
                picked = True
                break
        except Exception:
            continue
    if not picked:
        no_btn = field.get_by_text(re.compile(r"^no$", re.I))
        try:
            if no_btn.count():
                no_btn.first.click(timeout=3000)
                picked = True
        except Exception:
            pass
    if not picked:
        skipped.append({"label": "previous_employee", "reason": "No radio not found inside previously-worked formField"})
        return
    readback = _formfield_checked_yes_no(field)
    if readback != "No":
        skipped.append({"label": "previous_employee", "reason": f"readback {readback!r} is not No", "readback": readback})
        return
    if _employee_followups_visible(page):
        skipped.append(
            {
                "label": "previous_employee",
                "reason": "employee-id/manager still visible after No",
                "readback": readback,
            }
        )
        return
    filled.append(
        {"label": "previous_employee", "mapped_to": "previous_employee", "value": readback, "method": "formField-radio"}
    )


def _formfield_checked_yes_no(field: Any) -> str:
    radios = field.get_by_role("radio")
    try:
        n = radios.count()
    except Exception:
        n = 0
    for i in range(n):
        radio = radios.nth(i)
        try:
            if not radio.is_checked():
                continue
            blob = radio.evaluate(
                "el => (el.labels && el.labels[0] && el.labels[0].innerText || el.getAttribute('aria-label') || el.value || '').trim()"
            )
        except Exception:
            continue
        if re.search(r"\bno\b", str(blob), re.I):
            return "No"
        if re.search(r"\byes\b", str(blob), re.I):
            return "Yes"
    return ""


def _employee_followups_visible(page: Any) -> bool:
    for aid in EMPLOYEE_FOLLOWUP_AIDS:
        follow = page.locator(f'[data-automation-id*="{aid}"]')
        try:
            for i in range(follow.count()):
                el = follow.nth(i)
                if el.is_visible():
                    return True
        except Exception:
            continue
    return False


_FOLDER_LINE = re.compile(r"^(all|partial list\b.*|by\b.+)$", re.I)


def _prompt_option_locator(page: Any) -> Any:
    scoped = page.locator(
        '[data-automation-id="activeListContainer"] [data-automation-id="promptOption"]'
    )
    try:
        if scoped.count():
            return scoped
    except Exception:
        pass
    return page.locator('[data-automation-id="promptOption"]')


def _prompt_option_texts(page: Any) -> list[str]:
    loc = _prompt_option_locator(page)
    texts: list[str] = []
    try:
        n = min(loc.count(), 200)
    except Exception:
        return texts
    for i in range(n):
        opt = loc.nth(i)
        try:
            box = opt.bounding_box()
            if not box or box.get("height", 0) < 2:
                continue
            text = re.sub(r"\s+", " ", (opt.inner_text() or "")).strip()
        except Exception:
            continue
        if text and text not in texts:
            texts.append(text)
    return texts


def _is_prompt_folder_list(texts: list[str]) -> bool:
    return bool(texts) and all(_FOLDER_LINE.match(text) for text in texts)


def _multiselect_still_empty(page: Any, control: Any = None) -> bool:
    """True when this multiselect has no chip. Other empty prompts on the page do not count."""
    try:
        if control is not None:
            return bool(
                control.evaluate(
                    """el => {
                      const box = el.closest('[data-automation-id="multiSelectContainer"]') || el;
                      const note = box.querySelector('[data-automation-id="promptAriaInstruction"]');
                      const charm = box.querySelector('[data-automation-id="DELETE_charm"]');
                      const pill = box.querySelector("[data-automation-id='selectedItem'], [data-automation-id='selectedItemList'] li");
                      if (charm || pill) return false;
                      return !(note && /^[1-9]\\d* items selected/i.test(note.textContent || ''));
                    }"""
                )
            )
        return bool(
            page.evaluate(
                """() => [...document.querySelectorAll('[data-automation-id="promptAriaInstruction"]')]
                  .some(n => /0 items selected/i.test(n.textContent || ''))"""
            )
        )
    except Exception:
        return False


def _bring_prompt_list_into_view(page: Any) -> None:
    """The majors menu opens under the field. After five jobs that is below the window."""
    try:
        page.evaluate(
            """() => {
              const lists = [...document.querySelectorAll('[data-automation-id="activeListContainer"]')]
                .filter(el => el.getBoundingClientRect().height > 20);
              const root = lists[lists.length - 1];
              if (!root) return;
              root.scrollIntoView({block: 'center', inline: 'nearest', behavior: 'instant'});
            }"""
        )
    except Exception:
        return


def _mouse_click_prompt_text(page: Any, text: str) -> bool:
    """Click the prompt row that is actually under the pointer.

    Workday virtualizes this list. An off-screen duplicate still has a box, and
    clicking its center hits the page footer instead of selecting the major.
    """
    _bring_prompt_list_into_view(page)
    for offset in (24, 16, 48, 80):
        try:
            point = page.evaluate(
                """({text, offset}) => {
                  const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                  const lists = [...document.querySelectorAll('[data-automation-id="activeListContainer"]')]
                    .filter(el => el.getBoundingClientRect().height > 20);
                  const root = lists.length ? lists[lists.length - 1] : document;
                  const lr = lists.length ? root.getBoundingClientRect() : null;
                  const opts = [...root.querySelectorAll('[data-automation-id="promptOption"]')];
                  for (const opt of opts) {
                    if (clean(opt.innerText) !== text) continue;
                    const row = opt.closest('[data-automation-id="menuItem"]') || opt;
                    const r = row.getBoundingClientRect();
                    if (r.height < 2 || r.width < 2) continue;
                    const x = r.x + Math.min(offset, Math.max(8, r.width / 2));
                    const y = r.y + r.height / 2;
                    if (y < 2 || y > window.innerHeight - 2 || x < 2 || x > window.innerWidth - 2) continue;
                    if (lr && (y <= lr.top + 1 || y >= lr.bottom - 1)) continue;
                    const top = document.elementFromPoint(x, y);
                    // The row's parent often receives the hit. That is still the
                    // menu. A point outside the menu is the page footer.
                    if (!top || !root.contains(top)) continue;
                    return {x, y};
                  }
                  return null;
                }""",
                {"text": text, "offset": offset},
            )
        except Exception:
            point = None
        if not point:
            continue
        try:
            page.mouse.click(point["x"], point["y"])
            return True
        except Exception:
            continue
    return False


def _prompt_has_exact_option(page: Any, text: str) -> bool:
    try:
        return bool(
            page.evaluate(
                """(text) => {
                  const lists = [...document.querySelectorAll('[data-automation-id="activeListContainer"]')]
                    .filter(el => el.getBoundingClientRect().height > 20);
                  const root = lists.length ? lists[lists.length - 1] : document;
                  return [...root.querySelectorAll('[data-automation-id="promptOption"]')]
                    .some(el => (el.innerText || '').replace(/\\s+/g, ' ').trim() === text);
                }""",
                text,
            )
        )
    except Exception:
        return False


def _scroll_prompt_option_into_view(page: Any, text: str) -> None:
    """Scroll the virtual list until `text` sits inside the open menu."""
    for _ in range(80):
        if _prompt_has_exact_option(page, text):
            break
        try:
            moved = page.evaluate(
                """() => {
                  const lists = [...document.querySelectorAll('[data-automation-id="activeListContainer"]')]
                    .filter(el => el.getBoundingClientRect().height > 20);
                  const root = lists[lists.length - 1];
                  if (!root) return false;
                  let node = root;
                  let scroller = null;
                  for (let depth = 0; node && depth < 6 && !scroller; depth++) {
                    const nodes = [node, ...node.querySelectorAll('*')];
                    scroller = nodes.find(el => el.scrollHeight > el.clientHeight + 8);
                    node = node.parentElement;
                  }
                  if (!scroller) return false;
                  const before = scroller.scrollTop;
                  scroller.scrollTop = before + Math.max(40, scroller.clientHeight - 8);
                  scroller.dispatchEvent(new Event('scroll', {bubbles: true}));
                  return scroller.scrollTop !== before;
                }"""
            )
        except Exception:
            return
        if not moved:
            return
        _settle(page, 40)
    for _ in range(6):
        try:
            placed = page.evaluate(
                """(text) => {
                  const lists = [...document.querySelectorAll('[data-automation-id="activeListContainer"]')]
                    .filter(el => el.getBoundingClientRect().height > 20);
                  const root = lists[lists.length - 1];
                  if (!root) return false;
                  const nodes = [root, ...root.querySelectorAll('*')];
                  const scroller = nodes.find(el => el.scrollHeight > el.clientHeight + 8);
                  const opt = [...root.querySelectorAll('[data-automation-id="promptOption"]')]
                    .find(el => (el.innerText || '').replace(/\\s+/g, ' ').trim() === text);
                  if (!opt || !scroller) return false;
                  const lr = root.getBoundingClientRect();
                  let r = opt.getBoundingClientRect();
                  if (r.top < lr.top + 4) scroller.scrollTop -= (lr.top + 12 - r.top);
                  else if (r.bottom > lr.bottom - 4) scroller.scrollTop += (r.bottom - (lr.bottom - 12));
                  r = opt.getBoundingClientRect();
                  const y = r.y + r.height / 2;
                  return y > lr.top && y < lr.bottom;
                }""",
                text,
            )
        except Exception:
            return
        if placed:
            return
        _settle(page, 80)


def _wait_for_prompt_leaves(page: Any, timeout_ms: int = 4000) -> bool:
    waited = 0
    while waited <= timeout_ms:
        texts = _prompt_option_texts(page)
        if texts and not _is_prompt_folder_list(texts):
            return True
        page.wait_for_timeout(200)
        waited += 200
    return False


def field_of_study_committed(readback: str, term: str) -> bool:
    """True for the exact major or a table-driven synonym, not a longer compound."""
    from apply_engine.fields import field_of_study_terms

    got = re.sub(r"\s+", " ", readback or "").strip().lower()
    if not got:
        return False
    allowed = {re.sub(r"\s+", " ", t).strip().lower() for t in field_of_study_terms(term) if t.strip()}
    return got in allowed


def _clear_wrong_multiselect_chip(page: Any, control: Any, term: str, *, exact: bool = False) -> None:
    """Remove a chip that is not the major we want. Never click a matching chip."""
    current = widget_readback(control)
    matches = field_of_study_committed(current, term) if exact else readback_committed(current, [term])
    if not (current or "").strip() or matches:
        return
    try:
        point = control.evaluate(
            """el => {
              const box = el.closest('[data-automation-id="multiSelectContainer"]');
              if (!box) return null;
              const charm = box.querySelector('[data-automation-id="DELETE_charm"]');
              const nodes = charm ? [charm] : [...box.querySelectorAll('button, [role="button"]')];
              const label = (n) => ((n.getAttribute('aria-label') || '') + ' ' + (n.innerText || '')).trim();
              const btn = charm || nodes.find(n => /^(x|×)$/i.test(label(n)) || /\\b(remove|delete)\\b/i.test(label(n)));
              if (!btn) return null;
              const r = btn.getBoundingClientRect();
              if (r.width < 2 || r.height < 2) return null;
              return {x: r.x + r.width / 2, y: r.y + r.height / 2};
            }"""
        )
    except Exception:
        return
    if not point:
        try:
            point = control.evaluate(
                """(el, wrong) => {
                  const box = el.closest('[data-automation-id="multiSelectContainer"]');
                  if (!box) return null;
                  const nodes = [...box.querySelectorAll('*')].filter(n => (n.innerText || '').trim() === wrong && n.children.length === 0);
                  const node = nodes[0];
                  if (!node) return null;
                  const r = node.getBoundingClientRect();
                  if (r.width < 2) return null;
                  return {x: Math.max(2, r.x - 12), y: r.y + r.height / 2};
                }""",
                current.split(",")[-1].strip(),
            )
        except Exception:
            point = None
    if not point:
        return
    try:
        page.mouse.click(point["x"], point["y"])
    except Exception:
        return
    _settle(page, 300)
    if readback_committed(widget_readback(control), [current]):
        try:
            side = control.evaluate(
                """(el, wrong) => {
                  const box = el.closest('[data-automation-id="multiSelectContainer"]');
                  if (!box) return null;
                  const nodes = [...box.querySelectorAll('*')].filter(n => (n.innerText || '').trim() === wrong && n.children.length === 0);
                  const node = nodes[0];
                  if (!node) return null;
                  const r = node.getBoundingClientRect();
                  if (r.width < 2) return null;
                  return {x: Math.max(2, r.x - 14), y: r.y + r.height / 2};
                }""",
                current.split(",")[-1].strip(),
            )
        except Exception:
            side = None
        if side:
            try:
                page.mouse.click(side["x"], side["y"])
            except Exception:
                pass
            _settle(page, 300)


def _commit_field_of_study(page: Any, control: Any, term: str, notes: list | None = None) -> bool:
    """Open a Workday multiselect, enter the All folder, and click the major.

    Aero's Field of Study does not search on Enter. Enter opens two folders
    ("Partial List" and "All"). A click on All reveals the majors, and typing
    then jumps the list. Clicking the search input instead sends the prompt
    back to those folders, so this path never does that.
    """
    def _note(message: str) -> None:
        if notes is not None:
            notes.append(message)

    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    _settle(page, 100)
    try:
        control.scroll_into_view_if_needed(timeout=3000)
    except Exception:
        pass
    _clear_wrong_multiselect_chip(page, control, term, exact=True)
    try:
        control.evaluate("el => el.focus()")
    except Exception:
        pass
    if not _mouse_click_locator(page, control):
        try:
            control.click(timeout=3000)
        except Exception:
            if not _js_click(control):
                _note("fos: input click failed")
                return False
    _settle(page, 150)
    try:
        focused = page.evaluate("() => (document.activeElement && document.activeElement.id) || ''")
    except Exception:
        focused = ""
    _note(f"fos focus {focused}")
    try:
        page.keyboard.press("Enter")
    except Exception:
        _note("fos: enter failed")
        return False
    _wait_options(page)
    opened = _prompt_option_texts(page)
    _note("fos opened " + " | ".join(opened[:6]))
    if _is_prompt_folder_list(opened):
        if not _mouse_click_prompt_text(page, "All"):
            _note("fos: All click missed")
            return False
        left_folders = False
        for _ in range(10):
            _settle(page, 200)
            if not _is_prompt_folder_list(_prompt_option_texts(page)):
                left_folders = True
                break
        if not left_folders:
            _note("fos: still on folders after All")
            return False
    # Exact major or a synonym. "Computer Science" is a phrase inside
    # "Electrical Engineering and Computer Science", and that longer row is
    # not the degree.
    from apply_engine.fields import field_of_study_terms

    _bring_prompt_list_into_view(page)
    picked = ""
    for candidate in field_of_study_terms(term) or [term]:
        if not _prompt_has_exact_option(page, candidate):
            _scroll_prompt_option_into_view(page, candidate)
            _bring_prompt_list_into_view(page)
        if _prompt_has_exact_option(page, candidate):
            picked = candidate
            break
    if not picked:
        _note("fos: exact option never mounted | " + " | ".join(_prompt_option_texts(page)[:4]))
        return False
    if not _mouse_click_prompt_text(page, picked):
        _note("fos: major click missed")
        return False
    _settle(page, 250)
    if _multiselect_still_empty(page, control):
        # The visible label is sometimes a child of the row that actually selects.
        try:
            row = page.evaluate(
                """(text) => {
                  const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                  const lists = [...document.querySelectorAll('[data-automation-id="activeListContainer"]')]
                    .filter(el => el.getBoundingClientRect().height > 20);
                  const root = lists[lists.length - 1];
                  if (!root) return null;
                  const lr = root.getBoundingClientRect();
                  const opt = [...root.querySelectorAll('[data-automation-id="promptOption"]')]
                    .find(el => clean(el.innerText) === text);
                  const row = opt && (opt.closest('[data-automation-id="menuItem"]') || opt);
                  if (!row) return null;
                  const r = row.getBoundingClientRect();
                  const x = r.x + Math.min(40, r.width / 2);
                  const y = r.y + r.height / 2;
                  if (y < 2 || y > window.innerHeight - 2 || y <= lr.top || y >= lr.bottom) return null;
                  const top = document.elementFromPoint(x, y);
                  if (!top || !(row === top || row.contains(top))) return null;
                  return {x, y};
                }""",
                picked,
            )
        except Exception:
            row = None
        if row:
            try:
                page.mouse.click(row["x"], row["y"])
            except Exception:
                pass
            _settle(page, 250)
    if _multiselect_still_empty(page, control):
        # Enter commits the highlighted row. Only do that when it is this major.
        try:
            highlighted = page.evaluate(
                """(text) => {
                  const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                  const lists = [...document.querySelectorAll('[data-automation-id="activeListContainer"]')]
                    .filter(el => el.getBoundingClientRect().height > 20);
                  const root = lists[lists.length - 1];
                  if (!root) return '';
                  const row = root.querySelector('[aria-selected="true"], [data-automation-selected="true"]');
                  return row ? clean(row.innerText) : '';
                }""",
                picked,
            )
        except Exception:
            highlighted = ""
        if highlighted == picked:
            try:
                page.keyboard.press("Enter")
            except Exception:
                pass
            _settle(page, 250)
        else:
            _note(f"fos: highlighted {highlighted!r}")
    empty = _multiselect_still_empty(page, control)
    _note(f"fos readback {widget_readback(control)!r} empty={empty}")
    return not empty


def _fill_degree_and_fos(page: Any, profile: Profile, filled: list, skipped: list) -> None:
    deg = degree_search_term(profile)
    deg_loc = page.locator(
        '[data-automation-id="education-degree"], [data-automation-id="degree"], [id$="--degree"]'
    )
    if deg_loc.count() and deg_loc.first.is_visible() and deg:
        control = deg_loc.first
        readback = select_prompt(
            page,
            control,
            degree_fallback_terms(deg),
            readback_fn=lambda c=control: widget_readback(c),
            close_outside=True,
        )
        if not evaluate_prompt_readback(readback) or not readback_committed(readback, degree_fallback_terms(deg)):
            skipped.append({"label": "Degree", "reason": f"readback {readback!r} is Select One", "readback": readback})
        else:
            filled.append({"label": "Degree", "mapped_to": "degree", "value": readback, "method": "workday-prompt-readback"})
    fos = field_of_study_value(profile)
    fos_loc = _last_field_of_study_control(page)
    if fos_loc is not None and fos:
        current = widget_readback(fos_loc)
        fos_notes: list[str] = []
        if not field_of_study_committed(current, fos):
            try:
                _commit_field_of_study(page, fos_loc, fos, notes=fos_notes)
            except Exception as exc:
                fos_notes.append(f"fos commit error {exc}"[:160])
            _settle(page, 300)
        readback = widget_readback(fos_loc)
        # The virtual list's longer majors contain this phrase. Only the plain
        # search widget (no open menu) may fall through to a generic prompt pick.
        menu_open = _prompt_panel_open(page)
        if not field_of_study_committed(readback, fos) and not menu_open:
            from apply_engine.fields import field_of_study_terms

            readback = select_prompt(
                page,
                fos_loc,
                field_of_study_terms(fos) or [fos],
                readback_fn=lambda c=fos_loc: widget_readback(c),
                close_outside=False,
            )
        # Escape after a real chip deletes it. The fill log used to keep the
        # old "Computer Science" string, so the form looked done while the
        # required field was empty and Next stayed blocked.
        if _prompt_panel_open(page) and not field_of_study_committed(readback, fos):
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            _settle(page, 150)
            readback = widget_readback(fos_loc)
        if field_of_study_committed(readback, fos):
            filled.append(
                {"label": "Field of Study", "mapped_to": "field_of_study", "value": readback, "method": "workday-prompt-readback"}
            )
        else:
            reason = "FoS value missing after fill"
            if fos_notes:
                reason = f"{reason} | {' | '.join(fos_notes)}"[:500]
            skipped.append({"label": "Field of Study", "reason": reason, "readback": readback})


def _last_field_of_study_control(page: Any) -> Any | None:
    # The validation alert's id is error1-education-N--fieldOfStudy. Matching
    # every id that ends in --fieldOfStudy selects that paragraph and types
    # into the error instead of the search box.
    loc = page.locator(
        'input[id$="--fieldOfStudy"], select[id$="--fieldOfStudy"], '
        '[data-automation-id="fieldOfStudy"], [data-automation-id="field-of-study"]'
    )
    try:
        n = loc.count()
    except Exception:
        n = 0
    chosen = None
    for i in range(n):
        item = loc.nth(i)
        try:
            if not item.is_visible():
                continue
            tag = str(item.evaluate("el => (el.tagName || '').toLowerCase()"))
        except Exception:
            continue
        if tag not in {"input", "select", "button", "textarea"}:
            continue
        # A later blank Education panel is not the school we already filled.
        try:
            with_school = item.evaluate(
                """el => {
                  const id = el.id || '';
                  const prefix = id.split('--')[0];
                  if (!prefix) return false;
                  const school = document.getElementById(prefix + '--schoolName');
                  return !!(school && (school.value || '').trim());
                }"""
            )
        except Exception:
            with_school = False
        if with_school:
            return item
        chosen = item
    if chosen is not None:
        return chosen
    labels = page.get_by_text(re.compile(r"field of study", re.I))
    try:
        n = labels.count()
    except Exception:
        n = 0
    if n:
        try:
            wrap = labels.last.locator("xpath=ancestor::*[self::label or @data-automation-id][1]")
            control = wrap.locator("button, input, [role=combobox]").last
            if control.count() and control.is_visible():
                return control
        except Exception:
            pass
    return None


def _enrollment_status_terms(profile: Profile) -> list[str] | None:
    deg = (profile.degree or "").lower()
    if "associate" in deg:
        return ["Associate's", "Associate"]
    if re.search(r"ph\.?d|doctor", deg):
        return ["PhD", "Ph.D.", "Doctorate"]
    if "master" in deg:
        return ["Master's", "Master"]
    if "bachelor" in deg or re.search(r"\bbs\b", deg):
        return ["Full-time Status", "Full-time", "Bachelor's", "Bachelor", "Bachelors"]
    return ["Full-time Status", "Full-time"]


def _can_obtain_clearance(profile: Profile) -> bool | None:
    """Yes when the profile already says they can work in the US without sponsorship."""
    raw = (profile.extra or {}).get("clearance_eligible")
    if isinstance(raw, bool):
        return raw
    if profile.work_authorized_us and profile.need_sponsorship is False:
        return True
    return None


def _veteran_terms(value: str | None) -> list[str] | None:
    raw = (value or "").strip()
    if not raw:
        return None
    terms = [raw]
    low = raw.lower()
    if "not a protected veteran" in low or "not a veteran" in low or low in {"no", "i am not a veteran"}:
        terms.extend([
            "I am not a veteran",
            "I am NOT a veteran",
            "I am not a protected veteran",
            "Not a veteran",
            "Not a Protected Veteran",
        ])
    return terms


def _race_terms(value: str | None) -> list[str] | None:
    raw = (value or "").strip()
    if not raw:
        return None
    terms = [raw]
    if raw.lower() == "white":
        terms.append("White (United States of America)")
    return terms


def _no_active_clearance(profile: Profile) -> bool:
    raw = str((profile.extra or {}).get("security_clearance") or "None").strip().lower()
    return raw in {"", "none", "na", "n/a", "no"}


def _clearance_type_terms(profile: Profile) -> list[str]:
    raw = str((profile.extra or {}).get("security_clearance") or "None").strip()
    if _no_active_clearance(profile):
        # Aerospace lists "NA" for no active clearance. Other tenants say "None".
        return ["NA", "N/A", "None"]
    return [raw]


def _yes_no_terms(value: bool | None) -> list[str] | None:
    if value is True:
        return ["Yes"]
    if value is False:
        return ["No"]
    return None


def _extra_bool(profile: Profile, key: str, default: bool | None = None) -> bool | None:
    raw = (profile.extra or {}).get(key)
    if isinstance(raw, bool):
        return raw
    return default


def _iter_leaf_form_fields(page: Any):
    fields = page.locator("[data-automation-id*='formField']")
    try:
        count = fields.count()
    except Exception:
        return
    for i in range(count):
        field = fields.nth(i)
        try:
            if not field.is_visible():
                continue
            if field.locator("[data-automation-id*='formField']").count():
                continue
            yield field
        except Exception:
            continue


def _fill_question_radios(page: Any, profile: Profile, filled: list, skipped: list) -> None:
    """Yes/No radios the select-prompt pass does not own."""
    for field in _iter_leaf_form_fields(page):
        try:
            text = field.inner_text() or ""
            radios = field.get_by_role("radio")
            if not radios.count():
                continue
        except Exception:
            continue
        matched = match_application_question(text, profile)
        if matched is None:
            continue
        key, terms = matched
        picked = ""
        for i in range(radios.count()):
            radio = radios.nth(i)
            try:
                blob = radio.evaluate(
                    "el => (el.labels && el.labels[0] && el.labels[0].innerText || el.getAttribute('aria-label') || el.value || '').trim()"
                )
            except Exception:
                continue
            if not any(term.lower() in str(blob).lower() for term in terms):
                continue
            if not _click_styled_radio(radio):
                continue
            picked = " ".join(str(blob).split())
            break
        label = " ".join(text.split())[:120]
        if not picked:
            skipped.append({"label": label or key, "reason": f"radio not found for {terms[0]!r}"})
            continue
        filled.append({
            "label": label or key,
            "mapped_to": key,
            "value": picked,
            "method": "workday-question-radio",
        })


def _date_container_by_label(page: Any, source: str) -> Any | None:
    """Ancestor of a short label that holds the month/day/year inputs."""
    try:
        element_id = page.evaluate(
            """(source) => {
              let re;
              try { re = new RegExp(source, 'i'); } catch (err) { return ''; }
              const nodes = [...document.querySelectorAll('label, span, p, div, legend')];
              for (const el of nodes) {
                const t = (el.innerText || '').replace(/\\s+/g, ' ').trim();
                if (!t || t.length > 240 || /errors found/i.test(t) || !re.test(t)) continue;
                let node = el;
                for (let i = 0; i < 8 && node; i++) {
                  if (node.querySelector && node.querySelector('input[id*="dateSection"]')) {
                    if (!node.id) node.id = 'apply-engine-d-' + Math.random().toString(36).slice(2);
                    return node.id;
                  }
                  node = node.parentElement;
                }
              }
              return '';
            }""",
            source,
        )
    except Exception:
        return None
    if not element_id:
        return None
    loc = page.locator(f'[id="{element_id}"]')
    try:
        if loc.count():
            return loc.first
    except Exception:
        return None
    return None


def _smallest_question_field(page: Any, want: re.Pattern, avoid: re.Pattern) -> Any | None:
    """Shortest visible form field whose text matches. Parents that also wrap
    a different question are longer and lose."""
    fields = page.locator("[data-automation-id*='formField']")
    try:
        count = fields.count()
    except Exception:
        return None
    best = None
    best_len = 10**9
    for i in range(count):
        field = fields.nth(i)
        try:
            if not field.is_visible():
                continue
            text = field.inner_text() or ""
        except Exception:
            continue
        if avoid.search(text) or not want.search(text):
            continue
        length = len(" ".join(text.split()))
        if length < best_len:
            best = field
            best_len = length
    return best


def _date_input_ids(field: Any) -> list[str]:
    try:
        ids = field.evaluate(
            """el => [...el.querySelectorAll('input')].map(node => node.id || '').filter(Boolean)"""
        )
    except Exception:
        return []
    return [str(item) for item in ids or []]


def _write_date_parts(page: Any, field: Any, when: dict[str, str], *, day: str = "") -> bool:
    ids = _date_input_ids(field)
    month_id = next((item for item in ids if "dateSectionMonth" in item), "")
    day_id = next((item for item in ids if "dateSectionDay" in item), "")
    year_id = next((item for item in ids if "dateSectionYear" in item), "")
    # The visible spinbuttons are what Workday validates. The hidden inputs can
    # read 6/1/2027 while the field still shows an invalid date.
    _type_date_displays(page, field, when, day)
    if _date_committed(page, field, month_id, day_id, year_id, when, day):
        return True
    _set_date_inputs(page, month_id, day_id, year_id, when, day)
    return _date_committed(page, field, month_id, day_id, year_id, when, day)


def _date_committed(
    page: Any,
    field: Any,
    month_id: str,
    day_id: str,
    year_id: str,
    when: dict[str, str],
    day: str,
) -> bool:
    from apply_engine.workday_experience import _date_value_ok

    display = _read_date_display(field)
    try:
        blob = field.inner_text() or ""
    except Exception:
        blob = ""
    if date_field_rejected(blob) or re.search(r"invalid date", blob, re.I):
        return False
    if display is not None:
        month, shown_day, year = display
        if when.get("month_num") and not _date_value_ok(month, str(when.get("month_num") or "")):
            return False
        if day and not _date_value_ok(shown_day, day):
            return False
        if when.get("year") and not _date_value_ok(year, str(when["year"])):
            return False
        return True
    if not (month_id or day_id or year_id):
        return False
    return _date_parts_match(page, month_id, day_id, year_id, when, day)


def _read_date_display(field: Any) -> tuple[str, str, str] | None:
    try:
        parts = field.evaluate(
            """el => {
              const read = (aid) => {
                const node = el.querySelector(`[data-automation-id="${aid}"]`);
                if (!node) return null;
                return (node.innerText || '').replace(/\\s+/g, ' ').trim();
              };
              const month = read('dateSectionMonth-display');
              const day = read('dateSectionDay-display');
              const year = read('dateSectionYear-display');
              if (month === null && day === null && year === null) return null;
              return [month || '', day || '', year || ''];
            }"""
        )
    except Exception:
        return None
    if not parts or len(parts) != 3:
        return None
    return (str(parts[0]), str(parts[1]), str(parts[2]))


def _date_parts_match(page: Any, month_id: str, day_id: str, year_id: str, when: dict[str, str], day: str) -> bool:
    from apply_engine.workday_experience import _date_value_ok

    def read(element_id: str) -> str:
        if not element_id:
            return ""
        try:
            return (page.locator(f'[id="{element_id}"]').input_value() or "").strip()
        except Exception:
            return ""

    ok = True
    if month_id and when.get("month_num"):
        ok = _date_value_ok(read(month_id), str(when["month_num"])) and ok
    if day_id and day:
        ok = _date_value_ok(read(day_id), day) and ok
    if year_id and when.get("year"):
        ok = _date_value_ok(read(year_id), str(when["year"])) and ok
    return ok


def _set_date_inputs(page: Any, month_id: str, day_id: str, year_id: str, when: dict[str, str], day: str) -> None:
    """Commit each date segment through its React onChange and onBlur.

    Setting input.value and dispatching input/change leaves the box looking
    filled while Workday's required check still says the date is empty.
    """
    parts = (
        (month_id, str(when.get("month_num") or "")),
        (day_id, day),
        (year_id, str(when.get("year") or "")),
    )
    for element_id, value in parts:
        if not element_id or not value:
            continue
        try:
            page.evaluate(
                """({id, value}) => {
                  const el = document.getElementById(id);
                  if (!el) return false;
                  const handlers = (node) => {
                    if (!node || node.nodeType !== 1) return null;
                    const pk = Object.keys(node).find(k => k.startsWith('__reactProps'));
                    if (pk && node[pk] && (node[pk].onChange || node[pk].onBlur)) return node[pk];
                    const fk = Object.keys(node).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                    let fiber = fk ? node[fk] : null;
                    for (let i = 0; i < 8 && fiber; i++) {
                      const props = fiber.memoizedProps || fiber.pendingProps;
                      if (props && (props.onChange || props.onBlur)) return props;
                      fiber = fiber.return;
                    }
                    return null;
                  };
                  el.focus();
                  const proto = Object.getPrototypeOf(el);
                  const desc = Object.getOwnPropertyDescriptor(proto, 'value')
                    || Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
                  if (desc && desc.set) desc.set.call(el, value);
                  else el.value = value;
                  if (el._valueTracker) el._valueTracker.setValue('');
                  const fev = {
                    target: el, currentTarget: el, type: 'change', bubbles: true,
                    preventDefault() {}, stopPropagation() {}, persist() {},
                  };
                  el.dispatchEvent(new InputEvent('input', { bubbles: true, data: String(value), inputType: 'insertText' }));
                  let node = el;
                  for (let i = 0; i < 6 && node; i++) {
                    const props = handlers(node);
                    if (props) {
                      try { if (props.onChange) props.onChange(fev); } catch (err) {}
                      try { if (props.onBlur) props.onBlur(Object.assign({}, fev, { type: 'blur' })); } catch (err) {}
                      break;
                    }
                    node = node.parentElement;
                  }
                  el.dispatchEvent(new Event('change', { bubbles: true }));
                  el.dispatchEvent(new FocusEvent('blur', { bubbles: true }));
                  try { el.blur(); } catch (err) {}
                  return true;
                }""",
                {"id": element_id, "value": value},
            )
        except Exception:
            continue


def _type_date_displays(page: Any, field: Any, when: dict[str, str], day: str) -> None:
    """Type each visible month/day/year segment on its own. Never concatenate MMYYYY.

    A year typed while the month spinbutton still has focus is how every month
    collapsed to February: the leading 2 of 2024 landed in the month box.
    """
    segments = (
        ("dateSectionMonth-display", str(when.get("month_num") or "")[:2]),
        ("dateSectionDay-display", day[:2] if day else ""),
        ("dateSectionYear-display", str(when.get("year") or "")[:4]),
    )
    for aid, value in segments:
        if not value:
            continue
        try:
            point = field.evaluate(
                """(el, aid) => {
                  const node = el.querySelector(`[data-automation-id="${aid}"]`);
                  const target = (node && node.closest('[role="spinbutton"]')) || node;
                  if (!target) return null;
                  target.scrollIntoView({block: 'center', inline: 'nearest'});
                  const r = target.getBoundingClientRect();
                  if (r.width < 2 || r.height < 2) return null;
                  return {x: r.x + r.width / 2, y: r.y + r.height / 2, aid};
                }""",
                aid,
            )
        except Exception:
            point = None
        if not point:
            continue
        try:
            page.mouse.click(point["x"], point["y"])
            _settle(page, 40)
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            page.keyboard.type(value, delay=50)
            page.keyboard.press("Tab")
        except Exception:
            continue
        _settle(page, 80)
    try:
        page.keyboard.press("Tab")
    except Exception:
        pass
    _settle(page, 150)


def _fill_proposed_start_date(
    page: Any,
    job_title: str,
    job_text: str,
    filled: list,
    skipped: list,
) -> None:
    """Summer June 1, fall August 25, winter January 4, spring January 25."""
    heading = ""
    try:
        heading = page.locator("h1, h2").first.inner_text() or ""
    except Exception:
        heading = ""
    when = season_start(job_title, " ".join(part for part in (heading, job_text) if part))
    want = re.compile(r"proposed start|available to start|when can you start", re.I)
    avoid = re.compile(r"enrollment|graduation|job title|company", re.I)
    field = _smallest_question_field(page, want, avoid)
    if field is None:
        return
    try:
        text = field.inner_text() or ""
    except Exception:
        text = "Proposed Start Date"
    label = " ".join(text.split())[:120]
    if when is None:
        skipped.append({
            "label": label or "Proposed Start Date",
            "reason": "posting does not name a term and is not an internship",
        })
        return
    if not _write_date_parts(page, field, when, day=when["day"]):
        from apply_engine.workday_experience import _fill_date_field

        if not _fill_date_field(field, when):
            ids = _date_input_ids(field)
            skipped.append({
                "label": label or "Proposed Start Date",
                "reason": f"{when['season']} start date did not stick",
                "inputs": ids[:8],
            })
            return
    filled.append({
        "label": label or "Proposed Start Date",
        "mapped_to": "season_start",
        "value": f"{when['month_num']}/{when['day']}/{when['year']}",
        "method": "workday-question-date",
    })


def _fill_college_end_date(page: Any, profile: Profile, filled: list, skipped: list) -> None:
    """Enrollment end uses the graduation month. The day is the 15th, mid-month."""
    from apply_engine.workday_experience import parse_when

    when = parse_when(profile.graduation or "")
    if not when or when.get("current") or not when.get("year"):
        return
    want = re.compile(
        r"enrollment end|when do you graduate|when will you graduate|expected graduation|graduation date|"
        r"anticipated graduation|date of graduation|complete your (current )?degree",
        re.I,
    )
    avoid = re.compile(r"proposed start|\bstart date\b|enrollment status", re.I)
    field = _smallest_question_field(page, want, avoid)
    if field is None:
        field = _date_container_by_label(page, want.pattern)
        try:
            if field is not None and avoid.search(field.inner_text() or ""):
                field = None
        except Exception:
            field = None
    if field is None:
        return
    try:
        text = field.inner_text() or ""
    except Exception:
        text = ""
    label = " ".join(text.split())[:120]
    day = "15" if when.get("month_num") else ""
    if _write_date_parts(page, field, when, day=day):
        filled.append({
            "label": label or "college enrollment end",
            "mapped_to": "graduation",
            "value": f"{when.get('month_name') or when.get('month_num')} {day}, {when.get('year')}".strip(),
            "method": "workday-question-date",
        })
        return
    from apply_engine.workday_experience import _fill_date_field

    if _fill_date_field(field, when):
        filled.append({
            "label": label or "college enrollment end",
            "mapped_to": "graduation",
            "value": f"{when.get('month_name') or when.get('month_num')} {day}, {when.get('year')}".strip(),
            "method": "workday-question-date",
        })
        return
    skipped.append({
        "label": label or "college enrollment end",
        "reason": "college end date did not take the profile graduation",
    })


def _fill_no_relatives(page: Any, profile: Profile, filled: list, skipped: list) -> None:
    """Text under a question. No relatives means None. Plans means full-time work."""
    if _extra_bool(profile, "family_at_employer", default=False):
        return
    try:
        found = page.evaluate(
            r"""() => {
              const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
              const questionBefore = (box) => {
                let node = box;
                for (let i = 0; i < 8 && node; i++) {
                  let sib = node.previousElementSibling;
                  while (sib) {
                    const text = clean(sib.innerText);
                    if (text.length > 20 && text.length < 420 && !/^error\b/i.test(text)) return text;
                    sib = sib.previousElementSibling;
                  }
                  node = node.parentElement;
                }
                return '';
              };
              const out = [];
              for (const box of document.querySelectorAll("textarea, [contenteditable='true']")) {
                if (/dateSection/i.test(box.id || '')) continue;
                const r = box.getBoundingClientRect();
                if (r.width < 40 || r.height < 8) continue;
                const question = questionBefore(box);
                if (!question) continue;
                if (!box.id) box.id = 'apply-engine-qtext-' + Math.random().toString(36).slice(2);
                out.push({id: box.id, question});
              }
              return out;
            }"""
        )
    except Exception:
        return
    writes = (
        (re.compile(r"relatives currently employed|name\(s\) of any relatives", re.I), "None", "family_at_employer"),
        (re.compile(r"plans after graduation", re.I), "Full-time employment", "plans_after_graduation"),
        (re.compile(
            r"currently employed by the government|government.?ethics|audit (firm|client)|non-?compet",
            re.I,
        ), "N/A", "government_ethics_detail"),
    )
    for item in found or []:
        question = str(item.get("question") or "")
        for pattern, value, key in writes:
            if not pattern.search(question):
                continue
            box = page.locator(f'[id="{item.get("id")}"]')
            _write_plain_text(page, box, value, key, filled, skipped)
            break
    if any(row.get("mapped_to") == "family_at_employer" for row in filled):
        return
    _fill_textarea_after(page, "Full-time employment", "None", "family_at_employer", filled, skipped)


def _fill_textarea_after(page: Any, after_value: str, value: str, key: str, filled: list, skipped: list) -> None:
    """The empty text box after the one that already holds `after_value`."""
    areas = page.locator("textarea")
    try:
        count = areas.count()
    except Exception:
        return
    seen = False
    for i in range(count):
        box = areas.nth(i)
        try:
            if not box.is_visible():
                continue
            current = (box.input_value() or "").strip()
        except Exception:
            continue
        if not seen:
            if current == after_value:
                seen = True
            continue
        if current:
            return
        _write_plain_text(page, box, value, key, filled, skipped)
        return


def _write_plain_text(page: Any, box: Any, value: str, key: str, filled: list, skipped: list) -> None:
    try:
        current = (box.input_value() or "").strip()
    except Exception:
        try:
            current = (box.inner_text() or "").strip()
        except Exception:
            current = ""
    if current.lower() == value.lower():
        filled.append({
            "label": key,
            "mapped_to": key,
            "value": current,
            "method": "workday-text-already",
        })
        return
    try:
        box.click(timeout=2000)
        page.keyboard.press("Control+A")
        page.keyboard.type(value, delay=20)
        page.keyboard.press("Tab")
        _settle(page, 150)
        box.evaluate(
            """(el, value) => {
              const proto = Object.getPrototypeOf(el);
              const desc = Object.getOwnPropertyDescriptor(proto, 'value');
              if (desc && desc.set) desc.set.call(el, value);
              if (el._valueTracker) el._valueTracker.setValue('');
              const pk = Object.keys(el).find(k => k.startsWith('__reactProps'));
              const props = pk ? el[pk] : null;
              const fev = { target: el, currentTarget: el, type: 'change', bubbles: true, preventDefault() {}, stopPropagation() {}, persist() {} };
              el.dispatchEvent(new InputEvent('input', { bubbles: true, data: value, inputType: 'insertText' }));
              try { if (props && props.onChange) props.onChange(fev); } catch (err) {}
              try { if (props && props.onBlur) props.onBlur(Object.assign({}, fev, { type: 'blur' })); } catch (err) {}
            }""",
            value,
        )
        try:
            readback = (box.input_value() or "").strip()
        except Exception:
            readback = (box.inner_text() or "").strip()
    except Exception as exc:
        skipped.append({"label": key, "reason": f"text failed: {exc}"[:120]})
        return
    if readback.lower() == value.lower():
        filled.append({
            "label": key,
            "mapped_to": key,
            "value": readback,
            "method": "workday-text",
        })
    else:
        skipped.append({"label": key, "reason": f"readback {readback!r} is not {value!r}"})


def _clear_ungrounded_essays(page: Any) -> None:
    """Remove the generic intro that was written into textareas that are not essays."""
    from apply_engine.answers import looks_open_ended

    areas = page.locator("textarea")
    try:
        count = areas.count()
    except Exception:
        return
    for i in range(count):
        area = areas.nth(i)
        try:
            if not area.is_visible():
                continue
            value = area.input_value() or ""
        except Exception:
            continue
        if not re.match(r"I'm [^,\n]{2,60}, an? [^\n]{0,80}\bstudent at ", value):
            continue
        try:
            label = area.evaluate(
                """el => {
                  const wrap = el.closest("[data-automation-id*='formField']");
                  return ((wrap && wrap.innerText) || el.getAttribute('aria-label') || '').slice(0, 240);
                }"""
            )
        except Exception:
            label = ""
        if looks_open_ended(label or ""):
            continue
        try:
            area.fill("")
        except Exception:
            continue


_DISABILITY_BLOCK_RE = re.compile(
    r"disability|cc-?305|self-identif|voluntary disclosure",
    re.I,
)
_CC305_NAME_RE = re.compile(r"^(your )?name\*?\s*$|printed name|name \(please", re.I)
_CC305_DATE_RE = re.compile(r"^(today'?s )?date\*?\s*$|date signed|signature date", re.I)


def _fill_disability_self_id_block(page: Any, profile: Profile, filled: list, skipped: list) -> None:
    """CC-305 / disability self-ID asks for printed name and today's date."""
    try:
        body = page.inner_text("body") or ""
    except Exception:
        body = ""
    if not _DISABILITY_BLOCK_RE.search(body):
        return
    name = (profile.full_name or "").strip()
    today = date.today()
    when = {
        "month_num": f"{today.month:02d}",
        "month_name": today.strftime("%B"),
        "year": str(today.year),
        "day": f"{today.day:02d}",
    }
    for field in _iter_leaf_form_fields(page):
        try:
            text = " ".join((field.inner_text() or "").split())
            aid = field.get_attribute("data-automation-id") or ""
        except Exception:
            continue
        if re.search(r"legalName|firstName|lastName|jobTitle|companyName", aid):
            continue
        if name and (
            _CC305_NAME_RE.search(text.split(" ")[0] if text else "")
            or re.match(r"name\b", text, re.I)
        ) and not re.search(r"legal name|first name|last name|company name|school name", text, re.I):
            wrote = _write_plain_into_field(field, name)
            if wrote:
                filled.append({
                    "label": text[:80] or "Name",
                    "mapped_to": "full_name",
                    "value": wrote,
                    "method": "workday-cc305-name",
                })
            continue
        looks_date = bool(
            _CC305_DATE_RE.search(text)
            or re.match(r"date\b", text, re.I)
            or re.search(r"cc-?305.*date|dateSection", aid, re.I)
        )
        if looks_date and not re.search(r"start date|end date|graduation|birth|first year|last year", text, re.I):
            if _write_date_parts(page, field, when, day=when["day"]):
                filled.append({
                    "label": text[:80] or "Date",
                    "mapped_to": "disability_self_id_date",
                    "value": f"{when['month_num']}/{when['day']}/{when['year']}",
                    "method": "workday-cc305-date",
                })


def _write_plain_into_field(field: Any, value: str) -> str:
    loc = field.locator("input:not([type=hidden]):not([type=checkbox]):not([type=radio]), textarea")
    try:
        if not loc.count():
            return ""
        el = loc.first
        el.fill(value, timeout=3000)
        return (el.input_value() or "").strip()
    except Exception:
        return ""


def application_question_answers(profile: Profile) -> list[tuple[re.Pattern, str, list[str]]]:
    """Question-text rules for Workday Application Questions.

    Sponsorship is listed before work-authorization so "require sponsorship
    for an immigration-related employment benefit" / "employer support" /
    "work permit" is not answered as work auth. Authorized-without-sponsorship
    is listed before sponsorship so West Monroe polarity stays Yes.
    Age terms are 18+ phrases only — never a bare "18", which is also inside
    "Under 18".
    """
    rules: list[tuple[re.Pattern, str, list[str]]] = []

    def add(pattern: str, key: str, terms: list[str] | None) -> None:
        if terms:
            rules.append((re.compile(pattern, re.I), key, terms))

    add(
        r"(authori[sz]ed|legally (authori[sz]ed|eligible|able|permitted)|eligible to work).{0,120}without.{0,40}((visa )?sponsor|work permit|employer support)|"
        r"without.{0,40}((visa )?sponsorship|work permit|employer support).{0,80}(authori[sz]ed|eligible|able|permitted)",
        "work_authorized_without_sponsorship",
        _yes_no_terms(bool(profile.work_authorized_us) and profile.need_sponsorship is False),
    )
    # NVIDIA: "require employer support … authorization to work … (work permit)".
    # Keep after the without-sponsorship rule so "authorized … without visa
    # sponsorship" is not answered as need_sponsorship.
    add(
        r"sponsor|immigration-related employment benefit|\bvisa\b|"
        r"employer support|work permit",
        "need_sponsorship",
        _yes_no_terms(profile.need_sponsorship),
    )
    add(
        r"legally able to work|authorized to work|legally authorized|eligible to work|"
        r"work authorization within|provide work authorization",
        "work_authorized_us",
        _yes_no_terms(profile.work_authorized_us),
    )
    add(
        r"current or former government employee|"
        r"current or former (federal|state|local).{0,40}employee|"
        r"former government (employee|official)|government employee",
        "government_employee",
        _yes_no_terms(
            _extra_bool(profile, "government_employee", default=False)
            or _extra_bool(profile, "government_official", default=False)
        ),
    )
    add(
        r"minimum qualification|certify you meet",
        "meets_qualifications",
        ["Yes"],
    )
    add(
        r"age category|years of age|how old are you",
        "age_category",
        [
        "18 years of age and Over",
        "18 years of age or older",
        "18 or older",
        "18 and older",
        "I am 18 years of age or older",
        "and over",
        "18+",
        ],
    )
    if not profile.previous_employee:
        add(
            r"associate status|walmart associate|sam'?s club associate|"
            r"current(ly)? (a |an )?(walmart |sam'?s )?associate|"
            r"previously (worked|employed)|former associate|"
            r"internship or co-op|previously had an internship|"
            r"have you (ever )?(worked|been employed) (for|by)|"
            r"previously worked for|"
            r"worked for .{0,40}(subsidiary|affiliate|in the past)|"
            r"former (?!government).{0,40}employee",
            "previous_employee",
            [
                "I am not a current or former",
                "not a current or former",
                "I have never been",
                "never been",
                "not an associate",
                "No",
            ],
        )
    add(
        r"military/government work|military or government work|government work experience",
        "military_government_experience",
        _yes_no_terms(_extra_bool(profile, "military_government_experience", default=False)),
    )
    # Able to obtain a clearance follows work authorization. A candidate who
    # can already work in the US without sponsorship can answer Yes.
    # This rule stays above the clearance-type rule so the ability question
    # is not treated as the NA checkbox.
    add(
        r"obtain and maintain a security clearance|able to obtain.{0,40}clearance",
        "clearance_eligible",
        _yes_no_terms(_can_obtain_clearance(profile)),
    )
    add(
        r"plans after graduation|after you graduate",
        "plans_after_graduation",
        ["Full-time employment", "Full time employment", "Full-time work", "Seeking full-time employment"],
    )
    add(
        r"enrollment status",
        "enrollment_status",
        _enrollment_status_terms(profile),
    )
    add(
        r"security clearance type|active security clearance|clearance level",
        "security_clearance",
        _clearance_type_terms(profile),
    )
    add(
        r"do you (currently )?have a security clearance|hold a security clearance|"
        r"possess a security clearance|current security clearance\b",
        "security_clearance",
        ["No", "None", "NA"] if _no_active_clearance(profile) else _clearance_type_terms(profile),
    )
    # Not on the profile. Default No, overridable via extra.family_at_employer
    # and extra.military_spouse. These were the questions still on Select One
    # after the profile-backed Yes/No answers were committed.
    add(
        r"family member|direct family|relative who|"
        r"closely related|related to (an?|any) (current )?employee|related employee",
        "family_at_employer",
        _yes_no_terms(
            _extra_bool(profile, "family_at_employer", default=False)
            or _extra_bool(profile, "related_to_employee", default=False)
        ),
    )
    add(
        r"conflict of interest",
        "conflict_of_interest",
        _yes_no_terms(_extra_bool(profile, "conflict_of_interest", default=False)),
    )
    add(
        r"continuing employment restrictions|non-?compet|non-?solicitation",
        "non_compete",
        _yes_no_terms(_extra_bool(profile, "non_compete", default=False)),
    )
    add(
        r"if you are currently employed by the government|government.?ethics|"
        r"auditor|audit (firm|client)|independen(ce|t) audit",
        "government_ethics_detail",
        ["N/A", "Not Applicable", "Not applicable", "NA", "No"],
    )
    add(
        r"spouse/partner of someone|uniformed services",
        "military_spouse",
        _yes_no_terms(_extra_bool(profile, "military_spouse", default=False)),
    )
    # Walmart marks the SMS question required. Default is opt-out.
    sms = _extra_bool(profile, "sms_opt_in", default=False)
    add(
        r"text message|mobile text|\bsms\b",
        "sms_opt_in",
        ["Opt-in", "Opt in", "Yes"] if sms else ["Opt-out", "Opt out", "I do not", "No"],
    )
    add(
        r"phone device type|device type",
        "phone_device_type",
        list(PHONE_DEVICE_TERMS),
    )
    eeo = profile.eeo
    add(r"\bgender\b", "gender", [eeo.gender] if eeo.gender else None)
    add(
        r"hispanic|latino",
        "hispanic_latino",
        _yes_no_terms(_extra_bool(profile, "hispanic_latino", default=False)),
    )
    add(r"race|ethnicity", "race_ethnicity", _race_terms(eeo.race_ethnicity))
    add(r"\bveteran\b", "veteran", _veteran_terms(eeo.veteran))
    add(r"\bdisability\b", "disability", [eeo.disability] if eeo.disability else None)
    return rules


_RACE_LIST_MARKERS = (
    "white",
    "asian",
    "african american",
    "black or african",
    "american indian",
    "alaska native",
    "two or more races",
    "native hawaiian",
    "pacific islander",
)


def looks_like_race_list(text: str) -> bool:
    """True when Hispanic/Latino is a race checkbox, not its own Yes/No question."""
    low = (text or "").lower()
    hits = sum(1 for marker in _RACE_LIST_MARKERS if marker in low)
    if hits >= 2:
        return True
    if hits >= 1 and re.search(r"hispanic|latino", low) and re.search(
        r"\brace\b|ethnicity|select all that apply", low
    ):
        return True
    return bool(re.search(r"select all that apply", low) and re.search(r"\brace\b|ethnicity|hispanic|latino", low))


def match_application_question(text: str, profile: Profile) -> tuple[str, list[str]] | None:
    blob = text or ""
    for pattern, key, terms in application_question_answers(profile):
        if not pattern.search(blob):
            continue
        if key == "hispanic_latino" and looks_like_race_list(blob):
            continue
        return key, terms
    return None


def _yes_no_only(options: list[str]) -> bool:
    labels = {item.strip().lower() for item in options if item.strip()}
    labels.discard("select one")
    return bool(labels) and labels <= {"yes", "no"}


def _pattern_for(profile: Profile, key: str) -> re.Pattern:
    for pattern, rule_key, _terms in application_question_answers(profile):
        if rule_key == key:
            return pattern
    return re.compile(r"a^")


def _visible_prompt(field: Any) -> Any | None:
    loc = field.locator("select, button, [role=combobox]")
    try:
        count = loc.count()
    except Exception:
        return None
    fallback = None
    for i in range(min(count, 6)):
        cand = loc.nth(i)
        try:
            if cand.evaluate("el => el.getAttribute('type') === 'radio' || el.getAttribute('role') === 'radio'"):
                continue
            cand.scroll_into_view_if_needed(timeout=1500)
            if not cand.is_visible():
                continue
        except Exception:
            continue
        text = choice_readback(cand).strip().lower()
        if text in SELECT_ONE or cand.evaluate("el => el.tagName === 'SELECT'"):
            return cand
        if fallback is None:
            fallback = cand
    return fallback


def _prompt_by_label(page: Any, pattern: re.Pattern) -> Any | None:
    """Button or select next to a short label. The error summary is not a label."""
    try:
        element_id = page.evaluate(
            """(source) => {
              let re;
              try { re = new RegExp(source, 'i'); } catch (err) { return ''; }
              const nodes = [...document.querySelectorAll('label, span, p, div, legend, li')];
              const hits = nodes.filter((el) => {
                const t = (el.innerText || '').replace(/\\s+/g, ' ').trim();
                return t && t.length < 280 && !/errors found/i.test(t) && re.test(t);
              });
              const buttonIn = (el) => {
                let node = el;
                for (let i = 0; i < 6 && node; i++) {
                  const btn = node.querySelector('button, select, [role=combobox], [role=button]');
                  if (btn) return btn;
                  node = node.parentElement;
                }
                return null;
              };
              for (const hit of hits) {
                const btn = buttonIn(hit);
                if (!btn) continue;
                const rect = btn.getBoundingClientRect();
                if (rect.width < 2 || rect.height < 2) continue;
                if (!btn.id) btn.id = 'apply-engine-q-' + Math.random().toString(36).slice(2);
                return btn.id;
              }
              return '';
            }""",
            pattern.pattern,
        )
    except Exception:
        return None
    if not element_id:
        return None
    loc = page.locator(f'[id="{element_id}"]')
    try:
        if loc.count() and loc.first.is_visible():
            return loc.first
    except Exception:
        return None
    return None


def _set_race_checkboxes(page: Any, field: Any, terms: list[str]) -> str:
    """Check exactly the profile race. Uncheck Hispanic/Latino and every other race box."""
    try:
        rows = field.evaluate(
            """(el, terms) => {
              const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
              const wants = terms.map(t => clean(t).toLowerCase()).filter(Boolean);
              const wanted = (low) => wants.some(want =>
                low === want || low.startsWith(want + ' ') || low.startsWith(want + '(')
              );
              const boxes = [...el.querySelectorAll('input[type="checkbox"]')];
              return boxes.map((box) => {
                let label = '';
                let lab = null;
                if (box.id) {
                  lab = [...el.ownerDocument.querySelectorAll('label')].find(node => node.htmlFor === box.id);
                  if (lab) label = clean(lab.innerText);
                }
                if (!label && box.closest('label')) {
                  lab = box.closest('label');
                  label = clean(lab.innerText);
                }
                const target = lab || box;
                target.scrollIntoView({block: 'center', inline: 'nearest'});
                const r = target.getBoundingClientRect();
                const low = label.toLowerCase();
                return {
                  id: box.id || '',
                  label,
                  checked: !!box.checked,
                  wanted: wanted(low),
                  x: r.x + Math.min(12, r.width / 2),
                  y: r.y + r.height / 2,
                  w: r.width,
                  h: r.height,
                };
              });
            }""",
            terms,
        )
    except Exception:
        return ""
    picked = ""
    for row in rows or []:
        should = bool(row.get("wanted"))
        already = bool(row.get("checked"))
        if should:
            picked = str(row.get("label") or picked)
        if should == already:
            continue
        if float(row.get("w") or 0) < 2 or float(row.get("h") or 0) < 2:
            continue
        try:
            page.mouse.click(row["x"], row["y"])
        except Exception:
            box_id = str(row.get("id") or "")
            if not box_id:
                continue
            try:
                loc = page.locator(f'[id="{box_id}"]')
                if should:
                    loc.check(force=True, timeout=1500)
                else:
                    loc.uncheck(force=True, timeout=1500)
            except Exception:
                continue
        _settle(page, 120)
    if not picked:
        return ""
    try:
        checked = field.evaluate(
            """(el, want) => {
              const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
              const boxes = [...el.querySelectorAll('input[type="checkbox"]')];
              const on = [];
              for (const box of boxes) {
                if (!box.checked) continue;
                let label = '';
                if (box.id) {
                  const lab = [...el.ownerDocument.querySelectorAll('label')].find(node => node.htmlFor === box.id);
                  if (lab) label = clean(lab.innerText);
                }
                if (!label && box.closest('label')) label = clean(box.closest('label').innerText);
                on.push(label);
              }
              return on;
            }""",
            picked,
        )
    except Exception:
        checked = []
    on = [str(item) for item in (checked or []) if str(item).strip()]
    want = picked.strip().lower()
    extras = [item for item in on if item != want and not item.startswith(want + " ") and not item.startswith(want + "(")]
    if extras:
        return ""
    if want not in on and not any(item.startswith(want) for item in on):
        return ""
    return picked


def _check_box_phrase(page: Any, field: Any, terms: list[str]) -> str:
    """Check a box whose label contains a term, such as White inside a longer race name."""
    try:
        point = field.evaluate(
            """(el, terms) => {
              const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
              const boxes = [...el.querySelectorAll('input[type="checkbox"]')];
              for (const box of boxes) {
                let label = '';
                if (box.id) {
                  const lab = [...el.ownerDocument.querySelectorAll('label')].find(node => node.htmlFor === box.id);
                  if (lab) label = clean(lab.innerText);
                }
                if (!label && box.closest('label')) label = clean(box.closest('label').innerText);
                const low = label.toLowerCase();
                const hit = terms.find(term => {
                  const want = clean(term).toLowerCase();
                  return low === want || low.startsWith(want + ' ') || low.startsWith(want + '(');
                });
                if (!hit) continue;
                const target = (box.id && [...el.ownerDocument.querySelectorAll('label')].find(node => node.htmlFor === box.id)) || box;
                target.scrollIntoView({block: 'center', inline: 'nearest'});
                const r = target.getBoundingClientRect();
                if (r.width < 2 || r.height < 2) continue;
                return {x: r.x + Math.min(12, r.width / 2), y: r.y + r.height / 2, label, checked: !!box.checked, id: box.id || ''};
              }
              return null;
            }""",
            terms,
        )
    except Exception:
        return ""
    if not point:
        return ""
    if point.get("checked"):
        return str(point.get("label") or "")
    try:
        page.mouse.click(point["x"], point["y"])
    except Exception:
        return ""
    _settle(page, 200)
    box_id = str(point.get("id") or "")
    if not box_id:
        return ""
    try:
        checked = page.locator(f'[id="{box_id}"]').is_checked()
    except Exception:
        return ""
    return str(point.get("label") or "") if checked else ""


def _check_labeled_box(page: Any, field: Any, terms: list[str]) -> str:
    """Check a checkbox whose label is exactly one of `terms`. Workday ignores a synthetic click."""
    try:
        point = field.evaluate(
            """(el, terms) => {
              const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
              const wants = new Set(terms.map(t => clean(t).toLowerCase()));
              const boxes = [...el.querySelectorAll('input[type="checkbox"]')];
              for (const box of boxes) {
                let label = '';
            if (box.id) {
              const labs = [...el.ownerDocument.querySelectorAll('label')];
              const lab = labs.find(node => node.htmlFor === box.id);
              if (lab) label = clean(lab.innerText);
            }
                if (!label && box.closest('label')) label = clean(box.closest('label').innerText);
                if (!wants.has(label.toLowerCase())) continue;
                const target = (box.id && [...el.ownerDocument.querySelectorAll('label')].find(node => node.htmlFor === box.id)) || box;
                target.scrollIntoView({block: 'center', inline: 'nearest'});
                const r = target.getBoundingClientRect();
                if (r.width < 2 || r.height < 2) continue;
                return {x: r.x + Math.min(12, r.width / 2), y: r.y + r.height / 2, label, checked: !!box.checked, id: box.id || ''};
              }
              return null;
            }""",
            terms,
        )
    except Exception:
        return ""
    if not point:
        return ""
    if point.get("checked"):
        return str(point.get("label") or "")
    try:
        page.mouse.click(point["x"], point["y"])
    except Exception:
        return ""
    _settle(page, 200)
    box_id = str(point.get("id") or "")
    if not box_id:
        return ""
    try:
        checked = page.locator(f'[id="{box_id}"]').is_checked()
    except Exception:
        return ""
    return str(point.get("label") or "") if checked else ""


def _control_after_label(page: Any, source: str, selector: str) -> Any | None:
    """The next visible control after a short label, in document order."""
    try:
        element_id = page.evaluate(
            """({source, selector}) => {
              let re;
              try { re = new RegExp(source, 'i'); } catch (err) { return ''; }
              const nodes = [...document.querySelectorAll('label, legend, span, p, div, h3, h4')];
              const hits = [];
              for (const el of nodes) {
                const text = (el.innerText || '').replace(/\\s+/g, ' ').trim();
                if (!text || text.length > 280 || !re.test(text)) continue;
                hits.push({el, len: text.length});
              }
              hits.sort((a, b) => a.len - b.len);
              for (const {el} of hits) {
                const boxes = [...document.querySelectorAll(selector)];
                for (const box of boxes) {
                  const pos = el.compareDocumentPosition(box);
                  if (!(pos & Node.DOCUMENT_POSITION_FOLLOWING)) continue;
                  if (/dateSection/i.test(box.id || '')) continue;
                  const r = box.getBoundingClientRect();
                  if (r.width < 8 || r.height < 8) continue;
                  if (!box.id) box.id = 'apply-engine-after-' + Math.random().toString(36).slice(2);
                  return box.id;
                }
              }
              return '';
            }""",
            {"source": source, "selector": selector},
        )
    except Exception:
        return None
    if not element_id:
        return None
    loc = page.locator(f'[id="{element_id}"]')
    try:
        if loc.count() and loc.first.is_visible():
            return loc.first
    except Exception:
        return None
    return None


def _listbox_button_for_label(page: Any, source: str) -> Any | None:
    """Listbox button next to a short label, not the first button in a larger question."""
    try:
        element_id = page.evaluate(
            """(source) => {
              let re;
              try { re = new RegExp(source, 'i'); } catch (err) { return ''; }
              const own = (el) => [...el.childNodes]
                .filter(n => n.nodeType === 3)
                .map(n => n.textContent)
                .join(' ')
                .replace(/\\s+/g, ' ')
                .trim();
              const labels = [];
              for (const el of document.querySelectorAll('label, span, p, div, legend, h2, h3')) {
                const direct = own(el);
                const full = (el.innerText || '').replace(/\\s+/g, ' ').trim();
                const text = (direct && direct.length < 180 && re.test(direct))
                  ? direct
                  : (full.length < 140 && re.test(full) ? full : '');
                if (!text || /errors found/i.test(text)) continue;
                labels.push({el, len: text.length});
              }
              labels.sort((a, b) => a.len - b.len);
              for (const {el} of labels) {
                let node = el;
                for (let i = 0; i < 8 && node; i++) {
                  const buttons = [...node.querySelectorAll(
                    "button[aria-haspopup='listbox'], [data-automation-id='selectWidget']"
                  )].filter(btn => {
                    const r = btn.getBoundingClientRect();
                    return r.width > 2 && r.height > 2;
                  });
                  if (!buttons.length) { node = node.parentElement; continue; }
                  const lr = el.getBoundingClientRect();
                  const below = buttons.filter(btn => btn.getBoundingClientRect().top >= lr.top - 8);
                  const pool = below.length ? below : buttons;
                  pool.sort((a, b) =>
                    Math.abs(a.getBoundingClientRect().top - lr.bottom)
                    - Math.abs(b.getBoundingClientRect().top - lr.bottom));
                  const btn = pool[0];
                  if (!btn.id) btn.id = 'apply-engine-lb-' + Math.random().toString(36).slice(2);
                  return btn.id;
                }
              }
              return '';
            }""",
            source,
        )
    except Exception:
        return None
    if not element_id:
        return None
    loc = page.locator(f'[id="{element_id}"]')
    try:
        if loc.count() and loc.first.is_visible():
            return loc.first
    except Exception:
        return None
    return None


def _fill_application_questions(page: Any, profile: Profile, filled: list, skipped: list) -> None:
    """Fill Application Questions dropdowns from profile-backed rules."""
    fields = page.locator("[data-automation-id*='formField']")
    try:
        count = fields.count()
    except Exception:
        return
    for i in range(count):
        field = fields.nth(i)
        try:
            if not field.is_visible():
                continue
            # A parent wrapper contains every question. Fill the leaf field.
            if field.locator("[data-automation-id*='formField']").count():
                continue
            text = field.inner_text() or ""
        except Exception:
            continue
        matched = match_application_question(text, profile)
        if matched is None:
            continue
        key, terms = matched
        if re.search(r"errors found", text, re.I):
            continue
        if key == "race_ethnicity":
            try:
                box_count = field.locator('input[type="checkbox"]').count()
            except Exception:
                box_count = 0
            if box_count:
                checked = _set_race_checkboxes(page, field, terms)
                if checked:
                    filled.append({
                        "label": " ".join(text.split())[:120] or key,
                        "mapped_to": key,
                        "value": checked,
                        "method": "workday-checkbox",
                    })
                    continue
        if key == "hispanic_latino" and looks_like_race_list(text):
            continue
        if key == "plans_after_graduation":
            labeled = _control_after_label(
                page,
                r"plans after graduation",
                "button[aria-haspopup='listbox'], [data-automation-id='selectWidget']",
            ) or _listbox_button_for_label(page, r"plans after graduation")
            if labeled is not None:
                readback, options = _commit_listed_choice(page, labeled, terms)
                if not readback_committed(readback, terms) and _yes_no_only(options):
                    readback, options = _commit_listed_choice(page, labeled, ["Yes"])
                    terms = ["Yes"]
                label = " ".join(text.split())[:120]
                if readback_committed(readback, terms):
                    filled.append({
                        "label": label or key,
                        "mapped_to": key,
                        "value": readback,
                        "method": "workday-application-question",
                    })
                    continue
        if key == "security_clearance":
            checked = _check_labeled_box(page, field, terms) or _check_labeled_box(page, page.locator("body"), terms)
            if checked:
                filled.append({
                    "label": " ".join(text.split())[:120] or key,
                    "mapped_to": key,
                    "value": checked,
                    "method": "workday-checkbox",
                })
                continue
            labeled = _listbox_button_for_label(
                page,
                r"security clearance type|active security clearance|clearance level",
            )
            if labeled is not None:
                readback, options = _commit_listed_choice(page, labeled, terms)
                label = " ".join(text.split())[:120]
                if readback_committed(readback, terms):
                    filled.append({
                        "label": label or key,
                        "mapped_to": key,
                        "value": readback,
                        "method": "workday-application-question",
                    })
                    continue
        try:
            if field.get_by_role("radio").count():
                continue
        except Exception:
            pass
        widget = _visible_prompt(field) or _prompt_by_label(page, _pattern_for(profile, key))
        if widget is None:
            skipped.append({"label": key, "reason": "no select in formField"})
            continue
        prompts = field.locator(
            "select, button, [role=combobox], [data-automation-id='selectWidget'], [aria-haspopup='listbox']"
        )
        try:
            prompt_count = prompts.count()
        except Exception:
            prompt_count = 0
        order = list(range(min(prompt_count, 6)))
        if key == "security_clearance":
            try:
                order = field.evaluate(
                    """el => {
                      const nodes = [...el.querySelectorAll("select, button, [role=combobox], [data-automation-id='selectWidget'], [aria-haspopup='listbox']")];
                      return nodes.map((node, i) => {
                        const blob = ((node.getAttribute('aria-label') || '') + ' ' + (node.innerText || '')).toLowerCase();
                        let score = 0;
                        if (blob.includes('clearance type') || blob.includes('confidential')) score += 5;
                        if (blob.includes('select one')) score += 1;
                        if (blob.trim() === 'yes' || blob.trim() === 'no') score -= 3;
                        return {i, score};
                      }).sort((a, b) => b.score - a.score).map(row => row.i);
                    }"""
                ) or order
            except Exception:
                order = list(range(min(prompt_count, 6)))
        readback = ""
        options: list[str] = []
        tried = False
        for n in order[:6]:
            cand = prompts.nth(n)
            try:
                if cand.evaluate("el => el.getAttribute('type') === 'radio' || el.getAttribute('role') === 'radio'"):
                    continue
                if not cand.is_visible():
                    continue
            except Exception:
                continue
            tried = True
            readback, options = _commit_listed_choice(page, cand, terms)
            if readback_committed(readback, terms):
                widget = cand
                break
            if key == "enrollment_status" and _yes_no_only(options):
                readback, options = _commit_listed_choice(page, cand, ["Yes"])
                if readback_committed(readback, ["Yes"]):
                    terms = ["Yes"]
                    widget = cand
                    break
            if key == "plans_after_graduation" and _yes_no_only(options):
                readback, options = _commit_listed_choice(page, cand, ["Yes"])
                if readback_committed(readback, ["Yes"]):
                    terms = ["Yes"]
                    widget = cand
                    break
        if not tried:
            readback, options = _commit_listed_choice(page, widget, terms)
        label = " ".join(text.split())[:120]
        if not readback_committed(readback, terms):
            skipped.append({
                "label": label or key,
                "reason": f"readback {readback!r} did not match {terms[0]!r}",
                "readback": readback,
                "options": options,
            })
            continue
        filled.append({
            "label": label or key,
            "mapped_to": key,
            "value": readback,
            "method": "workday-application-question",
        })


TERMS_CONSENT_RE = re.compile(
    r"terms and conditions|i have read and consent|acceptterms|"
    r"i understand this privacy statement|privacy statement",
    re.I,
)


def _checkbox_consent_blob(box: Any) -> str:
    try:
        name = box.get_attribute("name") or ""
        element_id = box.get_attribute("id") or ""
        label = box.evaluate(
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
    except Exception:
        return ""
    return f"{label} {name} {element_id}"


def _ensure_box_checked(page: Any, box: Any) -> bool:
    """Check a box and confirm it on readback. Label click is what Workday honors."""
    try:
        if box.is_checked():
            return True
    except Exception:
        pass
    try:
        box.check(timeout=2000, force=True)
        if box.is_checked():
            return True
    except Exception:
        pass
    try:
        box.evaluate(
            """el => {
              const lab = el.id && el.ownerDocument.querySelector(`label[for="${CSS.escape(el.id)}"]`);
              const target = lab || el.closest('label') || el;
              target.click();
            }"""
        )
    except Exception:
        try:
            box.click(force=True, timeout=2000)
        except Exception:
            return False
    _settle(page, 80)
    try:
        return bool(box.is_checked())
    except Exception:
        return False


def _check_terms_consent(page: Any, filled: list, skipped: list) -> None:
    """Check every required terms/privacy box and confirm each stays checked."""
    boxes = page.locator("input[type=checkbox]")
    try:
        count = boxes.count()
    except Exception:
        return
    matched = 0
    stuck = 0
    for i in range(count):
        box = boxes.nth(i)
        blob = _checkbox_consent_blob(box)
        if not TERMS_CONSENT_RE.search(blob):
            continue
        try:
            visible = box.is_visible()
        except Exception:
            visible = False
        if not visible:
            try:
                box.evaluate("el => el.scrollIntoView({block: 'center'})")
            except Exception:
                pass
        matched += 1
        if _ensure_box_checked(page, box):
            stuck += 1
        else:
            skipped.append({"label": "Terms and Conditions*", "reason": "checkbox did not stay checked"})
    if not matched:
        return
    if stuck:
        if not any(row.get("mapped_to") == "policy_ack" for row in filled):
            filled.append({
                "label": "Terms and Conditions",
                "mapped_to": "policy_ack",
                "value": "Yes",
                "method": "workday-terms",
            })
        return
    if not any(row.get("label") == "Terms and Conditions*" for row in skipped):
        skipped.append({"label": "Terms and Conditions*", "reason": "checkbox did not stay checked"})


def _on_my_experience(page: Any) -> bool:
    loc = page.get_by_role("heading", name=re.compile(r"my experience", re.I))
    try:
        return bool(loc.count() and loc.first.is_visible())
    except Exception:
        return False
