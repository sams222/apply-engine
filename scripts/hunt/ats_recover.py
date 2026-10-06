#!/usr/bin/env python3
"""ATS URL recovery for Jobright-only cards (jobright.ai/jobs/info/<id>) + priority-firm allowlist.

Canonical home: scripts/hunt/ats_recover.py (keep next to run_hunt.py / build_jobright.py).
Added 2026-10-06 after Hudson River Trading "Algorithm Development (Quant Research & Trading) Internship – Summer
2027" was silently dropped as near_miss_unresolved_ats (HRT's public Greenhouse board is `wehrtyou`, not
`hudsonrivertrading`, and Jobright's apply URL is only in its JS app).

Recovery order (first hit wins):
  a) Simplify summer/newgrad listings, ANY age: same company, intern-ish, high title similarity, same role family
     (Data Scientist never matches Algorithm Development), not ambiguous (two different reqs tied => skip).
  b) Company careers / Greenhouse board for known custom hosts (KNOWN_CAREERS) + slugs discovered from Simplify
     gh_jid URLs: fuzzy-match the board/careers titles; prefer company URLs carrying gh_jid=.
  c) (in build_jobright.py) generic greenhouse/ashby/lever/workday board_map lookup.

Every network call goes through `fetch(url)` so tests can inject fixtures (set_fetcher()).
"""
from __future__ import annotations

import difflib
import json
import re
import subprocess

# ---------------------------------------------------------------- priority firms (shared with run_hunt.priority_for)
PRIORITY_FIRMS = ("visa", "disney", "nvidia", "stripe", "databricks", "citadel", "jane street",
                  "two sigma", "goldman", "morgan stanley", "jpmorgan", "meta", "google",
                  "apple", "amazon", "microsoft", "openai", "anthropic", "tiktok", "bytedance",
                  "spotify", "robinhood", "coinbase", "airbnb", "uber", "lyft", "netflix",
                  "bloomberg", "hudson river", "hrt", "jump", "tower", "drw", "imc",
                  "invesco", "blackrock", "fidelity", "capital one", "square", "block",
                  "palantir", "scale", "figma", "notion", "datadog", "snowflake",
                  "geneva", "lseg", "refinitiv", "okta", "snap", "rundoo", "hex ")
_PRIORITY_RE = re.compile(r"\b(" + "|".join(re.escape(p.strip()) for p in PRIORITY_FIRMS) + r")\b", re.I)


def is_priority_firm(company: str) -> str | None:
    """Word-boundary match on the COMPANY name only (so 'Metamorph'≠meta, 'JumpCloud'≠jump). Returns the hit."""
    m = _PRIORITY_RE.search(company or "")
    return m.group(1).lower() if m else None


# ---------------------------------------------------------------- normalisation (identical to run_hunt/build_jobright)
def norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def company_key(name):
    n = re.sub(r"[^a-z0-9 &+-]+", "", norm(name))
    for suffix in (" inc", " inc.", " llc", " ltd", " corp", " corporation", " co", " company"):
        if n.endswith(suffix):
            n = n[: -len(suffix)]
    return n.strip()


def tnorm(t):
    t = re.sub(r"\b(20\d\d|summer|fall|winter|spring|intern(ship)?|program|co-?op)\b", " ", norm(t))
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


INTERNISH = re.compile(r"(intern|co-?op|student|apprentice|trainee|fellow)", re.I)
PHD = re.compile(r"\b(ph\.?d|phds|doctoral)\b", re.I)
NEWGRAD = re.compile(r"(new grad|\b20\d\d grads?\b|graduate program|full[- ]time)", re.I)
FAMILIES = {
    "data_science": re.compile(r"data scien", re.I),
    "quant_algo": re.compile(r"(algorithm|quant(itative)? (research|trad)|\btrading\b|\bqr\b)", re.I),
    "software": re.compile(r"(software|\bswe\b|developer|full[\s-]?stack|front[\s-]?end|back[\s-]?end|c\+\+|python)", re.I),
    "hardware": re.compile(r"(hardware|fpga|asic|design verification|silicon|electrical)", re.I),
    "ml": re.compile(r"(machine learning|\bml\b|\bai\b)", re.I),
    "analytics": re.compile(r"analyt", re.I),
    "product": re.compile(r"product manag", re.I),
    "security": re.compile(r"(security|cyber)", re.I),
}


def families(title):
    return {k for k, rx in FAMILIES.items() if rx.search(title or "")}


def compatible(card_title, cand_title):
    """Guards so we never attach e.g. a Data Scientist or PhD URL to an Algorithm Development intern card."""
    if INTERNISH.search(card_title) and not INTERNISH.search(cand_title):
        return False, "candidate not intern-ish"
    if bool(PHD.search(card_title)) != bool(PHD.search(cand_title)):
        return False, "PhD mismatch"
    if bool(re.search(r"\bmba\b", card_title, re.I)) != bool(re.search(r"\bmba\b", cand_title, re.I)):
        return False, "MBA mismatch"
    if NEWGRAD.search(cand_title) and not NEWGRAD.search(card_title):
        return False, "candidate is new-grad/full-time"
    fa, fb = families(card_title), families(cand_title)
    if fa and fb and not (fa & fb):
        return False, f"role family mismatch {sorted(fa)} vs {sorted(fb)}"
    return True, ""


def score(card_title, cand_title):
    a = tnorm(card_title)
    r = difflib.SequenceMatcher(None, a, tnorm(cand_title)).ratio()
    return r + 0.01 * difflib.SequenceMatcher(None, norm(card_title), norm(cand_title)).ratio()


def ats_of(url):
    u = (url or "").lower()
    if "myworkdayjobs" in u:
        return "workday"
    if "greenhouse" in u or "gh_jid=" in u:
        return "greenhouse"
    if "ashbyhq" in u:
        return "ashby"
    if "lever.co" in u:
        return "lever"
    return None


SUPPORTED = {"greenhouse", "ashby", "lever", "workday"}


def pick(card_title, cands, min_ratio=0.86, tie=0.02):
    """cands: [(title, url, extra_dict)] -> (best|None, reason). Ambiguous ties between different reqs => None."""
    scored = []
    for t, u, extra in cands:
        ok, why = compatible(card_title, t)
        if not ok:
            continue
        s = score(card_title, t) + (0.005 if (extra or {}).get("active") else 0)
        scored.append((s, t, u, extra or {}))
    scored.sort(key=lambda x: -x[0])
    if not scored or scored[0][0] < min_ratio:
        return None, f"no compatible title ≥{min_ratio} (best {scored[0][0]:.2f} '{scored[0][1]}')" if scored else "no compatible candidates"
    top = scored[0]
    rivals = [s for s in scored[1:] if s[2] != top[2] and top[0] - s[0] < tie and ats_job_id(s[2]) != ats_job_id(top[2])]
    if rivals:
        return None, (f"ambiguous: '{top[1]}' {top[2]} vs '{rivals[0][1]}' {rivals[0][2]} (scores {top[0]:.2f}/"
                      f"{rivals[0][0]:.2f})")
    return top, ""


def ats_job_id(url):
    for pat in (r"gh_jid=(\d+)", r"token=(\d+)", r"/jobs/(\d+)", r"([0-9a-f-]{36})", r"_(R-?\d[\w-]*|JR\d[\w-]*)$"):
        m = re.search(pat, url or "")
        if m:
            return m.group(1)
    return url


# ---------------------------------------------------------------- network (injectable)
def _curl(url, timeout=20):
    cmd = ["curl", "-sL", "--max-time", str(timeout), "-A", "Mozilla/5.0", "-w", "\n%{http_code}", url]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5).stdout
    except Exception:
        return 0, ""
    body, _, code = out.rpartition("\n")
    try:
        return int(code), body
    except ValueError:
        return 0, ""


_FETCH = _curl
_CACHE: dict = {}
FIXTURE = False  # True while a test fetcher is installed (run_hunt then allows "network" recovery offline)


def set_fetcher(fn):
    """fn(url) -> (http_code, body). Use a fixture dict in tests; pass None to restore curl."""
    global _FETCH, FIXTURE
    _FETCH = fn or _curl
    FIXTURE = fn is not None
    _CACHE.clear()


def fetch(url):
    if url not in _CACHE:
        _CACHE[url] = _FETCH(url)
    return _CACHE[url]


# ---------------------------------------------------------------- a) Simplify
def recover_from_simplify(company, title, listings, min_ratio=0.86):
    """listings: Simplify dicts (any age, active or not). Returns resolved dict or None, plus reason."""
    ck = company_key(company)
    cands = []
    for x in listings:
        if company_key(x.get("company_name", "")) != ck:
            continue
        u = x.get("url") or ""
        if ats_of(u) not in SUPPORTED:
            continue
        cands.append((x.get("title", ""), u, {"active": bool(x.get("active")), "date_posted": x.get("date_posted")}))
    best, why = pick(title, cands, min_ratio)
    if not best:
        return None, f"simplify: {why}"
    s, t, u, extra = best
    note = (f"recovered via Simplify listing '{t}' (score {s:.2f}, simplify active={extra.get('active')}) — "
            f"Jobright card had only a jobright.ai link")
    return {"company": company, "title": title, "url": u, "note": note, "method": "simplify"}, ""


# ---------------------------------------------------------------- b) careers / custom-host Greenhouse boards
KNOWN_CAREERS = {
    # company_key -> careers pages to scrape + Greenhouse board slugs backing a custom host (gh_jid= URLs)
    "hudson river trading": {"careers": ["https://www.hudsonrivertrading.com/careers/"], "gh_boards": ["wehrtyou"]},
    "hrt": {"careers": ["https://www.hudsonrivertrading.com/careers/"], "gh_boards": ["wehrtyou"]},
}
GH_SLUG_RE = re.compile(r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_board(?:/js)?\?for=|embed/job_app\?for=)?"
                        r"([A-Za-z0-9_-]+)")
ANCHOR_RE = re.compile(r"<a[^>]+href=\"([^\"]*gh_jid=\d+[^\"]*)\"[^>]*>(.*?)</a>", re.I | re.S)


def _strip(t):
    import html
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(t or ""))).strip()


def discover_gh_slugs(company, listings=()):
    """Greenhouse slugs for a company: KNOWN_CAREERS + careers-page embeds + probing slug guesses with a gh_jid
    taken from any Simplify URL of that company on a custom host."""
    ck = company_key(company)
    known = KNOWN_CAREERS.get(ck, {})
    slugs = list(known.get("gh_boards", []))
    for cu in known.get("careers", []):
        code, body = fetch(cu)
        if code == 200:
            slugs += [s for s in GH_SLUG_RE.findall(body) if s not in ("embed", "v1")]
    jids = []
    for x in listings:
        if company_key(x.get("company_name", "")) == ck:
            m = re.search(r"gh_jid=(\d+)", x.get("url") or "")
            if m and "greenhouse.io" not in x["url"]:
                jids.append(m.group(1))
    if jids:
        base = re.sub(r"[^a-z0-9]", "", ck)
        guesses = [base, base.replace("trading", ""), "".join(w[0] for w in ck.split() if w)]
        for g in guesses:
            if g and g not in slugs and fetch(f"https://boards-api.greenhouse.io/v1/boards/{g}/jobs/{jids[-1]}")[0] == 200:
                slugs.append(g)
    return list(dict.fromkeys(slugs))


def recover_from_careers(company, title, listings=(), min_ratio=0.86):
    ck = company_key(company)
    cands = []
    known = KNOWN_CAREERS.get(ck, {})
    for cu in known.get("careers", []):  # static anchors on the careers page (if the site renders them)
        code, body = fetch(cu)
        if code == 200:
            for href, text in ANCHOR_RE.findall(body):
                href = href if href.startswith("http") else re.sub(r"(https?://[^/]+).*", r"\1", cu) + href
                cands.append((_strip(text), href, {"via": f"careers page {cu}"}))
    for slug in discover_gh_slugs(company, listings):
        code, body = fetch(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
        if code != 200:
            continue
        try:
            jobs = json.loads(body).get("jobs", [])
        except Exception:
            continue
        for j in jobs:
            board_url = f"https://job-boards.greenhouse.io/{slug}/jobs/{j.get('id')}"
            u = j.get("absolute_url") or board_url
            cands.append((j.get("title", ""), u, {"via": f"greenhouse board {slug}", "board_url": board_url,
                                                   "first_published": j.get("first_published"), "active": True}))
    if not cands:
        return None, "careers: no careers/board candidates"
    # prefer company URLs with gh_jid= when two candidates are the same req
    cands.sort(key=lambda c: 0 if "gh_jid=" in c[1] else 1)
    best, why = pick(title, cands, min_ratio)
    if not best:
        return None, f"careers: {why}"
    s, t, u, extra = best
    note = (f"recovered via {extra.get('via')} matched '{t}' (score {s:.2f})"
            + (f"; first_published {extra['first_published']}" if extra.get("first_published") else "")
            + " — Jobright card had only a jobright.ai link")
    out = {"company": company, "title": title, "url": u, "note": note, "method": "careers"}
    if extra.get("board_url"):
        out["board_url"] = extra["board_url"]
    return out, ""


def recover(company, title, listings, network=True, min_ratio=0.86):
    """a) Simplify then b) careers (network). Returns (resolved|None, [reasons])."""
    reasons = []
    r, why = recover_from_simplify(company, title, listings, min_ratio)
    if r:
        return r, reasons
    reasons.append(why)
    if network:
        r, why = recover_from_careers(company, title, listings, min_ratio)
        if r:
            return r, reasons
        reasons.append(why)
    return None, reasons
