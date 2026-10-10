
from apply_engine.workday import (
    auth_click_allowed,
    emails_match,
    is_standalone_sign_in_url,
    looks_like_standalone_sign_in,
    prefer_sign_in,
)


def test_prefer_sign_in_blocked_when_verify_visible():
    assert prefer_sign_in(known=True, verify_password_visible=True, visible_password_count=2) is False
    assert prefer_sign_in(known=True, verify_password_visible=False, visible_password_count=1) is True
    assert prefer_sign_in(known=False, verify_password_visible=False, visible_password_count=1) is False


def test_prefer_sign_in_standalone_even_when_tenant_unknown():
    # Unknown tenants must Create Account (GlobalFoundries). A known tenant on
    # a standalone Sign In wall still signs in.
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
    assert prefer_sign_in(
        known=True,
        verify_password_visible=True,
        visible_password_count=2,
        standalone_sign_in=True,
    ) is False


def test_standalone_sign_in_url_private_login():
    assert is_standalone_sign_in_url(
        "https://expedia.wd108.myworkdayjobs.com/en-US/private/login?redirect=%2Fen-US%2Fprivate"
    )
    assert is_standalone_sign_in_url("https://acme.wd1.myworkdayjobs.com/login")
    assert is_standalone_sign_in_url("https://acme.wd1.myworkdayjobs.com/en-US/signin")
    assert not is_standalone_sign_in_url(
        "https://expedia.wd108.myworkdayjobs.com/en-US/careers/job/Seattle/SDE_R1"
    )
    assert not is_standalone_sign_in_url("https://acme.wd1.myworkdayjobs.com/careers")


def test_looks_like_standalone_sign_in_form_and_create_veto():
    login = "https://expedia.wd108.myworkdayjobs.com/en-US/private/login"
    assert looks_like_standalone_sign_in(
        url=login,
        heading_sign_in=True,
        email_visible=True,
        visible_password_count=1,
        sign_in_submit_visible=True,
    )
    assert looks_like_standalone_sign_in(
        heading_sign_in=True,
        email_visible=True,
        visible_password_count=1,
        sign_in_submit_visible=True,
    )
    assert looks_like_standalone_sign_in(
        heading_create_account=False,
        email_visible=True,
        visible_password_count=1,
        sign_in_submit_visible=True,
    )
    assert not looks_like_standalone_sign_in(
        heading_create_account=True,
        email_visible=True,
        visible_password_count=2,
        verify_password_visible=True,
        sign_in_submit_visible=True,
        create_account_submit_visible=True,
    )
    assert not looks_like_standalone_sign_in(url=login)  # URL without widgets/heading is not fillable yet


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


def test_sso_email_gate_visible_only_without_email_password_fields():
    from apply_engine.workday import sso_email_gate_visible

    assert sso_email_gate_visible(
        email_input_count=0, password_input_count=0, sign_in_with_email_visible=True
    ) is True
    assert sso_email_gate_visible(
        email_input_count=1, password_input_count=0, sign_in_with_email_visible=True
    ) is False
    assert sso_email_gate_visible(
        email_input_count=0, password_input_count=0, sign_in_with_email_visible=False
    ) is False
