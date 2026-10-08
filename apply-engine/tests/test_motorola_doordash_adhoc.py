"""Regression for the 2026-10-08 DoorDash Labs / Motorola ad-hoc apply run."""

from __future__ import annotations

import pytest

from apply_engine.fields import select_readback_matches
from apply_engine.fill import greenhouse_http_blocked, review_status
from apply_engine.models import Profile
from apply_engine.questions import Context, _how_heard_score, _pick_how_heard, resolve
from apply_engine.workday_widgets import (
    _company_hint,
    _how_heard_leaf_score,
    match_application_question,
    readback_committed,
)
from tests.test_questions import CTX, _profile


def test_motorola_careers_website_beats_university_board():
    company = "Motorola Solutions"
    moto = "Motorola Careers Website"
    uni = "University Career Board/Website"
    assert _how_heard_score(uni, company) == 0
    assert _how_heard_leaf_score(uni, company) == 0
    assert _how_heard_score(moto, company) > _how_heard_score(uni, company)
    assert _how_heard_score(moto, company) > _how_heard_score("Website", company)
    assert _how_heard_score(moto, "motorolasolutions") >= 5
    picked = _pick_how_heard(
        ["Campus/University", uni, "Job Board/Website", moto, "Website", "Facebook"],
        company,
    )
    assert picked == [moto]


def test_how_heard_falls_back_to_website_then_facebook():
    assert _pick_how_heard(["LinkedIn", "Website", "Facebook"], "Acme") == ["Website"]
    assert _pick_how_heard(["LinkedIn", "Social Media", "Facebook"], "Acme")[:1] in (
        ["Facebook"],
        ["Social Media"],
    )
    assert _how_heard_score("Facebook") == 1


def test_company_hint_from_workday_host():
    url = "https://motorolasolutions.wd5.myworkdayjobs.com/Careers/job/Elgin-IL/Intern_R68679"
    assert "motorola" in _company_hint("", url).lower()
    assert _company_hint("", url, company="Motorola Solutions") == "Motorola Solutions"


def test_select_one_readback_is_never_committed():
    assert readback_committed("Select One", ["No"]) is False
    assert readback_committed("Need sponsorship Select One", ["No"]) is False
    assert readback_committed("No", ["No"]) is True
    assert select_readback_matches("Select One", "No") is False
    assert select_readback_matches("No", "No") is True


def test_irca_gsa_government_and_internship_rules():
    p = _profile()
    p.available_from = "May 24, 2027"
    ctx = CTX
    assert resolve(
        "Do you have unrestricted employment authorization as defined by IRCA?", p, ctx
    ).text == "Yes"
    assert resolve(
        "Are you on the GSA List of Parties excluded from federal procurement?", p, ctx
    ).text == "No"
    assert resolve(
        "Are you currently working for a government entity or have you in the past?", p, ctx
    ).text == "No"
    student = resolve(
        "Please confirm you are currently a student in an undergraduate program "
        "graduating on or after December 2027.",
        p,
        ctx,
    )
    assert student is not None and student.text == "Yes"
    term = resolve(
        "The internship program begins May 24, 2027 through August 6, 2027. Can you participate?",
        p,
        ctx,
    )
    assert term is not None and term.text == "Yes"
    housing = resolve("Will you require housing if hired?", p, ctx)
    assert housing is not None and housing.key == "requires_housing"
    assert not housing.text and not housing.terms
    p.requires_housing = False
    assert resolve("Will you require housing if hired?", p, ctx).text == "No"
    irca, terms = match_application_question(
        "Do you have unrestricted employment authorization (IRCA)?", p
    )
    assert irca == "unrestricted_authorization" and "Yes" in terms
    key, terms = match_application_question(
        "Are you on the GSA List of Parties excluded from federal programs?", p
    )
    assert key == "gsa_excluded" and "No" in terms


def test_application_question_text_rules():
    p = _profile()
    p.available_from = "June 1, 2027"
    p.extra["willing_to_relocate"] = True
    ctx = Context(job_title=CTX.job_title, company="Motorola", description=CTX.description)
    pay = resolve("What is your base salary range expectations?", p, ctx)
    assert pay is not None and pay.text == "$30/hour"
    start = resolve("When are you available to start a new position?", p, ctx)
    assert start is not None and start.text == "June 1, 2027"
    contact = resolve("What is the best way to contact you?", p, ctx)
    assert contact is not None and p.email in (contact.text or "")
    relocate = resolve("Are you open to relocation? If so, list cities", p, ctx)
    assert relocate is not None and "New York" in (relocate.text or "")
    heard = resolve("How did you hear about this program?", p, ctx)
    assert heard is not None and heard.text == "Company Website"
    gpa = resolve("What is your current G.P.A.?", p, ctx)
    assert gpa is not None and gpa.text == "3.9"
    essay = resolve("Why are you looking for new opportunities?", p, ctx)
    assert essay is not None and essay.essay


def test_greenhouse_406_is_needs_browser():
    assert greenhouse_http_blocked(406, "https://job-boards.greenhouse.io/doordashusa/jobs/8263774")
    assert not greenhouse_http_blocked(200, "https://job-boards.greenhouse.io/doordashusa/jobs/8263774")
    assert not greenhouse_http_blocked(406, "https://example.com/jobs/1")
    assert (
        review_status(
            submit_clicked=False,
            notes=["needs_browser: Greenhouse HTTP 406 — hand off to a real browser"],
            skipped=[{"label": "greenhouse_entry", "reason": "HTTP 406"}],
        )
        == "needs_browser"
    )


def test_sign_in_already_submitted_helper():
    from apply_engine.fill import _sign_in_already_submitted

    assert _sign_in_already_submitted(
        ["workday_auth: Sign In submitted with email readback ok"]
    )
    assert not _sign_in_already_submitted(["workday auth submitted (create or sign-in)"])


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


def test_virtualized_how_heard_scroll_sees_hidden_categories():
    html = """
    <div data-automation-id="formField-source">
      How Did You Hear About Us?
      <button id="hh" aria-haspopup="listbox">Select</button>
      <div id="box" data-automation-id="activeListContainer"
           style="height:80px; overflow:auto; border:1px solid #000">
        <div id="inner" style="position:relative"></div>
      </div>
    </div>
    <script>
      const ALL = ['Campus/University','EMEAInternetJobSites','Events',
                   'Job Board/Website','Other','Social Media'];
      const box = document.getElementById('box');
      const inner = document.getElementById('inner');
      function paint() {
        const start = Math.floor(box.scrollTop / 40);
        const shown = ALL.slice(start, start + 2);
        inner.style.height = (ALL.length * 40) + 'px';
        inner.innerHTML = shown.map((t, i) =>
          '<div data-automation-id="promptOption" role="option" style="position:absolute;left:0;right:0;height:40px;top:'
          + ((start + i) * 40) + 'px">' + t + '</div>').join('');
      }
      box.addEventListener('scroll', paint);
      paint();
    </script>
    """
    pw, browser, page = _playwright_page(html)
    try:
        from apply_engine.workday_widgets import _scroll_how_heard_options

        labels = [t for _, t in _scroll_how_heard_options(page)]
    finally:
        browser.close()
        pw.stop()
    assert "Campus/University" in labels
    assert "Job Board/Website" in labels
    assert "Social Media" in labels
    assert labels.index("Job Board/Website") > labels.index("Campus/University")


def test_virtualized_how_heard_walk_picks_company_careers_website():
    html = """
    <div data-automation-id="formField-source">
      How Did You Hear About Us?
      <div data-automation-id="multiSelectContainer" data-uxi-widget-type="multiselect">
        <button id="hh" aria-haspopup="listbox">Select</button>
        <ul data-automation-id="selectedItemList" id="chips"></ul>
      </div>
      <button id="back" data-automation-id="backButton" style="display:none">Back</button>
      <div id="box" data-automation-id="activeListContainer"
           style="height:80px; overflow:auto; border:1px solid #000; display:none">
        <div id="inner" style="position:relative"></div>
      </div>
    </div>
    <script>
      const CATS = ['Campus/University','EMEAInternetJobSites','Events',
                    'Job Board/Website','Other','Social Media'];
      const LEAVES = {
        'Campus/University': ['University Career Board/Website','Campus Event'],
        'EMEAInternetJobSites': ['EMEA Board'],
        'Events': ['Career Fair'],
        'Job Board/Website': ['Indeed','Motorola Careers Website','LinkedIn'],
        'Other': ['Other'],
        'Social Media': ['Facebook','Twitter']
      };
      let level = 'cats';
      let current = CATS;
      const box = document.getElementById('box');
      const inner = document.getElementById('inner');
      const chips = document.getElementById('chips');
      const back = document.getElementById('back');
      function paint() {
        const start = Math.floor(box.scrollTop / 40);
        const shown = current.slice(start, start + 2);
        inner.style.height = (current.length * 40) + 'px';
        inner.innerHTML = shown.map((t, i) =>
          '<div data-automation-id="promptOption" role="option" style="position:absolute;left:0;right:0;height:40px;top:'
          + ((start + i) * 40) + 'px">' + t + '</div>').join('');
      }
      function showCats() {
        level = 'cats';
        current = CATS;
        back.style.display = 'none';
        box.scrollTop = 0;
        paint();
      }
      function openList() {
        box.style.display = 'block';
        showCats();
      }
      document.getElementById('hh').addEventListener('click', openList);
      back.addEventListener('click', showCats);
      document.addEventListener('keydown', e => { if (e.key === 'Escape') showCats(); });
      box.addEventListener('scroll', paint);
      box.addEventListener('click', e => {
        const opt = e.target.closest('[data-automation-id="promptOption"]');
        if (!opt) return;
        const label = opt.textContent.trim();
        if (level === 'cats' && LEAVES[label]) {
          level = 'leaves';
          current = LEAVES[label];
          back.style.display = 'inline';
          box.scrollTop = 0;
          paint();
          return;
        }
        chips.innerHTML = '<li data-automation-id="selectedItem">' + label + '</li>';
        box.style.display = 'none';
      });
    </script>
    """
    pw, browser, page = _playwright_page(html)
    try:
        from apply_engine.models import EEO
        from apply_engine.workday_widgets import _fill_how_heard

        profile = Profile(
            full_name="Jordan Avery",
            first_name="Jordan",
            last_name="Avery",
            email="jordan@example.org",
            how_heard="Company Website",
            eeo=EEO(),
        )
        filled, skipped, notes = [], [], []
        _fill_how_heard(page, profile, filled, skipped, notes, company="Motorola Solutions")
        chip_n = page.locator("[data-automation-id='selectedItem']").count()
        chips = page.locator("[data-automation-id='selectedItem']").first.inner_text() if chip_n else ""
    finally:
        browser.close()
        pw.stop()
    blob = " ".join([str(filled), chips, str(notes)])
    assert filled, (filled, skipped, notes)
    assert "Motorola Careers Website" in blob


def test_application_question_textarea_fill_and_essay_park():
    html = """
    <div data-automation-id="formField-pay">
      What is your base salary range expectations?*
      <textarea id="pay"></textarea>
    </div>
    <div data-automation-id="formField-start">
      When are you available to start a new position?
      <textarea id="start"></textarea>
    </div>
    <div data-automation-id="formField-essay">
      Why are you looking for new opportunities?*
      <textarea id="essay"></textarea>
    </div>
    <div data-automation-id="formField-other">
      Name your favorite color*
      <textarea id="color"></textarea>
    </div>
    """
    pw, browser, page = _playwright_page(html)
    try:
        from apply_engine.workday_widgets import _fill_application_questions

        p = _profile()
        p.available_from = "June 1, 2027"
        filled, skipped, notes = [], [], []
        _fill_application_questions(page, p, filled, skipped, notes, job_title="Intern", job_text="")
        pay = page.locator("#pay").input_value()
        start = page.locator("#start").input_value()
        essay = page.locator("#essay").input_value()
        color = page.locator("#color").input_value()
    finally:
        browser.close()
        pw.stop()
    assert pay == "$30/hour"
    assert start == "June 1, 2027"
    assert essay == ""
    assert color == ""
    assert any("essay" in str(s.get("mapped_to") or "") or "essay" in str(s.get("reason") or "") for s in skipped)
    assert any("needs_user" in n for n in notes)
    assert any("required Application Question" in n or "required textarea" in str(s) for n in notes for s in skipped) or any(
        "no grounded rule" in str(s.get("reason") or "") for s in skipped
    )


def test_legal_name_readback_uses_first_last_inputs_not_fieldset():
    html = """
    <fieldset>
      <legend>Legal Name</legend>
      <label>
        Legal Name First Name* Last Name* I have a preferred name
        <input id="fn" name="first_name" data-automation-id="legalName--firstName" value="Jordan" />
        <input id="ln" name="last_name" data-automation-id="legalName--lastName" value="Avery" />
      </label>
    </fieldset>
    """
    pw, browser, page = _playwright_page(html)
    try:
        from apply_engine.fill import _find_by_aliases, _accessible_name
        from apply_engine.readback import capture
        from apply_engine.workday_widgets import widget_readback

        first = _find_by_aliases(page, ("first name",), key="first_name")
        last = _find_by_aliases(page, ("last name",), key="last_name")
        full = _find_by_aliases(page, ("legal name", "full name"), key="full_name")
        first_rb = widget_readback(first)
        last_rb = widget_readback(last)
        first_name = _accessible_name(first)
        last_name = _accessible_name(last)
        rows = capture(page)
    finally:
        browser.close()
        pw.stop()
    assert first_rb == "Jordan"
    assert last_rb == "Avery"
    assert "First Name" in first_name
    assert "Last Name" in last_name
    assert "I have a preferred name" not in first_name
    assert full is None or widget_readback(full) not in {"Legal Name First Name* Last Name* I have a preferred name"}
    values = {r.get("value") for r in rows}
    assert "Jordan" in values and "Avery" in values
    for row in rows:
        if row.get("value") in {"Jordan", "Avery"}:
            assert "I have a preferred name" not in str(row.get("label") or "")


def test_click_next_waits_until_save_and_continue_enabled():
    html = """
    <button id="next" disabled>Save and Continue</button>
    <script>
      setTimeout(() => { document.getElementById('next').disabled = false; }, 400);
    </script>
    """
    pw, browser, page = _playwright_page(html)
    try:
        from apply_engine.fill import _click_next

        clicked = _click_next(page)
        enabled = page.locator("#next").is_enabled()
    finally:
        browser.close()
        pw.stop()
    assert clicked is True
    assert enabled is True


def test_account_already_exists_reads_error_banner_not_signin_link():
    html = """
    <h2>Create Account</h2>
    <a href="#signin">Already have an account? Sign In</a>
    <div data-automation-id="errorMessage" id="err"></div>
    """
    pw, browser, page = _playwright_page(html)
    try:
        from apply_engine.fill import _account_already_exists

        before = _account_already_exists(page)
        page.locator("#err").evaluate("el => { el.textContent = 'An account already exists for this email'; }")
        after = _account_already_exists(page)
    finally:
        browser.close()
        pw.stop()
    assert before is False
    assert after is True


def test_auth_existing_account_signs_in_once():
    html = """
    <h2>Create Account</h2>
    <label>Email Address <input id="email" type="email" /></label>
    <label>Password <input id="pw" type="password" /></label>
    <label>Verify New Password <input id="vpw" type="password" /></label>
    <button id="create">Create Account</button>
    <a id="switch" href="#signin" data-automation-id="signInLink">Already have an account? Sign In</a>
    <div data-automation-id="errorMessage" id="err" style="display:none"></div>
    <div id="mi" hidden>
      <h1>My Information</h1>
      <label>First Name <input data-automation-id="legalName--firstName" /></label>
    </div>
    <script>
      window.signInClicks = 0;
      document.getElementById('create').addEventListener('click', () => {
        document.getElementById('err').style.display = 'block';
        document.getElementById('err').textContent = 'An account already exists for this email';
        document.getElementById('vpw').remove();
        document.querySelector('h2').textContent = 'Sign In';
        document.getElementById('create').id = 'signin';
        document.getElementById('signin').textContent = 'Sign In';
      });
      document.getElementById('switch').addEventListener('click', (e) => {
        e.preventDefault();
        const v = document.getElementById('vpw');
        if (v) v.remove();
        document.querySelector('h2').textContent = 'Sign In';
        const btn = document.getElementById('create') || document.getElementById('signin');
        btn.id = 'signin';
        btn.textContent = 'Sign In';
      });
      document.body.addEventListener('click', (e) => {
        const t = e.target;
        if (t && t.id === 'signin') {
          window.signInClicks += 1;
          document.getElementById('mi').hidden = false;
        }
      });
    </script>
    """
    pw, browser, page = _playwright_page(html)
    try:
        from apply_engine.fill import _workday_auth

        notes, skipped, filled = [], [], []
        ok = _workday_auth(
            page,
            url="https://motorolasolutions.wd5.myworkdayjobs.com/Careers/job/Elgin-IL/Intern_R68679/apply",
            email="jordan@example.org",
            password="test-only",
            filled=filled,
            skipped=skipped,
            notes=notes,
            tenant_map_path=None,
        )
        clicks = page.evaluate("window.signInClicks")
    finally:
        browser.close()
        pw.stop()
    submitted = [n for n in notes if "Sign In submitted" in n]
    assert len(submitted) <= 1
    assert clicks <= 1
    assert ok or any("Sign In" in n for n in notes)
