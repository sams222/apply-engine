"""Regression for the 2026-10-09 and 2026-10-10 live apply-batch engine bugs."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from apply_engine.fields import file_input_kind
from apply_engine.fill import review_status
from apply_engine.models import Profile
from apply_engine.questions import Context, _how_heard_score, _pick_how_heard, _standing_aliases, class_standing, resolve
from apply_engine.workday import prefer_sign_in
from tests.test_questions import CTX, POOL, _profile

ROOT = Path(__file__).resolve().parents[1]


def _playwright_page(html: str):
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(headless=True)
    except Exception as exc:
        pw.stop()
        if "Executable doesn't exist" in str(exc) or "playwright" in str(exc).lower():
            pytest.skip(f"chromium not installed: {exc}")
        raise
    page = browser.new_page()
    page.set_content(html)
    return pw, browser, page


def test_greenhouse_verification_code_is_needs_user_not_submitted():
    from apply_engine.fill import greenhouse_verification_code_visible

    html = """
    <h2>Verify your email</h2>
    <p>A verification code was sent to jordan@example.org</p>
    <div id="security-input">
      <input maxlength="1" value="" />
      <input maxlength="1" />
      <input maxlength="1" />
      <input maxlength="1" />
      <input maxlength="1" />
      <input maxlength="1" />
      <input maxlength="1" />
      <input maxlength="1" />
    </div>
    """
    pw, browser, page = _playwright_page(html)
    try:
        visible = greenhouse_verification_code_visible(page)
    finally:
        browser.close()
        pw.stop()
    assert visible is True
    assert (
        review_status(
            submit_clicked=True,
            notes=["needs_user: needs_code — Greenhouse emailed a verification code"],
            skipped=[],
        )
        == "needs_user"
    )
    assert (
        review_status(submit_clicked=True, notes=["submit clicked via confirm"], skipped=[])
        == "submitted"
    )


def test_guest_my_information_is_not_a_login_page():
    html = """
    <h2>My Information</h2>
    <label>First Name <input name="first_name" data-automation-id="legalName--firstName" /></label>
    <label>Last Name <input name="last_name" data-automation-id="legalName--lastName" /></label>
    <label>Email Address <input type="email" data-automation-id="emailAddress--emailAddress" /></label>
    """
    pw, browser, page = _playwright_page(html)
    try:
        from apply_engine.fill import _guest_my_information, _workday_auth

        notes, skipped, filled = [], [], []
        ok = _guest_my_information(page)
        signed = _workday_auth(
            page,
            url="https://jll.wd1.myworkdayjobs.com/en-US/jllcareers/job/x",
            email="jordan@example.org",
            password="unused",
            filled=filled,
            skipped=skipped,
            notes=notes,
            tenant_map_path=None,
        )
    finally:
        browser.close()
        pw.stop()
    assert ok is True
    assert signed is True
    assert any("guest apply" in n.lower() for n in notes)
    assert not any(s.get("label") == "password" for s in skipped)


def test_prefer_sign_in_creates_account_when_unknown():
    assert prefer_sign_in(
        known=False,
        verify_password_visible=False,
        visible_password_count=1,
        standalone_sign_in=True,
    ) is False
    assert prefer_sign_in(
        known=True,
        verify_password_visible=False,
        visible_password_count=1,
        standalone_sign_in=True,
    ) is True


def test_class_standing_junior_from_start_and_grad():
    p = _profile()
    p.education_start = "August 2024"
    p.graduation = "May 2028"
    assert class_standing(p, date(2026, 10, 8)) == "Junior"
    assert class_standing(p, date(2026, 9, 26)) == "Junior"
    assert "Rising Junior" in _standing_aliases("Junior")
    want = resolve("What is your class standing? Rising Junior / Rising Senior", p, CTX)
    assert want is not None and want.key == "class_standing"
    assert want.text == "Junior"
    assert "Rising Junior" in (want.terms or [])


def test_how_heard_website_category_prefers_company_site_leaf():
    company = "Gilead"
    leaf = "Website - Gilead.com"
    assert _how_heard_score(leaf, company) > _how_heard_score("Website", company)
    assert _how_heard_score(leaf, company) > _how_heard_score("Career Fair/Event", company)
    picked = _pick_how_heard(
        ["Career Fair/Event", "Website", leaf, "LinkedIn"],
        company,
    )
    assert picked == [leaf]


def test_sagesure_hourly_rate_and_company_title_mapping():
    p = _profile()
    p.extra["conflict_of_interest"] = False
    ctx = Context(
        job_title=CTX.job_title,
        company="SageSure",
        description=CTX.description,
        pool=POOL,
        today=CTX.today,
    )
    pay = resolve("What is your desired hourly rate?", p, ctx)
    assert pay is not None and pay.key == "desired_pay"
    assert pay.text == "30"
    assert not pay.essay
    company = resolve("Current company", p, ctx)
    title = resolve("Job title", p, ctx)
    assert company is not None and company.key == "current_company"
    assert company.text == "Tech Fellows Program"
    assert title is not None and title.key == "current_title"
    assert title.text == "Data Science Fellow"
    assert company.text != title.text
    conflict = resolve(
        "Are you involved in any active or potential relationships with Grosvenor?",
        p,
        ctx,
    )
    assert conflict is not None and not conflict.essay
    assert conflict.text == "No"
    detail = resolve(
        "If yes, please describe the employee relationship (name and details)",
        p,
        ctx,
    )
    assert detail is not None and detail.text == "N/A"
    legal = resolve("What is your full legal name?", p, ctx)
    assert legal is not None and legal.key == "full_name" and not legal.essay
    assert legal.text == "Jordan Avery"


def test_file_input_kind_greenhouse_question_ids():
    assert file_input_kind("Transcript (Undergraduate)*", "", "question_123") == "transcript"
    assert file_input_kind("Cover Letter", "job_application[answers_attributes][0][file]", "question_456") == "cover_letter"
    assert file_input_kind("", "job_application[answers_attributes][1][file]", "question_789") == "other"


def test_ashby_failed_upload_is_needs_browser():
    from apply_engine.fill import _record_ashby_upload_failure, ashby_upload_failed

    html = """
    <form>
      <input type="file" name="resume" />
      <div role="alert">failed to upload</div>
    </form>
    """
    pw, browser, page = _playwright_page(html)
    try:
        failed = ashby_upload_failed(page)
    finally:
        browser.close()
        pw.stop()
    assert failed is True
    filled = [{"label": "resume", "mapped_to": "resume", "value": "/tmp/x.pdf", "method": "file"}]
    skipped, notes = [], []
    _record_ashby_upload_failure(filled, skipped, notes)
    assert filled == []
    assert (
        review_status(submit_clicked=False, notes=notes, skipped=skipped) == "needs_browser"
    )


def test_greenhouse_required_question_files_are_not_silent(tmp_path):
    from apply_engine.fill import _upload_resume
    from apply_engine.models import Profile as P

    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    html = """
    <form>
      <div class="field">
        <label>Resume*</label>
        <input type="file" name="resume" required />
      </div>
      <div class="field">
        <label>Cover Letter*</label>
        <input type="file" id="question_11" name="job_application[answers_attributes][0][file]" required />
      </div>
      <div class="field">
        <label>Transcript (Undergraduate)*</label>
        <input type="file" id="question_12" name="job_application[answers_attributes][1][file]" required />
      </div>
    </form>
    """
    profile = P(
        full_name="Jordan Avery", first_name="Jordan", last_name="Avery",
        email="jordan@example.org",
    )
    pw, browser, page = _playwright_page(html)
    try:
        filled, skipped, notes = [], [], []
        _upload_resume(page, str(pdf), filled, skipped, notes, profile=profile)
    finally:
        browser.close()
        pw.stop()
    labels = " ".join(str(s.get("label") or "") for s in skipped).lower()
    assert "cover" in labels, skipped
    assert "transcript" in labels, skipped
    assert all(str(s.get("label") or "").endswith("*") for s in skipped if "cover" in str(s.get("label") or "").lower() or "transcript" in str(s.get("label") or "").lower())


def test_workday_country_germany_sets_us_then_refills():
    from apply_engine.models import EEO
    from apply_engine.workday_widgets import fill_workday_sticky_fields, find_country_control

    html = """
    <h2>My Information</h2>
    <div data-automation-id="formField-legalName--firstName">
      First Name <input id="fn" data-automation-id="legalName--firstName" value="Jordan" />
    </div>
    <div data-automation-id="formField-legalName--lastName">
      Last Name <input id="ln" data-automation-id="legalName--lastName" value="Avery" />
    </div>
    <div id="middle-wrap"></div>
    <div data-automation-id="formField-country">
      Country
      <div id="country-btn" role="button" aria-haspopup="listbox">Germany</div>
      <div id="country-list" hidden role="listbox">
        <div data-automation-id="promptOption" data-automation-label="Germany">Germany</div>
        <div data-automation-id="promptOption" data-automation-label="United States of America">United States of America</div>
        <div data-automation-id="promptOption" data-automation-label="United States Minor Outlying Islands">United States Minor Outlying Islands</div>
      </div>
    </div>
    <div data-automation-id="formField-countryPhoneCode">
      Country Phone Code
      <button type="button" id="cc" data-automation-id="countryPhoneCode">Germany (+49)</button>
      <div id="cc-list" hidden role="listbox">
        <div data-automation-id="promptOption">Germany (+49)</div>
        <div data-automation-id="promptOption">United States of America (+1)</div>
      </div>
    </div>
    <div data-automation-id="formField-addressLine1">
      Address <input id="addr" data-automation-id="addressLine1" value="46 W 86th St" />
    </div>
    <div data-automation-id="formField-emailAddress--emailAddress">
      Email <input id="em" type="email" data-automation-id="emailAddress--emailAddress" value="jordan@example.org" />
    </div>
    <script>
      const btn = document.getElementById('country-btn');
      const list = document.getElementById('country-list');
      btn.addEventListener('click', () => { list.hidden = !list.hidden; });
      list.querySelectorAll('[data-automation-id=promptOption]').forEach(el => {
        el.addEventListener('click', () => {
          const t = el.getAttribute('data-automation-label');
          btn.textContent = t;
          list.hidden = true;
          if (/united states of america/i.test(t)) {
            document.getElementById('addr').value = '';
            document.getElementById('em').value = '';
            document.getElementById('middle-wrap').innerHTML =
              '<div data-automation-id="formField-legalName--middleName">Middle Name <input id="mn" data-automation-id="legalName--middleName" /></div>';
            const ln = document.getElementById('ln');
            const mn = document.getElementById('mn');
            mn.value = ln.value;
            ln.value = '';
          }
        });
      });
      const cc = document.getElementById('cc');
      const ccl = document.getElementById('cc-list');
      cc.addEventListener('click', () => { ccl.hidden = !ccl.hidden; });
      ccl.querySelectorAll('[data-automation-id=promptOption]').forEach(el => {
        el.addEventListener('click', () => { cc.textContent = el.textContent.trim(); ccl.hidden = true; });
      });
    </script>
    """
    profile = Profile(
        full_name="Jordan Avery",
        first_name="Jordan",
        last_name="Avery",
        email="jordan@example.org",
        address_line1="46 W 86th St",
        city="New York",
        state="NY",
        postal_code="10024",
        country="United States",
        phone="(212) 555-0147",
        eeo=EEO(),
    )
    pw, browser, page = _playwright_page(html)
    try:
        control = find_country_control(page)
        filled, skipped, notes = [], [], []
        fill_workday_sticky_fields(page, profile, filled, skipped, notes, company="Acme")
        first = page.locator("#fn").input_value()
        last = page.locator("#ln").input_value()
        addr = page.locator("#addr").input_value()
        email = page.locator("#em").input_value()
        country = page.locator("#country-btn").inner_text()
        phone_code = page.locator("#cc").inner_text()
        middle_n = page.locator("#mn").count()
        middle = page.locator("#mn").input_value() if middle_n else ""
    finally:
        browser.close()
        pw.stop()
    assert control is not None
    assert "united states" in country.lower()
    assert "+1" in phone_code
    assert first == "Jordan"
    assert last == "Avery"
    assert addr == "46 W 86th St"
    assert email == "jordan@example.org"
    if middle_n:
        assert middle == ""


def test_how_heard_walk_opens_website_category_not_stale_leaf():
    from apply_engine.models import EEO
    from apply_engine.workday_widgets import _fill_how_heard

    html = """
    <div data-automation-id="formField-source">
      How Did You Hear About Us?
      <div data-automation-id="multiSelectContainer" data-uxi-widget-type="multiselect">
        <button id="hh" aria-haspopup="listbox">Select</button>
        <ul data-automation-id="selectedItemList" id="chips"></ul>
      </div>
      <button id="back" data-automation-id="backButton" style="display:none">Back</button>
      <div id="box" data-automation-id="activeListContainer" style="display:none">
        <div id="inner"></div>
      </div>
    </div>
    <script>
      const CATS = ['Events', 'Website', 'Referral'];
      const LEAVES = {
        'Events': ['Career Fair/Event', 'Campus Event'],
        'Website': ['Website - Gilead.com', 'Other Website'],
        'Referral': ['Employee Referral']
      };
      let level = 'cats';
      let current = CATS;
      const box = document.getElementById('box');
      const inner = document.getElementById('inner');
      const chips = document.getElementById('chips');
      const back = document.getElementById('back');
      function paint() {
        inner.innerHTML = current.map(t =>
          '<div data-automation-id="promptOption" role="option" style="height:28px">' + t + '</div>'
        ).join('');
      }
      document.getElementById('hh').addEventListener('click', () => {
        box.style.display = 'block';
        level = 'cats';
        current = CATS;
        back.style.display = 'none';
        paint();
      });
      back.addEventListener('click', () => {
        level = 'cats'; current = CATS; back.style.display = 'none'; paint();
      });
      box.addEventListener('click', e => {
        const opt = e.target.closest('[data-automation-id="promptOption"]');
        if (!opt) return;
        const label = opt.textContent.trim();
        if (level === 'cats' && LEAVES[label]) {
          level = 'leaves';
          current = LEAVES[label];
          back.style.display = 'inline';
          paint();
          return;
        }
        chips.innerHTML = '<li data-automation-id="selectedItem">' + label + '</li>';
        box.style.display = 'none';
      });
    </script>
    """
    profile = Profile(
        full_name="Jordan Avery",
        first_name="Jordan",
        last_name="Avery",
        email="jordan@example.org",
        how_heard="Company Website",
        eeo=EEO(),
    )
    pw, browser, page = _playwright_page(html)
    try:
        filled, skipped, notes = [], [], []
        _fill_how_heard(page, profile, filled, skipped, notes, company="Gilead")
        chip_n = page.locator("[data-automation-id='selectedItem']").count()
        chip = page.locator("[data-automation-id='selectedItem']").first.inner_text() if chip_n else ""
    finally:
        browser.close()
        pw.stop()
    blob = " ".join([str(filled), chip, str(notes)])
    assert "Website - Gilead.com" in blob, (filled, skipped, notes, chip)
    assert "Career Fair" not in chip
