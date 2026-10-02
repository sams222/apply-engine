from __future__ import annotations

import re
from collections import Counter
from html import unescape
from urllib.parse import urlparse

import httpx

from apply_engine.detect import (
    ATS_ASHBY,
    ATS_GREENHOUSE,
    ATS_LEVER,
    detect_ats,
    parse_company_from_url,
    parse_job_id,
)
from apply_engine.models import JobPosting
from apply_engine.util import strip_html

UA = "ApplierApplyEngine/0.1 (+https://localhost; truthful-resume-tailor)"


def greenhouse_board_token(url: str, jid: str, html: str = "", timeout: float = 10.0) -> str | None:
    """Board token for a gh_jid posting on a company's own careers site, validated against the API."""
    tokens = re.findall(r"greenhouse\.io/(?:embed/job_board(?:/js)?|embed/job_app)\?for=([A-Za-z0-9_-]+)", html)
    tokens += re.findall(r"(?:job-boards|boards)\.greenhouse\.io/([A-Za-z0-9_-]+)/jobs", html)
    host = (urlparse(url).hostname or "").lower().removeprefix("www.").removeprefix("careers.").removeprefix("jobs.")
    sld = host.split(".")[0]
    tokens += [sld, re.sub(r"(hq|careers|jobs)$", "", sld)]
    seen: set[str] = set()
    for token in tokens:
        token = token.lower()
        if not token or token in seen:
            continue
        seen.add(token)
        try:
            resp = httpx.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{jid}", timeout=timeout)
        except Exception:
            continue
        if resp.status_code == 200:
            return token
    return None


def fetch_job(url: str, timeout: float = 20.0) -> JobPosting:
    ats = detect_ats(url)
    company = parse_company_from_url(url, ats)
    job_id = parse_job_id(url, ats)
    posting = JobPosting(url=url, apply_url=url, ats=ats, company=company, source="url")
    gh_jid = re.search(r"gh_jid=(\d+)", url)
    if ats == ATS_GREENHOUSE and gh_jid and "greenhouse.io" not in (urlparse(url).hostname or ""):
        try:
            html = _get_text(url, timeout)
        except (httpx.HTTPError, OSError):
            html = ""
        token = greenhouse_board_token(url, gh_jid.group(1), html)
        if token:
            company, job_id = token, gh_jid.group(1)
    try:
        if ats == ATS_GREENHOUSE and company and job_id:
            data = _get_json(
                f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs/{job_id}",
                timeout,
            )
            if data:
                posting.title = str(data.get("title") or "")
                posting.company = str(data.get("company_name") or company)
                loc = data.get("location") or {}
                posting.location = str(loc.get("name") or "") if isinstance(loc, dict) else str(loc or "")
                posting.description = strip_html(unescape(str(data.get("content") or "")))
                posting.apply_url = str(data.get("absolute_url") or url)
                posting.source = "greenhouse-api"
                return posting
        if ats == ATS_LEVER and company and job_id:
            data = _get_json(f"https://api.lever.co/v0/postings/{company}/{job_id}", timeout)
            if data:
                posting.title = str(data.get("text") or "")
                cats = data.get("categories") or {}
                posting.location = str(cats.get("location") or "") if isinstance(cats, dict) else ""
                desc = data.get("descriptionPlain") or data.get("description") or ""
                lists = data.get("lists") or []
                extra = []
                for item in lists:
                    extra.append(str(item.get("text") or ""))
                    extra.append(strip_html(str(item.get("content") or "")))
                posting.description = strip_html(unescape(str(desc) + "\n" + "\n".join(extra)))
                posting.company = _display_name(company, posting.description)
                posting.source = "lever-api"
                return posting
        if ats == ATS_ASHBY and company:
            data = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{company}", timeout)
            jobs = []
            if isinstance(data, dict):
                jobs = data.get("jobs") or data.get("jobPostings") or []
            match = _match_ashby(jobs, job_id, url)
            if match:
                posting.title = str(match.get("title") or match.get("name") or "")
                posting.location = str(match.get("location") or "")
                posting.description = strip_html(str(match.get("descriptionHtml") or match.get("description") or ""))
                posting.company = _display_name(company, posting.description)
                posting.source = "ashby-api"
                return posting
    except httpx.HTTPError:
        pass

    # HTML fallback. A JD that 404s or times out must not abort the apply: the
    # form fill needs the URL, not the description. Tailoring just loses its
    # keyword signal and falls back to pool order.
    try:
        html = _get_text(url, timeout)
    except (httpx.HTTPError, OSError):
        posting.source = "url-only"
        if not posting.company:
            posting.company = parse_company_from_url(url, ats)
        return posting
    posting.title = _og(html, "og:title") or _h1(html) or posting.title
    posting.description = strip_html(html)
    posting.source = "html"
    if not posting.company:
        posting.company = parse_company_from_url(url, ats)
    return posting


def fetch_job_from_text(url: str, title: str, company: str, description: str) -> JobPosting:
    ats = detect_ats(url)
    return JobPosting(
        url=url,
        apply_url=url,
        ats=ats,
        title=title,
        company=company or parse_company_from_url(url, ats),
        description=description,
        source="inline",
    )


def _display_name(slug: str, text: str = "") -> str:
    """Lever and Ashby only expose the board slug ("palantir", "openai"); prefer the posting's own casing."""
    if not slug.islower():
        return slug
    spaced = r" ?".join(re.escape(ch) for ch in slug.replace("-", ""))
    spelled = re.findall(rf"\b{spaced}\b", text or "", re.I)
    cased = Counter(s for s in spelled if s != s.lower())
    if cased:
        return cased.most_common(1)[0][0]
    return " ".join(w.capitalize() for w in re.split(r"[-_]+", slug))


def _get_json(url: str, timeout: float) -> dict | None:
    with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": UA}) as client:
        resp = client.get(url)
        if resp.status_code >= 400:
            return None
        data = resp.json()
        return data if isinstance(data, dict) else None


def _get_text(url: str, timeout: float) -> str:
    with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": UA}) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.text


def _og(html: str, prop: str) -> str:
    m = re.search(rf'<meta[^>]+property=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)', html, re.I)
    if m:
        return unescape(m.group(1)).strip()
    m = re.search(rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']{re.escape(prop)}["\']', html, re.I)
    return unescape(m.group(1)).strip() if m else ""


def _h1(html: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
    return strip_html(m.group(1)) if m else ""


def _match_ashby(jobs: list, job_id: str, url: str) -> dict | None:
    if not isinstance(jobs, list):
        return None
    for job in jobs:
        if not isinstance(job, dict):
            continue
        jid = str(job.get("id") or job.get("jobId") or "")
        jurl = str(job.get("jobUrl") or job.get("applyUrl") or "")
        if job_id and (job_id == jid or job_id in jurl or job_id in str(job.get("title") or "")):
            return job
        if urlparse(url).path.rstrip("/") and jurl.endswith(urlparse(url).path):
            return job
    return jobs[0] if len(jobs) == 1 and isinstance(jobs[0], dict) else None
