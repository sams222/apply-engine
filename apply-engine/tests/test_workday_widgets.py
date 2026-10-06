from apply_engine.fields import map_field
from apply_engine.workday_widgets import (
    canonicalize_state,
    degree_fallback_terms,
    evaluate_state_widget_readback,
    is_country_phone_code_field,
    is_employee_followup_aid,
    is_plausible_state_option_list,
    is_state_control_meta,
    looks_like_country_phone_code_option,
    parse_state_widget_text,
    phone_digits,
    phone_digits_match,
    phone_last10,
    pick_option_substring,
    readback_committed,
)


def test_dated_work_uses_resume_dates_and_skips_projects():
    from apply_engine.pool import dated_work, parse_pool
    from apply_engine.workday_experience import parse_when

    assert parse_when("Sept. 2026") == {"month_num": "09", "month_name": "September", "year": "2026"}
    assert parse_when("May 2028")["year"] == "2028"
    assert parse_when("Present") == {"current": True}
    text = """
## Brightwork SWE Intern
kind: experience
company: Brightwork
role: Software Engineer Intern
location: New York, NY
start: March 2026
end: May 2026
- Built the S.C.O.P.E. Engine.

## Relay
kind: project
company: Relay
role: Author
start: June 2026
end: August 2026
- Not a job.
"""
    rows = dated_work(parse_pool(text))
    assert [row.company for row in rows] == ["Brightwork"]
    assert rows[0].role == "Software Engineer Intern"
    assert rows[0].start == "March 2026"


def test_evaluate_state_widget_readback_city_on_page_does_not_count():
    """Motorola failure: City is New York on the page while State widget is still Illinois."""
    page_body = "City New York  State Illinois  Postal 10001"
    result = evaluate_state_widget_readback(
        "Illinois",
        "NY",
        page_body=page_body,
        postal_error=False,
    )
    assert result["ok"] is False
    assert result["field"] == "State*"
    assert "Illinois" in result["reason"]


def test_evaluate_state_widget_readback_widget_new_york_matches_ny():
    page_body = "City New York  leftover Illinois in help text"
    result = evaluate_state_widget_readback(
        "New York",
        "NY",
        page_body=page_body,
        postal_error=False,
    )
    assert result["ok"] is True
    assert result["readback"] == "New York"


def test_evaluate_state_widget_readback_postal_error_fails_state():
    result = evaluate_state_widget_readback(
        "New York",
        "NY",
        page_body="City New York",
        postal_error=True,
    )
    assert result["ok"] is False
    assert result["field"] == "State*"
    assert "postal" in result["reason"].lower()


def test_evaluate_state_widget_readback_select_one_fails():
    result = evaluate_state_widget_readback("Select One", "New York")
    assert result["ok"] is False
    assert result["field"] == "State*"


def test_parse_state_widget_text_ignores_label_line_not_city():
    assert parse_state_widget_text("Illinois") == "Illinois"
    assert parse_state_widget_text("State\nNew York") == "New York"
    assert parse_state_widget_text("State*\nNY") == "NY"
    assert parse_state_widget_text("Select One") == "Select One"
    assert canonicalize_state(parse_state_widget_text("New York")) == canonicalize_state("NY")


def test_is_state_control_meta_excludes_city_and_phone():
    assert is_state_control_meta(automation_id="addressSection_countryRegion") is True
    assert is_state_control_meta(automation_id="addressSection_stateProvince") is True
    assert is_state_control_meta(aria_label="State") is True
    assert is_state_control_meta(aria_label="Province / Region") is True
    assert is_state_control_meta(automation_id="addressSection_city") is False
    assert is_state_control_meta(aria_label="City") is False
    assert is_state_control_meta(automation_id="country-phone-code") is False
    assert is_state_control_meta(aria_label="Country Phone Code") is False
    assert is_state_control_meta(automation_id="phone-number") is False
    assert is_state_control_meta(aria_label="Phone") is False


def test_country_phone_code_option_list_is_not_state():
    assert looks_like_country_phone_code_option("+1") is True
    assert looks_like_country_phone_code_option("United States (+1)") is True
    assert is_plausible_state_option_list(["+1"]) is False
    assert is_plausible_state_option_list(["+1", "United States (+1)"]) is False
    assert is_plausible_state_option_list(["New York"]) is False  # len==1
    assert is_plausible_state_option_list(["Illinois", "New York", "California"]) is True
    assert pick_option_substring(["+1", "United States (+1)"], ["NY", "New York"]) is None


def test_pick_option_substring_degree_and_state():
    opts = ["Bachelor of Science (B.S.)", "B.S. Computer Science", "Master of Science"]
    assert pick_option_substring(opts, ["B.S. Computer Science", "Bachelor"]) == "B.S. Computer Science"
    assert pick_option_substring(opts, ["Bachelor", "BS", "BA", "B.S.", "Bachelors"]) == "Bachelor of Science (B.S.)"
    assert pick_option_substring(["Illinois", "New York", "California"], ["NY"]) == "New York"
    assert pick_option_substring(["Illinois", "New York"], ["California"]) is None


def test_degree_fallback_terms_include_bachelor_aliases():
    terms = degree_fallback_terms("B.S. Computer Science")
    assert terms[0] == "B.S. Computer Science"
    for alias in ("Bachelor", "BS", "B.S.", "Bachelors"):
        assert alias in terms
    assert "BA" not in terms
    assert "BA" in degree_fallback_terms("Bachelor of Arts")


def test_science_degree_does_not_pick_ba():
    options = ["BA", "BS", "MS", "PhD"]
    science = degree_fallback_terms("Bachelor of Science in Computer Science")
    arts = degree_fallback_terms("Bachelor of Arts")
    assert pick_option_substring(options, science) == "BS"
    assert pick_option_substring(options, arts) == "BA"
    assert pick_option_substring(["B.S."], ["BS"]) == "B.S."


def test_readback_committed_is_widget_truth_not_page_city():
    assert readback_committed("New York", ["NY", "New York"]) is True
    assert readback_committed("Illinois", ["NY", "New York"]) is False
    assert readback_committed("Select One", ["New York"]) is False
    assert readback_committed("Bachelor of Science (B.S.)", ["Bachelor", "BS"]) is True
    # City text is not a state widget readback — committed check is on the string we were given
    assert readback_committed("Computer Science", ["New York"]) is False


def test_phone_digits_match_last10():
    assert phone_digits_match("2125551000", "212-555-1000")
    assert phone_digits_match("(212) 555-1000", "+1 212 555 1000")
    assert phone_digits_match("555-0100", "+1-555-0100")
    assert not phone_digits_match("2175551000", "212-555-1000")
    assert phone_last10("+1-212-555-1000") == "2125551000"
    assert phone_digits("+1-555-0100") == "15550100"


def test_country_phone_code_not_mapped():
    assert map_field("Country Phone Code") is None
    assert map_field("Phone", "country-phone-code") is None
    assert map_field("", "", "country-phone-code") is None
    assert is_country_phone_code_field(label="Country Phone Code") is True
    assert is_country_phone_code_field(automation_id="country-phone-code") is True
    assert map_field("Phone Number") == "phone"
    assert map_field("Phone") == "phone"


def test_employee_followup_aids():
    assert is_employee_followup_aid("employee-id") is True
    assert is_employee_followup_aid("employeeId") is True
    assert is_employee_followup_aid("workerId") is True
    assert is_employee_followup_aid("manager") is True
    assert is_employee_followup_aid("phone-number") is False


WALMART_QUESTIONS = {
    "quals": "Do you certify you meet all minimum qualifications for this job as outlined in the job posting?",
    "work": "Are you legally able to work in the country where this job is located?",
    "age": "Please select your age category",
    "associate": "Please select your Walmart Associate Status/Affiliation",
    "sponsor": "Will you now or in the future require sponsorship for an immigration-related employment benefit?",
    "three_day": "Are you able to provide work authorization within 3 days of your hire?",
    "family": "Do you have a direct family member who currently works for Walmart or Sam's Club?",
    "spouse": "Are you the Spouse/Partner of someone in the Uniformed Services of the United States?",
    "sms": "Would you like to receive mobile text message updates relating to your employment relationship with Walmart?",
}


def test_walmart_application_questions_map_from_profile():
    from pathlib import Path

    from apply_engine.profile import load_profile
    from apply_engine.workday_widgets import match_application_question

    profile = load_profile(Path(__file__).resolve().parents[1] / "examples" / "profile.json")
    assert match_application_question(WALMART_QUESTIONS["quals"], profile)[0] == "meets_qualifications"
    assert match_application_question(WALMART_QUESTIONS["work"], profile) == ("work_authorized_us", ["Yes"])
    assert match_application_question(WALMART_QUESTIONS["three_day"], profile) == ("work_authorized_us", ["Yes"])
    assert match_application_question(WALMART_QUESTIONS["sponsor"], profile) == ("need_sponsorship", ["No"])
    key, terms = match_application_question(WALMART_QUESTIONS["age"], profile)
    assert key == "age_category"
    assert "18" not in terms
    assert "18 years of age and Over" in terms
    key, terms = match_application_question(WALMART_QUESTIONS["associate"], profile)
    assert key == "previous_employee"
    assert terms[0].lower().startswith("i am not") or "not a current" in terms[0].lower()
    assert match_application_question(WALMART_QUESTIONS["family"], profile) == ("family_at_employer", ["No"])
    assert match_application_question(WALMART_QUESTIONS["spouse"], profile) == ("military_spouse", ["No"])
    assert match_application_question(WALMART_QUESTIONS["sms"], profile)[0] == "sms_opt_in"
    assert "Opt-out" in match_application_question(WALMART_QUESTIONS["sms"], profile)[1]


def test_authorized_without_sponsorship_not_mapped_as_need_sponsorship():
    from pathlib import Path

    from apply_engine.profile import load_profile
    from apply_engine.workday_widgets import match_application_question

    profile = load_profile(Path(__file__).resolve().parents[1] / "examples" / "profile.json")
    q = (
        "Are you legally authorized to work in the US now and in the future "
        "for any employer without visa sponsorship?"
    )
    key, terms = match_application_question(q, profile)
    assert key == "work_authorized_without_sponsorship"
    assert terms == ["Yes"]


def test_phone_device_type_question_maps_to_mobile():
    from pathlib import Path

    from apply_engine.profile import load_profile
    from apply_engine.workday_widgets import match_application_question

    profile = load_profile(Path(__file__).resolve().parents[1] / "examples" / "profile.json")
    key, terms = match_application_question("Phone Device Type *", profile)
    assert key == "phone_device_type"
    assert "Mobile" in terms or "Mobile Phone" in terms


def test_fill_application_questions_on_selects():
    import pytest
    from pathlib import Path

    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from apply_engine.profile import load_profile
    from apply_engine.workday_widgets import _fill_application_questions

    profile = load_profile(Path(__file__).resolve().parents[1] / "examples" / "profile.json")
    html = """
    <div data-automation-id="formField-quals">
      Do you certify you meet all minimum qualifications for this job? *
      <select id="quals"><option>Select One</option><option>Yes</option><option>No</option></select>
    </div>
    <div data-automation-id="formField-work">
      Are you legally able to work in the country where this job is located? *
      <select id="work"><option>Select One</option><option>Yes</option><option>No</option></select>
    </div>
    <div data-automation-id="formField-sponsor">
      Will you now or in the future require sponsorship for an immigration-related employment benefit? *
      <select id="sponsor"><option>Select One</option><option>Yes</option><option>No</option></select>
    </div>
    <div data-automation-id="formField-age">
      Please select your age category *
      <select id="age">
        <option>Select One</option>
        <option>Under 18</option>
        <option>18 years of age or older</option>
      </select>
    </div>
    <div data-automation-id="formField-assoc">
      Please select your Walmart Associate Status/Affiliation *
      <select id="assoc">
        <option>Select One</option>
        <option>Current Associate</option>
        <option>Former Associate</option>
        <option>Not a Current or Former Associate</option>
      </select>
    </div>
    """
    filled: list = []
    skipped: list = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            _fill_application_questions(page, profile, filled, skipped)
            values = {
                "quals": page.locator("#quals").input_value(),
                "work": page.locator("#work").input_value(),
                "sponsor": page.locator("#sponsor").input_value(),
                "age": page.locator("#age").locator("option:checked").inner_text(),
                "assoc": page.locator("#assoc").locator("option:checked").inner_text(),
            }
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert values == {
        "quals": "Yes",
        "work": "Yes",
        "sponsor": "No",
        "age": "18 years of age or older",
        "assoc": "Not a Current or Former Associate",
    }
    assert not skipped
    mapped = {row["mapped_to"]: row["value"] for row in filled}
    assert mapped["need_sponsorship"] == "No"
    assert mapped["work_authorized_us"] == "Yes"
    assert mapped["age_category"] == "18 years of age or older"


def test_terms_checkbox_is_checked():
    import pytest
    from playwright.sync_api import sync_playwright

    from apply_engine.workday_widgets import _check_terms_consent

    pytest.importorskip("playwright")
    html = """
    <label>
      <input id="termsAndConditions--acceptTermsAndAgreements" name="acceptTermsAndAgreements" type="checkbox" />
      Yes, I have read and consent to the Terms and Conditions*
    </label>
    <label><input id="other" type="checkbox" /> Send me mail</label>
    """
    filled: list = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            _check_terms_consent(page, filled, [])
            terms = page.locator("#termsAndConditions--acceptTermsAndAgreements").is_checked()
            other = page.locator("#other").is_checked()
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert terms is True
    assert other is False
    assert filled[0]["mapped_to"] == "policy_ack"


def test_add_panels_fill_education_and_work_only():
    import pytest
    from playwright.sync_api import sync_playwright

    from apply_engine.models import PoolEntry, Profile
    from apply_engine.workday_widgets import fill_workday_sticky_fields

    pytest.importorskip("playwright")
    profile = Profile(
        full_name="Jordan Avery",
        first_name="Jordan",
        last_name="Avery",
        email="jordan.avery@example.org",
        school="Hudson State University",
        degree="Bachelor of Science in Computer Science",
        gpa="3.9",
        graduation="May 2028",
        field_of_study="Computer Science",
        country="United States",
    )
    entries = [
        PoolEntry(
            title="Tech Fellows Program",
            kind="experience",
            tags=[],
            bullets=["Selected for a year-long fellowship."],
            company="Tech Fellows Program",
            role="Data Science Fellow",
            location="New York, NY",
            start="July 2026",
            end="Present",
        ),
        PoolEntry(
            title="Brightwork SWE Intern",
            kind="experience",
            tags=[],
            bullets=["Built the S.C.O.P.E. Engine."],
            company="Brightwork",
            role="Software Engineer Intern",
            location="New York, NY",
            start="March 2026",
            end="May 2026",
        ),
        PoolEntry(
            title="Relay",
            kind="project",
            tags=[],
            bullets=["Not employment."],
            company="Relay",
            role="Author",
            start="June 2026",
            end="August 2026",
        ),
    ]
    html = """
    <h2>My Experience</h2>
    <section>
      <h3>Work Experience</h3>
      <button type="button" id="add-work">Add</button>
      <div id="jobs"></div>
    </section>
    <section>
      <h3>Education</h3>
      <button type="button" id="add-edu">Add</button>
      <div id="edu-panel" hidden>
        <div data-automation-id="formField-school">School*<input id="school" /></div>
        <div data-automation-id="formField-degree">Degree*
          <select data-automation-id="education-degree" id="degree">
            <option>Select One</option>
            <option>Bachelor of Science in Computer Science</option>
            <option>Master of Science</option>
          </select>
        </div>
        <div data-automation-id="formField-fieldOfStudy">Field of Study*
          <select data-automation-id="fieldOfStudy" id="fos">
            <option>Select One</option>
            <option>Computer Science</option>
            <option>Other</option>
          </select>
        </div>
        <div data-automation-id="formField-gpa">GPA*<input id="gpa" /></div>
        <div data-automation-id="formField-endDate">Expected Graduation*
          <input id="grad-month" />
          <input id="grad-year" />
        </div>
        <label><input id="attend" type="checkbox" /> I currently attend</label>
      </div>
    </section>
    <section>
      <h3>Languages</h3>
      <button type="button" id="add-lang">Add</button>
      <div id="lang-panel" hidden>
        <div data-automation-id="formField-language">Language*<input id="language" /></div>
      </div>
    </section>
    <script>
      function jobPanel() {
        const wrap = document.createElement('div');
        wrap.className = 'job';
        wrap.innerHTML = `
          <div data-automation-id="formField-jobTitle">Job Title*<input class="title" /></div>
          <div data-automation-id="formField-companyName">Company*<input class="company" /></div>
          <div data-automation-id="formField-location">Location<input class="location" /></div>
          <div data-automation-id="formField-startDate">Start Date*<input class="start-month" /><input class="start-year" /></div>
          <div data-automation-id="formField-endDate">End Date*<input class="end-month" /><input class="end-year" /></div>
          <label><input class="current" type="checkbox" /> I currently work here</label>
          <div data-automation-id="formField-roleDescription">Role Description<textarea class="desc"></textarea></div>
        `;
        document.getElementById('jobs').appendChild(wrap);
      }
      document.getElementById('add-work').onclick = jobPanel;
      document.getElementById('add-edu').onclick = () => { document.getElementById('edu-panel').hidden = false; };
      document.getElementById('add-lang').onclick = () => { document.getElementById('lang-panel').hidden = false; };
    </script>
    """
    filled: list = []
    skipped: list = []
    notes: list = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            fill_workday_sticky_fields(page, profile, filled, skipped, notes, experience=entries)
            result = {
                "school": page.locator("#school").input_value(),
                "degree": page.locator("#degree").locator("option:checked").inner_text(),
                "fos": page.locator("#fos").locator("option:checked").inner_text(),
                "gpa": page.locator("#gpa").input_value(),
                "grad_month": page.locator("#grad-month").input_value(),
                "grad_year": page.locator("#grad-year").input_value(),
                "attend": page.locator("#attend").is_checked(),
                "companies": page.locator(".company").evaluate_all("els => els.map(el => el.value)"),
                "titles": page.locator(".title").evaluate_all("els => els.map(el => el.value)"),
                "start_months": page.locator(".start-month").evaluate_all("els => els.map(el => el.value)"),
                "start_years": page.locator(".start-year").evaluate_all("els => els.map(el => el.value)"),
                "end_months": page.locator(".end-month").evaluate_all("els => els.map(el => el.value)"),
                "end_years": page.locator(".end-year").evaluate_all("els => els.map(el => el.value)"),
                "current": page.locator(".current").evaluate_all("els => els.map(el => el.checked)"),
                "descs": page.locator(".desc").evaluate_all("els => els.map(el => el.value)"),
                "jobs": page.locator(".job").count(),
                "lang_hidden": page.locator("#lang-panel").get_attribute("hidden") is not None,
            }
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert result["school"] == "Hudson State University"
    assert result["degree"] == "Bachelor of Science in Computer Science"
    assert result["fos"] == "Computer Science"
    assert result["gpa"] == "3.9"
    assert result["grad_month"] == "05"
    assert result["grad_year"] == "2028"
    assert result["attend"] is True
    assert result["jobs"] == 2
    assert result["companies"] == ["Tech Fellows Program", "Brightwork"]
    assert result["titles"] == ["Data Science Fellow", "Software Engineer Intern"]
    assert result["start_months"] == ["07", "03"]
    assert result["start_years"] == ["2026", "2026"]
    assert result["end_months"] == ["", "05"]
    assert result["end_years"] == ["", "2026"]
    assert result["current"] == [True, False]
    assert "fellowship" in result["descs"][0].lower()
    assert result["lang_hidden"] is True
    assert not any("Relay" in str(row.get("value")) for row in filled)
    assert not skipped


def test_science_degree_and_field_of_study_search():
    import pytest
    from playwright.sync_api import sync_playwright

    from apply_engine.models import Profile
    from apply_engine.workday_widgets import _fill_degree_and_fos

    pytest.importorskip("playwright")
    profile = Profile(
        full_name="Jordan Avery",
        first_name="Jordan",
        last_name="Avery",
        email="jordan.avery@example.org",
        degree="Bachelor of Science in Computer Science",
        field_of_study="Computer Science",
    )
    html = """
    <div data-automation-id="formField-degree">Degree*
      <select data-automation-id="education-degree" id="degree">
        <option>Select One</option>
        <option>BA</option>
        <option>BS</option>
        <option>MS</option>
      </select>
    </div>
    <div data-automation-id="formField-fieldOfStudy">Field of Study*
      <input id="education-1--fieldOfStudy" data-automation-id="fieldOfStudy" />
      <ul id="fos-results" hidden></ul>
      <ul data-automation-id="selectedItemList" id="picked"></ul>
    </div>
    <script>
      const input = document.getElementById('education-1--fieldOfStudy');
      const results = document.getElementById('fos-results');
      input.addEventListener('keydown', (e) => {
        if (e.key !== 'Enter') return;
        results.hidden = false;
        results.innerHTML = '<li role="option">Computer Engineering</li><li role="option">Computer Science</li>';
      });
      results.addEventListener('click', (e) => {
        const opt = e.target.closest('[role="option"]');
        if (!opt) return;
        document.getElementById('picked').innerHTML = '<li>' + opt.textContent + '</li>';
        results.hidden = true;
        input.value = '';
      });
    </script>
    """
    filled: list = []
    skipped: list = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            _fill_degree_and_fos(page, profile, filled, skipped)
            degree = page.locator("#degree").locator("option:checked").inner_text()
            chip = page.locator("#picked").inner_text().strip()
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert degree == "BS"
    assert chip == "Computer Science"
    assert not skipped


def test_field_of_study_enters_all_folder():
    import pytest
    from playwright.sync_api import sync_playwright

    from apply_engine.models import Profile
    from apply_engine.workday_widgets import _fill_degree_and_fos

    pytest.importorskip("playwright")
    profile = Profile(
        full_name="Jordan Avery",
        first_name="Jordan",
        last_name="Avery",
        email="jordan.avery@example.org",
        degree="Bachelor of Science in Computer Science",
        field_of_study="Computer Science",
    )
    html = """
    <div data-automation-id="formField-degree">Degree*
      <select data-automation-id="education-degree" id="degree">
        <option>Select One</option>
        <option>BS</option>
      </select>
    </div>
    <div data-automation-id="multiSelectContainer" id="box">
      <input id="education-1--fieldOfStudy" placeholder="Search" />
      <div data-automation-id="promptSelectionLabel" id="picked"></div>
      <div id="menu"></div>
    </div>
    <p id="error1-education-1--fieldOfStudy" data-automation-id="inputAlert">Error: The field Field of Study is required and must have a value.</p>
    <script>
      const input = document.getElementById('education-1--fieldOfStudy');
      const menu = document.getElementById('menu');
      function show(items, onClick) {
        menu.innerHTML = items.map(t =>
          '<div data-automation-id="promptOption" style="display:block;height:24px;width:240px">' + t + '</div>'
        ).join('');
        menu.querySelectorAll('[data-automation-id="promptOption"]').forEach(el => {
          el.addEventListener('click', () => onClick(el.textContent.trim()));
        });
      }
      input.addEventListener('keydown', (e) => {
        if (e.key !== 'Enter') return;
        show(['Partial List (First 500 Entries)', 'All'], (text) => {
          if (text !== 'All') return;
          show(['Accounting', 'Computer Science'], (leaf) => {
            document.getElementById('picked').textContent = leaf;
            const charm = document.createElement('span');
            charm.setAttribute('data-automation-id', 'DELETE_charm');
            document.getElementById('box').appendChild(charm);
            menu.innerHTML = '';
          });
        });
      });
    </script>
    """
    filled: list = []
    skipped: list = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            _fill_degree_and_fos(page, profile, filled, skipped)
            chip = page.locator("#picked").inner_text().strip()
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert chip == "Computer Science"
    assert not any(row.get("label") == "Field of Study" for row in skipped)


def test_field_of_study_does_not_accept_a_longer_major():
    from apply_engine.workday_widgets import field_of_study_committed

    assert field_of_study_committed("Computer Science", "Computer Science")
    assert not field_of_study_committed("Electrical Engineering and Computer Science", "Computer Science")
    assert not field_of_study_committed("Computer and Information Science", "Computer Science")


def test_aerospace_internship_question_is_no():
    from apply_engine.models import Profile
    from apply_engine.workday_widgets import match_application_question

    profile = Profile(
        full_name="Jordan Avery",
        first_name="Jordan",
        last_name="Avery",
        email="jordan.avery@example.org",
        previous_employee=False,
    )
    key, terms = match_application_question(
        "Have you previously had an Internship or Co-op with The Aerospace Corporation?",
        profile,
    )
    assert key == "previous_employee"
    assert "No" in terms
    key, terms = match_application_question(
        "Do you have Military/Government work experience?",
        profile,
    )
    assert key == "military_government_experience"
    assert terms == ["No"]


def test_field_of_study_click_ignores_offscreen_duplicate():
    import pytest
    from playwright.sync_api import sync_playwright

    from apply_engine.workday_widgets import _mouse_click_prompt_text

    pytest.importorskip("playwright")
    html = """
    <div data-automation-id="activeListContainer" style="height:180px;overflow:hidden;position:relative">
      <div data-automation-id="promptOption" id="stale" style="position:absolute;top:900px;height:24px;width:240px">Computer Science</div>
      <div data-automation-id="promptOption" id="live" style="height:24px;width:240px">Computer Science</div>
    </div>
    <script>
      document.getElementById('stale').addEventListener('click', () => { window.hit = 'stale'; });
      document.getElementById('live').addEventListener('click', () => { window.hit = 'live'; });
    </script>
    """
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            clicked = _mouse_click_prompt_text(page, "Computer Science")
            hit = page.evaluate("() => window.hit || ''")
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert clicked
    assert hit == "live"


def test_season_start_follows_the_named_term():
    from datetime import date

    from apply_engine.workday_widgets import season_start

    assert season_start("Summer 2027 Software Engineer Intern") == {
        "season": "summer",
        "month_num": "06",
        "day": "01",
        "year": "2027",
    }
    assert season_start("Winter 2027 Intern")["month_num"] == "01"
    assert season_start("Winter 2027 Intern")["day"] == "04"
    assert season_start("Spring 2027 Intern") == {
        "season": "spring",
        "month_num": "01",
        "day": "25",
        "year": "2027",
    }
    assert season_start("Fall 2027 Intern") == {
        "season": "fall",
        "month_num": "08",
        "day": "25",
        "year": "2027",
    }
    assert season_start("2027 Machine Learning Engineer Undergrad Intern") == {
        "season": "summer",
        "month_num": "06",
        "day": "01",
        "year": "2027",
    }
    titled = season_start("2027 Undergrad Intern", "Summer internship in El Segundo")
    assert titled["season"] == "summer"
    assert titled["year"] == "2027"
    nxt = season_start("Summer Intern", today=date(2026, 9, 22))
    assert nxt["year"] == "2027"
    assert nxt["month_num"] == "06"


def test_clearance_type_is_none_and_ability_follows_work_auth():
    from apply_engine.models import Profile
    from apply_engine.workday_widgets import match_application_question

    profile = Profile(
        full_name="Jordan Avery",
        first_name="Jordan",
        last_name="Avery",
        email="jordan.avery@example.org",
        work_authorized_us=True,
        need_sponsorship=False,
    )
    key, terms = match_application_question(
        "Please indicate your active security clearance type",
        profile,
    )
    assert key == "security_clearance"
    assert terms == ["NA", "N/A", "None"]
    key, terms = match_application_question(
        "This position requires the ability to obtain and maintain a security clearance. Are you able to meet this requirement?",
        profile,
    )
    assert key == "clearance_eligible"
    assert terms == ["Yes"]
    key, terms = match_application_question(
        "What are your plans after graduation? (i.e., full-time employment, starting MS or Ph.D. program)",
        profile,
    )
    assert key == "plans_after_graduation"
    assert terms[0] == "Full-time employment"
    unauthorized = Profile(
        full_name="Jordan Avery",
        first_name="Jordan",
        last_name="Avery",
        email="jordan.avery@example.org",
        work_authorized_us=False,
        need_sponsorship=True,
    )
    assert match_application_question(
        "Are you able to obtain and maintain a security clearance?",
        unauthorized,
    ) is None
    key, terms = match_application_question("Do you have a security clearance?", profile)
    assert key == "security_clearance"
    assert terms[0] == "No"
    profile.degree = "Bachelor of Science in Computer Science"
    key, terms = match_application_question(
        "Please provide your current college enrollment status",
        profile,
    )
    assert key == "enrollment_status"
    assert "Bachelor's" in terms


def test_united_states_label_rejects_territories():
    from apply_engine.workday_widgets import united_states_label

    assert united_states_label("United States")
    assert united_states_label("United States of America")
    assert not united_states_label("United States Minor Outlying Islands")
    assert not united_states_label("United States Virgin Islands")


def test_date_field_rejected_catches_the_empty_announcement():
    from apply_engine.workday_widgets import date_field_rejected

    assert date_field_rejected(
        "Proposed Start Date current value is MM/DD/YYYY Error: The field Proposed Start Date is required and must have a value"
    )
    assert not date_field_rejected("Proposed Start Date current value is 6/1/2027")


def test_date_segment_calls_react_onchange():
    import pytest
    from playwright.sync_api import sync_playwright

    from apply_engine.workday_widgets import _set_date_inputs

    pytest.importorskip("playwright")
    html = """
    <input id="start-dateSectionMonth-input" />
    <script>
      const el = document.getElementById('start-dateSectionMonth-input');
      el.__reactProps$test = {
        onChange(ev) { window.changed = ev.target.value; },
        onBlur(ev) { window.blurred = ev.target.value; },
      };
    </script>
    """
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            _set_date_inputs(page, "start-dateSectionMonth-input", "", "", {"month_num": "06"}, "")
            changed = page.evaluate("() => window.changed || ''")
            blurred = page.evaluate("() => window.blurred || ''")
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert changed == "06"
    assert blurred == "06"


def test_phone_device_type_selects_mobile():
    import pytest
    from playwright.sync_api import sync_playwright

    from apply_engine.workday_widgets import _fill_phone_device_type

    pytest.importorskip("playwright")
    html = """
    <div data-automation-id="formField-phoneDeviceType">
      Phone Device Type *
      <select id="device">
        <option>Select One</option>
        <option>Mobile</option>
        <option>Landline</option>
        <option>Fax</option>
      </select>
    </div>
    """
    filled: list = []
    skipped: list = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            _fill_phone_device_type(page, filled, skipped)
            shown = page.locator("#device").locator("option:checked").inner_text()
            browser.close()
    except Exception as extra:
        if "Executable doesn't exist" in str(extra):
            pytest.skip(f"chromium not installed: {extra}")
        raise
    assert shown == "Mobile"
    assert not skipped
    assert filled and filled[0]["mapped_to"] == "phone_device_type"
    assert filled[0]["value"] == "Mobile"
