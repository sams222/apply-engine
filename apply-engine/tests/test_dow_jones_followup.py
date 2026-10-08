"""Regression for the 2026-10-08 Dow Jones Workday follow-up."""

from __future__ import annotations

from datetime import date

import pytest

from apply_engine.fields import field_of_study_terms
from apply_engine.fill import (
    should_retry_workday_headed,
    workday_waf_blocked_text,
    review_status,
)
from apply_engine.models import EEO, PoolEntry, Profile
from apply_engine.questions import choose, resolve, _pick_veteran
from tests.test_questions import CTX
from apply_engine.workday_experience import _prefix_for_row, _work_already_listed, fill_work_panels
from apply_engine.workday_widgets import (
    PREV_EMPLOYEE_RE,
    _how_heard_leaf_score,
    _phone_device_committed,
    field_of_study_committed,
    match_application_question,
)


def _profile(**kwargs) -> Profile:
    extra = {"hispanic_latino": False}
    extra.update(kwargs.pop("extra", {}))
    return Profile(
        full_name="Jordan Avery",
        first_name="Jordan",
        last_name="Avery",
        email="jordan.avery@example.org",
        field_of_study="Computer Science",
        eeo=EEO(
            gender="Male",
            race_ethnicity="White",
            veteran="I am not a protected veteran",
            disability="I do not have a disability",
        ),
        extra=extra,
        **kwargs,
    )


def test_headless_429_security_check_is_needs_user_and_retries_headed():
    assert workday_waf_blocked_text("Security Check")
    assert workday_waf_blocked_text("HTTP 429 Too Many Requests")
    assert not workday_waf_blocked_text("My Information")
    assert should_retry_workday_headed(headed=False, waf=True) is True
    assert should_retry_workday_headed(headed=True, waf=True) is False
    assert (
        review_status(
            submit_clicked=False,
            notes=["needs_user: Workday Security Check (HTTP 429) blocked the browser; re-run --headed"],
            skipped=[{"label": "workday_entry", "reason": "WAF security check (HTTP 429)"}],
        )
        == "needs_user"
    )


def test_veteran_maps_to_i_am_not_a_veteran_when_protected_phrasing_is_absent():
    options = ["I am a veteran", "I am not a veteran", "I do not wish to answer"]
    want = resolve("Veteran Status", _profile(), CTX)
    assert want.key == "veteran"
    assert choose(options, want) == ["I am not a veteran"]
    assert _pick_veteran(options) == ["I am not a veteran"]
    assert _pick_veteran(
        ["I identify as a protected veteran", "I am not a protected veteran", "Decline"]
    ) == ["I am not a protected veteran"]
    from apply_engine.workday_widgets import _veteran_terms

    terms = [t.lower() for t in _veteran_terms("I am not a protected veteran")]
    assert "i am not a veteran" in terms


def test_corporate_careers_website_leaf_beats_named_program():
    assert _how_heard_leaf_score(".JOBS Microsite") > _how_heard_leaf_score("News Fund Careers")
    assert _how_heard_leaf_score("Corporate Careers Website") >= 4
    from apply_engine.questions import _how_heard_score

    assert _how_heard_score("Corporate Careers Website") > _how_heard_score("Career Site")


def test_field_of_study_synonyms_include_computer_and_information_science():
    terms = [t.lower() for t in field_of_study_terms("Computer Science")]
    assert "computer and information science" in terms
    assert field_of_study_committed("Computer and Information Science", "Computer Science")
    assert not field_of_study_committed("Electrical Engineering and Computer Science", "Computer Science")


def test_previous_employee_matches_worked_for_a_parent_company():
    q = "Have you previously worked for a News Corp company?"
    assert PREV_EMPLOYEE_RE.search(q)
    key, terms = match_application_question(q, _profile())
    assert key == "previous_employee"
    assert "No" in terms


def test_business_mobile_is_not_a_committed_phone_device():
    assert _phone_device_committed("Personal Mobile") is True
    assert _phone_device_committed("Mobile") is True
    assert _phone_device_committed("Business Mobile") is False
    assert _phone_device_committed("Landline") is False


def test_work_experience_dedupes_by_title_and_company():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    html = """
    <h3>Work Experience</h3>
    <div data-automation-id="formField-jobTitle">
      Job Title*<input id="job-1--jobTitle" value="Fellow" />
    </div>
    <div data-automation-id="formField-companyName">
      Company*<input id="job-1--companyName" value="CUNY Tech Prep" />
    </div>
    <button type="button" id="add-work">Add</button>
    <div id="jobs"></div>
    <script>
      document.getElementById('add-work').onclick = () => {
        const n = document.querySelectorAll('.dup').length + 2;
        const wrap = document.createElement('div');
        wrap.className = 'dup';
        wrap.innerHTML = '<input id="job-' + n + '--jobTitle" /><input id="job-' + n + '--companyName" />';
        document.getElementById('jobs').appendChild(wrap);
      };
    </script>
    """
    row = PoolEntry(
        title="CUNY Tech Prep",
        kind="experience",
        tags=[],
        bullets=["Prep"],
        company="CUNY Tech Prep",
        role="Fellow",
        start="June 2025",
        end="August 2025",
    )
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            assert _prefix_for_row(page, row)
            assert _work_already_listed(page, row)
            fill_work_panels(page, [row], [], [], [])
            extras = page.locator(".dup").count()
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or "playwright" in str(exc).lower():
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert extras == 0


def test_how_heard_hierarchical_picks_a_leaf_not_just_the_category():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from apply_engine.workday_widgets import _fill_how_heard

    html = """
    <div data-automation-id="formField-source">
      How Did You Hear About Us?
      <div data-automation-id="multiSelectContainer" data-uxi-widget-type="multiselect">
        <input id="src" data-automation-id="howDidYouHearAboutUs" data-uxi-widget-type="selectinput" />
        <ul data-automation-id="selectedItemList" id="chips"></ul>
      </div>
      <div id="menu"></div>
    </div>
    <script>
      let level = 'top';
      const menu = document.getElementById('menu');
      const chips = document.getElementById('chips');
      function show(items) {
        menu.innerHTML = items.map(t =>
          '<div data-automation-id="promptOption" style="display:block;height:24px;width:280px">' + t + '</div>'
        ).join('');
        menu.querySelectorAll('[data-automation-id="promptOption"]').forEach(el => {
          el.addEventListener('click', () => {
            const t = el.textContent.trim();
            if (level === 'top' && t === 'Corporate Careers Website') {
              level = 'leaf';
              show(['.JOBS Microsite', 'News Fund Careers', 'Parent Co Careers', 'Brand Careers']);
              return;
            }
            chips.innerHTML = '<li data-automation-id="selectedItem">' + t + '</li>';
            menu.innerHTML = '';
          });
        });
      }
      document.getElementById('src').addEventListener('click', () => {
        level = 'top';
        show(['Direct Source', 'Corporate Careers Website', 'Job Boards']);
      });
    </script>
    """
    filled, skipped, notes = [], [], []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            _fill_how_heard(page, _profile(), filled, skipped, notes)
            chip = page.locator("#chips").inner_text().strip()
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or "playwright" in str(exc).lower():
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert chip == ".JOBS Microsite"
    assert not skipped


def test_previous_worker_radio_clicks_the_label():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from apply_engine.workday_widgets import _fill_previous_employee_no

    html = """
    <div data-automation-id="formField-candidateIsPreviousWorker">
      Have you previously worked for a News Corp company?
      <label><input type="radio" name="prev" value="Yes" style="pointer-events:none;opacity:0;width:1px;height:1px" /> Yes</label>
      <label><input type="radio" name="prev" value="No" style="pointer-events:none;opacity:0;width:1px;height:1px" /> No</label>
    </div>
    """
    filled, skipped = [], []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            _fill_previous_employee_no(page, _profile(), filled, skipped)
            checked = page.locator("input[name=prev]:checked").get_attribute("value")
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or "playwright" in str(exc).lower():
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert checked == "No"
    assert not skipped


def test_phone_device_prefers_personal_mobile_over_business():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from apply_engine.workday_widgets import _fill_phone_device_type

    html = """
    <div data-automation-id="formField-phoneDeviceType">
      Phone Device Type *
      <select id="device">
        <option>Select One</option>
        <option selected>Business Mobile</option>
        <option>Personal Mobile</option>
        <option>Landline</option>
      </select>
    </div>
    """
    filled, skipped = [], []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            _fill_phone_device_type(page, filled, skipped)
            shown = page.locator("#device").locator("option:checked").inner_text()
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or "playwright" in str(exc).lower():
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert shown == "Personal Mobile"
    assert not skipped


def test_disability_self_id_fills_name_and_date():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from apply_engine.workday_widgets import _fill_disability_self_id_block

    html = """
    <h2>Voluntary Self-Identification of Disability (CC-305)</h2>
    <div data-automation-id="formField-disability">
      Disability
      <select><option>I do not have a disability</option></select>
    </div>
    <div data-automation-id="formField-cc305Name">Name
      <input id="cc-name" />
    </div>
    <div data-automation-id="formField-cc305Date">Date
      <div role="spinbutton" tabindex="0" data-automation-id="dateSectionMonth-display"
           style="display:inline-block;width:40px;height:24px">MM</div>
      <input id="cc--dateSectionMonth-input" />
      <div role="spinbutton" tabindex="0" data-automation-id="dateSectionDay-display"
           style="display:inline-block;width:40px;height:24px">DD</div>
      <input id="cc--dateSectionDay-input" />
      <div role="spinbutton" tabindex="0" data-automation-id="dateSectionYear-display"
           style="display:inline-block;width:56px;height:24px">YYYY</div>
      <input id="cc--dateSectionYear-input" />
    </div>
    <script>
      document.querySelectorAll('[role=spinbutton]').forEach((el) => {
        el.addEventListener('click', () => { window._seg = el.getAttribute('data-automation-id'); el.focus(); });
      });
      document.addEventListener('keydown', (e) => {
        const aid = window._seg;
        if (!aid || !/^[0-9]$/.test(e.key)) return;
        const node = document.querySelector('[data-automation-id="' + aid + '"]');
        const cur = (node.textContent === 'MM' || node.textContent === 'DD' || node.textContent === 'YYYY')
          ? '' : node.textContent.replace(/\\D/g, '');
        node.textContent = (cur + e.key).slice(0, aid.includes('Year') ? 4 : 2);
        const hidden = aid.includes('Month') ? document.getElementById('cc--dateSectionMonth-input')
          : aid.includes('Day') ? document.getElementById('cc--dateSectionDay-input')
          : document.getElementById('cc--dateSectionYear-input');
        hidden.value = node.textContent;
      });
    </script>
    """
    filled, skipped = [], []
    today = date.today()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            _fill_disability_self_id_block(page, _profile(), filled, skipped)
            result = {
                "name": page.locator("#cc-name").input_value(),
                "month": page.locator("[data-automation-id='dateSectionMonth-display']").inner_text(),
                "year": page.locator("[data-automation-id='dateSectionYear-display']").inner_text(),
            }
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or "playwright" in str(exc).lower():
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert result["name"] == "Jordan Avery"
    assert result["month"] in {f"{today.month:02d}", str(today.month)}
    assert result["year"] == str(today.year)
    assert not skipped


def test_terms_rechecked_on_voluntary_disclosures():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from apply_engine.workday_widgets import _check_terms_consent

    html = """
    <h2>Voluntary Disclosures</h2>
    <label>
      <input id="terms" type="checkbox" />
      Yes, I have read and consent to the Terms and Conditions*
    </label>
    """
    filled, skipped = [], []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            _check_terms_consent(page, filled, skipped)
            page.evaluate("() => { document.getElementById('terms').checked = false; }")
            _check_terms_consent(page, filled, skipped)
            stuck = page.locator("#terms").is_checked()
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or "playwright" in str(exc).lower():
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert stuck is True
    assert not skipped
