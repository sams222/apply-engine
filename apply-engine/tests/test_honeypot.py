"""Bot traps must never be filled.

Live finding (walmart.wd504.myworkdayjobs.com, Sept 2026): the Workday
Create Account form ships a hidden input alongside the real email/password
fields:

    <input name="website" data-automation-id="beecatcher"
           label="Enter website. This input is for robots only, do not enter
                  if you're human." >   // 1x0 px, display:block, opacity:1

`map_field` mapped it to the profile's `website` key. Filling it tells Walmart
the application came from a bot. It is CSS-"visible" — only its 1x0 box and its
label give it away.
"""

from __future__ import annotations

import pytest

from apply_engine.fields import is_honeypot, is_noise_field, map_field

WALMART_LABEL = (
    "Enter website. This input is for robots only, do not enter if you're human."
)


def test_walmart_beecatcher_is_not_mapped():
    assert map_field(WALMART_LABEL, "website") is None
    assert is_noise_field(WALMART_LABEL, "website")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"automation_id": "beecatcher"},
        {"name": "beecatcher"},
        {"name": "honeypot"},
        {"name": "bot-field"},
        {"label": WALMART_LABEL},
        {"label": "Leave this field blank"},
        {"label": "Website", "width": 1, "height": 0},
        {"label": "Website", "width": 0, "height": 40},
    ],
)
def test_honeypot_signals(kwargs):
    assert is_honeypot(**kwargs)


@pytest.mark.parametrize(
    "label,expected",
    [
        ("Website", "website"),
        ("Personal Website", "website"),
        ("Portfolio", "website"),
        ("LinkedIn Profile", "linkedin"),
        ("GitHub", "github"),
    ],
)
def test_real_url_fields_still_map(label, expected):
    """The trap fix must not cost us legitimate website/portfolio fields."""
    assert map_field(label) == expected
    assert not is_honeypot(label=label, width=376, height=40)


def test_normal_sized_field_is_not_a_honeypot():
    assert not is_honeypot(label="Email Address*", name="", width=376, height=40)


def test_honeypot_not_filled_on_a_live_shaped_form(tmp_path):
    """End-to-end on the exact DOM shape Walmart serves."""
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from apply_engine.fill import _find_by_aliases
    from apply_engine.fields import FIELD_ALIASES

    html = """
      <form>
        <label for="input-4">Email Address*</label>
        <input id="input-4" data-automation-id="email" type="text">
        <label for="hp">Enter website. This input is for robots only, do not enter if you're human.</label>
        <input id="hp" name="website" data-automation-id="beecatcher" type="text"
               style="width:1px;height:0px;display:block;visibility:visible;opacity:1">
      </form>
    """
    aliases = dict(FIELD_ALIASES).get("website", ("website",))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.set_content(html)
            found = _find_by_aliases(page, aliases, key="website")
            got_id = found.get_attribute("id") if found is not None else None
        finally:
            browser.close()

    assert got_id != "hp", "the field finder handed back the bot trap"
