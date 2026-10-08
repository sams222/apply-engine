"""do-not-retry: refuse specific jobs before a browser launches.

Burned requisitions stay blocked. Distinct reqs at the same company (Motorola
R68679 vs submitted R68388; DoorDash Labs 8263774 vs 8171041) must still open
when the owner asks.

The list is the union of:
  * SEED_JOBS — job-level keys in code so a missing JSON file cannot re-enable them
  * <data-tree>/do-not-retry.json — {"jobs": [...], "companies": [...], "allow": [...]}

Company entries in the JSON still block every URL at that firm (operator
opt-in). The in-code seed is job-level only — never a bare company token.

An allowlist (--allow-req / --allow-url / JSON "allow") beats a company-level
block. It never beats a job-level block for the same req.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

# Job-level seeds. Motorola Chicago R68388 is submitted; DoorDash 8171041 is the
# burned greenhouse req. Bedrock is not seeded as a company — use ledger dedupe
# or a JSON company/job entry if a specific req must stay blocked.
SEED_JOBS: tuple[str, ...] = (
    "wd:motorolasolutions.wd5:R68388",
    "gh:doordashusa:8171041",
)

# Back-compat alias so older imports of SEED do not crash; it is empty on purpose.
SEED: tuple[str, ...] = ()


@dataclass(frozen=True)
class Blocked:
    """Why a URL was refused."""

    token: str
    matched: str
    source: str
    job_key: str = ""
    kind: str = "job"  # "job" | "company"

    def reason(self) -> str:
        return (
            f"do_not_retry: {self.token!r} matches {self.matched!r} "
            f"(source: {self.source})"
        )


def _norm(text: str) -> str:
    """Lowercase and strip separators so 'Motorola Solutions' == 'motorolasolutions'."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _strip_apply_suffix(path: str) -> str:
    return re.sub(r"/(applyManually|apply)/?$", "", path or "", flags=re.I)


def job_key(url: str) -> str:
    """Stable id for a posting: Workday req, Greenhouse/Ashby/Lever job id, else host+path."""
    if not url:
        return ""
    raw = url if "//" in url else f"//{url}"
    parts = urlsplit(raw)
    host = (parts.netloc or "").lower()
    path = _strip_apply_suffix(parts.path or "")
    qmap = {k.lower(): v for k, v in parse_qs(parts.query or "", keep_blank_values=True).items()}

    wd_req = re.search(r"(?:_|/)(R-?\d+)\b", path, re.I)
    if wd_req and ("myworkdayjobs" in host or "workdayjobs" in host or re.search(r"\.wd\d+\.", host)):
        tenant = host.split(".")[0]
        wd = re.search(r"\.(wd\d+)\.", host)
        board = f"{tenant}.{wd.group(1)}" if wd else tenant
        req = wd_req.group(1).upper().replace("R-", "R")
        return f"wd:{board}:{req}"

    gid = ""
    m = re.search(r"/jobs/(\d+)", path)
    if m:
        gid = m.group(1)
    if not gid:
        for key in ("gh_jid", "token"):
            vals = qmap.get(key) or []
            if vals and re.fullmatch(r"\d+", str(vals[0] or "")):
                gid = str(vals[0])
                break
    greenhouseish = "greenhouse" in host or bool(qmap.get("gh_jid")) or bool(gid and "/jobs/" in path)
    if gid and greenhouseish:
        org = ""
        for_vals = qmap.get("for") or []
        if for_vals:
            org = str(for_vals[0] or "").lower()
        if not org:
            segs = [s for s in path.split("/") if s and s.lower() not in {"jobs", "embed", "job_app", "en-us", "en"}]
            if segs:
                org = segs[0].lower()
        return f"gh:{org}:{gid}" if org else f"gh:{gid}"

    uuid = re.search(
        r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
        path,
        re.I,
    )
    if uuid and "ashby" in host:
        return f"ashby:{uuid.group(1).lower()}"
    if uuid and "lever.co" in host:
        return f"lever:{uuid.group(1).lower()}"
    if "lever.co" in host:
        segs = [s for s in path.split("/") if s]
        if segs:
            return f"lever:{segs[-1].lower()}"

    host_path = (host + path).rstrip("/").lower()
    return f"url:{re.sub(r'[^a-z0-9]+', '', host_path)}"


def _job_id(key: str) -> str:
    if not key:
        return ""
    tail = key.split(":")[-1]
    return re.sub(r"^r-", "r", tail.lower())


def jobs_match(extracted: str, listed: str) -> bool:
    """True when extracted job_key is the same req as a seed/JSON/allow entry."""
    a, b = (extracted or "").strip(), (listed or "").strip()
    if not a or not b:
        return False
    if a.lower() == b.lower():
        return True
    aid = _job_id(a)
    if ":" not in b:
        return bool(aid) and aid == _job_id(f"x:{b}")
    bid = _job_id(b)
    if not aid or aid != bid:
        return False
    ap, bp = a.split(":"), b.split(":")
    if ap[0].lower() != bp[0].lower():
        return False
    if len(ap) >= 3 and len(bp) >= 3:
        return bp[1].lower() in ap[1].lower() or ap[1].lower() in bp[1].lower()
    return True


def _as_list(raw: object) -> list[str]:
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return []


def load_blocklist(path: Path | None = None) -> dict[str, object]:
    """Seed jobs plus JSON jobs/companies/allow. Corrupt JSON keeps the seeds."""
    jobs: dict[str, str] = {k.lower(): "seed" for k in SEED_JOBS}
    companies: dict[str, str] = {}
    allow: list[str] = []
    if path and Path(path).exists():
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"jobs": jobs, "companies": companies, "allow": allow}
        if isinstance(raw, list):
            for entry in raw:
                token = _norm(str(entry))
                if token:
                    companies.setdefault(token, str(path))
            return {"jobs": jobs, "companies": companies, "allow": allow}
        if not isinstance(raw, dict):
            return {"jobs": jobs, "companies": companies, "allow": allow}
        for entry in _as_list(raw.get("jobs")):
            jobs.setdefault(entry.lower(), str(path))
        for entry in _as_list(raw.get("companies")):
            token = _norm(entry)
            if token:
                companies.setdefault(token, str(path))
        allow = _as_list(raw.get("allow"))
    return {"jobs": jobs, "companies": companies, "allow": allow}


def _haystacks(url: str, company: str = "") -> list[tuple[str, str]]:
    """(normalized text, human label) pairs a company token may match against."""
    out: list[tuple[str, str]] = []
    if company:
        out.append((_norm(company), company))
    if url:
        parts = urlsplit(url if "//" in url else f"//{url}")
        host = parts.netloc or ""
        if host:
            out.append((_norm(host), host))
        segments = [s for s in (parts.path or "").split("/") if s][:2]
        for seg in segments:
            out.append((_norm(seg), seg))
    return [(h, label) for h, label in out if h]


def _allowed(url: str, key: str, allow_reqs: list[str], allow_urls: list[str], json_allow: list[str]) -> bool:
    needles = [*(allow_reqs or []), *(allow_urls or []), *(json_allow or [])]
    if not needles:
        return False
    if any((u or "").rstrip("/") and (u or "").rstrip("/") in (url or "") for u in allow_urls or []):
        return True
    for item in needles:
        if jobs_match(key, item) or jobs_match(job_key(item), key):
            return True
        if item and item.lower() in (url or "").lower():
            return True
    return False


def check(
    url: str,
    company: str = "",
    path: Path | None = None,
    allow_reqs: list[str] | None = None,
    allow_urls: list[str] | None = None,
) -> Blocked | None:
    """Return why this job is refused, or None when it may proceed."""
    lists = load_blocklist(path)
    jobs: dict[str, str] = lists["jobs"]  # type: ignore[assignment]
    companies: dict[str, str] = lists["companies"]  # type: ignore[assignment]
    json_allow: list[str] = lists["allow"]  # type: ignore[assignment]
    key = job_key(url)

    for listed, source in jobs.items():
        if jobs_match(key, listed):
            return Blocked(
                token=listed.split(":")[-1],
                matched=key or listed,
                source=source,
                job_key=key,
                kind="job",
            )

    allowed = _allowed(url, key, allow_reqs or [], allow_urls or [], json_allow)
    for haystack, label in _haystacks(url, company):
        for token, source in companies.items():
            if token and token in haystack:
                if allowed:
                    continue
                return Blocked(
                    token=token,
                    matched=label,
                    source=source,
                    job_key=key,
                    kind="company",
                )
    return None


def result_payload(blocked: Blocked, url: str, company: str = "") -> dict:
    """APPLY_ENGINE_RESULT body for a refusal. Same contract as every other exit."""
    return {
        "status": "do_not_retry",
        "url": url,
        "company": company,
        "blocked_token": blocked.token,
        "matched": blocked.matched,
        "source": blocked.source,
        "job_key": blocked.job_key or job_key(url),
        "submit_clicked": False,
        "notes": [blocked.reason(), "not retryable; remove from do-not-retry.json to re-enable"],
    }
