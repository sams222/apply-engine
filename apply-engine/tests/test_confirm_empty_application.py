"""confirm must refuse an application that was never actually filled.

Live Walmart run 8: sign-in succeeded, then Workday threw its own
"Something went wrong" interstitial. The run reported waiting_confirm with only
auth rows and an empty skipped list, so neither the required-field guard nor the
readback guard fired — confirm would have submitted a blank application.
"""

from __future__ import annotations

import pytest

from apply_engine.cli import _assert_application_filled


def _item(*pairs):
    return {"filled": [{"mapped_to": k, "value": v} for k, v in pairs]}


def test_auth_only_run_is_refused():
    item = _item(("email", "a@b.com"), ("workday_password", "[redacted]"))
    with pytest.raises(SystemExit) as exc:
        _assert_application_filled(item)
    assert "never completed" in str(exc.value)


def test_completely_empty_is_refused():
    with pytest.raises(SystemExit):
        _assert_application_filled({"filled": []})


def test_one_or_two_fields_is_refused():
    with pytest.raises(SystemExit):
        _assert_application_filled(_item(("first_name", "Jordan"), ("last_name", "Avery")))


def test_real_application_is_allowed():
    item = _item(
        ("email", "a@b.com"),
        ("workday_password", "[redacted]"),
        ("first_name", "Jordan"),
        ("last_name", "Avery"),
        ("address_line1", "160 Convent Avenue"),
        ("city", "New York"),
        ("state", "New York"),
        ("postal_code", "10001"),
        ("phone", "(212) 555-0147"),
    )
    _assert_application_filled(item)


def test_auth_rows_do_not_count_toward_the_threshold():
    """email/password are auth, not application content."""
    item = _item(
        ("email", "a@b.com"),
        ("workday_password", "[redacted]"),
        ("first_name", "Jordan"),
    )
    with pytest.raises(SystemExit):
        _assert_application_filled(item)
