from apply_engine.detect import detect_ats, parse_company_from_url, parse_job_id


def test_greenhouse_job_boards():
    url = "https://job-boards.greenhouse.io/linkedin/jobs/5079761"
    assert detect_ats(url) == "greenhouse"
    assert parse_company_from_url(url) == "linkedin"
    assert parse_job_id(url) == "5079761"


def test_greenhouse_classic_boards():
    url = "https://boards.greenhouse.io/acme/jobs/12345"
    assert detect_ats(url) == "greenhouse"
    assert parse_company_from_url(url) == "acme"
    assert parse_job_id(url) == "12345"


def test_greenhouse_embed():
    url = "https://boards.greenhouse.io/embed/job_app?for=acme&token=999"
    assert detect_ats(url) == "greenhouse"
    assert parse_company_from_url(url) == "acme"
    assert parse_job_id(url) == "999"


def test_ashby():
    url = "https://jobs.ashbyhq.com/openai/123-abc"
    assert detect_ats(url) == "ashby"
    assert parse_company_from_url(url) == "openai"


def test_lever():
    url = "https://jobs.lever.co/stripe/aaaaaaaa-bbbb-cccc"
    assert detect_ats(url) == "lever"
    assert parse_company_from_url(url) == "stripe"
    assert parse_job_id(url) == "aaaaaaaa-bbbb-cccc"


def test_workday_classic_host():
    url = "https://acme.myworkdayjobs.com/en-US/careers/job/NYC/Intern_R1"
    assert detect_ats(url) == "workday"
    assert parse_company_from_url(url) == "acme"
    assert parse_job_id(url) == "Intern_R1"


def test_workday_wd1_tenant():
    url = "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/Santa-Clara-CA/SWE-Intern_JR12345"
    assert detect_ats(url) == "workday"
    assert parse_company_from_url(url) == "nvidia"
    assert parse_job_id(url) == "SWE-Intern_JR12345"


def test_workday_wd1_root_host():
    url = "https://wd1.myworkdayjobs.com/en-US/External/job/Role_R9"
    assert detect_ats(url) == "workday"


def test_workday_wd3():
    url = "https://company.wd3.myworkdayjobs.com/en-US/External"
    assert detect_ats(url) == "workday"
    assert parse_company_from_url(url) == "company"


def test_html_workday_board():
    html = '<html data-automation-id="jobPostingPage"><iframe src="https://acme.wd1.myworkdayjobs.com/apply"></iframe></html>'
    assert detect_ats("https://careers.example.com/job/1", html) == "workday"


def test_html_greenhouse_iframe():
    html = '<iframe id="grnhse_iframe" src="https://boards.greenhouse.io/embed/job_app?for=x"></iframe>'
    assert detect_ats("https://careers.example.com/job/1", html) == "greenhouse"


def test_html_ashby():
    html = '<div class="ashby-application-form" data-ashbyhq="1">Apply</div>'
    assert detect_ats("https://careers.example.com/job/1", html) == "ashby"


def test_html_lever():
    html = '<div class="lever-apply"><form class="application-form">'
    assert detect_ats("https://jobs.example.com/posting", html) == "lever"
