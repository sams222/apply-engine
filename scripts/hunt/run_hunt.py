#!/usr/bin/env python3
"""List-only hunt: Simplify + optional Jobright (jobright-discovery.json) + jobright-ai README.

Canonical copy: scripts/hunt/run_hunt.py (+ build_jobright.py, ats_recover.py,
test_priority_unresolved.py). Copy these into a run-artifacts/<slot>/ dir, or run in place with
HUNT_ART=<dir> / HUNT_SLOT=<name>. Default ART is this script's directory.

2026-10-06 fix (HRT Algorithm Development dropped as near_miss_unresolved_ats):
  * Jobright-only cards get ATS recovery (ats_recover: Simplify any-age -> careers/custom-host Greenhouse board).
  * company careers URLs with gh_jid= are Greenhouse.
  * PRIORITY firms (ats_recover.PRIORITY_FIRMS: bloomberg/hrt/jump/tower/drw/imc/...) whose ATS stays
    unresolved/unsupported are PROMOTED to apply-worthy with flag + needs_explicit_approval (Jobright URL kept),
    after all location/pay/skip/dnr filters; they appear in hunt_summary.md apply-worthy, apply_targets.json and
    sam_digest.md. Priority roles that are stale only per ATS first_published are kept with a caveat + flag.

LIST ONLY — this script never applies, confirms, or submits anything.

Jobright input: ART/jobright-discovery.json (built by build_jobright.py from raw.txt [+ hrefs.json]).
If that file is absent the run is Simplify + jobright-ai README only, and hunt_summary.md says so.

Rerun: python3 scripts/hunt/run_hunt.py   (set HUNT_ART to the run dir)
       (add --no-verify to skip the live ATS check)
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import os
import sys as _sys0

_HERE = Path(__file__).resolve().parent
_sys0.path.insert(0, str(_HERE))
import ats_recover  # noqa: E402  (sibling helper; copy scripts/hunt/ats_recover.py next to this file)

# HUNT_ART=<dir> + HUNT_NO_ROOT=1 let you dry-run against a copy without touching private root files.
# HUNT_ROOT / HUNT_ARTS point at an optional private internship-apps tree (absent in this public repo).
_DEFAULT_ART = _HERE
ART = Path(os.environ.get("HUNT_ART") or _DEFAULT_ART)
NO_ROOT = os.environ.get("HUNT_NO_ROOT") == "1"
SLOT = os.environ.get("HUNT_SLOT") or ART.name
OFFLINE = os.environ.get("HUNT_OFFLINE") == "1"  # no network at all (regression tests)
ROOT = Path(os.environ.get("HUNT_ROOT") or "/workspace/internship-apps")
ARTS = Path(os.environ.get("HUNT_ARTS") or (ROOT / "run-artifacts"))
NOW = time.time()
PREF_H = 24
SOFT_H = 40  # soft ≤40h for apply-worthy
HARD_H = 72  # note age-skipped for >40h ≤72h

CATS = {"Software", "AI/ML/Data", "Product", "Quant", "Hardware"}
ALLOWED_ATS = {"greenhouse", "lever", "ashby", "workday"}
CLASS_TOO_YOUNG = re.compile(r"class of 202[9]|graduat(?:ing|e|es)?\s*202[9]|2029[-\s]?only|class of 2030|graduat(?:ing|e|es)?\s*2030|2030[-\s]?only", re.I)
SWE_TITLE = re.compile(r"(software|swe|full[\s-]?stack|front[\s-]?end|back[\s-]?end|data\s*eng|machine\s*learning|ml\s*eng|ai\s*eng|applied\s*(ai|ml)|devops|sre|platform\s*eng|infra|quant\s*(dev|eng|soft)|backend|frontend)", re.I)

DO_NOT_RETRY = {
    "doordash", "bedrock", "bedrock robotics", "talos", "retell", "viam", "revel", "k2",
    "motorola", "motorola solutions", "antares", "mercor", "cohere", "onepay", "one finance",
    "kensho", "kensho technologies",
    "optiver",  # held 2026-09-22-2pm needs_user — do_not_retry
    "collinear", "collinear ai",  # submitted prior
    "rhoda ai", "rhoda",  # submitted 2026-09-23-1am
    "bracket bot", "bracketbot",  # submitted 2026-09-24-1am
    "genesis molecular ai", "genesis",  # submitted 2026-09-28-9am
    "plot technologies", "plot",  # submitted 2026-09-29-2pm
    "perchwell",  # submitted 2026-09-29-2pm (SWE + Data Analytics)
    "stand together",  # submitted 2026-10-02-1am Analytics Intern Lever
    "shopback",  # submitted 2026-10-02-9am SWE Intern Lever NYC
    # 2026-10-05-evening: Sam dismissed Capstone Investment Advisors (was 2pm KEEP)
    "capstone", "capstone investment advisors", "capstone investment",
    # 2026-10-05-evening: submitted Assured Guaranty Front-End Summer 2027 (Greenhouse job 8827460002)
    # 2026-10-06-1am: Back-End Summer 2027 (GH 8827458002) approved by Sam / apply in progress
    "assured guaranty", "assuredguaranty",
    # 2026-10-06: Khan Academy SWE Intern Summer 2027 (GH 8250259) already applied — do_not_retry
    "khan academy", "khanacademy",
}

# 2026-10-06-9am: role-level handled set (already sent to Sam at 1am and approved / applied / submitted).
# Matched by ATS job id first, then company+title. Other roles at Bobyard/Expedia are still evaluated
# but carry a caveat that Sam has an in-progress application there.
HANDLED_JOB_IDS = {
    "8250259": "Khan Academy SWE Intern Summer 2027 — already applied (do_not_retry)",
    "ae7aa71b-5ed2-4066-b173-fc0618f2ed8f": "Bobyard CV Research Engineer Intern (Ashby) — approved 2026-10-06, apply in progress",
    "R-110311": "Expedia Group SDE Intern 2027 (Workday) — approved 2026-10-06, apply in progress",
    "R-110306": "Expedia Group Mobile Engineer Intern 2027 (Workday) — approved 2026-10-06, apply in progress",
    "8827458002": "Assured Guaranty Back-End Summer 2027 (GH) — approved 2026-10-06, apply in progress",
    "8827460002": "Assured Guaranty Front-End Summer 2027 (GH) — submitted 2026-10-05",
    "7964062": "Hudson River Trading Algorithm Development (Quant Research & Trading) Internship – Summer 2027 "
               "(GH wehrtyou 7964062) — Sam applied himself 2026-10-06 (do_not_retry this role)",
}
HANDLED_ROLES = [  # (company_key prefix, title regex, note)
    ("khan academy", r"software engineer(ing)? intern", HANDLED_JOB_IDS["8250259"]),
    ("bobyard", r"computer vision|cv research|research engineer", HANDLED_JOB_IDS["ae7aa71b-5ed2-4066-b173-fc0618f2ed8f"]),
    ("expedia", r"software develop\w* engineer\w* intern|sde intern", HANDLED_JOB_IDS["R-110311"]),
    ("expedia", r"mobile engineer\w* intern", HANDLED_JOB_IDS["R-110306"]),
    ("assured guaranty", r"back[\s-]?end", HANDLED_JOB_IDS["8827458002"]),
    ("assured guaranty", r"front[\s-]?end", HANDLED_JOB_IDS["8827460002"]),
    ("hudson river trading", r"^(?!.*ph\.?d).*algorithm develop\w*.*intern", HANDLED_JOB_IDS["7964062"]),
]
IN_PROGRESS_COMPANIES = {"bobyard": "Bobyard", "expedia": "Expedia Group", "expedia group": "Expedia Group"}


def handled_note(company_k: str, title: str, url: str) -> str | None:
    jid = ats_job_id(url or "")
    if jid and jid in HANDLED_JOB_IDS:
        return HANDLED_JOB_IDS[jid]
    for ck_, pat, note in HANDLED_ROLES:
        if (company_k == ck_ or company_k.startswith(ck_ + " ")) and re.search(pat, title or "", re.I):
            return note
    return None


def load_dnr_json() -> set[str]:
    try:
        return {str(x).lower() for x in json.loads((ROOT / "do-not-retry.json").read_text()).get("companies", [])}
    except Exception:
        return set()

# Role-level exceptions to company DNR: evaluate on merits but FLAG (never auto-target silently).
# Assured Guaranty is DNR only because Front-End (GH 8827460002) was submitted 2026-10-05; Back-End is a different req.
# 2026-10-06-9am: Assured Guaranty Back-End exception removed (Sam approved it at 1am; now in HANDLED_JOB_IDS).
DNR_ROLE_EXCEPTIONS: dict[str, str] = {}


def ats_job_id(url: str) -> str:
    u = url or ""
    for pat in (r"token=(\d+)", r"/jobs/(\d+)", r"gh_jid=(\d+)", r"ashbyhq\.com/[^/]+/([0-9a-f-]{36})",
                r"lever\.co/[^/]+/([0-9a-f-]{36})", r"_(R-?\d[\w-]*|JR\d[\w-]*)$"):
        m = re.search(pat, u)
        if m:
            return m.group(1)
    return ""


def load_submitted_ids() -> set[str]:
    ids = set()
    try:
        led = json.loads((ROOT / "submitted-ledger.json").read_text())
        rows = led if isinstance(led, list) else (led.get("submitted") or led.get("entries") or list(led.values()))
        for r in rows if isinstance(rows, list) else []:
            if isinstance(r, dict):
                jid = ats_job_id(r.get("url") or "")
                if jid:
                    ids.add(jid)
                for k in r.get("dedup_keys") or r.get("keys") or []:
                    m = re.search(r":(\w[\w-]+)$", str(k))
                    if m and m.group(1).isdigit():
                        ids.add(m.group(1))
    except Exception:
        pass
    return ids


PRIOR_INTERN_RE = re.compile(r"(previous|prior|at least one|completed (a|an|one)|past) (technical |software |relevant )?internship", re.I)


# company-level hold from prior batches this week — skip all roles
HOLD_COMPANIES = {
    "disney", "the walt disney company", "walt disney",
    "visa",
    "invesco",
    "clockwork", "clockwork systems",
    "emergent", "emergent labs",
    "renesas", "renesas electronics",
    "waymo",
    "rbc", "royal bank of canada",
    "five rings", "fiverings",
    "persona",
    "decagon",
    "rundoo", "lseg", "aeg", "aeg worldwide", "occ", "the occ", "theocc",
    "chemours", "rocket lab", "rocket lab usa", "tesla",
    "microsoft",  # prior: apply_engine empty fill on careers SPA — Jobright/manual only
    "mercury",  # prior needs_user hold
    "lazard",  # 2026-09-21-2pm: Oracle HCM email skip HOLD
    "collinear", "collinear ai",  # submitted 2pm
    # 2026-09-22-1am needs_user holds (company-level)
    "bytedance",
    "headlands", "headlands tech", "headlands tech holdings",
    "zimmer biomet", "zimmer biomet holdings",
    "fidelity", "fidelity investments",
    "koch", "koch industries",
    "general motors",
    "marvell", "marvell technology",
    "vialto", "vialto partners",  # 9am needs_user preflight HOLD
    "voyager technologies",  # 1am filtered non-intern; keep held out of apply-worthy noise
    # ONE / OnePay family — NOT bare "one" (substring hold match would over-match)
    "one finance", "onepay", "oneapp",
    # 2026-09-22-2pm needs_user holds
    "optiver",
    # 2026-09-23-1am needs_user / submitted (company-level HOLD)
    "grow therapy",
    "rhoda ai", "rhoda",
    "vantor", "maxar",  # Vantor AI Engineer Intern Workday auth stuck
    "william blair",
    "tiktok",  # bytedance already held
    "vital lyfe", "vital lyfe ",
    "astranis",
    # 2026-09-23-9am needs_user
    "kla", "kla corporation",
    # 2026-09-23-2pm needs_user
    "neuberger", "neuberger berman",
    # 2026-09-24-1am needs_user HOLDs (company-level)
    "apple",
    "ziprecruiter", "zip recruiter",
    "super", "super.com",
    "clearwater", "clearwater analytics",
    "ramp",
    # 2026-09-24-2pm needs_user HOLD
    "wurl",
    # 2026-09-28-9am needs_user / failed (company-level HOLD)
    "snowflake",
    "envoy",
    "electronic arts", "ea",
    "geospatial consulting group international", "geocgi",
    "tradeweb",
    "cohen & steers", "cohen and steers", "cnssummerassociates",
    "goto", "goto group",
    "biogen",
    # 2026-09-28-9am needs_user HOLD (company-level)
    "revantage", "revantage corporate services",
    "irhythm", "irhythm technologies",
    "labcorp",
    "fox", "fox news", "fox corporation",
    # 2026-09-29-1am needs_user HOLD
    "gitai",
    # 2026-09-30-1am needs_user HOLD (company-level)
    "amca",
    "moog",
    "enova",
    "risepoint",
    "s&c electric", "s&c electric company", "sandc", "s and c electric",
    "honeywell",
    # 2026-09-30-9am needs_user HOLD (Oracle empty fill)
    "ul solutions", "ul",
    # 2026-10-01-1am needs_user HOLD (company-level) — from final_summary new_hold_companies_for_next
    "muon space",
    "itt",
    "assurant",
    "monolithic power systems", "mps", "monolithic",
    "metlife",
    "clay", "claylabs",
    # 2026-10-01-9am needs_user HOLD (Greenhouse ITAR/sponsorship)
    "varda space", "varda",
    # 2026-10-01-2pm needs_user HOLD (Greenhouse empty fill)
    "old mission", "old mission capital",

    # 2026-10-02-1am needs_user / failed (company-level HOLD) — from final_summary new_hold_companies_for_next
    "principal", "principal financial", "principal financial group",
    "glean",
    "riot games", "riot",
    "costar", "costar group",
    "pinterest",
    "attentive",
    "walleye", "walleye capital",
    "seatgeek",
    "meta",
}

GOV = re.compile(
    r"\b(department of|u\.?s\.? (army|navy|air force|space force|government|dept)|"
    r"national lab|national laboratory|nasa|darpa|nsa|cia|fbi|dod|doe |"
    r"booz allen|lockheed|northrop|raytheon|rtx\b|general dynamics|leidos|"
    r"mitre|sandia|lawrence livermore|los alamos|oak ridge|pacific northwest|"
    r"johns hopkins applied physics|apl\b|bae systems|l3harris|caci|saic|"
    r"federal |government of|city of |county of |state of |"
    r"aerospace corporation|ffrdc|mit lincoln lab|lincoln laboratory)\b",
    re.I,
)
NONCOMP_NP = re.compile(
    r"\b(red cross|united way|habitat for humanity|boys & girls|ymca|ywca)\b",
    re.I,
)
NEWGRAD = re.compile(
    r"(new[\s-]?grad|university grad|full[\s-]?time|graduating 2027|"
    r"class of 2027|2027 (new|full)|start(ing)? (in )?2027 full)",
    re.I,
)
PHD_ONLY = re.compile(r"\b(ph\.?d|phd)\b", re.I)
MS_ONLY_TITLE = re.compile(r"(master'?s only|ms[/\s-]?only|ms/phd|phd/ms|ph\.?d only|current master|\(master'?s\)|"
                           r"^master'?s\b|graduate intern|campus graduate|\bmba\b)", re.I)

# Bay Area + LA + NYC + Chicago + Remote
LOC_EXACT = {
    "sf", "nyc", "la", "remote", "remote in usa", "remote in us", "united states",
    "chicago, il", "new york, ny", "san francisco, ca", "los angeles, ca",
    "foster city, ca", "palo alto, ca", "mountain view, ca", "sunnyvale, ca",
    "menlo park, ca", "redwood city, ca", "san mateo, ca", "santa clara, ca",
    "san jose, ca", "cupertino, ca", "milpitas, ca", "fremont, ca",
    "south san francisco, ca", "oakland, ca", "berkeley, ca",
    "brooklyn, ny", "manhattan, ny", "jersey city, nj",
    "santa monica, ca", "culver city, ca", "glendale, ca", "burbank, ca",
    "irvine, ca", "pasadena, ca", "el segundo, ca", "venice, ca",
    "torrance, ca", "long beach, ca", "marina del rey, ca",
    "hoboken, nj", "weehawken, nj", "newport beach, ca",
}

LOC_SUBSTR = [
    "san francisco", "new york", "nyc", "chicago", "los angeles",
    "foster city", "palo alto", "mountain view", "sunnyvale", "menlo park",
    "redwood city", "san mateo", "santa clara", "san jose", "cupertino",
    "milpitas", "fremont", "south san francisco", "oakland", "berkeley",
    "brooklyn", "manhattan", "jersey city", "santa monica", "culver city",
    "glendale, ca", "burbank", "irvine", "pasadena", "el segundo",
    "bay area", "remote", "hybrid - san francisco", "hybrid - new york",
    "hybrid - chicago", "hybrid - los angeles",
]

# competitive enough if unknown pay
COMPETITIVE_HINT = re.compile(
    r"(tech|software|fintech|trading|quant|bank|capital|ai|ml|robot|cloud|"
    r"semiconductor|chip|finance|asset|hedge|exchange|payment|crypto|venture)",
    re.I,
)

SMALL_UNKNOWN = {
    "allen lund company", "gordon food service", "cole engineering",
}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def company_key(name: str) -> str:
    n = norm(name)
    n = re.sub(r"[^a-z0-9 &+-]+", "", n)
    for suffix in (" inc", " inc.", " llc", " ltd", " corp", " corporation", " co", " company"):
        if n.endswith(suffix):
            n = n[: -len(suffix)]
    return n.strip()


def load_skip_companies() -> set[str]:
    try:
        lines = (ROOT / "skip-companies.txt").read_text().splitlines()
    except FileNotFoundError:
        return set()
    return {norm(x) for x in lines if x.strip() and not x.strip().startswith("#")}


def load_applied_pairs() -> set[tuple[str, str]]:
    pairs = set()
    # jobright
    try:
        for r in json.loads((ROOT / "jobright-applied.json").read_text()):
            pairs.add((company_key(r.get("company", "")), norm(r.get("role", ""))))
    except Exception:
        pass
    # dedup companies as company-only skip already in skip list
    # prior hunts
    for p in [
        ROOT / "hunt-2026-09-17-1am-deduped.json",
        ROOT / "hunt-2026-09-17-9am-deduped.json",
        ROOT / "hunt-2026-09-17-2pm-deduped.json",
        ROOT / "hunt-2026-09-17-1am.json",
        ROOT / "hunt-2026-09-17-9am.json",
        ROOT / "hunt-2026-09-17-2pm.json",
        ROOT / "hunt-2026-09-18-1am-deduped.json",
        ROOT / "hunt-2026-09-18-9am-deduped.json",
        ROOT / "hunt-2026-09-18-9am.json",
        ROOT / "hunt-2026-09-18-2pm-deduped.json",
        ROOT / "hunt-2026-09-18-2pm.json",
        ROOT / "hunt-2026-09-18-1am.json",
        ROOT / "hunt-2026-09-21-1am.json",
        ROOT / "hunt-2026-09-21-1am-deduped.json",
        ROOT / "hunt-2026-09-21-9am.json",
        ROOT / "hunt-2026-09-21-9am-deduped.json",
        ROOT / "hunt-2026-09-21-2pm.json",
        ROOT / "hunt-2026-09-21-2pm-deduped.json",
        ROOT / "hunt-2026-09-22-1am.json",
        ROOT / "hunt-2026-09-22-9am.json",
        ROOT / "hunt-2026-09-22-1am-deduped.json",
        ROOT / "hunt-2026-09-22-9am-deduped.json",
        ROOT / "hunt-2026-09-22-2pm.json",
        ROOT / "hunt-2026-09-22-2pm-deduped.json",
        ROOT / "hunt-2026-09-23-1am.json",
        ROOT / "hunt-2026-09-23-1am-deduped.json",
        ROOT / "hunt-2026-09-23-9am.json",
        ROOT / "hunt-2026-09-23-9am-deduped.json",
        ARTS / "2026-09-23-1am" / "hunt-2026-09-23-1am.json",
        ARTS / "2026-09-23-1am" / "hunt-2026-09-23-1am-deduped.json",
        ARTS / "2026-09-23-9am" / "hunt-2026-09-23-9am.json",
        ARTS / "2026-09-23-9am" / "hunt-2026-09-23-9am-deduped.json",
        ROOT / "hunt-2026-09-23-2pm.json",
        ROOT / "hunt-2026-09-23-2pm-deduped.json",
        ROOT / "hunt-2026-09-24-1am.json",
        ROOT / "hunt-2026-09-24-1am-deduped.json",
        ARTS / "2026-09-23-2pm" / "hunt-2026-09-23-2pm.json",
        ARTS / "2026-09-23-2pm" / "hunt-2026-09-23-2pm-deduped.json",
        ARTS / "2026-09-24-1am" / "hunt-2026-09-24-1am.json",
        ARTS / "2026-09-24-1am" / "hunt-2026-09-24-1am-deduped.json",
        ARTS / "2026-09-24-9am" / "hunt-2026-09-24-9am.json",
        ARTS / "2026-09-24-9am" / "hunt-2026-09-24-9am-deduped.json",
        ROOT / "hunt-2026-09-24-9am.json",
        ROOT / "hunt-2026-09-24-9am-deduped.json",
        ARTS / "2026-09-22-2pm" / "hunt-2026-09-22-1am.json",
        ARTS / "2026-09-22-2pm" / "hunt-2026-09-22-9am.json",
        ARTS / "2026-09-22-2pm" / "hunt-2026-09-22-1am-deduped.json",
        ARTS / "2026-09-22-2pm" / "hunt-2026-09-22-9am-deduped.json",
        ARTS / "2026-09-22-2pm" / "hunt-2026-09-22-2pm.json",
        ARTS / "2026-09-22-2pm" / "hunt-2026-09-22-2pm-deduped.json",
        ROOT / "hunt-2026-09-24-2pm.json",
        ROOT / "hunt-2026-09-24-2pm-deduped.json",
        ROOT / "hunt-2026-09-25-1am.json",
        ROOT / "hunt-2026-09-25-1am-deduped.json",
        ROOT / "hunt-2026-09-25-9am.json",
        ROOT / "hunt-2026-09-25-9am-deduped.json",
        ROOT / "hunt-2026-09-25-2pm.json",
        ROOT / "hunt-2026-09-25-2pm-deduped.json",
        ARTS / "2026-09-24-2pm" / "hunt-2026-09-24-2pm.json",
        ARTS / "2026-09-24-2pm" / "hunt-2026-09-24-2pm-deduped.json",
        ARTS / "2026-09-25-1am" / "hunt-2026-09-25-1am.json",
        ARTS / "2026-09-25-1am" / "hunt-2026-09-25-1am-deduped.json",
        ARTS / "2026-09-25-9am" / "hunt-2026-09-25-9am.json",
        ARTS / "2026-09-25-9am" / "hunt-2026-09-25-9am-deduped.json",
        ARTS / "2026-09-25-2pm" / "hunt-2026-09-25-2pm.json",
        ARTS / "2026-09-25-2pm" / "hunt-2026-09-25-2pm-deduped.json",
        # 2026-09-28 + 2026-09-29-1am (root + ART)
        ROOT / "hunt-2026-09-28-1am.json",
        ROOT / "hunt-2026-09-28-1am-deduped.json",
        ROOT / "hunt-2026-09-28-9am.json",
        ROOT / "hunt-2026-09-28-9am-deduped.json",
        ROOT / "hunt-2026-09-28-2pm.json",
        ROOT / "hunt-2026-09-28-2pm-deduped.json",
        ROOT / "hunt-2026-09-29-1am.json",
        ROOT / "hunt-2026-09-29-1am-deduped.json",
        ARTS / "2026-09-28-1am" / "hunt-2026-09-28-1am.json",
        ARTS / "2026-09-28-1am" / "hunt-2026-09-28-1am-deduped.json",
        ARTS / "2026-09-28-9am" / "hunt-2026-09-28-9am.json",
        ARTS / "2026-09-28-9am" / "hunt-2026-09-28-9am-deduped.json",
        ARTS / "2026-09-28-2pm" / "hunt-2026-09-28-2pm.json",
        ARTS / "2026-09-28-2pm" / "hunt-2026-09-28-2pm-deduped.json",
        ARTS / "2026-09-29-1am" / "hunt-2026-09-29-1am.json",
        ARTS / "2026-09-29-1am" / "hunt-2026-09-29-1am-deduped.json",
        # 2026-09-29-9am (root + ART)
        ROOT / "hunt-2026-09-29-9am.json",
        ROOT / "hunt-2026-09-29-9am-deduped.json",
        ARTS / "2026-09-29-9am" / "hunt-2026-09-29-9am.json",
        ARTS / "2026-09-29-9am" / "hunt-2026-09-29-9am-deduped.json",
        # 2026-09-29-2pm (root + ART)
        ROOT / "hunt-2026-09-29-2pm.json",
        ROOT / "hunt-2026-09-29-2pm-deduped.json",
        ARTS / "2026-09-29-2pm" / "hunt-2026-09-29-2pm.json",
        ARTS / "2026-09-29-2pm" / "hunt-2026-09-29-2pm-deduped.json",
        # 2026-09-30-1am (root + ART)
        ROOT / "hunt-2026-09-30-1am.json",
        ROOT / "hunt-2026-09-30-1am-deduped.json",
        ARTS / "2026-09-30-1am" / "hunt-2026-09-30-1am.json",
        ARTS / "2026-09-30-1am" / "hunt-2026-09-30-1am-deduped.json",
        # 2026-09-30-9am (root + ART)
        ROOT / "hunt-2026-09-30-9am.json",
        ROOT / "hunt-2026-09-30-9am-deduped.json",
        ARTS / "2026-09-30-9am" / "hunt-2026-09-30-9am.json",
        ARTS / "2026-09-30-9am" / "hunt-2026-09-30-9am-deduped.json",
        # 2026-09-30-2pm (root + ART)
        ROOT / "hunt-2026-09-30-2pm.json",
        ROOT / "hunt-2026-09-30-2pm-deduped.json",
        ARTS / "2026-09-30-2pm" / "hunt-2026-09-30-2pm.json",
        ARTS / "2026-09-30-2pm" / "hunt-2026-09-30-2pm-deduped.json",
        # 2026-10-01-1am (root + ART)
        ROOT / "hunt-2026-10-01-1am.json",
        ROOT / "hunt-2026-10-01-1am-deduped.json",
        ARTS / "2026-10-01-1am" / "hunt-2026-10-01-1am.json",
        ARTS / "2026-10-01-1am" / "hunt-2026-10-01-1am-deduped.json",
        # 2026-10-01-9am (root + ART)
        ROOT / "hunt-2026-10-01-9am.json",
        ROOT / "hunt-2026-10-01-9am-deduped.json",
        ARTS / "2026-10-01-9am" / "hunt-2026-10-01-9am.json",
        ARTS / "2026-10-01-9am" / "hunt-2026-10-01-9am-deduped.json",
        # 2026-10-01-2pm (root + ART)
        ROOT / "hunt-2026-10-01-2pm.json",
        ROOT / "hunt-2026-10-01-2pm-deduped.json",
        ARTS / "2026-10-01-2pm" / "hunt-2026-10-01-2pm.json",
        ARTS / "2026-10-01-2pm" / "hunt-2026-10-01-2pm-deduped.json",
        # 2026-10-05-evening deduped (root + ART) — Assured Guaranty submitted
        ROOT / "hunt-2026-10-05-evening-deduped.json",
        ARTS / "2026-10-05-evening" / "hunt-2026-10-05-evening-deduped.json",
        # 2026-10-06-1am deduped (root + ART) — the 5-6 roles already sent to Sam at 1am
        ROOT / "hunt-2026-10-06-1am-deduped.json",
        ARTS / "2026-10-06-1am" / "hunt-2026-10-06-1am-deduped.json",
    ]:
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text())
        except Exception:
            continue
        for r in data if isinstance(data, list) else []:
            if r.get("skip_reason") is None or r.get("skip_reason") in (None, "", "null"):
                # only count apply-worthy from deduped; from full hunt only if skip_reason null
                pairs.add((company_key(r.get("company", "")), norm(r.get("role", ""))))
            # also always add company+role from any prior hunt entry for already_seen awareness
            # Actually: for full hunt files with skip_reason set, still skip same company+role if it was apply_worthy
            pass
    # glob every prior deduped hunt (incl. 2026-10-02 + 2026-10-03 list already sent to Sam)
    for p in sorted(list(ARTS.glob("*/hunt-*-deduped.json"))
                    + list(ROOT.glob("hunt-*-deduped.json"))):
        if SLOT in str(p):  # skip this run's own output
            continue
        try:
            for r in json.loads(p.read_text()):
                pairs.add((company_key(r.get("company", "")), norm(r.get("role", ""))))
        except Exception:
            pass
    try:
        for r in json.loads((ROOT / "submitted-ledger.json").read_text()).get("submitted", []):
            pairs.add((company_key(r.get("company", "")), norm(r.get("title", ""))))
    except Exception:
        pass
    # Explicit: all deduped targets are already applied/attempted
    for p in [
        ROOT / "hunt-2026-09-17-1am-deduped.json",
        ROOT / "hunt-2026-09-17-9am-deduped.json",
        ROOT / "hunt-2026-09-17-2pm-deduped.json",
        ROOT / "hunt-2026-09-18-1am-deduped.json",
        ROOT / "hunt-2026-09-18-9am-deduped.json",
        ROOT / "hunt-2026-09-18-2pm-deduped.json",
        ROOT / "hunt-2026-09-21-1am-deduped.json",
        ROOT / "hunt-2026-09-21-9am-deduped.json",
        ROOT / "hunt-2026-09-21-2pm-deduped.json",
        ROOT / "hunt-2026-09-22-1am-deduped.json",
        ROOT / "hunt-2026-09-22-9am-deduped.json",
        ROOT / "hunt-2026-09-22-2pm-deduped.json",
        ROOT / "hunt-2026-09-23-1am-deduped.json",
        ROOT / "hunt-2026-09-23-9am-deduped.json",
        ARTS / "2026-09-22-2pm" / "hunt-2026-09-22-1am-deduped.json",
        ARTS / "2026-09-22-2pm" / "hunt-2026-09-22-9am-deduped.json",
        ARTS / "2026-09-22-2pm" / "hunt-2026-09-22-2pm-deduped.json",
        ARTS / "2026-09-23-1am" / "hunt-2026-09-23-1am-deduped.json",
        ARTS / "2026-09-23-9am" / "hunt-2026-09-23-9am-deduped.json",
        ROOT / "hunt-2026-09-23-2pm-deduped.json",
        ROOT / "hunt-2026-09-24-1am-deduped.json",
        ARTS / "2026-09-23-2pm" / "hunt-2026-09-23-2pm-deduped.json",
        ARTS / "2026-09-24-1am" / "hunt-2026-09-24-1am-deduped.json",
        ARTS / "2026-09-24-9am" / "hunt-2026-09-24-9am-deduped.json",
        ROOT / "hunt-2026-09-24-9am-deduped.json",

        ROOT / "hunt-2026-09-24-2pm-deduped.json",
        ROOT / "hunt-2026-09-25-1am-deduped.json",
        ROOT / "hunt-2026-09-25-9am-deduped.json",
        ROOT / "hunt-2026-09-25-2pm-deduped.json",
        ARTS / "2026-09-24-2pm" / "hunt-2026-09-24-2pm-deduped.json",
        ARTS / "2026-09-25-1am" / "hunt-2026-09-25-1am-deduped.json",
        ARTS / "2026-09-25-9am" / "hunt-2026-09-25-9am-deduped.json",
        ARTS / "2026-09-25-2pm" / "hunt-2026-09-25-2pm-deduped.json",
        # 2026-09-28 + 2026-09-29-1am deduped (root + ART)
        ROOT / "hunt-2026-09-28-1am-deduped.json",
        ROOT / "hunt-2026-09-28-9am-deduped.json",
        ROOT / "hunt-2026-09-28-2pm-deduped.json",
        ROOT / "hunt-2026-09-29-1am-deduped.json",
        ARTS / "2026-09-28-1am" / "hunt-2026-09-28-1am-deduped.json",
        ARTS / "2026-09-28-9am" / "hunt-2026-09-28-9am-deduped.json",
        ARTS / "2026-09-28-2pm" / "hunt-2026-09-28-2pm-deduped.json",
        ARTS / "2026-09-29-1am" / "hunt-2026-09-29-1am-deduped.json",
        # 2026-09-29-9am deduped (root + ART)
        ROOT / "hunt-2026-09-29-9am-deduped.json",
        ARTS / "2026-09-29-9am" / "hunt-2026-09-29-9am-deduped.json",
        # 2026-09-29-2pm deduped (root + ART)
        ROOT / "hunt-2026-09-29-2pm-deduped.json",
        ARTS / "2026-09-29-2pm" / "hunt-2026-09-29-2pm-deduped.json",
        # 2026-09-30-1am deduped (root + ART)
        ROOT / "hunt-2026-09-30-1am-deduped.json",
        ARTS / "2026-09-30-1am" / "hunt-2026-09-30-1am-deduped.json",
        # 2026-09-30-9am deduped (root + ART)
        ROOT / "hunt-2026-09-30-9am-deduped.json",
        ARTS / "2026-09-30-9am" / "hunt-2026-09-30-9am-deduped.json",
        # 2026-09-30-2pm deduped (root + ART)
        ROOT / "hunt-2026-09-30-2pm-deduped.json",
        ARTS / "2026-09-30-2pm" / "hunt-2026-09-30-2pm-deduped.json",
        # 2026-10-01-1am deduped (root + ART)
        ROOT / "hunt-2026-10-01-1am-deduped.json",
        ARTS / "2026-10-01-1am" / "hunt-2026-10-01-1am-deduped.json",
        # 2026-10-01-9am deduped (root + ART)
        ROOT / "hunt-2026-10-01-9am-deduped.json",
        ARTS / "2026-10-01-9am" / "hunt-2026-10-01-9am-deduped.json",
        # 2026-10-01-2pm deduped (root + ART)
        ROOT / "hunt-2026-10-01-2pm-deduped.json",
        ARTS / "2026-10-01-2pm" / "hunt-2026-10-01-2pm-deduped.json",
        # 2026-10-05-evening deduped (root + ART)
        ROOT / "hunt-2026-10-05-evening-deduped.json",
        ARTS / "2026-10-05-evening" / "hunt-2026-10-05-evening-deduped.json",
        # 2026-10-06-1am deduped (root + ART)
        ROOT / "hunt-2026-10-06-1am-deduped.json",
        ARTS / "2026-10-06-1am" / "hunt-2026-10-06-1am-deduped.json",
    ]:
        if not p.exists():
            continue
        for r in json.loads(p.read_text()):
            pairs.add((company_key(r.get("company", "")), norm(r.get("role", ""))))
    # APPLY_LOG table rows (absent in the public repo — skip rather than crash)
    try:
        log = (ROOT / "APPLY_LOG.md").read_text()
    except FileNotFoundError:
        log = ""
    for m in re.finditer(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", log, re.M):
        c, role = m.group(1).strip(), m.group(2).strip()
        if c.lower() in ("company", "---") or c.startswith("-"):
            continue
        pairs.add((company_key(c), norm(role)))
    return pairs


def load_applied_urls() -> set[str]:
    urls = set()
    for p in [
        ROOT / "hunt-2026-09-18-1am-deduped.json",
        ROOT / "hunt-2026-09-18-9am-deduped.json",
        ROOT / "hunt-2026-09-18-2pm-deduped.json",
        ROOT / "hunt-2026-09-21-1am-deduped.json",
        ROOT / "hunt-2026-09-21-9am-deduped.json",
        ROOT / "hunt-2026-09-21-2pm-deduped.json",
        ROOT / "hunt-2026-09-22-1am.json",
        ROOT / "hunt-2026-09-22-9am.json",
        ROOT / "hunt-2026-09-22-1am-deduped.json",
        ROOT / "hunt-2026-09-22-9am-deduped.json",
        ROOT / "hunt-2026-09-22-2pm.json",
        ROOT / "hunt-2026-09-22-2pm-deduped.json",
        ROOT / "hunt-2026-09-23-1am.json",
        ROOT / "hunt-2026-09-23-1am-deduped.json",
        ROOT / "hunt-2026-09-23-9am.json",
        ROOT / "hunt-2026-09-23-9am-deduped.json",
        ARTS / "2026-09-22-2pm" / "hunt-2026-09-22-1am.json",
        ARTS / "2026-09-22-2pm" / "hunt-2026-09-22-9am.json",
        ARTS / "2026-09-22-2pm" / "hunt-2026-09-22-1am-deduped.json",
        ARTS / "2026-09-22-2pm" / "hunt-2026-09-22-9am-deduped.json",
        ARTS / "2026-09-22-2pm" / "hunt-2026-09-22-2pm.json",
        ARTS / "2026-09-22-2pm" / "hunt-2026-09-22-2pm-deduped.json",
        ARTS / "2026-09-23-1am" / "hunt-2026-09-23-1am.json",
        ARTS / "2026-09-23-1am" / "hunt-2026-09-23-1am-deduped.json",
        ARTS / "2026-09-23-9am" / "hunt-2026-09-23-9am.json",
        ARTS / "2026-09-23-9am" / "hunt-2026-09-23-9am-deduped.json",
        ROOT / "hunt-2026-09-23-2pm.json",
        ROOT / "hunt-2026-09-23-2pm-deduped.json",
        ROOT / "hunt-2026-09-24-1am.json",
        ROOT / "hunt-2026-09-24-1am-deduped.json",
        ARTS / "2026-09-23-2pm" / "hunt-2026-09-23-2pm.json",
        ARTS / "2026-09-23-2pm" / "hunt-2026-09-23-2pm-deduped.json",
        ARTS / "2026-09-24-1am" / "hunt-2026-09-24-1am.json",
        ARTS / "2026-09-24-1am" / "hunt-2026-09-24-1am-deduped.json",
        ROOT / "hunt-2026-09-24-9am.json",
        ROOT / "hunt-2026-09-24-9am-deduped.json",
        ARTS / "2026-09-24-9am" / "hunt-2026-09-24-9am.json",
        ARTS / "2026-09-24-9am" / "hunt-2026-09-24-9am-deduped.json",

        ROOT / "hunt-2026-09-24-2pm.json",
        ROOT / "hunt-2026-09-24-2pm-deduped.json",
        ROOT / "hunt-2026-09-25-1am.json",
        ROOT / "hunt-2026-09-25-1am-deduped.json",
        ROOT / "hunt-2026-09-25-9am.json",
        ROOT / "hunt-2026-09-25-9am-deduped.json",
        ROOT / "hunt-2026-09-25-2pm.json",
        ROOT / "hunt-2026-09-25-2pm-deduped.json",
        ARTS / "2026-09-24-2pm" / "hunt-2026-09-24-2pm.json",
        ARTS / "2026-09-24-2pm" / "hunt-2026-09-24-2pm-deduped.json",
        ARTS / "2026-09-25-1am" / "hunt-2026-09-25-1am.json",
        ARTS / "2026-09-25-1am" / "hunt-2026-09-25-1am-deduped.json",
        ARTS / "2026-09-25-9am" / "hunt-2026-09-25-9am.json",
        ARTS / "2026-09-25-9am" / "hunt-2026-09-25-9am-deduped.json",
        ARTS / "2026-09-25-2pm" / "hunt-2026-09-25-2pm.json",
        ARTS / "2026-09-25-2pm" / "hunt-2026-09-25-2pm-deduped.json",

        # 2026-09-28 + 2026-09-29-1am (root + ART)
        ROOT / "hunt-2026-09-28-1am.json",
        ROOT / "hunt-2026-09-28-1am-deduped.json",
        ROOT / "hunt-2026-09-28-9am.json",
        ROOT / "hunt-2026-09-28-9am-deduped.json",
        ROOT / "hunt-2026-09-28-2pm.json",
        ROOT / "hunt-2026-09-28-2pm-deduped.json",
        ROOT / "hunt-2026-09-29-1am.json",
        ROOT / "hunt-2026-09-29-1am-deduped.json",
        ARTS / "2026-09-28-1am" / "hunt-2026-09-28-1am.json",
        ARTS / "2026-09-28-1am" / "hunt-2026-09-28-1am-deduped.json",
        ARTS / "2026-09-28-9am" / "hunt-2026-09-28-9am.json",
        ARTS / "2026-09-28-9am" / "hunt-2026-09-28-9am-deduped.json",
        ARTS / "2026-09-28-2pm" / "hunt-2026-09-28-2pm.json",
        ARTS / "2026-09-28-2pm" / "hunt-2026-09-28-2pm-deduped.json",
        ARTS / "2026-09-29-1am" / "hunt-2026-09-29-1am.json",
        ARTS / "2026-09-29-1am" / "hunt-2026-09-29-1am-deduped.json",
        # 2026-09-29-9am (root + ART)
        ROOT / "hunt-2026-09-29-9am.json",
        ROOT / "hunt-2026-09-29-9am-deduped.json",
        ARTS / "2026-09-29-9am" / "hunt-2026-09-29-9am.json",
        ARTS / "2026-09-29-9am" / "hunt-2026-09-29-9am-deduped.json",
        # 2026-09-29-2pm (root + ART)
        ROOT / "hunt-2026-09-29-2pm.json",
        ROOT / "hunt-2026-09-29-2pm-deduped.json",
        ARTS / "2026-09-29-2pm" / "hunt-2026-09-29-2pm.json",
        ARTS / "2026-09-29-2pm" / "hunt-2026-09-29-2pm-deduped.json",
        # 2026-09-30-1am (root + ART)
        ROOT / "hunt-2026-09-30-1am.json",
        ROOT / "hunt-2026-09-30-1am-deduped.json",
        ARTS / "2026-09-30-1am" / "hunt-2026-09-30-1am.json",
        ARTS / "2026-09-30-1am" / "hunt-2026-09-30-1am-deduped.json",
        # 2026-09-30-9am (root + ART)
        ROOT / "hunt-2026-09-30-9am.json",
        ROOT / "hunt-2026-09-30-9am-deduped.json",
        ARTS / "2026-09-30-9am" / "hunt-2026-09-30-9am.json",
        ARTS / "2026-09-30-9am" / "hunt-2026-09-30-9am-deduped.json",
        # 2026-09-30-2pm (root + ART)
        ROOT / "hunt-2026-09-30-2pm.json",
        ROOT / "hunt-2026-09-30-2pm-deduped.json",
        ARTS / "2026-09-30-2pm" / "hunt-2026-09-30-2pm.json",
        ARTS / "2026-09-30-2pm" / "hunt-2026-09-30-2pm-deduped.json",
        # 2026-10-01-1am (root + ART)
        ROOT / "hunt-2026-10-01-1am.json",
        ROOT / "hunt-2026-10-01-1am-deduped.json",
        ARTS / "2026-10-01-1am" / "hunt-2026-10-01-1am.json",
        ARTS / "2026-10-01-1am" / "hunt-2026-10-01-1am-deduped.json",
        # 2026-10-01-9am (root + ART)
        ROOT / "hunt-2026-10-01-9am.json",
        ROOT / "hunt-2026-10-01-9am-deduped.json",
        ARTS / "2026-10-01-9am" / "hunt-2026-10-01-9am.json",
        ARTS / "2026-10-01-9am" / "hunt-2026-10-01-9am-deduped.json",
        # 2026-10-01-2pm (root + ART)
        ROOT / "hunt-2026-10-01-2pm.json",
        ROOT / "hunt-2026-10-01-2pm-deduped.json",
        ARTS / "2026-10-01-2pm" / "hunt-2026-10-01-2pm.json",
        ARTS / "2026-10-01-2pm" / "hunt-2026-10-01-2pm-deduped.json",
        # 2026-10-02-1am (root + ART)
        ROOT / "hunt-2026-10-02-1am.json",
        ROOT / "hunt-2026-10-02-1am-deduped.json",
        ARTS / "2026-10-02-1am" / "hunt-2026-10-02-1am.json",
        ARTS / "2026-10-02-1am" / "hunt-2026-10-02-1am-deduped.json",
        # 2026-10-02-9am (root + ART)
        ROOT / "hunt-2026-10-02-9am.json",
        ROOT / "hunt-2026-10-02-9am-deduped.json",
        ARTS / "2026-10-02-9am" / "hunt-2026-10-02-9am.json",
        ARTS / "2026-10-02-9am" / "hunt-2026-10-02-9am-deduped.json",
        # 2026-10-05-evening deduped (root + ART)
        ROOT / "hunt-2026-10-05-evening-deduped.json",
        ARTS / "2026-10-05-evening" / "hunt-2026-10-05-evening-deduped.json",
        # 2026-10-06-1am deduped (root + ART) + its apply_targets (sent to Sam at 1am)
        ROOT / "hunt-2026-10-06-1am-deduped.json",
        ARTS / "2026-10-06-1am" / "hunt-2026-10-06-1am-deduped.json",
        ARTS / "2026-10-06-1am" / "apply_targets.json",
        ROOT / "jobright-applied.json",
    ]:
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text())
        except Exception:
            continue
        for r in data if isinstance(data, list) else []:
            u = r.get("url") or r.get("job_url") or r.get("apply_url")
            if u:
                urls.add(u)
    return urls


def load_applied_companies() -> set[str]:
    cos = set()
    try:
        for r in json.loads((ROOT / "jobright-applied.json").read_text()):
            cos.add(company_key(r.get("company", "")))
    except Exception:
        pass
    try:
        for c in json.loads((ROOT / "dedup-companies.json").read_text()):
            cos.add(company_key(c))
    except Exception:
        pass
    return cos


NON_US_REMOTE = re.compile(r"remote\s*(in|-|,|\()?\s*(canada|uk|united kingdom|india|europe|emea|mexico|brazil|germany|"
                           r"poland|ireland|australia|philippines|latam|apac)", re.I)


def loc_ok(locs: list[str]) -> tuple[bool, str]:
    if not locs:
        return False, "no location"
    joined = ", ".join(locs)
    # 2026-10-06-9am: "Remote in Canada" etc. used to pass via the "remote" substring; Sam is US-only.
    locs = [x for x in locs if not NON_US_REMOTE.search(x or "")]
    if not locs:
        return False, joined
    # Jobright shape: "Torrance, CA (Onsite)", "San Francisco, CA +1 more (Hybrid)"
    low = [re.sub(r"\s*(\+\d+ more|\((onsite|hybrid|remote)\))", "", norm(x)).strip() for x in locs] + \
          [norm(x) for x in locs if "(remote)" in norm(x)]
    for L in low:
        if L in LOC_EXACT:
            return True, joined
        # remote variants
        if L.startswith("remote"):
            return True, joined
    blob = " | ".join(low)
    for sub in LOC_SUBSTR:
        if sub in blob:
            return True, joined
    # CA cities that are Bay/LA — word-boundary style
    for L in low:
        for city in (
            "san francisco", "palo alto", "mountain view", "sunnyvale", "menlo park",
            "redwood city", "san mateo", "santa clara", "san jose", "cupertino",
            "milpitas", "fremont", "oakland", "berkeley", "foster city",
            "south san francisco", "los angeles", "santa monica", "culver city",
            "glendale", "burbank", "irvine", "pasadena", "el segundo", "long beach",
            "chicago", "new york", "brooklyn", "jersey city", "hoboken",
        ):
            if city in L:
                return True, joined
    return False, joined


def degrees_undergrad_ok(degrees: list) -> bool:
    if not degrees:
        return True
    dnorm = [norm(d) for d in degrees]
    # if only MS/PhD/MBA and no Bachelor's/Associate's
    under = any("bachelor" in d or "associate" in d or d in ("bs", "ba", "b.s.", "b.a.") for d in dnorm)
    grad_only = all(
        ("master" in d or "phd" in d or "ph.d" in d or "mba" in d or d in ("ms", "m.s.", "phd"))
        for d in dnorm
    )
    if grad_only and not under:
        return False
    return True


def guess_ats(url: str) -> str:
    u = url.lower()
    if "myworkdayjobs" in u or "workday" in u:
        return "workday"
    if "greenhouse" in u or "boards.greenhouse" in u or "gh_jid=" in u:  # company careers ?gh_jid= = GH embed
        return "greenhouse"
    if "ashbyhq" in u or "jobs.ashby" in u:
        return "ashby"
    if "lever.co" in u:
        return "lever"
    if "smartrecruiters" in u:
        return "smartrecruiters"
    if "icims" in u:
        return "icims"
    if "taleo" in u:
        return "taleo"
    if "jobvite" in u:
        return "jobvite"
    if "successfactors" in u or "oraclecloud" in u:
        return "oracle"
    return "unknown"


def priority_for(company: str, title: str, category: str, ats: str) -> str:
    blob = f"{company} {title} {category}".lower()
    high = ats_recover.PRIORITY_FIRMS  # single source of truth (also drives priority-unresolved promotion)
    if any(h in blob for h in high) or category in ("Quant", "Software", "AI/ML/Data"):
        if ats != "workday" and category in ("Software", "AI/ML/Data", "Quant"):
            return "high"
        return "high" if any(h in blob for h in high) else "medium"
    return "medium"


def fmt_posted(ts: float) -> str:
    age_h = (NOW - ts) / 3600
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"~{age_h:.0f}h ago ({dt})"



def parse_jobright_readme(path: Path) -> list[dict]:
    """Parse jobright-ai README table rows from last ~3 days into Simplify-like dicts."""
    if not path.exists():
        return []
    import calendar
    text = path.read_text()
    rows = []
    last_company = ""
    last_company_url = ""
    month_map = {m: i for i, m in enumerate(calendar.month_abbr) if m}
    for i, m in enumerate(calendar.month_name):
        if m:
            month_map[m[:3]] = i
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        if "Company" in line and "Job Title" in line:
            continue
        if re.match(r"^\|\s*[-:]+", line):
            continue
        parts = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(parts) < 5:
            continue
        company_cell, title_cell, loc, work_model, date_posted = parts[:5]
        cm = re.search(r"\[([^\]]+)\]\(([^)]+)\)", company_cell)
        if cm:
            company = cm.group(1).strip()
            company_url = cm.group(2).strip()
            last_company, last_company_url = company, company_url
        elif company_cell.strip() in ("↳", "->", "→", ""):
            company, company_url = last_company, last_company_url
        else:
            company = re.sub(r"[*\[\]]", "", company_cell).strip()
            company_url = ""
            if company:
                last_company, last_company_url = company, company_url
        tm = re.search(r"\[([^\]]+)\]\(([^)]+)\)", title_cell)
        if not tm:
            continue
        title = tm.group(1).strip()
        url = tm.group(2).strip()
        m = re.match(r"([A-Za-z]+)\s+(\d{1,2})", date_posted.strip())
        if not m:
            continue
        mon = month_map.get(m.group(1)[:3].title())
        day = int(m.group(2))
        if not mon:
            continue
        # last ~3 days relative to this run (README has dates only; assume 12:00 UTC)
        try:
            ts = datetime(datetime.fromtimestamp(NOW, tz=timezone.utc).year, mon, day, 12, 0, tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
        if not (-24 * 3600 <= NOW - ts <= 3 * 86400):
            continue
        if not SWE_TITLE.search(title) and not re.search(
            r"(data|ai|ml|software|devops|sre|platform|quant|full.?stack)", title, re.I
        ):
            continue
        cat = "Software"
        if re.search(r"(machine learning|\bml\b|\bai\b|data)", title, re.I):
            cat = "AI/ML/Data"
        locs = [loc.strip()]
        if "remote" in norm(work_model):
            locs.append("Remote")
        rows.append({
            "source": "jobright-ai/2026-Engineer-Internship README",
            "category": cat,
            "company_name": company,
            "id": url,
            "title": title,
            "active": True,
            "date_posted": ts,
            "url": url,
            "locations": locs,
            "company_url": company_url,
            "is_visible": True,
            "degrees": [],
            "_source": "jobright-ai/2026-Engineer-Internship README",
        })
    return rows


JR_RESOLVED_PATH = ART / "jobright-ats-resolved.json"
JR_HW = re.compile(r"(electrical|hardware|firmware|embedded|asic|fpga|silicon|rf engineer|digital design|avionics|controls)", re.I)
JR_TECH_WORDS = re.compile(r"(software|swe|developer|full[\s-]?stack|front[\s-]?end|back[\s-]?end|data|\bai\b|\bml\b|machine|"
                           r"cyber|security|\bit\b|computer|quant|product|analy|scien|cloud|devops|platform|embedded|"
                           r"firmware|hardware|asic|fpga|technolog|engineering intern - (software|ai))", re.I)
JR_NONTECH = re.compile(r"(civil|structural|geotechnical|mechanical|chemical|process engineer|manufacturing|industrial|"
                        r"sales|plasma|fluids|additive|process control|building technology|power systems|^electrical intern|"
                        r"data center engineer - electrical|crop science|product & design|"
                        r"construction|safety|fire (engineering|protection)|traffic|refining|materials|nuclear|quality|"
                        r"reliability|integration & test|plasma|bioengineering|estimating|landman)", re.I)


def jobright_pay(text: str) -> tuple[str, float | None]:
    """Parse Jobright pay chip (e.g. '$30/hr - $32/hr', '$12,500/mo', '$182K/yr', '$4,500/wk') -> (note, max hourly)."""
    m = re.search(r"\$([\d,.]+)\s*([kK])?\s*/\s*(hr|mo|wk|yr)(?:\s*-\s*\$([\d,.]+)\s*([kK])?\s*/\s*(hr|mo|wk|yr))?", text or "")
    if not m:
        return "", None
    def val(num, k, unit):
        v = float(num.replace(",", "")) * (1000 if k else 1)
        return v / {"hr": 1, "wk": 40, "mo": 173.33, "yr": 2080}[unit]
    lo = val(m.group(1), m.group(2), m.group(3))
    hi = val(m.group(4), m.group(5), m.group(6)) if m.group(4) else lo
    note = m.group(0).replace(" - ", "-")
    if m.group(3) != "hr":
        note += f" (~${lo:.2f}-${hi:.2f}/hr)" if lo != hi else f" (~${hi:.2f}/hr)"
    return f"{note} [Jobright]", hi


def jobright_category(title: str, notes: str, swe_ai) -> str:
    t = title or ""
    if swe_ai:
        if JR_NONTECH.search(t) and not SWE_TITLE.search(t) and not re.search(r"(machine learning|\bai\b|software)", t, re.I):
            return "Non-tech"
        if re.search(r"quant", t, re.I):
            return "Quant"
        if re.search(r"(product manag|program manag|\bpm\b)", t, re.I):
            return "Product"
        if re.search(r"(data|machine learning|\bml\b|\bai\b|scien|analy)", t, re.I):
            return "AI/ML/Data"
        if JR_NONTECH.search(t) and not SWE_TITLE.search(t):
            return "Non-tech"
        if not JR_TECH_WORDS.search(t) and not SWE_TITLE.search(t):
            return "Non-tech"
        if JR_HW.search(t) and not SWE_TITLE.search(t):
            return "Hardware"
        return "Software"
    # swe_ai False: Jobright says not SWE/AI. Keep software-titled + hardware/EE; drop civil/mech/etc + 'non-tech'.
    if SWE_TITLE.search(t):
        return "Software"
    if JR_HW.search(t) and not JR_NONTECH.search(t):
        return "Hardware"
    return "Non-tech"


def jobright_key(company: str, title: str) -> str:
    return f"{company_key(company)}|{re.sub(r'[^a-z0-9]+', ' ', norm(title)).strip()}"


def load_jobright_discovery(path: Path) -> list[dict]:
    """Normalize jobright-discovery.json cards into Simplify-like dicts.

    Tolerates the 2026-10-06 scrape shape: {company,title,location,posted,url,ats,notes,source,swe_ai}
    with url=null (84 cards), relative ages ("8 hours ago", "Reposted 55 minutes ago"), pay chips inside
    notes, and swe_ai bool. Optional sidecar jobright-ats-resolved.json maps jobright_key -> resolved ATS URL.
    """
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except Exception:
        return []
    cards = data if isinstance(data, list) else (
        data.get("cards") or data.get("jobs") or data.get("listings") or data.get("results") or []
    )
    resolved = {}
    prev_files = sorted((f for f in ARTS.glob("*/jobright-ats-resolved.json")
                         if f.resolve() != JR_RESOLVED_PATH.resolve() and not f.parent.name.startswith("_")),
                        key=lambda f: f.stat().st_mtime)
    for prev_res in prev_files:  # prior runs' lookups as fallback (older first); this run's file wins
        try:
            resolved.update(json.loads(prev_res.read_text()))
        except Exception:
            pass
    if JR_RESOLVED_PATH.exists():
        try:
            resolved.update(json.loads(JR_RESOLVED_PATH.read_text()))
        except Exception:
            pass
    # relative ages ("8 hours ago") are relative to the scrape: use raw.txt's mtime when it sits next to the
    # discovery file (build_jobright.py may run well after the scrape), else the discovery file's own mtime.
    raw_p = path.parent / "raw.txt"
    scrape_ref = raw_p.stat().st_mtime if raw_p.exists() else path.stat().st_mtime
    out = []
    JR_STATS.clear()
    for c in cards:
        if not isinstance(c, dict):
            continue
        company = (c.get("company") or c.get("company_name") or c.get("companyName") or "").strip()
        title = (c.get("title") or c.get("role") or c.get("jobTitle") or "").strip()
        url = (c.get("url") or c.get("apply_url") or c.get("job_url") or c.get("link") or "")
        url = url.strip() if isinstance(url, str) else ""
        notes = c.get("notes") or ""
        key = jobright_key(company, title)
        res = resolved.get(key) or {}
        if res.get("url"):
            url = res["url"]
        locs = c.get("locations") or c.get("location") or []
        if isinstance(locs, str):
            locs = [locs]
        posted = c.get("date_posted") or c.get("posted_at") or c.get("posted") or c.get("age_h")
        ts = None
        reposted = False
        if isinstance(posted, (int, float)):
            ts = scrape_ref - float(posted) * 3600 if posted < 1000 else float(posted)
        elif isinstance(posted, str):
            reposted = "repost" in posted.lower()
            m = re.search(r"(\d+(?:\.\d+)?)\s*(minute|min|hour|hr|h\b|day|d\b)", posted, re.I)
            if m:
                n = float(m.group(1))
                unit = m.group(2).lower()
                mult = 1 / 60 if unit.startswith("min") else (24 if unit.startswith("d") else 1)
                ts = scrape_ref - n * mult * 3600
            elif re.search(r"just now|moments", posted, re.I):
                ts = scrape_ref
            else:
                try:
                    ts = datetime.fromisoformat(posted.replace("Z", "+00:00")).timestamp()
                except Exception:
                    ts = None
        if ts is None:
            ts = scrape_ref - 12 * 3600
        swe_ai = c.get("swe_ai")
        cat = c.get("category")
        if cat not in CATS:
            cat = jobright_category(title, notes, swe_ai) if (swe_ai is not None or not cat) else "Software"
        if not title or not company:
            JR_STATS["missing company/title"] += 1
            continue
        # Jobright scrape was run with the Internship job-type filter, so every card is an internship even when
        # the title omits "intern" (e.g. Assured Guaranty "Product Software Developer – Back-End - Summer 2027").
        if not any(k in title.lower() for k in ("intern", "co-op", "coop", "co op", "student researcher", "trainee")):
            JR_STATS["title lacks 'intern' (kept: Jobright internship filter)"] += 1
        if cat not in CATS:
            JR_STATS["non-tech (swe_ai=false / civil-mech-etc)"] += 1
        if not url:
            JR_STATS["url null (no jobright id / ATS)"] += 1
        pay_note, pay_max = jobright_pay(c.get("pay_note") or c.get("salary") or c.get("pay") or notes)
        out.append({
            "source": "jobright-discovery",
            "category": cat,
            "company_name": company,
            "id": c.get("id") or url or key,
            "title": title,
            "active": True,
            "date_posted": ts,
            "url": url,
            "locations": locs,
            "company_url": "",
            "is_visible": True,
            "degrees": c.get("degrees") or [],
            "_source": "jobright-discovery.json",
            "_pay": pay_note,
            "_pay_max": pay_max,
            "_jr_key": key,
            "_jr_ats": (c.get("ats") or ""),
            "_jr_notes": notes,
            "_jr_reposted": reposted,
            "_jr_resolved": res,
            "_swe_ai": swe_ai,
            "_is_intern": True,
        })
    return out


JR_STATS = Counter()
FLAG_EXTRA: list[str] = []
HELD_FLAG_RECS: list[dict] = []  # free-text flags (e.g. held company with interesting new role)


# ---------------------------------------------------------------------------
# Live-posting verification (added 2026-10-06-1am). Hits public ATS APIs for
# every apply-worthy candidate: confirms live, ATS, posted date, and pay.
# Pay floor: drop if the best known hourly (or annualized/2080) < $30.
# Disable with --no-verify.
# ---------------------------------------------------------------------------
import html as _html
import subprocess as _sp
import sys as _sys

PAY_FLOOR = 30.0
VERIFY_DIR = ART / "verify"


def _curl(url: str, accept_json: bool = True, timeout: int = 20) -> tuple[int, str]:
    cmd = ["curl", "-sL", "--max-time", str(timeout), "-A", "Mozilla/5.0", "-w", "\n%{http_code}"]
    if accept_json:
        cmd += ["-H", "Accept: application/json"]
    try:
        out = _sp.run(cmd + [url], capture_output=True, text=True, timeout=timeout + 5).stdout
    except Exception:
        return 0, ""
    body, _, code = out.rpartition("\n")
    try:
        return int(code), body
    except ValueError:
        return 0, out


def _strip_html(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", _html.unescape(_html.unescape(t or ""))))


PAY_CTX = re.compile(r"(hour|/hr|p/h|hourly|salary|compensation|pay|rate|range|wage|stipend)", re.I)


def extract_pay(text: str) -> tuple[str, float | None]:
    """Return (pay_note, max_hourly_equiv). Hourly if <$300, annual if $10k-$500k (÷2080)."""
    hourly, annual = [], []
    for m in re.finditer(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?\s*([kK])?", text):
        ctx = text[max(0, m.start() - 140): m.end() + 60]
        if not PAY_CTX.search(ctx):
            continue
        v = float(m.group(1).replace(",", "") + ("." + m.group(2) if m.group(2) else ""))
        if m.group(3):
            v *= 1000
        if 7 <= v < 300:
            hourly.append(v)
        elif 10000 <= v <= 500000:
            annual.append(v)
    if hourly:
        lo, hi = min(hourly), max(hourly)
        note = f"${lo:g}/hr" if lo == hi else f"${lo:g}-${hi:g}/hr"
        return note, hi
    if annual:
        lo, hi = min(annual), max(annual)
        note = f"${lo:,.0f}-${hi:,.0f}/yr (~${lo/2080:.2f}-${hi/2080:.2f}/hr)"
        return note, hi / 2080
    return "unknown", None


def _edu_note(text: str) -> str:
    hits = re.findall(r"[^.;]{0,120}(?:graduat\w*|class of|rising (?:junior|senior)|pursuing a)[^.;]{0,120}", text, re.I)
    return " | ".join(h.strip()[:220] for h in hits[:2])


def _ats_age_h(posted) -> float | None:
    """Hours since the ATS says the req was posted. Workday buckets: Today≈12h, Yesterday≈36h, N Days≈24N."""
    if not posted:
        return None
    s_ = str(posted)
    if re.search(r"posted today", s_, re.I):
        return 12.0
    if re.search(r"posted yesterday", s_, re.I):
        return 36.0
    m = re.search(r"posted (\d+)\+? days? ago", s_, re.I)
    if m:
        return 24.0 * int(m.group(1))
    try:
        return (NOW - datetime.fromisoformat(s_.replace("Z", "+00:00")).timestamp()) / 3600
    except Exception:
        return None


def verify_posting(rec: dict) -> dict:
    url = rec["url"]
    ats = rec["ats"]
    v = {"live": None, "ats_confirmed": None, "posted_ats": None, "pay_note": "unknown",
         "max_hourly": None, "edu_note": "", "api": None, "http": None, "title_ats": None}
    text = ""
    try:
        if ats == "greenhouse":
            m = re.search(r"greenhouse\.io/(?:embed/job_app\?for=)?([^/?#]+)/jobs/(\d+)", url) or \
                re.search(r"for=([^&]+).*token=(\d+)", url)
            if m:
                api = f"https://boards-api.greenhouse.io/v1/boards/{m.group(1)}/jobs/{m.group(2)}?pay_transparency=true"
                code, body = _curl(api)
                v.update(api=api, http=code)
                if code == 200:
                    d = json.loads(body)
                    v.update(live=True, ats_confirmed="greenhouse", title_ats=d.get("title"),
                             posted_ats=d.get("first_published") or d.get("updated_at"))
                    text = _strip_html(d.get("content", ""))
                    for pr in d.get("pay_input_ranges") or []:
                        text += f" pay range ${pr.get('min_cents', 0)/100:.2f} - ${pr.get('max_cents', 0)/100:.2f} "
                else:
                    v["live"] = False
        elif ats == "ashby":
            m = re.search(r"ashbyhq\.com/([^/?#]+)/([0-9a-f-]{36})", url)
            if m:
                api = f"https://api.ashbyhq.com/posting-api/job-board/{m.group(1)}?includeCompensation=true"
                code, body = _curl(api)
                v.update(api=api, http=code)
                if code == 200:
                    jobs = json.loads(body).get("jobs", [])
                    j = next((j for j in jobs if j.get("id") == m.group(2)), None)
                    v["live"] = j is not None
                    if j:
                        v.update(ats_confirmed="ashby", title_ats=j.get("title"), posted_ats=j.get("publishedAt"))
                        text = (j.get("descriptionPlain") or "") + " " + str(
                            (j.get("compensation") or {}).get("compensationTierSummary") or "")
        elif ats == "lever":
            m = re.search(r"lever\.co/([^/?#]+)/([0-9a-f-]{36})", url)
            if m:
                api = f"https://api.lever.co/v0/postings/{m.group(1)}/{m.group(2)}"
                code, body = _curl(api)
                v.update(api=api, http=code)
                if code == 200:
                    d = json.loads(body)
                    v.update(live=True, ats_confirmed="lever", title_ats=d.get("text"),
                             posted_ats=datetime.fromtimestamp(d.get("createdAt", 0) / 1000, tz=timezone.utc).isoformat())
                    text = (d.get("descriptionPlain") or "") + " " + " ".join(
                        _strip_html(l.get("content", "")) for l in d.get("lists", [])) + " " + (d.get("additionalPlain") or "")
                    sr = d.get("salaryRange") or {}
                    if sr:
                        text += f" salary range ${sr.get('min')} - ${sr.get('max')} {sr.get('interval')}"
                else:
                    v["live"] = False
        elif ats == "workday":
            m = re.match(r"https://([^.]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Za-z]{2}/)?([^/]+)/(job/[^?#]+)", url)
            if m:
                tenant, wd, site, path = m.groups()
                api = f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/{path}"
                code, body = _curl(api)
                v.update(api=api, http=code)
                if code == 200:
                    d = json.loads(body).get("jobPostingInfo", {})
                    v.update(live=bool(d) and d.get("canApply", True) is not False, ats_confirmed="workday",
                             title_ats=d.get("title"),
                             posted_ats=f"{d.get('postedOn')} (startDate {d.get('startDate')})")
                    text = _strip_html(d.get("jobDescription", ""))
                else:
                    v["live"] = False
        if v["live"] is None:  # fallback plain HTTP
            code, body = _curl(url, accept_json=False)
            v.update(http=code, live=(200 <= code < 400) if code else None)
            text = _strip_html(body)[:200000]
    except Exception as e:  # never crash the hunt on verification
        v["error"] = str(e)[:200]
    v["ats_age_h"] = _ats_age_h(v.get("posted_ats"))
    if text:
        v["pay_note"], v["max_hourly"] = extract_pay(text)
        v["edu_note"] = _edu_note(text)
        if CLASS_TOO_YOUNG.search(text) and not re.search(r"2028", text):
            v["class_too_young"] = True
        pm = PRIOR_INTERN_RE.search(text)
        if pm:
            v["prior_internship_note"] = text[max(0, pm.start() - 80): pm.end() + 80].strip()
        if re.search(r"(currently pursuing|enrolled in) (a )?(master|ph\.?d|graduate)", text, re.I) and not re.search(
                r"bachelor|\bBS\b|\bB\.S\.|undergrad", text, re.I):
            v["grad_only"] = True
    return v


def apply_verification(apply_worthy: list[dict], skip_breakdown: Counter) -> tuple[list[dict], list[dict]]:
    VERIFY_DIR.mkdir(exist_ok=True)
    kept, dropped = [], []
    for rec in apply_worthy:
        if "jobright.ai" in (rec.get("url") or "") or OFFLINE:
            # Jobright pages are a JS app: a plain GET proves nothing and pay-scrapes junk. Keep Jobright's chip.
            v = {"live": None, "ats_confirmed": None, "posted_ats": None, "pay_note": "unknown", "max_hourly": None,
                 "edu_note": "", "api": None, "http": None, "title_ats": None, "ats_age_h": None,
                 "note": "not verified (Jobright-only link)" if not OFFLINE else "not verified (HUNT_OFFLINE)"}
        else:
            v = verify_posting(rec)
        rec["verify"] = v
        if v.get("pay_note") and v["pay_note"] != "unknown":
            rec["pay_note"] = v["pay_note"]
        elif rec.get("_pay_max") is not None:
            v["max_hourly"] = rec["_pay_max"]  # Jobright chip as fallback for pay floor
        reason = None
        if v.get("live") is False:
            reason = f"posting not live (HTTP {v.get('http')})"
        elif v.get("max_hourly") is not None and v["max_hourly"] < PAY_FLOOR:
            reason = f"pay below ${PAY_FLOOR:.0f}/hr floor ({v['pay_note']})"
        elif v.get("ats_age_h") is not None and v["ats_age_h"] > SOFT_H:
            reason = (f"stale at ATS (posted ~{v['ats_age_h']:.0f}h ago per ATS: {v.get('posted_ats')}; "
                      f"Jobright/Simplify age was ~{rec['age_h']:.0f}h)")
        elif v.get("class_too_young"):
            reason = "class-of-2029/2030-only (posting text)"
        elif v.get("grad_only"):
            reason = "MS/PhD or PhD-targeted (posting text)"
        hit = ats_recover.is_priority_firm(rec["company"])
        if reason and hit and reason.startswith("stale at ATS") and rec["age_h"] <= SOFT_H \
                and "jobright" in (rec.get("source") or "").lower():
            # PRIORITY firm freshly (re)surfaced on Jobright/Simplify but ATS first_published is old (HRT reposts
            # keep the July gh_jid): keep it for Sam with a caveat instead of dropping silently.
            rec["caveats"].append(reason + " — kept because priority firm; likely a repost/refresh, confirm it is still open")
            rec["flag"] = rec.get("flag") or (f"PRIORITY FIRM ({hit}) — {reason}; needs Sam's explicit approval")
            reason = None
        if reason and rec.get("flag") and reason.startswith("stale at ATS"):
            # flagged role-exception: surface to Sam with the caveat instead of auto-dropping
            rec["caveats"].append(reason + " — same first_published day as the Front-End req Sam already approved/submitted")
            reason = None
        if reason:
            rec["skip_reason"] = reason
            skip_breakdown[reason.split(" (")[0]] += 1
            dropped.append(rec)
        else:
            kept.append(rec)
    (VERIFY_DIR / "verification.json").write_text(json.dumps(
        [{"company": r["company"], "role": r["role"], "url": r["url"], "skip_reason": r.get("skip_reason"),
          **r["verify"]} for r in apply_worthy], indent=2) + "\n")
    return kept, dropped


GHJID_CACHE: dict[str, str | None] = {}


def resolve_ghjid(url: str, company: str = "") -> str | None:
    """Company careers page with ?gh_jid=N (Greenhouse embed) -> canonical job-boards.greenhouse.io URL, if the
    page names its Greenhouse board (or ats_recover.KNOWN_CAREERS knows it, e.g. HRT=wehrtyou) and boards-api
    confirms the job id. Added 2026-10-06-9am."""
    m = re.search(r"gh_jid=(\d+)", url or "")
    if not m or "greenhouse.io" in url or OFFLINE:
        return None
    if url in GHJID_CACHE:
        return GHJID_CACHE[url]
    jid, out = m.group(1), None
    known = ats_recover.KNOWN_CAREERS.get(company_key(company), {}).get("gh_boards", [])
    body = ""
    if not known:
        code, body = _curl(url, accept_json=False)
    slugs = list(dict.fromkeys(known + re.findall(r"greenhouse\.io/(?:embed/job_board(?:/js)?\?for=|embed/job_app\?for=)([A-Za-z0-9_-]+)", body or "")))
    for slug in slugs:
        c2, _ = _curl(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{jid}")
        if c2 == 200:
            out = f"https://job-boards.greenhouse.io/{slug}/jobs/{jid}"
            break
    GHJID_CACHE[url] = out
    return out


RECOVERY_NOTES: list[str] = []


def recover_jobright_cards(jr_cards: list[dict], simplify: list[dict]) -> None:
    """Hunt-time ATS recovery for Jobright cards still on a jobright.ai-only link (build_jobright.py normally did this
    already). Simplify any-age match is offline; careers/board lookup only for priority firms and only with network.
    Successes are merged into ART/jobright-ats-resolved.json with a note."""
    simp = [x for x in simplify if "Simplify" in (x.get("_source") or "")]
    new = {}
    for x in jr_cards:
        u = x.get("url") or ""
        if u and "jobright.ai" not in u:
            continue
        if x.get("category") not in CATS:
            continue
        prio = ats_recover.is_priority_firm(x["company_name"])
        net = bool(prio) and (ats_recover.FIXTURE or not OFFLINE)
        r, why = ats_recover.recover(x["company_name"], x["title"], simp, network=net)
        if r:
            r = dict(r, note=r["note"] + f" [hunt-time recovery {SLOT}]")
            x["url"], x["_jr_resolved"] = r["url"], r
            new[x["_jr_key"]] = r
            RECOVERY_NOTES.append(f"RESOLVED **{x['company_name']}** — {x['title']} → {r['url']} ({r['note']})")
        elif prio:
            RECOVERY_NOTES.append(f"unresolved priority card **{x['company_name']}** — {x['title']}: " + "; ".join(why))
    if new:
        cur = json.loads(JR_RESOLVED_PATH.read_text()) if JR_RESOLVED_PATH.exists() else {}
        for k, v in new.items():
            cur.setdefault(k, v)
        JR_RESOLVED_PATH.write_text(json.dumps(cur, indent=1))


PRIORITY_UNRESOLVED_FLAG = ("PRIORITY FIRM ({hit}) — ATS {why}; Jobright link kept: {url}. Not auto-appliable by "
                            "apply-engine: needs Sam's explicit approval (apply via Jobright/company site).")


def main():
    skip_cos = load_skip_companies()
    applied_pairs = load_applied_pairs()
    applied_urls = load_applied_urls()
    applied_cos = load_applied_companies()
    submitted_ids = load_submitted_ids()
    dnr_all = set(DO_NOT_RETRY) | load_dnr_json()
    dnr = {company_key(x) for x in dnr_all} | {norm(x) for x in dnr_all}
    hold = {company_key(x) for x in HOLD_COMPANIES} | {norm(x) for x in HOLD_COMPANIES}

    listings = []
    source_notes = []
    for fname, src in [
        ("simplify-summer2027.json", "SimplifyJobs/Summer2027-Internships listings.json"),
        ("simplify-newgrad.json", "SimplifyJobs/New-Grad-Positions listings.json"),
    ]:
        path = ART / fname
        if not path.exists():
            source_notes.append(f"- {src}: **MISSING**")
            continue
        data = json.loads(path.read_text())
        for x in data:
            x = dict(x)
            x["_source"] = src
            listings.append(x)
        source_notes.append(f"- {src.split()[0]}: **OK** ({len(data)} listings; path `.github/scripts/listings.json`)")

    jr_path = ART / "jobright-discovery.json"
    jr_status = "missing"
    if jr_path.exists():
        jr_cards = load_jobright_discovery(jr_path)
        listings.extend(jr_cards)
        jr_status = f"loaded ({len(jr_cards)} cards)"
        recover_jobright_cards(jr_cards, listings)
        n_raw_cards = len(json.loads(jr_path.read_text()))
        source_notes.append(
            f"- Jobright discovery JSON: **OK** — {n_raw_cards} cards in file → {len(jr_cards)} internship cards loaded "
            f"({', '.join(f'{k}: {v}' for k, v in JR_STATS.items())}); "
            f"{sum(1 for c in jr_cards if c['category'] in CATS)} tech-category"
        )
    else:
        source_notes.append("- Jobright discovery JSON: **PENDING / missing** at run time")

    readme_rows = parse_jobright_readme(ART / "jobright-ai-readme.md")
    listings.extend(readme_rows)
    source_notes.append(
        f"- jobright-ai/2026-Engineer-Internship README: **OK** — {len(readme_rows)} SWE-adjacent rows (last ~3 days)"
    )

    raw = []
    seen_cr = {}
    skip_breakdown = Counter()
    age_skipped = []
    apply_worthy = []
    near_misses = []  # wrong ATS but otherwise apply-worthy

    for x in listings:
        if not x.get("active"):
            continue
        if x.get("is_visible") is False:
            continue
        cat = x.get("category") or ""
        if cat not in CATS:
            continue
        title = x.get("title") or ""
        tlow = title.lower()
        # internship-ish
        is_intern = any(k in tlow for k in ("intern", "co-op", "coop", "co op")) or bool(x.get("_is_intern"))
        is_newgrad_src = "New-Grad" in x.get("_source", "")
        if is_newgrad_src:
            # almost all filtered — only keep if explicitly internship
            if not is_intern:
                skip_breakdown["new-grad / 2027 start (Sam graduates May 2028)"] += 1
                continue
        if not is_intern:
            continue

        if CLASS_TOO_YOUNG.search(title):
            # only skip if clearly class-of-2029/2030 exclusive
            skip_breakdown["class-of-2029/2030-only"] = skip_breakdown.get("class-of-2029/2030-only", 0) + 1
            continue

        ts = float(x.get("date_posted") or 0)
        if not ts:
            continue
        age_h = (NOW - ts) / 3600
        if age_h > HARD_H:
            continue

        company = (x.get("company_name") or "").strip()
        ck = company_key(company)
        rk = norm(title)
        url = x.get("url") or ""
        locs = x.get("locations") or []
        degrees = x.get("degrees") or []

        ok_loc, loc_str = loc_ok(locs)
        rec = {
            "company": company,
            "role": title,
            "url": url,
            "location": loc_str,
            "posted": fmt_posted(ts),
            "source": x.get("_source"),
            "pay_note": x.get("_pay") or "unknown",
            "priority": "medium",
            "skip_reason": None,
            "age_h": round(age_h, 1),
            "category": cat,
            "ats": guess_ats(url) if url else "unresolved",
            "_pay_max": x.get("_pay_max"),
            "caveats": [],
            "jr_key": x.get("_jr_key"),
        }
        if url and "jobright.ai/jobs/info" in url:
            rec["ats"] = "unresolved"
        if x.get("_jr_reposted"):
            rec["caveats"].append("Jobright says 'Reposted' — original req may be older")
        if (x.get("_jr_resolved") or {}).get("note"):
            rec["caveats"].append("ATS resolved off-Jobright: " + x["_jr_resolved"]["note"])
        dk = (ck, re.sub(r"[^a-z0-9]+", " ", rk).strip())

        # hard filters — only count duplicates among location-eligible postings
        # (otherwise Indianapolis can shadow Chicago for same company+role)
        if not ok_loc:
            rec["skip_reason"] = f"location not in remote/SF/Chicago/NYC/LA: {loc_str}"
            skip_breakdown[rec["skip_reason"]] += 1
            raw.append(rec)
            continue

        if dk in seen_cr:
            rec["skip_reason"] = "duplicate posting (same company+role)"
            rec["_dup_of"] = seen_cr[dk]
            skip_breakdown[rec["skip_reason"]] += 1
            raw.append(rec)
            continue
        seen_cr[dk] = rec

        if GOV.search(company) or GOV.search(title) or GOV.search(loc_str):
            # also company list defense contractors
            rec["skip_reason"] = "government / defense contractor"
            skip_breakdown[rec["skip_reason"]] += 1
            raw.append(rec)
            continue
        # extra defense names
        defense_names = {
            "rtx", "northrop grumman", "lockheed martin", "general dynamics",
            "general dynamics mission systems", "booz allen", "booz allen hamilton",
            "leidos", "l3harris", "bae systems", "caci", "saic", "mitre",
            "johns hopkins applied physics laboratory", "pacific northwest national laboratory",
            "sandia national laboratories", "analytical mechanics associates",
            "aerospace", "aerospace corporation", "the aerospace corporation",
        }
        if ck in defense_names or any(ck.startswith(d) for d in defense_names):
            rec["skip_reason"] = "government / defense contractor"
            skip_breakdown[rec["skip_reason"]] += 1
            raw.append(rec)
            continue

        if NONCOMP_NP.search(company):
            rec["skip_reason"] = "non-competitive nonprofit"
            skip_breakdown[rec["skip_reason"]] += 1
            raw.append(rec)
            continue

        if NEWGRAD.search(title) and "intern" not in tlow:
            rec["skip_reason"] = "new-grad / 2027 start (Sam graduates May 2028)"
            skip_breakdown[rec["skip_reason"]] += 1
            raw.append(rec)
            continue
        if is_newgrad_src and "intern" not in tlow:
            rec["skip_reason"] = "new-grad / 2027 start (Sam graduates May 2028)"
            skip_breakdown[rec["skip_reason"]] += 1
            raw.append(rec)
            continue

        if not degrees_undergrad_ok(degrees) or (PHD_ONLY.search(title) and "intern" in tlow and "bachelor" not in " ".join(degrees).lower() and degrees and not any("bachelor" in norm(d) for d in degrees)):
            # PhD in title with degrees only PhD
            if (degrees and not degrees_undergrad_ok(degrees)) or MS_ONLY_TITLE.search(title) or (
                PHD_ONLY.search(title) and degrees and not any("bachelor" in norm(d) for d in degrees)
            ):
                rec["skip_reason"] = "MS/PhD or PhD-targeted (Sam is undergrad BS)"
                skip_breakdown[rec["skip_reason"]] += 1
                raw.append(rec)
                continue
        if (degrees and not degrees_undergrad_ok(degrees)) or (
                MS_ONLY_TITLE.search(title) and not re.search(r"\b(bs|ba|bachelor|undergrad)", title, re.I)):
            rec["skip_reason"] = "MS/PhD or PhD-targeted (Sam is undergrad BS)"
            skip_breakdown[rec["skip_reason"]] += 1
            raw.append(rec)
            continue
        if re.search(r"\b(ph\.?d|phd)\b.*intern|intern.*\b(ph\.?d|phd)\b", title, re.I) and (
            not degrees or not any("bachelor" in norm(d) for d in degrees)
        ):
            # if title says PhD Intern, skip for undergrad
            if re.search(r"ph\.?d\s+intern|intern\s+.*ph\.?d|phd\s+intern", title, re.I):
                rec["skip_reason"] = "MS/PhD or PhD-targeted (Sam is undergrad BS)"
                skip_breakdown[rec["skip_reason"]] += 1
                raw.append(rec)
                continue

        hn = handled_note(ck, title, url)
        if hn:
            rec["skip_reason"] = f"already handled 2026-10-06 ({hn})"
            skip_breakdown["handled 2026-10-06 (sent at 1am / applied / in progress)"] += 1
            raw.append(rec)
            continue
        for ipk, ipname in IN_PROGRESS_COMPANIES.items():
            if ck == ipk or ck.startswith(ipk + " "):
                rec["caveats"].append(f"{ipname}: Sam already has an approved/in-progress application for a different role")
                break

        jid = ats_job_id(url)
        if jid and jid in submitted_ids:
            rec["skip_reason"] = "already submitted (submitted-ledger job id)"
            skip_breakdown["APPLY"] += 1
            raw.append(rec)
            continue
        if jid in DNR_ROLE_EXCEPTIONS:
            rec["flag"] = DNR_ROLE_EXCEPTIONS[jid]
            rec["caveats"].append(DNR_ROLE_EXCEPTIONS[jid])
        elif ck in dnr or any(ck == d or ck.startswith(d + " ") for d in dnr):
            rec["skip_reason"] = "do_not_retry"
            skip_breakdown[rec["skip_reason"]] += 1
            raw.append(rec)
            continue

        # Exact match always; substring only for hold tokens length>=4 (avoids "gm"→Two Sigma/Figma)
        held_hit = ck in hold or any(
            (h == ck) or (len(h) >= 4 and h in ck) for h in hold
        )
        if held_hit:
            rec["skip_reason"] = "prior needs_user / held company+role (Disney/Visa/Invesco/Clockwork/Emergent/Renesas/Waymo/etc)"
            if rec["ats"] in ALLOWED_ATS and "jobright-discovery" in (rec["source"] or "") and age_h <= SOFT_H \
                    and not (rec.get("_pay_max") is not None and rec["_pay_max"] < PAY_FLOOR) \
                    and not re.search(r"(ms/phd|phd|master)", tlow):
                HELD_FLAG_RECS.append(rec)
                FLAG_EXTRA.append(f"HELD company, new ATS-resolved role (skipped per hold; lift hold to consider): "
                                  f"**{company}** — {title} — {loc_str} — ats={rec['ats']} — pay={rec['pay_note']} — "
                                  f"{rec['posted']} — {url}")
            skip_breakdown["prior needs_user / held"] += 1
            raw.append(rec)
            continue

        if ck in skip_cos or norm(company) in skip_cos:
            rec["skip_reason"] = "skip-companies.txt"
            skip_breakdown[rec["skip_reason"]] += 1
            raw.append(rec)
            continue

        # applied company from jobright — company-level skip for same company (aggressive like prior)
        if ck in applied_cos:
            # only skip if role also seen OR company fully in skip — actually skip-companies already has most
            # For jobright: skip same company+role; company-only is via skip-companies/dedup
            pass

        if url in applied_urls or (not rec.get("flag") and (ck, rk) in applied_pairs):
            rec["skip_reason"] = "APPLY / jobright / prior hunt same company+role"
            skip_breakdown["APPLY"] += 1
            raw.append(rec)
            continue

        # fuzzy role match against applied pairs for same company
        for ac, ar in ([] if rec.get("flag") else applied_pairs):  # flagged role-exceptions: exact job id already checked
            if ac == ck and (ar in rk or rk in ar or ar[:20] == rk[:20]):
                rec["skip_reason"] = "APPLY / jobright / prior hunt same company+role"
                skip_breakdown["APPLY"] += 1
                break
        if rec["skip_reason"]:
            raw.append(rec)
            continue

        # weak company competitiveness for unknown pay
        if ck in SMALL_UNKNOWN and not COMPETITIVE_HINT.search(company + " " + title):
            rec["skip_reason"] = "not competitive mid-size+/finance/tech (unknown pay)"
            skip_breakdown[rec["skip_reason"]] += 1
            raw.append(rec)
            continue

        # MBA-only
        if re.search(r"\bmba\b", title, re.I) and "intern" in tlow:
            if degrees and all("mba" in norm(d) or "master" in norm(d) for d in degrees) and not any("bachelor" in norm(d) for d in degrees):
                rec["skip_reason"] = "MS/PhD or PhD-targeted (Sam is undergrad BS)"
                skip_breakdown[rec["skip_reason"]] += 1
                raw.append(rec)
                continue
            if re.search(r"\bmba\s+intern|intern.*\bmba\b", title, re.I):
                rec["skip_reason"] = "MS/PhD or PhD-targeted (Sam is undergrad BS)"
                skip_breakdown[rec["skip_reason"]] += 1
                raw.append(rec)
                continue

        if rec.get("_pay_max") is not None and rec["_pay_max"] < PAY_FLOOR:
            rec["skip_reason"] = f"pay below $30/hr floor ({rec['pay_note']})"
            skip_breakdown["pay below $30/hr floor"] += 1
            raw.append(rec)
            continue

        rec["priority"] = priority_for(company, title, cat, rec["ats"])

        # age soft/hard for otherwise-worthy
        if age_h > SOFT_H:
            rec["skip_reason"] = f"age_skipped ({age_h:.0f}h >{SOFT_H:.0f}h ≤{HARD_H:.0f}h)"
            age_skipped.append(rec)
            skip_breakdown["age_skipped"] += 1
            raw.append(rec)
            continue

        # gh_jid company-site pages are Greenhouse embeds: resolve to the board URL so verification can run
        if rec["ats"] in ("unknown", "greenhouse") and "gh_jid=" in url and "greenhouse.io" not in url:
            gh = (x.get("_jr_resolved") or {}).get("board_url") or (
                resolve_ghjid(url, company) if "--no-verify" not in _sys.argv else None)
            if gh:
                rec["caveats"].append(f"Greenhouse embed on company site ({url}); resolved to board URL")
                rec["url"], rec["ats"], rec["company_site_url"] = gh, "greenhouse", url

        # ATS gate: only Greenhouse/Lever/Ashby/Workday are final apply-worthy
        if rec["ats"] not in ALLOWED_ATS:
            hit = ats_recover.is_priority_firm(company)
            if hit:
                # PRIORITY firm: never bury under near-misses — surface on the approval list with a flag.
                why = ("unresolved (Jobright-only link; Simplify/careers/board recovery found no matching req)"
                       if rec["ats"] == "unresolved" else f"is '{rec['ats']}' (not Greenhouse/Lever/Ashby/Workday)")
                rec["flag"] = PRIORITY_UNRESOLVED_FLAG.format(hit=hit, why=why, url=url or "(none)")
                rec["priority_unresolved"] = True
                rec["priority"] = "high"
                rec["caveats"].append(rec["flag"])
                skip_breakdown["KEEP priority firm with unresolved/unsupported ATS (flagged)"] += 1
                apply_worthy.append(rec)
                raw.append(rec)
                continue
            rec["skip_reason"] = (f"near_miss_unresolved_ats (Jobright-only link)" if rec["ats"] == "unresolved"
                                  else f"near_miss_wrong_ats ({rec['ats']})")
            near_misses.append(rec)
            skip_breakdown["near_miss_wrong_ats"] += 1
            raw.append(rec)
            continue

        # apply worthy
        apply_worthy.append(rec)
        raw.append(rec)

    for r in raw:
        if r.get("_dup_of") is not None:
            f = r["_dup_of"]
            r["skip_reason"] = (f"duplicate posting (same company+role; first copy from "
                                f"{(f.get('source') or '').split()[0]} → {f.get('skip_reason') or 'KEEP'})")

    verify_dropped = []
    if "--no-verify" not in _sys.argv:
        apply_worthy, verify_dropped = apply_verification(apply_worthy, skip_breakdown)
        for i, hr in enumerate(HELD_FLAG_RECS):  # live-check held flags too, so Sam sees real ATS age
            hv = verify_posting(hr)
            FLAG_EXTRA[i] += (f" — live={hv.get('live')} — ATS posted {hv.get('posted_ats')}"
                              + (f" (STALE: ~{hv['ats_age_h']/24:.0f} days old at ATS)" if (hv.get('ats_age_h') or 0) > SOFT_H else ""))

    # prefer non-Workday when ranking; cap ~12
    def sort_key(r):
        pr = {"high": 0, "medium": 1, "low": 2}.get(r["priority"], 9)
        ats_pen = 0 if r["ats"] != "workday" else 1
        return (pr, ats_pen, r["age_h"])

    apply_worthy.sort(key=sort_key)
    # dedupe by company keeping best priority (max 2 roles per company)
    selected = []
    per_co = Counter()
    for r in apply_worthy:
        ck = company_key(r["company"])
        if per_co[ck] >= 2:
            r["skip_reason"] = "cap: already selected 2 roles for company"
            skip_breakdown[r["skip_reason"]] += 1
            continue
        per_co[ck] += 1
        selected.append(r)
        if len(selected) >= 12:
            break

    sel_ids = {id(r) for r in selected}
    for r in apply_worthy:
        if id(r) not in sel_ids and not r.get("skip_reason"):
            r["skip_reason"] = "cap: >12 apply-worthy this batch"
    for r in selected:
        r["skip_reason"] = None
    apply_worthy_final = selected
    hunt_path = (ART if NO_ROOT else ROOT) / f"hunt-{SLOT}.json"
    dedup_path = (ART if NO_ROOT else ROOT) / f"hunt-{SLOT}-deduped.json"

    out_raw = []
    for r in raw:
        o = {
            "company": r["company"],
            "role": r["role"],
            "url": r["url"],
            "location": r["location"],
            "posted": r["posted"],
            "source": r["source"],
            "pay_note": r["pay_note"],
            "priority": r["priority"],
            "skip_reason": r.get("skip_reason"),
            "ats": r.get("ats"),
            "caveats": r.get("caveats") or [],
        }
        out_raw.append(o)

    out_deduped = [
        {
            "company": r["company"],
            "role": r["role"],
            "url": r["url"],
            "location": r["location"],
            "posted": r["posted"],
            "source": r["source"],
            "pay_note": r["pay_note"],
            "priority": r["priority"],
            "skip_reason": None,
            "ats": r.get("ats"),
            "age_h": r.get("age_h"),
            "verified_live": (r.get("verify") or {}).get("live"),
            "posted_ats": (r.get("verify") or {}).get("posted_ats"),
            "edu_note": (r.get("verify") or {}).get("edu_note"),
            "caveats": r.get("caveats") or [],
            "flag": r.get("flag"),
        }
        for r in apply_worthy_final
    ]

    hunt_path.write_text(json.dumps(out_raw, indent=2) + "\n")
    dedup_path.write_text(json.dumps(out_deduped, indent=2) + "\n")
    (ART / f"hunt-{SLOT}.json").write_text(hunt_path.read_text())
    (ART / f"hunt-{SLOT}-deduped.json").write_text(dedup_path.read_text())

    targets = []
    for r in apply_worthy_final:
        label = f"{r['company'].split('(')[0].strip()}"
        short_role = r["role"][:60]
        name = f"{label} {short_role}".replace("/", "-")[:80]
        targets.append({
            "company": name if len(r["company"]) < 40 else r["company"][:40],
            "role": r["role"],
            "url": r["url"],
            "workday": r.get("ats") == "workday",
            "ats": r.get("ats"),
            "priority": r["priority"],
            "location": r["location"],
            "pay_note": r["pay_note"],
            "posted": r["posted"],
            "posted_ats": (r.get("verify") or {}).get("posted_ats"),
            "verified_live": (r.get("verify") or {}).get("live"),
            "source": r["source"],
            "caveats": r.get("caveats") or [],
            "flag": r.get("flag"),
            "needs_explicit_approval": bool(r.get("flag")),
            "priority_unresolved": bool(r.get("priority_unresolved")),
            "jobright_url": r["url"] if "jobright.ai" in (r.get("url") or "") else None,
        })
        # better company label for batch
        targets[-1]["company"] = r["company"]

    (ART / "apply_targets.json").write_text(json.dumps(targets, indent=2) + "\n")

    already = skip_breakdown.get("APPLY", 0) + skip_breakdown.get("skip-companies.txt", 0) + skip_breakdown.get("do_not_retry", 0) + skip_breakdown.get("prior needs_user / held", 0)
    counts = {
        "raw_found": len(out_raw),
        "apply_worthy": len(out_deduped),
        "age_skipped": len(age_skipped),
        "already_applied_skipped": already,
        "skip_breakdown": dict(skip_breakdown.most_common()),
        "targets": [
            {"company": t["company"], "role": t["role"], "url": t["url"], "ats": t["ats"], "priority": t["priority"]}
            for t in targets
        ],
    }
    (ART / "hunt_counts.json").write_text(json.dumps(counts, indent=2) + "\n")

    # hunt_summary.md
    lines = [
        f"# Hunt summary — {SLOT} (list-only)",
        "",
        ("**Sources this run:** Simplify (Summer2027 + New-Grad) + jobright-ai README + Jobright discovery JSON."
         if jr_path.exists() else
         "**Sources this run:** Simplify (Summer2027 + New-Grad) + jobright-ai README ONLY — "
         f"`{jr_path}` was not present at run time, so **no Jobright cards are included**. "
         "Build it with build_jobright.py and rerun this script to merge Jobright."),
        "",
        f"**Window:** prefer ≤{PREF_H}h; soft ≤{SOFT_H}h; age-note ≤{HARD_H}h (Simplify date_posted + Jobright/README).",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}.",
        "",
        "## Counts",
        f"- **Raw found:** {counts['raw_found']}",
        f"- **After dedup (apply-worthy):** {counts['apply_worthy']}",
        f"- **Age-skipped (>{SOFT_H:.0f}h ≤{HARD_H:.0f}h, else-matching):** {counts['age_skipped']}",
        f"- **Already-applied / prior-hunt / do_not_retry / skip-list / held:** {counts['already_applied_skipped']}",
        f"- **Near-misses (wrong ATS):** {len(near_misses)}",
        f"- **Priority firms kept despite unresolved/unsupported ATS (flagged, in apply-worthy):** "
        f"{sum(1 for t in targets if t.get('priority_unresolved'))}",
        f"- **Jobright discovery:** {jr_status}",
        "",
        "## Apply-worthy (Greenhouse/Lever/Ashby/Workday + PRIORITY firms flagged ⚑ even if ATS unresolved)",
    ]
    for t in targets:
        lines.append(
            f"- {'⚑ ' if t.get('flag') else ''}**{t['company']}** — {t['role']} — {t['location']} — ats={t['ats']} — "
            f"pay={t['pay_note']} — posted {t['posted']} (ATS: {t['posted_ats']}) — live={t['verified_live']} — "
            f"priority={t['priority']}" + (" — NEEDS EXPLICIT APPROVAL" if t.get("needs_explicit_approval") else "")
        )
        lines.append(f"  - {t['url']}")
        for cv in t.get("caveats") or []:
            lines.append(f"  - caveat: {cv}")
    if not targets:
        lines.append("- (none this run)")
    flagged = [t for t in targets if t.get("flag")]
    lines += ["", "## Flagged separately (needs Sam's explicit OK)"]
    if not flagged:
        lines.append("- (none)")
    for t in flagged:
        lines.append(f"- **{t['company']}** — {t['role']} — {t['url']} — {t['flag']}")
    for r in FLAG_EXTRA:
        lines.append(f"- {r}")
    lines += ["", "## Jobright ATS recovery (priority firms / hunt-time)"]
    lines += [f"- {n}" for n in RECOVERY_NOTES] or ["- (nothing to recover)"]
    lines += ["", "## Dropped at live verification (pay floor / dead / grad-only / stale at ATS)"]
    if not verify_dropped:
        lines.append("- (none)")
    for r in verify_dropped:
        lines.append(f"- {r['company']} — {r['role']} — {r['location']} — **{r['skip_reason']}**")
        lines.append(f"  - {r['url']}")
    lines += ["", "## Age-skipped (else would apply)"]
    if not age_skipped:
        lines.append("- (none)")
    for r in age_skipped[:30]:
        lines.append(f"- {r['company']} — {r['role']} — {r['location']} — {r['posted']}")
        lines.append(f"  - {r['url']}")
    lines += ["", "## Near-misses (wrong / unresolved ATS — else apply-worthy)"]
    if not near_misses:
        lines.append("- (none)")
    else:
        _seen_nm = set()
        for r in near_misses[:60]:
            if r["url"] and r["url"] in _seen_nm:
                continue
            _seen_nm.add(r["url"])
            lines.append(
                f"- **{r['company']}** — {r['role']} — {r['location']} — ats={r['ats']} — pay={r['pay_note']} — {r['posted']}"
                f" — src={'Jobright' if 'jobright-discovery' in (r['source'] or '') else r['source'].split()[0]}"
            )
            lines.append(f"  - {r['url'] or '(no URL captured)'}")
            for cv in r.get("caveats") or []:
                lines.append(f"  - {cv}")
    lines += [
        "",
        "## Skip breakdown (top)",
    ]
    for k, v in skip_breakdown.most_common(40):
        lines.append(f"- {k}: {v}")
    lines += [
        "",
        "## Source notes / failures",
    ]
    lines.extend(source_notes)
    lines += [
        f"- Jobright discovery scrape status: **{jr_status}**",
        "- Dedup used: submitted-ledger.json + jobright-applied.json + APPLY_LOG + skip-companies + do-not-retry.json + "
        "do_not_retry/HOLD + every prior hunt deduped (root + run-artifacts, incl. 2026-10-06-1am)",
        "- Handled 2026-10-06 (skipped by job id / company+title): Khan Academy SWE Intern Summer 2027 (GH 8250259, applied); "
        "Bobyard CV Research Eng Intern (Ashby, in progress); Expedia SDE Intern 2027 (R-110311) + Mobile Eng Intern 2027 "
        "(R-110306) (in progress); Assured Guaranty Back-End (GH 8827458002, in progress) + Front-End (8827460002, submitted)",
        "- Capstone Investment Advisors: **SKIPPED** (Sam dismissed 2026-10-05 evening)",
        "- LIST ONLY — zero applies / zero confirms this run",
        "",
    ]
    jr_recs = [r for r in raw if "jobright-discovery" in (r.get("source") or "")]
    jr_lines = ["# Jobright-sourced decisions — 2026-10-06 9am", "",
                ("" if jr_path.exists() else f"**Jobright discovery JSON missing at run time ({jr_path}) — nothing to decide.**"),
                f"Cards in file: {len(json.loads(jr_path.read_text())) if jr_path.exists() else 0}; "
                f"loader stats: {dict(JR_STATS)}; reached filter pipeline (tech category, ≤72h): {len(jr_recs)}", ""]
    for r in sorted(jr_recs, key=lambda r: (r.get("skip_reason") is not None, r.get("skip_reason") or "", r["company"])):
        keep = "KEEP ⚑ priority-flagged" if r.get("flag") else "KEEP"
        jr_lines.append(f"- {keep if r.get('skip_reason') is None else r['skip_reason']} — **{r['company']}** — {r['role']} — "
                        f"{r['location']} — ats={r['ats']} — pay={r['pay_note']} — {r['posted']}")
    (ART / "jobright-decisions.md").write_text("\n".join(jr_lines) + "\n")
    counts["jobright_loader_stats"] = dict(JR_STATS)
    counts["jobright_in_pipeline"] = len(jr_recs)
    counts["jobright_kept"] = sum(1 for r in jr_recs if r.get("skip_reason") is None)
    counts["flagged"] = [{"company": t["company"], "role": t["role"], "url": t["url"], "flag": t["flag"]} for t in flagged]
    lines += ["", "## Jobright decisions", f"- Full per-card list: `{ART / 'jobright-decisions.md'}`",
              (f"- {len(jr_recs)} Jobright tech cards reached filters; kept {counts['jobright_kept']}" if jr_path.exists()
               else "- Jobright discovery JSON **not present** — Simplify + README only this run")]
    (ART / "hunt_summary.md").write_text("\n".join(lines) + "\n")
    write_digest(targets)
    counts["near_misses"] = [
        {"company": r["company"], "role": r["role"], "url": r["url"], "ats": r["ats"]}
        for r in near_misses
    ]
    counts["verify_dropped"] = [
        {"company": r["company"], "role": r["role"], "url": r["url"], "reason": r["skip_reason"]}
        for r in verify_dropped
    ]
    counts["targets"] = [
        {k: t[k] for k in ("company", "role", "location", "url", "ats", "pay_note", "posted", "posted_ats", "verified_live", "priority")}
        for t in targets
    ]
    counts["jobright_discovery_status"] = jr_status
    counts["source_notes"] = source_notes
    (ART / "hunt_counts.json").write_text(json.dumps(counts, indent=2) + "\n")
    print(json.dumps(counts, indent=2))


def write_digest(targets: list[dict]) -> None:
    """ART/sam_digest.md — the text the routine should send Sam (approval list). Priority-flagged roles first."""
    order = sorted(targets, key=lambda t: (not t.get("priority_unresolved"), not t.get("flag")))
    out = [f"Hunt {SLOT} — {len(targets)} role(s) for your approval (list only, nothing applied):", ""]
    for i, t in enumerate(order, 1):
        out.append(f"{i}. {'⚑ ' if t.get('flag') else ''}{t['company']} — {t['role']} — {t['location']} — "
                   f"pay {t['pay_note']} — posted {t['posted']}")
        out.append(f"   {t['url']}")
        if t.get("flag"):
            out.append(f"   ⚑ {t['flag']}")
    if not targets:
        out.append("(nothing new this run)")
    out += ["", "Reply with the numbers to approve. ⚑ = needs your explicit OK (ATS unresolved / stale at ATS)."]
    (ART / "sam_digest.md").write_text("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
