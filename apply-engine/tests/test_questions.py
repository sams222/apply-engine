from datetime import date

import pytest

from apply_engine.models import EEO, PoolEntry, Profile
from apply_engine.questions import Context, choose, class_standing, resolve


def _profile() -> Profile:
    return Profile(
        full_name="Jordan Avery",
        first_name="Jordan",
        last_name="Avery",
        email="jordan@example.org",
        phone="(212) 555-0147",
        linkedin="https://linkedin.com/in/jordan-avery",
        github="https://github.com/javery-dev",
        location="New York, NY",
        city="New York",
        state="NY",
        country="United States",
        address_line1="46 W 86th St",
        postal_code="10024",
        school="Hudson State University",
        degree="Bachelor of Science in Computer Science",
        gpa="3.9",
        graduation="May 2028",
        work_authorized_us=True,
        need_sponsorship=False,
        field_of_study="Computer Science",
        preferred_locations=["Remote", "San Francisco", "New York"],
        eeo=EEO(gender="Male", race_ethnicity="White", veteran="I am not a protected veteran",
                disability="I do not have a disability"),
        extra={
            "preferred_name": "Jordan", "us_citizen": True, "willing_to_relocate": True, "willing_onsite": True,
            "hispanic_latino": False, "pronouns": "He/him", "sms_opt_in": False, "felony_conviction": False,
        },
    )


POOL = [
    PoolEntry(title="CTP", kind="experience", tags=[], bullets=[], company="Tech Fellows Program", role="Data Science Fellow",
              start="July 2026", end="Present"),
    PoolEntry(title="Brightwork", kind="experience", tags=[], bullets=[], company="Brightwork", role="Software Engineer Intern",
              start="March 2026", end="May 2026"),
    PoolEntry(title="Code Camp Co", kind="experience", tags=[], bullets=[], company="Code Camp Co",
              role="Programming Instructor", start="April 2024", end="August 2025"),
]
CTX = Context(job_title="Software Engineer Intern (Summer 2027)", company="Acme", pool=POOL, today=date(2026, 9, 26))


def pick(question: str, options: list[str]) -> list[str]:
    want = resolve(question, _profile(), CTX)
    assert want is not None, question
    return choose(options, want)


@pytest.mark.parametrize(
    "question,options,expected",
    [
        ("Are you authorized to work in the country for which you applied?", ["Yes", "No"], "Yes"),
        ("Are you currently legally authorized to work in the country in which this job is based "
         "(e.g. you are a citizen, you have a visa, etc.)?*", ["Yes", "No"], "Yes"),
        ("Are you able to work from Figma's SF Hub?*", ["Yes", "No"], "Yes"),
        ("Third location preference*", ["San Francisco, CA, United States", "Seattle, WA, United States",
                                        "New York, NY, United States", "I am open to working in any office",
                                        "I do not have flexibility to consider another office location"],
         "I am open to working in any office"),
        ("This position is based in the United States. Do you currently reside in commutable proximity to a Lyft "
         "Office located in New York City or are you open to relocating?*",
         ["I am willing to relocate before starting employment.", "I am not willing to relocate before starting employment.",
          "I already reside near a Lyft office and I am able to work at a Lyft On-site Office."],
         "I already reside near a Lyft office and I am able to work at a Lyft On-site Office."),
        ("If you selected a response to the prior question other than \u201cnone of the above,\u201d please confirm "
         "whether any of the following also applies to you.",
         ["U.S. citizen", "None of these apply to me", "Not applicable (i.e., I selected \u201cnone of the above\u201d for the prior question)"],
         "Not applicable (i.e., I selected \u201cnone of the above\u201d for the prior question)"),
        ("Will you now or in the future require sponsorship (e.g. H1B, OPT)?", ["OPT", "H1B", "TN", "None", "Other"], "None"),
        ("Have you worked at Spotify before?", ["No", "Yes - Intern", "Yes - Full Time Employment"], "No"),
        ("Country*", ["United States Minor Outlying Islands", "United States", "Uruguay"], "United States"),
        ("Gender", ["Female", "Male", "Decline"], "Male"),
        ("Race", ["Hispanic or Latino", "White (Not Hispanic or Latino)", "Asian (Not Hispanic or Latino)"],
         "White (Not Hispanic or Latino)"),
        ("Are you Hispanic/Latino?", ["Yes", "No", "Decline To Self Identify"], "No"),
        ("Veteran Status", ["I identify as a protected veteran", "I am not a protected veteran", "I decline"],
         "I am not a protected veteran"),
        ("Do you have a disability?", ["Yes, I have a disability", "No, I do not have a disability and have not had one in the past",
                                        "I do not want to answer"], "No, I do not have a disability and have not had one in the past"),
        ("Expected graduation date?", ["May 2027", "Spring 2028", "May 2028"], "May 2028"),
        ("What is your expected date of graduation?", ["May 2027", "Spring 2028", "May 2028"], "May 2028"),
        ("How many prior internships have you had?", ["0", "1", "2", "3+"], "1"),
        ("Which conference did you attend?", ["RecSys 2026", "I did not attend a conference"], "I did not attend a conference"),
        ("Degree Type", ["Undergraduate/Bachelors", "Master's", "PhD"], "Undergraduate/Bachelors"),
        ("Are you a U.S. citizen?", ["Yes", "No"], "Yes"),
        ("Have you ever been convicted of a felony?", ["Yes", "No"], "No"),
        ("Do you have relatives currently employed by Stripe?", ["Yes", "No"], "No"),
    ],
)
def test_choice_answers(question, options, expected):
    assert pick(question, options)[:1] == [expected]


def test_explanatory_paragraph_does_not_steer_the_rule():
    q = ("We work from our offices on Mondays, Tuesdays, and Thursdays (Anchor Days). If you need an accommodation, "
         "we'll partner with you. Are you able to work in office 3 days a week?")
    assert resolve(q, _profile(), CTX).key == "willing_onsite"


def test_how_heard_prefers_company_site_and_never_export_rule():
    assert pick("How did you hear about this opportunity? (select all that apply)",
                ["LinkedIn", "Glassdoor", "Notion Website"]) == ["Notion Website"]


def test_marketing_and_sms_stay_unchecked():
    p = _profile()
    assert resolve("Spotify has my consent to contact me about future job opportunities.", p, CTX).leave_blank
    assert resolve("I agree to receive SMS text messages about my application", p, CTX).polarity is False


def test_text_answers():
    p = _profile()
    assert resolve("First Name*", p, CTX).text == "Jordan"
    assert resolve("Preferred First Name", p, CTX).text == "Jordan"
    assert resolve("Current company", p, CTX).text == "Tech Fellows Program"
    assert resolve("Why do you want to join Figma?*", p, CTX).essay
    grad = resolve("What is your expected date of graduation?", p, CTX)
    assert grad is not None and not grad.essay and grad.key == "graduation"
    assert "2028" in (grad.text or "")
    assert resolve("Portfolio Password or Access Code(s)*", p, CTX).text == "N/A"
    assert resolve("What is your current or previous job title?*", p, CTX).text == "Data Science Fellow"
    duo = resolve("Do you have a Duolingo account? If yes, what is your username?*", p, CTX)
    assert not duo.essay and not duo.text and not duo.terms
    assert resolve("Please share your SAT or ACT score if you have one.", p, CTX).leave_blank
    p.extra.update(high_school_name="Example High School", alternate_terms=["Winter"])
    assert resolve("High School Name*", p, CTX).text == "Example High School"
    cohort = resolve("Do you have flexibility to consider a second cohort option?*", p, CTX)
    assert choose(["I am not pursuing another cohort at this time", "Winter (January - April)", "Summer (May - September)"],
                  cohort) == ["Winter (January - April)"]


def test_unknown_preference_is_left_for_the_picker():
    assert resolve("What type of engineering role are you interested in?", _profile(), CTX) is None


def test_class_standing_from_graduation():
    assert class_standing(_profile(), date(2026, 9, 26)) == "Junior"


def _rich_profile() -> Profile:
    p = _profile()
    p.education_start = "August 2024"
    p.extra.update({
        "government_official": False, "government_official_relative": False, "conflict_of_interest": False,
        "ai_tool_usage": "I design or automate workflows with AI tools (e.g., building agents, integrating AI into team processes).",
        "role_preferences": ["Applied AI", "Data Engineering", "Full Stack"],
        "internship_priorities": ["Impact of work", "Career growth"],
        "desired_pay_fallback": "$25/hour",
    })
    return p


AREAS = ["Applied AI", "Backend", "Data Engineering", "Frontend", "No preference"]


@pytest.mark.parametrize(
    "question,options,expected",
    [
        ("Education - Start date month*", ["July", "August"], ["August"]),
        ("Education - End date month*", ["April", "May"], ["May"]),
        ("Employment - Start date month*", ["June", "July"], ["July"]),
        ("Are you in your final year of study and applying for an end-of-study internship?", ["Yes", "No", "Not sure"], ["No"]),
        ("If you were offered full-time employment with Datadog, when would you be able to start?", ["May", "June", "Other"], ["June"]),
        ("I am available to begin a potential full-time role before September 2028.", ["Yes", "No"], ["Yes"]),
        ("Please confirm receipt of the above linked Global Data Privacy Notice.", ["Confirmed"], ["Confirmed"]),
        ("Are you a current government official or were you a government official in the last five years?",
         ["No, I am not a current or former Government Official", "Yes, I am a current Government Official"],
         ["No, I am not a current or former Government Official"]),
        ("Are you a close relative of a government official (i.e., child/step-child, spouse/partner)?",
         ["Yes, I am a relative of a government official.", "No, I am not a relative of a government official."],
         ["No, I am not a relative of a government official."]),
        ("Do you or a close relative currently hold a role with a senior leader that could create a conflict of interest?",
         ["Yes", "No"], ["No"]),
        ("Which of the following best describes how you use AI tools today?",
         ["I have experimented with AI tools (professionally and/or personally).",
          "I design or automate workflows with AI tools (e.g., building agents, integrating AI into team processes)."],
         ["I design or automate workflows with AI tools (e.g., building agents, integrating AI into team processes)."]),
        ("Which opportunity are you most interested in?", AREAS, ["Applied AI"]),
        ("Which area is your second choice?", AREAS, ["Data Engineering"]),
        ("When considering an internship, what are the most important factors to you?",
         ["Career growth", "Company culture", "Impact of work"], ["Impact of work", "Career growth"]),
        ("Please select all the languages you speak fluently.", ["English", "French"], ["English"]),
    ],
)
def test_block_and_custom_answers(question, options, expected):
    want = resolve(question, _rich_profile(), CTX)
    assert want is not None, question
    assert choose(options, want) == expected


def test_education_year_is_bare_number():
    assert resolve("Education - Start date year*", _rich_profile(), CTX).text == "2024"
    assert resolve("Education - End date year*", _rich_profile(), CTX).text == "2028"


def test_programming_languages_from_pool_tags():
    pool = [PoolEntry(title="x", kind="project", tags=["python", "typescript", "c"],
                      bullets=["Built the S.C.O.P.E. Engine in PHP, SQL, and JavaScript."])]
    ctx = Context(pool=pool, today=date(2026, 9, 26))
    want = resolve("Which scripting / programming languages do you have experience with?", _rich_profile(), ctx)
    got = choose(["C", "C#", "Go", "Java", "Javascript", "PHP", "Python", "R", "SQL, PL/SQL", "Typescript"], want)
    assert set(got) == {"C", "Javascript", "PHP", "Python", "SQL, PL/SQL", "Typescript"}


def test_pay_uses_posted_floor_then_fallback():
    ctx = Context(description="The hourly pay for this role is $42 - $55 per hour.", pool=POOL, today=date(2026, 9, 26))
    assert resolve("What are your salary expectations?", _rich_profile(), ctx).text == "$42/hour"
    yearly = Context(description="Base salary range: $120,000 - $150,000 USD per year", pool=POOL, today=date(2026, 9, 26))
    assert resolve("Desired salary", _rich_profile(), yearly).text == "$120,000/year"
    assert resolve("Desired salary", _rich_profile(), CTX).text == "$25/hour"


WEST_MONROE_AUTH = (
    "Are you legally authorized to work in the US now and in the future "
    "for any employer without visa sponsorship?"
)


def test_norm_strips_trailing_colon_and_asterisk():
    from apply_engine.questions import norm

    assert norm("Address Line 1:*") == "address line 1"
    assert norm("City:*") == "city"
    assert norm("Country*") == "country"
    assert norm("Phone Device Type*") == "phone device type"


def test_address_labels_with_trailing_colon_map_from_profile():
    p = _profile()
    assert resolve("Address Line 1:*", p, CTX).key == "address_line1"
    assert resolve("Address Line 1:*", p, CTX).text == "46 W 86th St"
    assert resolve("City:*", p, CTX).key == "city"
    assert resolve("City:*", p, CTX).text == "New York"


def test_authorized_without_sponsorship_is_yes_not_need_sponsorship():
    p = _profile()
    want = resolve(WEST_MONROE_AUTH, p, CTX)
    assert want is not None
    assert want.key == "work_authorized_without_sponsorship"
    assert want.polarity is True
    assert want.text == "Yes"
    assert choose(["Yes", "No"], want) == ["Yes"]
    from apply_engine.fields import map_field, profile_value

    assert map_field(WEST_MONROE_AUTH) == "work_authorized_without_sponsorship"
    assert profile_value(p, "work_authorized_without_sponsorship") == "Yes"


def test_authorized_without_sponsorship_is_no_when_sponsorship_needed():
    p = _profile()
    p.need_sponsorship = True
    want = resolve(WEST_MONROE_AUTH, p, CTX)
    assert want.key == "work_authorized_without_sponsorship"
    assert want.polarity is False
    assert choose(["Yes", "No"], want) == ["No"]


def test_plain_sponsorship_question_still_maps_to_need_sponsorship():
    want = resolve("Will you now or in the future require visa sponsorship?", _profile(), CTX)
    assert want.key == "need_sponsorship"
    assert want.polarity is False
    assert choose(["Yes", "No"], want) == ["No"]


NVIDIA_WORK_PERMIT = (
    "Will you require employer support to obtain or maintain authorization "
    "to work in that country? e.g. (work permit)"
)


def test_employer_support_work_permit_maps_to_need_sponsorship():
    p = _profile()
    want = resolve(NVIDIA_WORK_PERMIT, p, CTX)
    assert want is not None
    assert want.key == "need_sponsorship"
    assert want.polarity is False
    assert want.text == "No"
    assert choose(["Yes", "No"], want) == ["No"]
    from apply_engine.fields import map_field, profile_value

    assert map_field(NVIDIA_WORK_PERMIT) == "need_sponsorship"
    assert profile_value(p, "need_sponsorship") == "No"

    p.need_sponsorship = True
    want = resolve(NVIDIA_WORK_PERMIT, p, CTX)
    assert want.key == "need_sponsorship"
    assert want.polarity is True
    assert choose(["Yes", "No"], want) == ["Yes"]
    assert profile_value(p, "need_sponsorship") == "Yes"


def test_graduation_window_dec_2027_aug_2028_yes_for_may_2028():
    q = "Is your graduation date between December 2027 and August 2028?"
    want = resolve(q, _profile(), CTX)
    assert want is not None
    assert want.key == "graduation_window"
    assert want.polarity is True
    assert choose(["Yes", "No"], want) == ["Yes"]
    early = _profile()
    early.graduation = "May 2027"
    assert choose(["Yes", "No"], resolve(q, early, CTX)) == ["No"]
    late = _profile()
    late.graduation = "December 2028"
    assert choose(["Yes", "No"], resolve(q, late, CTX)) == ["No"]


def test_how_heard_prefers_company_website_over_relish_careers():
    options = ["Relish Careers", "Company Website", "LinkedIn", "Employee Referral"]
    assert pick("How did you hear about us?", options) == ["Company Website"]
    assert pick("How did you hear about this opportunity?",
                ["Relish Careers", "Company Career Site", "Indeed"]) == ["Company Career Site"]
    assert pick("How did you hear about this role?",
                ["Relish Careers", "Career Site"]) == ["Career Site"]


def test_eeo_race_multiselect_matches_white():
    options = [
        "American Indian or Alaska Native",
        "Asian",
        "Black or African American",
        "Hispanic or Latino",
        "White",
        "Two or More Races",
        "I do not wish to answer",
    ]
    assert pick("Please select your race/ethnicity (select all that apply)", options) == ["White"]
    assert pick("Race", options) == ["White"]
    # Options leaking into the question text must not steer this onto hispanic_latino.
    blob = "Voluntary self-identification " + " / ".join(options)
    want = resolve(blob, _profile(), CTX)
    assert want.key == "race_ethnicity"
    assert choose(options, want) == ["White"]


def test_phone_device_type_maps_to_mobile():
    want = resolve("Phone Device Type*", _profile(), CTX)
    assert want.key == "phone_device_type"
    assert choose(["Select One", "Mobile", "Landline", "Fax"], want) == ["Mobile"]
    assert choose(["Select One", "Mobile Phone", "Home"], want) == ["Mobile Phone"]


def test_internship_track_radio_maps_from_role_preferences():
    want = resolve("Which internship track are you applying for?*", _rich_profile(), CTX)
    assert want is not None
    assert choose(
        ["Product Engineering", "ML/AI Infrastructure", "Data Engineering"],
        want,
    ) == ["ML/AI Infrastructure"]
