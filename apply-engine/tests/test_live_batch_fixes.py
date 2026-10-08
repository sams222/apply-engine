"""Regression for the 2026-10-08 live apply-batch engine bugs."""

from __future__ import annotations

import pytest

from apply_engine.fields import file_input_kind, profile_transcript_path
from apply_engine.fill import CONSENT_RE, WORKDAY_BLOCKERS, review_status
from apply_engine.models import Profile


def test_review_status_workday_entry_is_needs_user():
    assert (
        review_status(
            submit_clicked=False,
            notes=["workday entry FAILED: blank Careers shell (SPA never painted)"],
            skipped=[{"label": "workday_entry", "reason": "stuck on job listing / Apply CTA"}],
        )
        == "needs_user"
    )
    assert (
        review_status(
            submit_clicked=False,
            notes=["hard-stop: submit not clicked"],
            skipped=[{"label": "workday_auth", "reason": "blank Create Account/Sign In shell"}],
        )
        == "needs_user"
    )
    assert (
        review_status(
            submit_clicked=False,
            notes=["hard-stop: submit not clicked"],
            skipped=[],
        )
        == "waiting_confirm"
    )


def test_privacy_statement_matches_consent():
    assert CONSENT_RE.search("I understand this Privacy Statement.")
    assert CONSENT_RE.search("Yes, I have read and consent to the terms and conditions")
    assert CONSENT_RE.search("I agree to the privacy policy")
    assert not CONSENT_RE.search("Subscribe to our newsletter")


def test_email_activation_is_a_workday_blocker():
    texts = [
        "Please verify your email to activate your account.",
        "We've sent you a verification email.",
        "Check your email to confirm your account.",
        "Please activate your account using the link we sent.",
    ]
    for text in texts:
        assert any(rx.search(text) for rx, _ in WORKDAY_BLOCKERS), text


def test_file_input_kind_classifies_transcript_and_video():
    assert file_input_kind("Resume*") == "resume"
    assert file_input_kind("Transcript*") == "transcript"
    assert file_input_kind("Unofficial Transcript") == "transcript"
    assert file_input_kind("Record a 1-minute video*") == "other"
    assert file_input_kind("Cover Letter") == "cover_letter"


def test_profile_transcript_path_requires_a_real_file(tmp_path):
    missing = Profile(full_name="Jordan Avery", first_name="Jordan", last_name="Avery",
                      email="jordan@example.org", extra={"transcript_path": str(tmp_path / "nope.pdf")})
    assert profile_transcript_path(missing) is None
    pdf = tmp_path / "transcript.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    present = Profile(full_name="Jordan Avery", first_name="Jordan", last_name="Avery",
                      email="jordan@example.org", extra={"transcript_path": str(pdf)})
    assert profile_transcript_path(present) == str(pdf)


def test_how_heard_terms_include_career_site_synonyms():
    from apply_engine.workday_widgets import _how_heard_terms

    profile = Profile(full_name="Jordan Avery", first_name="Jordan", last_name="Avery",
                      email="jordan@example.org", how_heard="Company Website")
    terms = [t.lower() for t in _how_heard_terms(profile)]
    for needle in ("company website", "corporate website", "career site", "company career site"):
        assert needle in terms, terms


def test_required_file_uploads_on_ashby_style_form(tmp_path):
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from apply_engine.fill import _upload_resume

    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    transcript = tmp_path / "transcript.pdf"
    transcript.write_bytes(b"%PDF-1.4\n")
    html = """
    <form>
      <label>Resume*<input type="file" name="resume" required></label>
      <label>Transcript*<input type="file" name="transcript" required></label>
      <label>Record a 1-minute video*<input type="file" name="video" required></label>
    </form>
    """
    profile = Profile(
        full_name="Jordan Avery", first_name="Jordan", last_name="Avery",
        email="jordan@example.org", extra={"transcript_path": str(transcript)},
    )
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            filled, skipped, notes = [], [], []
            _upload_resume(page, str(pdf), filled, skipped, notes, profile=profile)
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or "playwright" in str(exc).lower():
            pytest.skip(f"chromium not installed: {exc}")
        raise
    mapped = {row["mapped_to"]: row for row in filled}
    assert "resume" in mapped
    assert "transcript" in mapped
    video = [s for s in skipped if "video" in str(s.get("label") or "").lower()]
    assert video and str(video[0]["label"]).endswith("*"), skipped


def test_required_transcript_without_profile_file_is_skipped(tmp_path):
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from apply_engine.fill import _upload_resume

    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    html = """
    <form>
      <label>Resume*<input type="file" name="resume" required></label>
      <label>Transcript*<input type="file" name="transcript" required></label>
    </form>
    """
    profile = Profile(full_name="Jordan Avery", first_name="Jordan", last_name="Avery",
                      email="jordan@example.org")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            filled, skipped, notes = [], [], []
            _upload_resume(page, str(pdf), filled, skipped, notes, profile=profile)
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or "playwright" in str(exc).lower():
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert any(s.get("label", "").startswith("Transcript") and str(s["label"]).endswith("*") for s in skipped), skipped


def test_last_listbox_option_clicks_after_scroll():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from apply_engine.workday_widgets import _commit_listed_choice, readback_committed

    html = """
    <div data-automation-id="formField-race" style="width:320px">
      Race
      <button id="race" aria-haspopup="listbox">Select One</button>
      <ul id="list" role="listbox" style="height:80px; overflow:auto; border:1px solid #000">
        <li role="option">American Indian or Alaska Native (United States of America)</li>
        <li role="option">Asian (United States of America)</li>
        <li role="option">Black or African American (United States of America)</li>
        <li role="option">Hispanic or Latino (United States of America)</li>
        <li role="option">Native Hawaiian or Other Pacific Islander (United States of America)</li>
        <li role="option">Two or More Races (United States of America)</li>
        <li role="option">White (United States of America)</li>
      </ul>
    </div>
    <script>
      const btn = document.getElementById('race');
      document.getElementById('list').addEventListener('click', e => {
        const opt = e.target.closest('[role=option]');
        if (!opt) return;
        btn.textContent = opt.textContent.trim();
      });
    </script>
    """
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            btn = page.locator("#race")
            readback, options = _commit_listed_choice(
                page, btn, ["White (United States of America)", "White"]
            )
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or "playwright" in str(exc).lower():
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert readback_committed(readback, ["White (United States of America)"]), (readback, options)


def test_how_heard_multiselect_uses_chips_not_typed_text():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from apply_engine.workday_widgets import _is_multiselect_control, _multiselect_chips, widget_readback

    html = """
    <div data-automation-id="formField-source">
      How Did You Hear About Us?
      <div data-automation-id="multiSelectContainer" data-uxi-widget-type="multiselect">
        <input id="src" data-uxi-widget-type="selectinput" value="Company Website">
        <ul data-automation-id="selectedItemList"></ul>
      </div>
    </div>
    """
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            control = page.locator("#src")
            assert _is_multiselect_control(control)
            assert _multiselect_chips(control) == []
            assert widget_readback(control).strip() == ""
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or "playwright" in str(exc).lower():
            pytest.skip(f"chromium not installed: {exc}")
        raise


def test_corporate_website_beats_generic_career_site():
    from apply_engine.questions import _how_heard_score

    assert _how_heard_score("Corporate Website") > _how_heard_score("Career Site")
    assert _how_heard_score("Company Website") > _how_heard_score("Career Site")


def test_hispanic_race_list_is_not_the_hispanic_question():
    from apply_engine.models import EEO
    from apply_engine.workday_widgets import looks_like_race_list, match_application_question

    profile = Profile(
        full_name="Jordan Avery", first_name="Jordan", last_name="Avery",
        email="jordan@example.org", eeo=EEO(race_ethnicity="White"),
        extra={"hispanic_latino": False},
    )
    race_blob = (
        "Race (select all that apply) American Indian or Alaska Native Asian "
        "Black or African American Hispanic or Latino White Two or More Races"
    )
    assert looks_like_race_list(race_blob)
    key, terms = match_application_question(race_blob, profile)
    assert key == "race_ethnicity"
    assert any("white" in t.lower() for t in terms)
    hisp_blob = "Are you Hispanic or Latino? Yes No"
    assert not looks_like_race_list(hisp_blob)
    key, terms = match_application_question(hisp_blob, profile)
    assert key == "hispanic_latino"
    assert terms == ["No"]


_DATE_SPIN_JS = r"""
(() => {
  const bind = (disp, hidden, kind) => {
    const activate = () => { window._seg = kind; disp.focus(); };
    disp.addEventListener('click', activate);
    disp.addEventListener('focus', activate);
    hidden.addEventListener('focus', activate);
  };
  document.querySelectorAll('[data-date]').forEach((root) => {
    const month = root.querySelector('[data-automation-id="dateSectionMonth-display"]');
    const year = root.querySelector('[data-automation-id="dateSectionYear-display"]');
    const monthIn = root.querySelector('[id$="dateSectionMonth-input"]');
    const yearIn = root.querySelector('[id$="dateSectionYear-input"]');
    bind(month, monthIn, root.id + '-month');
    bind(year, yearIn, root.id + '-year');
  });
  document.addEventListener('keydown', (e) => {
    const seg = window._seg || '';
    const rootId = seg.replace(/-(month|year)$/, '');
    const kind = seg.endsWith('-year') ? 'year' : (seg.endsWith('-month') ? 'month' : '');
    const root = document.getElementById(rootId);
    if (!root || !kind) return;
    const disp = root.querySelector(`[data-automation-id="dateSection${kind === 'month' ? 'Month' : 'Year'}-display"]`);
    const hidden = root.querySelector(`[id$="dateSection${kind === 'month' ? 'Month' : 'Year'}-input"]`);
    if (e.key === 'Tab') {
      if (kind === 'month') {
        const y = root.querySelector('[data-automation-id="dateSectionYear-display"]');
        y && y.focus();
        window._seg = root.id + '-year';
        e.preventDefault();
      }
      return;
    }
    if (e.key === 'Backspace' || e.key === 'Delete') {
      disp.dataset.buf = '';
      disp.textContent = kind === 'month' ? 'MM' : 'YYYY';
      hidden.value = '';
      return;
    }
    if (!/^[0-9]$/.test(e.key)) return;
    disp.dataset.buf = (disp.dataset.buf || '') + e.key;
    if (kind === 'month') {
      const n = parseInt(disp.dataset.buf, 10);
      if (disp.dataset.buf.length === 1) disp.textContent = disp.dataset.buf.padStart(2, '0');
      else if (n >= 1 && n <= 12) disp.textContent = String(n).padStart(2, '0');
      hidden.value = disp.textContent;
    } else {
      disp.textContent = disp.dataset.buf.slice(0, 4);
      hidden.value = disp.textContent;
    }
  });
})();
"""


def test_work_experience_month_year_uses_profile_month_not_february():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from apply_engine.workday_experience import _write_span, parse_when

    html = f"""
    <div data-automation-id="formField-startDate" data-date id="start" style="width:320px">
      Start Date
      <div role="spinbutton" tabindex="0" data-automation-id="dateSectionMonth-display"
           style="display:inline-block;width:40px;height:24px">MM</div>
      <input id="job-1--startDate-dateSectionMonth-input" />
      <div role="spinbutton" tabindex="0" data-automation-id="dateSectionYear-display"
           style="display:inline-block;width:56px;height:24px">YYYY</div>
      <input id="job-1--startDate-dateSectionYear-input" />
    </div>
    <div data-automation-id="formField-endDate" data-date id="end" style="width:320px">
      End Date
      <div role="spinbutton" tabindex="0" data-automation-id="dateSectionMonth-display"
           style="display:inline-block;width:40px;height:24px">MM</div>
      <input id="job-1--endDate-dateSectionMonth-input" />
      <div role="spinbutton" tabindex="0" data-automation-id="dateSectionYear-display"
           style="display:inline-block;width:56px;height:24px">YYYY</div>
      <input id="job-1--endDate-dateSectionYear-input" />
    </div>
    <script>{_DATE_SPIN_JS}</script>
    """
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            assert _write_span(page, "job-1", "startDate", parse_when("April 2024"))
            assert _write_span(page, "job-1", "endDate", parse_when("August 2025"))
            result = {
                "sm": page.locator("#start [data-automation-id='dateSectionMonth-display']").inner_text(),
                "sy": page.locator("#start [data-automation-id='dateSectionYear-display']").inner_text(),
                "em": page.locator("#end [data-automation-id='dateSectionMonth-display']").inner_text(),
                "ey": page.locator("#end [data-automation-id='dateSectionYear-display']").inner_text(),
            }
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or "playwright" in str(exc).lower():
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert result["sm"] in {"04", "4", "April"}
    assert result["sy"] == "2024"
    assert result["em"] in {"08", "8", "August"}
    assert result["ey"] == "2025"


def test_race_checkbox_list_does_not_check_hispanic():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from apply_engine.models import EEO
    from apply_engine.workday_widgets import _fill_application_questions, _fill_question_radios

    profile = Profile(
        full_name="Jordan Avery", first_name="Jordan", last_name="Avery",
        email="jordan@example.org",
        eeo=EEO(race_ethnicity="White"),
        extra={"hispanic_latino": False},
    )
    html = """
    <div data-automation-id="formField-hispanic">
      Are you Hispanic or Latino?
      <label><input type="radio" name="hisp" value="Yes" /> Yes</label>
      <label><input type="radio" name="hisp" value="No" /> No</label>
    </div>
    <div data-automation-id="formField-race">
      Race (select all that apply)
      <label><input type="checkbox" id="r-ai" /> American Indian or Alaska Native</label>
      <label><input type="checkbox" id="r-as" /> Asian</label>
      <label><input type="checkbox" id="r-bl" /> Black or African American</label>
      <label><input type="checkbox" id="r-hi" /> Hispanic or Latino</label>
      <label><input type="checkbox" id="r-nh" /> Native Hawaiian or Other Pacific Islander</label>
      <label><input type="checkbox" id="r-tm" /> Two or More Races</label>
      <label><input type="checkbox" id="r-wh" /> White (United States of America)</label>
    </div>
    """
    filled, skipped = [], []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            _fill_application_questions(page, profile, filled, skipped)
            _fill_question_radios(page, profile, filled, skipped)
            result = {
                "hisp": page.locator("input[name=hisp]:checked").get_attribute("value"),
                "white": page.locator("#r-wh").is_checked(),
                "hispanic": page.locator("#r-hi").is_checked(),
                "two": page.locator("#r-tm").is_checked(),
                "asian": page.locator("#r-as").is_checked(),
            }
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or "playwright" in str(exc).lower():
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert result["hisp"] == "No"
    assert result["white"] is True
    assert result["hispanic"] is False
    assert result["two"] is False
    assert result["asian"] is False
    mapped = {row["mapped_to"]: row["value"] for row in filled}
    assert mapped["hispanic_latino"].lower().startswith("no")
    assert "white" in mapped["race_ethnicity"].lower()


def test_terms_consent_stays_checked_on_review_readback():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from apply_engine.fill import _required_terms_unchecked
    from apply_engine.workday_widgets import _check_terms_consent

    html = """
    <h2>Review</h2>
    <label>
      <input id="privacy" type="checkbox" checked />
      I understand this Privacy Statement.
    </label>
    <label>
      <input id="terms" type="checkbox" />
      Yes, I have read and consent to the Terms and Conditions*
    </label>
    <label><input id="mail" type="checkbox" /> Send me mail</label>
    """
    filled, skipped = [], []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            _check_terms_consent(page, filled, skipped)
            # Review remount: Self Identify left the box checked, then the
            # step re-renders it unchecked. Fill again and confirm readback.
            page.evaluate("() => { document.getElementById('terms').checked = false; }")
            assert _required_terms_unchecked(page) is True
            _check_terms_consent(page, filled, skipped)
            result = {
                "privacy": page.locator("#privacy").is_checked(),
                "terms": page.locator("#terms").is_checked(),
                "mail": page.locator("#mail").is_checked(),
                "unchecked": _required_terms_unchecked(page),
            }
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or "playwright" in str(exc).lower():
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert result["privacy"] is True
    assert result["terms"] is True
    assert result["mail"] is False
    assert result["unchecked"] is False
    assert any(row.get("mapped_to") == "policy_ack" for row in filled)
    assert not skipped
