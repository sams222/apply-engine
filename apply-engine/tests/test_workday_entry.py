from apply_engine.guard import is_apply_nav
from apply_engine.workday import (
    page_looks_like_job_listing,
    page_looks_like_workday_auth,
    page_looks_like_workday_form,
    workday_apply_urls,
    workday_job_base,
)

WD = "https://motorolasolutions.wd5.myworkdayjobs.com/Careers/job/Chicago-IL/Software-Engineering-Intern---Summer-2027_R68388"


def test_workday_apply_urls_prefer_manual():
    urls = workday_apply_urls(WD)
    assert urls[0].endswith("/apply/applyManually")
    assert urls[1].endswith("/apply")
    assert workday_job_base(urls[0]) == workday_job_base(WD)


def test_workday_apply_urls_idempotent_on_apply_path():
    base = workday_job_base(WD + "/apply/applyManually")
    assert base == workday_job_base(WD)


def test_is_apply_nav_accepts_role_suffix_rejects_partners():
    assert is_apply_nav("Apply")
    assert is_apply_nav("Apply Now")
    assert is_apply_nav("Apply for Software Engineering Intern")
    assert not is_apply_nav("Apply with LinkedIn")
    assert not is_apply_nav("Apply with Indeed")


def test_listing_vs_form_heuristics():
    listing = "Careers\nJob Description\nApply\nAbout the role"
    assert page_looks_like_job_listing(listing, WD) is True
    form = "My Information\nFirst Name\nLegal Name\nPreviously Worked"
    assert page_looks_like_workday_form(form) is True
    assert page_looks_like_job_listing(form, WD) is False
    auth = "Create Account\nEmail Address\nPassword\nVerify New Password\nSign In"
    assert page_looks_like_workday_auth(auth) is True
