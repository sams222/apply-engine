from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

ATS_GREENHOUSE = "greenhouse"
ATS_ASHBY = "ashby"
ATS_LEVER = "lever"
ATS_WORKDAY = "workday"
ATS_GENERIC = "generic"

GREENHOUSE_HOSTS = (
    "greenhouse.io",
    "job-boards.greenhouse.io",
    "boards.greenhouse.io",
)
ASHBY_HOSTS = ("ashbyhq.com", "jobs.ashbyhq.com")
LEVER_HOSTS = ("lever.co", "jobs.lever.co")


def detect_ats(url: str, html: str = "") -> str:
    """Heuristic ATS detection from URL first, then page HTML."""
    host = (urlparse(url).hostname or "").lower()
    path = (urlparse(url).path or "").lower()
    hay = f"{host} {path} {(html or '').lower()}"

    if _host_endswith(host, GREENHOUSE_HOSTS) or "greenhouse.io" in host:
        return ATS_GREENHOUSE
    # Waymo careers.withwaymo.com?gh_jid=… and other Greenhouse embeds on custom hosts.
    if "gh_jid=" in (url or "").lower() or "gh_jid" in parse_qs(urlparse(url).query):
        return ATS_GREENHOUSE
    if "grnhse" in hay or "greenhouse-job-board" in hay or "boards-api.greenhouse" in hay:
        return ATS_GREENHOUSE
    if "greenhouse" in hay and (
        "form_submission" in hay or "job_questions" in hay or "job-boards.greenhouse" in hay
    ):
        return ATS_GREENHOUSE
    if _host_endswith(host, ASHBY_HOSTS) or "ashbyhq" in host:
        return ATS_ASHBY
    if "ashby" in hay and ("application" in hay or "ashbyhq" in hay):
        return ATS_ASHBY
    if _host_endswith(host, LEVER_HOSTS) or host.endswith("lever.co"):
        return ATS_LEVER
    if "lever-apply" in hay or "postings.lever.co" in hay:
        return ATS_LEVER
    if is_workday_host(host) or "myworkdayjobs.com" in hay:
        return ATS_WORKDAY
    if "workday" in hay and (
        "data-automation-id" in hay or "wd-popup" in hay or "workday-ui" in hay or "jobpostingpage" in hay
    ):
        return ATS_WORKDAY
    return ATS_GENERIC


def is_workday_host(host: str) -> bool:
    h = (host or "").lower().removeprefix("www.")
    if h == "myworkdayjobs.com" or h.endswith(".myworkdayjobs.com"):
        return True
    if re.match(r"^wd\d+\.myworkdayjobs\.com$", h):
        return True
    return False


def parse_workday_tenant(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    m = re.match(r"^([a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com$", host)
    if m:
        return m.group(1)
    m = re.match(r"^([a-z0-9-]+)\.myworkdayjobs\.com$", host)
    if m and not re.match(r"^wd\d+$", m.group(1)):
        return m.group(1)
    parts = [p for p in urlparse(url).path.split("/") if p]
    skip = {"en-us", "en", "job", "jobs", "careers", "external", "apply"}
    for part in parts:
        if part.lower() not in skip and not part.startswith("job/"):
            return part
    return host.split(".")[0] if host else ""


def _host_endswith(host: str, suffixes: tuple[str, ...]) -> bool:
    return any(host == s or host.endswith("." + s) for s in suffixes)


def parse_company_from_url(url: str, ats: str | None = None) -> str:
    ats = ats or detect_ats(url)
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if ats == ATS_GREENHOUSE:
        qs = parse_qs(parsed.query)
        if "for" in qs:
            return qs["for"][0]
        if parts:
            return parts[0]
    if ats == ATS_WORKDAY:
        tenant = parse_workday_tenant(url)
        if tenant:
            return tenant
    if ats in {ATS_ASHBY, ATS_LEVER} and parts:
        return parts[0]
    if parts:
        return parts[0]
    host = parsed.hostname or "company"
    host = re.sub(r"^www\.", "", host)
    return host.split(".")[0]


def parse_job_id(url: str, ats: str | None = None) -> str:
    ats = ats or detect_ats(url)
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    qs = parse_qs(parsed.query)
    if ats == ATS_GREENHOUSE:
        if "gh_jid" in qs:
            return qs["gh_jid"][0]
        if "token" in qs:
            return qs["token"][0]
        if "jobs" in parts:
            i = parts.index("jobs")
            if i + 1 < len(parts):
                return parts[i + 1]
    if ats == ATS_LEVER and len(parts) >= 2:
        return parts[-1]
    if ats == ATS_ASHBY and parts:
        return parts[-1]
    if ats == ATS_WORKDAY and parts:
        return parts[-1]
    return parts[-1] if parts else ""
