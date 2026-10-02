
from apply_engine.workday import auth_click_allowed, emails_match, prefer_sign_in


def test_prefer_sign_in_blocked_when_verify_visible():
    assert prefer_sign_in(known=True, verify_password_visible=True, visible_password_count=2) is False
    assert prefer_sign_in(known=True, verify_password_visible=False, visible_password_count=1) is True
    assert prefer_sign_in(known=False, verify_password_visible=False, visible_password_count=1) is False


def test_auth_click_allowed_requires_email_and_consent_on_create():
    assert auth_click_allowed(
        email_readback="",
        expected_email="jordan.avery@example.org",
        create_mode=True,
        password_filled=True,
        verify_filled=True,
        consent_visible=True,
        consent_checked=True,
    ) is False
    assert auth_click_allowed(
        email_readback="jordan.avery@example.org",
        expected_email="jordan.avery@example.org",
        create_mode=True,
        password_filled=True,
        verify_filled=True,
        consent_visible=True,
        consent_checked=False,
    ) is False
    assert auth_click_allowed(
        email_readback="jordan.avery@example.org",
        expected_email="jordan.avery@example.org",
        create_mode=True,
        password_filled=True,
        verify_filled=True,
        consent_visible=True,
        consent_checked=True,
    ) is True


def test_emails_match_casefold():
    assert emails_match("Jordan@X.COM", "jordan@x.com")
    assert not emails_match("", "jordan@x.com")
