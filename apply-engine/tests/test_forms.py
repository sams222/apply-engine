from pathlib import Path

import pytest

from apply_engine.models import JobPosting
from tests.test_questions import POOL, _profile

FIXTURE = Path(__file__).parent / "fixtures" / "forms-mixed.html"


@pytest.fixture()
def page(monkeypatch):
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:
            pytest.skip(f"chromium not installed: {exc}")
        pg = browser.new_page()
        pg.set_content(FIXTURE.read_text(encoding="utf-8"))
        yield pg
        browser.close()


def _run(page, monkeypatch=None):
    from apply_engine.forms import fill_form

    filled, skipped, notes = [], [], []
    job = JobPosting(url="https://example.org", title="Software Engineer Intern", company="Acme")
    fill_form(page, profile=_profile(), pool=POOL, job=job, filled=filled, skipped=skipped, notes=notes)
    return {r["mapped_to"]: r["value"] for r in filled}, skipped, notes


def test_every_widget_kind_is_answered_and_read_back(page):
    mapped, skipped, notes = _run(page)
    assert mapped["first_name"] == "Jordan"
    assert mapped["work_authorized_us"] == "Yes"
    assert mapped["need_sponsorship"] == "No"
    assert page.locator("button[aria-pressed=true]").inner_text() == "No"
    assert mapped["gender"] == "Male"
    assert page.locator("input[name=gender][value=m]").is_checked()
    assert mapped["how_heard"] == "Acme Website"
    assert not page.locator("input[name=LinkedIn]").is_checked()
    assert page.locator("input[name=ack]").is_checked()
    assert not page.locator("input[name='consent[sms]']").is_checked()
    assert page.locator("#loc").input_value() == "New York City, New York, United States"


def test_essay_without_llm_parks_needs_user(page):
    _, skipped, notes = _run(page)
    assert page.locator("#why").input_value() == ""
    assert any(s["label"].startswith("Why do you want to work at Acme?") and s["label"].endswith("*") for s in skipped)
    assert any(n.startswith("needs_user: required question unanswered: Why do you want") for n in notes)


def test_essay_uses_llm_when_configured(page, monkeypatch):
    monkeypatch.setattr("apply_engine.llm.available", lambda: True)
    monkeypatch.setattr("apply_engine.llm.draft_essay_checked", lambda q, facts, limit_hint="": ("I build data tools at Tech Fellows Program.", []))
    mapped, skipped, notes = _run(page)
    assert page.locator("#why").input_value() == "I build data tools at Tech Fellows Program."
    assert not any("needs_user" in n for n in notes)


def test_saved_answers_are_reused_verbatim_and_never_redrafted(monkeypatch):
    from apply_engine import forms

    calls = []
    monkeypatch.setattr(forms.llm, "available", lambda: True)
    monkeypatch.setattr(forms.llm, "draft_essay_checked", lambda *a, **k: calls.append(a) or ("fresh draft", []))
    filler = forms.FormFiller(None, profile=None, pool=[], job=None, filled=[], skipped=[], notes=[],
                              saved_answers={"Why us?": "Reviewed text."})
    filler._facts = ""
    assert filler._essay({"label": "Why us?", "kind": "textarea"}) == "Reviewed text."
    assert filler._essay({"label": "Something new?", "kind": "textarea"}) is None
    assert filler._llm_pick({"label": "Pick one"}, ["A", "B"]) == []
    filler.saved["Pick one"] = "B"
    assert filler._llm_pick({"label": "Pick one"}, ["A", "B"]) == ["B"]
    assert calls == []


def test_ashby_required_radio_resticks_after_other_fields_clear_it():
    pytest.importorskip("playwright")
    from pathlib import Path

    from playwright.sync_api import sync_playwright

    from apply_engine.forms import fill_form
    from apply_engine.models import JobPosting
    from tests.test_questions import POOL, _rich_profile

    html = (Path(__file__).parent / "fixtures" / "ashby-track-radio.html").read_text(encoding="utf-8")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            filled, skipped, notes = [], [], []
            job = JobPosting(url="https://jobs.ashbyhq.com/niantic", title="Intern", company="Niantic")
            fill_form(page, profile=_rich_profile(), pool=POOL, job=job, filled=filled, skipped=skipped, notes=notes)
            checked = page.locator("input[name=track]:checked")
            value = checked.get_attribute("value") if checked.count() else None
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert value == "ml", (value, filled, skipped, notes)
    assert page_radio_mapped(filled) == "ML/AI Infrastructure"


def page_radio_mapped(filled):
    for row in filled:
        if row.get("mapped_to") == "role_preferences":
            return row.get("value")
    return None


def test_greenhouse_country_combobox_waits_for_delayed_options():
    pytest.importorskip("playwright")
    from pathlib import Path

    from playwright.sync_api import sync_playwright

    from apply_engine.forms import fill_form
    from apply_engine.models import JobPosting
    from tests.test_questions import POOL, _profile

    html = (Path(__file__).parent / "fixtures" / "greenhouse-country-delayed.html").read_text(encoding="utf-8")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            filled, skipped, notes = [], [], []
            job = JobPosting(url="https://job-boards.greenhouse.io/memx", title="Intern", company="MEMX")
            fill_form(page, profile=_profile(), pool=POOL, job=job, filled=filled, skipped=skipped, notes=notes)
            shown = page.locator("#country").input_value()
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            pytest.skip(f"chromium not installed: {exc}")
        raise
    assert shown == "United States", (shown, filled, skipped, notes)
    assert not any("Country" in (s.get("label") or "") for s in skipped)
