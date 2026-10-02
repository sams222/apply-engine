"""filled-log vs screenshot reconciliation.

A filled log that claims a value the form never rendered is worse than no log,
because `confirm` trusts it (9372e5: auth rows claimed email/password while the
screenshot showed an empty Sign In). These tests pin the refusal.
"""

from __future__ import annotations

import pytest

from apply_engine.cli import _assert_readback_clean
from apply_engine.readback import CRITICAL, capture, digits, reconcile

SHOWN = [
    {"value": "New York", "visible": True},
    {"value": "10001", "visible": True},
    {"value": "(212) 555-0147", "visible": True},
    {"value": "No", "visible": True},
    {"value": "jordan.avery@example.org", "visible": True},
]


def test_matching_log_reconciles_clean():
    filled = [
        {"mapped_to": "state", "value": "New York"},
        {"mapped_to": "postal_code", "value": "10001"},
        {"mapped_to": "phone", "value": "(212) 555-0147"},
        {"mapped_to": "previous_employee", "value": "No"},
        {"mapped_to": "email", "value": "jordan.avery@example.org"},
    ]
    assert reconcile(filled, SHOWN) == []


def test_phone_matches_on_digits_not_formatting():
    assert reconcile([{"mapped_to": "phone", "value": "+1 212 555 0147"}], SHOWN) == []
    assert reconcile([{"mapped_to": "phone", "value": "2125550147"}], SHOWN) == []


def test_wrong_phone_is_caught():
    problems = reconcile([{"mapped_to": "phone", "value": "212-555-0100"}], SHOWN)
    assert len(problems) == 1
    assert problems[0]["mapped_to"] == "phone"


@pytest.mark.parametrize(
    "key,value",
    [
        ("state", "California"),
        ("postal_code", "94103"),
        ("previous_employee", "Yes"),
        ("email", "someone.else@example.com"),
    ],
)
def test_drifted_values_are_caught(key, value):
    problems = reconcile([{"mapped_to": key, "value": value}], SHOWN)
    assert problems and problems[0]["mapped_to"] == key


def test_empty_snapshot_is_unverified_not_clean():
    problems = reconcile([{"mapped_to": "state", "value": "New York"}], [])
    assert problems and problems[0]["reason"] == "no dom snapshot captured"


def test_redacted_and_noncritical_rows_are_skipped():
    assert reconcile([{"mapped_to": "workday_password", "value": "[redacted]"}], SHOWN) == []
    assert reconcile([{"mapped_to": "linkedin", "value": "https://example.invalid"}], SHOWN) == []


def test_confirm_refuses_on_drift():
    item = {
        "extra": {
            "readback_problems": [
                {"mapped_to": "state", "logged": "California", "shown": "New York"}
            ]
        }
    }
    with pytest.raises(SystemExit) as exc:
        _assert_readback_clean(item)
    assert "does not match the screenshot" in str(exc.value)


def test_confirm_allows_clean_item():
    _assert_readback_clean({"extra": {"readback_problems": []}})
    _assert_readback_clean({})


def test_digits_helper():
    assert digits("(212) 555-0147") == "2125550147"
    assert digits("+1-212-555-0147") == "12125550147"


def test_critical_keys_cover_spec_values():
    for key in ("state", "postal_code", "phone", "previous_employee"):
        assert key in CRITICAL


def test_capture_reads_rendered_values():
    """capture() must report what the page shows, including a custom widget."""
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    html = """
      <label for=city>City</label><input id=city value="New York">
      <label for=zip>Postal Code</label><input id=zip value="10001">
      <input type=password id=pw value="hunter2">
      <select id=st><option>Alabama</option><option selected>New York</option></select>
      <button aria-haspopup="listbox" aria-label="Degree">Bachelor of Science (B.S.)</button>
    """
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.set_content(html)
            rows = capture(page)
        finally:
            browser.close()

    values = {r["value"] for r in rows}
    assert "New York" in values
    assert "10001" in values
    assert "Bachelor of Science (B.S.)" in values
    # password captured as presence only
    assert "hunter2" not in values
    assert "[present]" in values


def test_capture_never_raises_on_a_dead_page():
    class Dead:
        def evaluate(self, *_a, **_k):
            raise RuntimeError("page closed")

    assert capture(Dead()) == []
