#!/usr/bin/env python3
"""Build Jobright cards.json + jobright-discovery.json for a hunt run dir (LIST ONLY; never applies).

Canonical copy: scripts/hunt/build_jobright.py (+ ats_recover.py next to it).
Copy scripts/hunt/*.py into a run-artifacts/<slot>/ dir, or run in place with --dir / HUNT_ART.

2026-10-06 fix: Jobright-only cards (url=jobright.ai/jobs/info/<id>) now try, in order,
  a) Simplify summer/newgrad listings of ANY age (same company, intern-ish, same role family, not ambiguous),
  b) company careers / custom-host Greenhouse board (ats_recover.KNOWN_CAREERS, e.g. HRT -> board `wehrtyou`),
  c) the old greenhouse/ashby/lever/workday board_map slug lookup.
Recoveries land in jobright-ats-resolved.json with a note saying how. Priority firms are always attempted
(even swe_ai=false). Company careers URLs carrying gh_jid= count as Greenhouse.

Input (in --dir, default this script's dir):
  raw.txt          Jobright Recommended-feed page text. Chunks may be separated by '@@' (1am style).
  hrefs.json       optional. Either {"/jobs/info/<id>": [title, company]} (1am style) or
                   {"/jobs/info/<id>": "<card text prefix>"} (9am seg*.json style).
  apply-urls.json  optional. {"/jobs/info/<id>" | "<jobright_key>": "<original apply URL>"} written by a browser agent.
  --from-segs      optional: if raw.txt is absent, first build raw.txt + hrefs.json from seg*.json
                   ({"same", "raw", "hrefs"} dumps written by the browser agent's merge.py).

Output (same schema as 2026-10-06-1am):
  cards.json               [{company,title,location,posted,pay,tags,desc,match,extras,sw,jid}]
  jobright-discovery.json  [{company,title,location,posted,url,ats,notes,source:"jobright",swe_ai}]
  jobright-ats-resolved.json  merged (never overwritten) jobright_key -> {company,title,url,note}; seeded from the
                           1am file (same keys) + automatic board lookups (Greenhouse/Ashby/Lever by slug, Workday CXS
                           search on tenants known from Simplify/1am). run_hunt.py reads it and swaps the URL in.
  build_jobright.log.json  stats

Usage:
  python3 build_jobright.py                 # needs raw.txt
  python3 build_jobright.py --from-segs     # build raw.txt/hrefs.json from seg*.json first if raw.txt is missing
  python3 build_jobright.py --no-resolve    # skip network board lookups
"""
from __future__ import annotations

import argparse
import difflib
import glob
import json
import re
import subprocess
import sys
from pathlib import Path

import os

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try:
    import ats_recover  # sibling helper (scripts/hunt/ats_recover.py); copy it with this script
except ImportError:  # pragma: no cover
    ats_recover = None
    print("WARNING: ats_recover.py not found next to build_jobright.py — Simplify/careers ATS recovery disabled",
          file=sys.stderr)
ARTS = Path(os.environ.get("HUNT_ARTS") or Path(os.environ.get("HUNT_ROOT") or "/workspace/internship-apps") / "run-artifacts")
DEFAULT_DIR = Path(os.environ.get("HUNT_ART") or HERE)


def prev_dir(d: Path) -> Path:
    """Previous run dir to carry Jobright resolutions from: $HUNT_PREV, else the run-artifacts dir (≠ d) whose
    jobright-ats-resolved.json is newest."""
    if os.environ.get("HUNT_PREV"):
        return Path(os.environ["HUNT_PREV"])
    best = None
    for f in ARTS.glob("*/jobright-ats-resolved.json"):
        if f.parent.resolve() == d.resolve() or f.parent.name.startswith("_"):
            continue
        if best is None or f.stat().st_mtime > best.stat().st_mtime:
            best = f
    return best.parent if best else ARTS / "2026-10-06-1am"


PREV = ARTS / "2026-10-06-1am"  # rebound in main() via prev_dir()

AGE_RE = re.compile(r"^(?:Reposted )?\d+ (?:minutes?|hours?|days?) ago$")
SPLIT_RE = re.compile(r"\n(?=(?:Reposted )?\d+ (?:minutes?|hours?|days?) ago\n)")
FOOTER_RE = re.compile(r"^(We couldn't find more jobs|📌 What's limiting|S$|Sam$|Turbo Plan|Your Saved Filters|ASK ORION$|APPLY)")
TECH = re.compile(r"(software|\bswe\b|develop(er|ment)|programm|full[\s-]?stack|front[\s-]?end|back[\s-]?end|\bdata\b|"
                  r"machine learning|\bml\b|\bai\b|artificial intelligence|quant|computer|cloud|devops|\bsre\b|platform|"
                  r"security|cyber|\bit\b|information technology|product manag|technical program|research engineer|"
                  r"vision|mobile|\bios\b|android|\bweb\b|infrastructure|analytics|robotics software|forward deployed)", re.I)
NONTECH = re.compile(r"(civil|structural|geotechnical|mechanical|chemical|process engineer|manufacturing|industrial|"
                     r"construction|safety|fire (engineering|protection)|traffic|refining|materials|nuclear|quality|"
                     r"landman|estimating|bioengineering|\bhr\b|human resources|marketing|social media|tax|audit|"
                     r"accounting|legal|regulatory|clinical|real estate|sales)", re.I)
SW_STRONG = re.compile(r"(software|\bswe\b|full[\s-]?stack|front[\s-]?end|back[\s-]?end|machine learning|\bml\b|\bai\b|"
                       r"data (engineer|scien)|developer)", re.I)


def norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def company_key(name):  # identical to run_hunt.company_key
    n = re.sub(r"[^a-z0-9 &+-]+", "", norm(name))
    for suffix in (" inc", " inc.", " llc", " ltd", " corp", " corporation", " co", " company"):
        if n.endswith(suffix):
            n = n[: -len(suffix)]
    return n.strip()


def jobright_key(company, title):  # identical to run_hunt.jobright_key
    return f"{company_key(company)}|{re.sub(r'[^a-z0-9]+', ' ', norm(title)).strip()}"


# --------------------------------------------------------------------------- parsing
def title_company_from_prefix(text: str):
    L = [x for x in text.split("\n") if x.strip()]
    if "/" not in L:
        return None
    i = L.index("/")
    return (L[i - 2], L[i - 1]) if i >= 2 else None


def load_hrefs(path: Path) -> dict:
    """-> {(title, company): jid}"""
    if not path.exists():
        return {}
    h = json.loads(path.read_text())
    out = {}
    for jid, v in h.items():
        tc = tuple(v[:2]) if isinstance(v, list) else title_company_from_prefix(str(v))
        if tc:
            out[tc] = jid
    return out


def parse_raw(raw: str) -> list[dict]:
    cards: dict[tuple, dict] = {}
    for ch in raw.split("@@"):
        body = ch.split("\nRecommended\n", 1)[-1]
        for p in SPLIT_RE.split(body):
            L = [x.strip() for x in p.split("\n") if x.strip()]
            if not L or not AGE_RE.match(L[0]) or "/" not in L:
                continue
            i = L.index("/")
            if i < 3:
                continue
            company, title, tags = L[i - 1], L[i - 2], L[1:i - 2]
            rest = L[i + 2:]  # skip company descriptor line
            if "Internship" not in rest[:8]:
                continue
            k = rest.index("Internship")
            loc = " ".join(rest[:k])
            after = rest[k + 1:k + 6]
            pay = after[0] if after and "$" in after[0] and "/" in after[0] else None
            wm = next((x for x in after if x in ("Onsite", "Remote", "Hybrid")), None)
            m = re.search(r"(\d+)%\n(\w+ MATCH)", p)
            extras = []
            if m:
                for x in [x.strip() for x in p[m.end():].split("\n") if x.strip()]:
                    if FOOTER_RE.match(x) or AGE_RE.match(x):
                        break
                    extras.append(x)
                extras = extras[:3]
            c = cards.get((company, title)) or {}
            c.update(company=company, title=title, location=f"{loc} ({wm})" if wm else loc, posted=L[0],
                     pay=pay, tags=tags, desc=[])
            if m:
                c["match"] = f"{m.group(1)}% {m.group(2)}"
                c["extras"] = extras
            cards[(company, title)] = c
    return list(cards.values())


def classify_sw(title: str) -> bool:
    if SW_STRONG.search(title):
        return True
    return bool(TECH.search(title)) and not NONTECH.search(title)


# --------------------------------------------------------------------------- ATS resolution
def curl(url, data=None, timeout=20):
    cmd = ["curl", "-sL", "--max-time", str(timeout), "-A", "Mozilla/5.0", "-H", "Accept: application/json",
           "-w", "\n%{http_code}"]
    if data is not None:
        cmd += ["-H", "Content-Type: application/json", "--data", json.dumps(data)]
    try:
        out = subprocess.run(cmd + [url], capture_output=True, text=True, timeout=timeout + 5).stdout
    except Exception:
        return 0, ""
    body, _, code = out.rpartition("\n")
    try:
        return int(code), body
    except ValueError:
        return 0, ""


def guess_ats(url: str):
    u = (url or "").lower()
    if "myworkdayjobs" in u:
        return "workday"
    if "greenhouse" in u or "gh_jid=" in u:
        return "greenhouse"
    if "ashbyhq" in u:
        return "ashby"
    if "lever.co" in u:
        return "lever"
    return "other" if u and "jobright.ai" not in u else None


def board_map(dirs) -> dict:
    """company_key -> set of ('greenhouse'|'ashby'|'lever', slug) / ('workday', tenant, wd, site) from Simplify + 1am."""
    bm: dict[str, set] = {}

    def add(company, url):
        ck = company_key(company)
        u = url or ""
        m = re.search(r"greenhouse\.io/(?:embed/job_app\?for=)?([A-Za-z0-9_-]+)", u)
        if m and m.group(1) not in ("embed", "v1"):
            bm.setdefault(ck, set()).add(("greenhouse", m.group(1)))
        m = re.search(r"jobs\.ashbyhq\.com/([^/?#]+)", u)
        if m:
            bm.setdefault(ck, set()).add(("ashby", m.group(1)))
        m = re.search(r"jobs\.lever\.co/([^/?#]+)", u)
        if m:
            bm.setdefault(ck, set()).add(("lever", m.group(1)))
        m = re.match(r"https://([^.]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Za-z]{2}/)?([^/?#]+)/", u)
        if m:
            bm.setdefault(ck, set()).add(("workday",) + m.groups())

    for d in dirs:
        for f in ("simplify-summer2027.json", "simplify-newgrad.json"):
            p = Path(d) / f
            if p.exists():
                try:
                    for x in json.loads(p.read_text()):
                        add(x.get("company_name", ""), x.get("url", ""))
                except Exception:
                    pass
        p = Path(d) / "jobright-ats-resolved.json"
        if p.exists():
            for v in json.loads(p.read_text()).values():
                add(v.get("company", ""), v.get("url", ""))
    return bm


def tnorm(t):
    t = re.sub(r"\b(20\d\d|summer|fall|winter|spring|intern(ship)?|program|co-?op)\b", " ", norm(t))
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


INTERNISH = re.compile(r"(intern|co-?op|student|apprentice|trainee|fellow)", re.I)


def best_match(title, cands, penalty=0.15):  # cands: [(title, url)]
    """Fuzzy title match. Season/year/'intern' words are ignored for the core ratio, but a candidate whose title lacks
    an intern-ish word (when the card has one) is penalised so a full-time twin never beats the intern req
    (e.g. Bobyard 'Computer Vision Research Engineer' vs '... - Intern'). Workday uses a smaller penalty because
    many Workday intern reqs omit the word."""
    best = (0.0, None, None)
    a = tnorm(title)
    want_intern = bool(INTERNISH.search(title))
    for t, u in cands:
        r = difflib.SequenceMatcher(None, a, tnorm(t)).ratio()
        r += 0.01 * difflib.SequenceMatcher(None, norm(title), norm(t)).ratio()
        if want_intern and not INTERNISH.search(t):
            r -= penalty
        if r > best[0]:
            best = (r, t, u)
    return best


BOARD_CACHE: dict = {}


def board_jobs(entry):
    if entry in BOARD_CACHE:
        return BOARD_CACHE[entry]
    jobs = []
    kind = entry[0]
    if kind == "greenhouse":
        code, body = curl(f"https://boards-api.greenhouse.io/v1/boards/{entry[1]}/jobs")
        if code == 200:
            jobs = [(j.get("title", ""), f"https://job-boards.greenhouse.io/{entry[1]}/jobs/{j.get('id')}")
                    for j in json.loads(body).get("jobs", [])]
    elif kind == "ashby":
        code, body = curl(f"https://api.ashbyhq.com/posting-api/job-board/{entry[1]}")
        if code == 200:
            jobs = [(j.get("title", ""), j.get("jobUrl") or f"https://jobs.ashbyhq.com/{entry[1]}/{j.get('id')}")
                    for j in json.loads(body).get("jobs", [])]
    elif kind == "lever":
        code, body = curl(f"https://api.lever.co/v0/postings/{entry[1]}?mode=json")
        if code == 200:
            jobs = [(j.get("text", ""), j.get("hostedUrl", "")) for j in json.loads(body)]
    BOARD_CACHE[entry] = jobs
    return jobs


def workday_search(entry, title):
    _, tenant, wd, site = entry
    code, body = curl(f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs",
                      data={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": tnorm(title)[:80]})
    if code != 200:
        return []
    try:
        posts = json.loads(body).get("jobPostings", [])
    except Exception:
        return []
    return [(p.get("title", ""), f"https://{tenant}.{wd}.myworkdayjobs.com/{site}{p.get('externalPath', '')}")
            for p in posts]


def resolve(card, bm, min_ratio=0.86):
    ck = company_key(card["company"])
    entries = set(bm.get(ck, set()))
    slug = re.sub(r"[^a-z0-9]", "", ck)
    if slug:
        entries |= {("greenhouse", slug), ("ashby", slug), ("lever", slug)}
    best = (0.0, None, None, None)
    for e in sorted(entries):
        cands = workday_search(e, card["title"]) if e[0] == "workday" else board_jobs(e)
        r, t, u = best_match(card["title"], cands, penalty=0.05 if e[0] == "workday" else 0.15)
        if r > best[0]:
            best = (r, t, u, e)
    if best[2] and ats_recover and not ats_recover.compatible(card["title"], best[1])[0]:
        return None  # e.g. PhD/MBA/new-grad twin or different role family (Data Scientist vs Algorithm Development)
    if best[0] >= min_ratio and best[2]:
        warn = "" if (INTERNISH.search(best[1]) or not INTERNISH.search(card["title"])) else \
            " — WARNING matched title lacks 'intern'; confirm it is the intern req"
        return {"company": card["company"], "title": card["title"], "url": best[2],
                "note": f"auto board lookup {best[3][0]}:{'/'.join(best[3][1:])} matched '{best[1]}' (score {best[0]:.2f}){warn}"}
    return None


# --------------------------------------------------------------------------- main
def segs_to_raw(d: Path) -> bool:
    segs = sorted(glob.glob(str(d / "seg*.json")), key=lambda x: int(re.sub(r"\D", "", Path(x).stem) or 0))
    if not segs:
        return False
    raws, hrefs = [], {}
    for f in segs:
        s = json.loads(Path(f).read_text())
        raws.append(s.get("raw", ""))
        for k, v in (s.get("hrefs") or {}).items():
            hrefs.setdefault(k, v)
    (d / "raw.txt").write_text("@@\n" + "\n@@\n".join(raws))
    if not (d / "hrefs.json").exists():
        (d / "hrefs.json").write_text(json.dumps(hrefs, indent=1))
    print(f"built raw.txt + hrefs.json from {len(segs)} seg files ({len(hrefs)} hrefs)")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(DEFAULT_DIR))
    ap.add_argument("--from-segs", action="store_true")
    ap.add_argument("--no-resolve", action="store_true")
    ap.add_argument("--resolve-all", action="store_true", help="also board-lookup swe_ai=false cards")
    a = ap.parse_args()
    d = Path(a.dir)
    global PREV
    PREV = prev_dir(d)
    raw_p = d / "raw.txt"
    if not raw_p.exists() and not (a.from_segs and segs_to_raw(d)):
        sys.exit(f"{raw_p} not found (pass --from-segs to build it from seg*.json)")

    cards = parse_raw(raw_p.read_text())
    tc2jid = load_hrefs(d / "hrefs.json")
    apply_urls = json.loads((d / "apply-urls.json").read_text()) if (d / "apply-urls.json").exists() else {}

    res_p = d / "jobright-ats-resolved.json"
    resolved = json.loads(res_p.read_text()) if res_p.exists() else {}
    prev_res = json.loads((PREV / "jobright-ats-resolved.json").read_text()) if (PREV / "jobright-ats-resolved.json").exists() else {}
    prev_disc = {}
    if (PREV / "jobright-discovery.json").exists():
        for x in json.loads((PREV / "jobright-discovery.json").read_text()):
            if x.get("url") and "jobright.ai" not in x["url"]:
                prev_disc[jobright_key(x["company"], x["title"])] = x["url"]

    bm = {} if a.no_resolve else board_map([d, PREV])
    simplify = []  # any age, active or not — used for ATS recovery of Jobright-only cards
    for f in ("simplify-summer2027.json", "simplify-newgrad.json"):
        for dd in (d, PREV):
            if (dd / f).exists():
                try:
                    simplify += json.loads((dd / f).read_text())
                    break
                except Exception:
                    pass
    stats = {"cards": len(cards), "jid": 0, "apply_url_sidecar": 0, "carried_1am_url": 0,
             "resolved_carried_1am": 0, "resolved_auto": 0, "resolved_existing": 0, "swe_ai_true": 0,
             "resolved_simplify": 0, "resolved_careers": 0, "priority_unresolved": 0, "prev_dir": str(PREV)}
    recovery_log = []
    disc = []
    for c in cards:
        jid = tc2jid.get((c["title"], c["company"]))
        c["sw"] = classify_sw(c["title"])
        c["jid"] = jid
        key = jobright_key(c["company"], c["title"])
        stats["jid"] += bool(jid)
        stats["swe_ai_true"] += c["sw"]
        url = apply_urls.get(jid or "") or apply_urls.get(key)
        if url:
            stats["apply_url_sidecar"] += 1
        elif key in prev_disc:
            url = prev_disc[key]
            stats["carried_1am_url"] += 1
        elif jid:
            url = "https://jobright.ai" + jid
        ats = guess_ats(url) if url else None
        if ats not in ("greenhouse", "ashby", "lever", "workday"):
            if key in resolved:
                stats["resolved_existing"] += 1
            elif key in prev_res:
                resolved[key] = dict(prev_res[key], note=(prev_res[key].get("note", "") + " [carried from 2026-10-06-1am]"))
                stats["resolved_carried_1am"] += 1
            else:
                prio = ats_recover.is_priority_firm(c["company"]) if ats_recover else None
                r, why = None, []
                if ats_recover and (c["sw"] or prio or a.resolve_all):
                    # a) Simplify any-age (offline) then b) careers/custom-host board (network unless --no-resolve)
                    r, why = ats_recover.recover(c["company"], c["title"], simplify, network=not a.no_resolve)
                    if r:
                        stats["resolved_" + r["method"]] += 1
                if not r and not a.no_resolve and (c["sw"] or prio or a.resolve_all):
                    r = resolve(c, bm)  # c) generic board_map / slug lookup
                    if r:
                        stats["resolved_auto"] += 1
                if r:
                    resolved[key] = r
                elif prio:
                    stats["priority_unresolved"] += 1
                if prio:
                    recovery_log.append({"company": c["company"], "title": c["title"], "priority_hit": prio,
                                         "resolved": (r or {}).get("url"), "note": (r or {}).get("note"),
                                         "tried": why})
        notes = [c.get("match")] if c.get("match") else []
        notes += ([c["pay"]] if c.get("pay") else []) + (c.get("extras") or []) + (c.get("tags") or [])
        if ats == "other":
            notes.append("original apply URL is not a standard ATS (LinkedIn/company site)")
        if not c["sw"]:
            notes.append("non-tech")
        if not jid and not url:
            notes.append("jobright id not captured")
        disc.append({"company": c["company"], "title": c["title"], "location": c["location"], "posted": c["posted"],
                     "url": url, "ats": ats, "notes": "; ".join(notes), "source": "jobright", "swe_ai": c["sw"]})

    (d / "cards.json").write_text(json.dumps(cards, indent=1))
    (d / "jobright-discovery.json").write_text(json.dumps(disc, indent=1))
    res_p.write_text(json.dumps(resolved, indent=1))
    stats["priority_recovery"] = recovery_log
    (d / "build_jobright.log.json").write_text(json.dumps(stats, indent=1))
    print(json.dumps(stats, indent=1))
    print(f"wrote {d / 'cards.json'}, {d / 'jobright-discovery.json'}, {res_p}")


if __name__ == "__main__":
    main()
