#!/usr/bin/env python3
"""Offline regression for the 2026-10-06 HRT miss (no Jobright login, no network).

Replays the bundled 2026-10-06-9am Jobright card for Hudson River Trading
"Algorithm Development (Quant Research & Trading) Internship – Summer 2027" (url = jobright.ai only) through
ats_recover + run_hunt.main() and asserts it is NOT a silent near-miss:

  1. unit: Simplify fuzzy match is refused (two HRT reqs share the Simplify title; one is the PhD req) and the
     Data Scientist Intern gh_jid=8257369 is never attached to the Algorithm card;
  2. unit: careers/custom-host board recovery (fixture of greenhouse board `wehrtyou`) -> gh_jid=7964062
     (PhD twin 8059837 is not chosen by title alone);
  3. replay A (board fixture): HRT lands in apply_targets.json with Greenhouse board `wehrtyou` gh_jid=7964062;
  4. replay B (known HRT board + a priority firm with no board): HRT still resolves to wehrtyou; Citadel stays
     flagged priority_unresolved with the Jobright URL (do not drop it as a near-miss);
  5. replay C (already applied): skipped as handled/do_not_retry, never re-targeted;
  6. unit: careers URLs with gh_jid= count as Greenhouse; Jobright-only links are not plain-fetched;
     Jobright-sourced priority roles that are only "stale" by ATS publish date are kept with a flag.

Usage (from repo root):
  python3 scripts/hunt/test_priority_unresolved.py
  python3 scripts/hunt/test_priority_unresolved.py --live   # optional networked replay; does not apply

Default --src is scripts/hunt/fixtures/hrt-miss-2026-10-06/ (synthetic reconstruction of the silent drop:
public job titles/URLs only). Replays run in a temp dir (HUNT_ART, HUNT_NO_ROOT=1, HUNT_OFFLINE=1,
HUNT_NOW=2026-10-06 13:20 UTC). HUNT_NO_ROOT ignores inherited HUNT_ROOT / skip-companies / prior
apply_targets so a box that already listed Citadel cannot silently drop replay B.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ats_recover as A  # noqa: E402

HRT = "Hudson River Trading"
ALGO = "Algorithm Development (Quant Research & Trading) Internship – Summer 2027"
DS_JID = "8257369"
ALGO_JID = "7964062"
PHD_JID = "8059837"
UNRESOLVED_FIRM = "Citadel"
UNRESOLVED_ROLE = "Software Engineer Intern – Summer 2027"
UNRESOLVED_URL = "https://jobright.ai/jobs/info/citadel-swe-2027"
RUN_NOW = datetime(2026, 10, 6, 13, 20, tzinfo=timezone.utc).timestamp()  # when the 9am hunt ran
DEFAULT_SRC = HERE / "fixtures" / "hrt-miss-2026-10-06"


def isolate_hunt_env(tmp: Path, *, slot: str, live: bool = False) -> None:
    """Pin artifact dir, clock, and a private-tree firewall.

    The 2pm hunt box exports HUNT_ROOT=/workspace/internship-apps (Citadel is already in
    skip-companies / prior apply_targets). Replays must not inherit that, or replay B
    drops Citadel while HRT still resolves. HUNT_NOW freezes age against fixture dates.
    """
    for key in ("HUNT_ROOT", "HUNT_ARTS"):
        os.environ.pop(key, None)
    os.environ.update(
        HUNT_ART=str(tmp),
        HUNT_NO_ROOT="1",
        HUNT_OFFLINE="0" if live else "1",
        HUNT_SLOT=slot,
        HUNT_NOW=str(RUN_NOW),
    )


def fixture_fetcher(with_board=True):
    fx = json.loads((HERE / "fixtures" / "hrt-careers-2026-10-06.json").read_text())
    if with_board:
        fx["https://boards-api.greenhouse.io/v1/boards/wehrtyou/jobs"] = [
            200, (HERE / "fixtures" / "greenhouse-wehrtyou-jobs-2026-10-06.json").read_text()]
    return lambda url: tuple(fx.get(url, (404, "")))


def src_file(src: Path, name: str) -> Path:
    b = src / "_pre-fix-backup" / name  # the 9am state as it was before the fix
    return b if b.exists() else src / name


def load_simplify(src):
    return [dict(x, _source="SimplifyJobs/" + f) for f in ("simplify-summer2027.json", "simplify-newgrad.json")
            for x in json.loads((src / f).read_text())]


def unit_tests(src):
    card = next(c for c in json.loads(src_file(src, "jobright-discovery.json").read_text())
                if c["company"] == HRT and c["title"] == ALGO)
    assert "jobright.ai" in card["url"] and not card.get("ats"), card
    simp = load_simplify(src)
    r, why = A.recover_from_simplify(HRT, ALGO, simp)
    assert r is None and "ambiguous" in why, (r, why)
    assert not r or DS_JID not in r["url"]
    ok, why_ds = A.compatible(ALGO, "Data Scientist Intern")
    assert not ok, "Data Scientist must never match Algorithm Development"
    ok_phd, why_phd = A.compatible(
        ALGO, "Algorithm Development (Quant Research & Trading) PhD Internship – Summer 2027")
    assert not ok_phd, "PhD twin must not match the intern card by title alone"
    A.set_fetcher(fixture_fetcher(True))
    r, _ = A.recover_from_careers(HRT, ALGO, simp)
    assert r and f"gh_jid={ALGO_JID}" in r["url"] and r["board_url"].endswith(f"/wehrtyou/jobs/{ALGO_JID}"), r
    assert PHD_JID not in r["url"] and PHD_JID not in r["board_url"], r
    assert A.is_priority_firm(HRT) and not A.is_priority_firm("Metamorph") and not A.is_priority_firm("JumpCloud")
    print(f"unit OK: simplify refused ({why[:70]}…); DS guard: {why_ds}; PhD guard: {why_phd}; careers -> {r['url']}")
    return card


def isolation_from_private_root_tests():
    """HUNT_NO_ROOT must ignore skip-companies / applied pairs on an inherited HUNT_ROOT.

    Reproduces the box failure: unit/A pass (HRT recovers) but replay B drops Citadel
    because /workspace/internship-apps/skip-companies.txt already lists it.
    """
    poison = Path(tempfile.mkdtemp(prefix="hunt-poison-root-"))
    (poison / "skip-companies.txt").write_text("citadel\n")
    (poison / "jobright-applied.json").write_text(json.dumps([
        {"company": UNRESOLVED_FIRM, "role": UNRESOLVED_ROLE},
    ]) + "\n")
    arts = poison / "run-artifacts" / "2026-10-06-1am"
    arts.mkdir(parents=True)
    (arts / "hunt-2026-10-06-1am-deduped.json").write_text(json.dumps([
        {"company": UNRESOLVED_FIRM, "role": UNRESOLVED_ROLE, "url": UNRESOLVED_URL, "skip_reason": None},
    ]) + "\n")
    tmp = Path(tempfile.mkdtemp(prefix="hunt-isolation-"))
    os.environ["HUNT_ROOT"] = str(poison)
    os.environ["HUNT_ARTS"] = str(poison / "run-artifacts")
    isolate_hunt_env(tmp, slot="isolation")
    # isolate_hunt_env pops HUNT_ROOT; re-export poison so a regression that *reads* it fails this test
    os.environ["HUNT_ROOT"] = str(poison)
    os.environ["HUNT_ARTS"] = str(poison / "run-artifacts")
    os.environ["HUNT_NO_ROOT"] = "1"
    os.environ["HUNT_ART"] = str(tmp)
    os.environ["HUNT_NOW"] = str(RUN_NOW)
    sys.modules.pop("run_hunt", None)
    rh = importlib.import_module("run_hunt")
    skipped = rh.load_skip_companies()
    pairs = rh.load_applied_pairs()
    assert rh.NO_ROOT and "citadel" not in skipped, skipped
    assert (A.company_key(UNRESOLVED_FIRM), A.norm(UNRESOLVED_ROLE)) not in pairs, pairs
    print("isolation OK: HUNT_NO_ROOT ignores skip-companies/applied Citadel on inherited HUNT_ROOT")


def extra_behavior_tests():
    """gh_jid Greenhouse, no Jobright page-fetch, stale-at-ATS keep for Jobright-sourced priority firms."""
    careers_gh = f"https://www.hudsonrivertrading.com/careers/job/?gh_jid={ALGO_JID}"
    assert A.ats_of(careers_gh) == "greenhouse"
    tmp = Path(tempfile.mkdtemp(prefix="hunt-behavior-"))
    isolate_hunt_env(tmp, slot="behavior", live=True)  # live=True => HUNT_OFFLINE=0 for verify stubs
    sys.modules.pop("run_hunt", None)
    rh = importlib.import_module("run_hunt")
    assert rh.guess_ats(careers_gh) == "greenhouse"

    rec = {
        "company": HRT, "role": ALGO,
        "url": f"https://job-boards.greenhouse.io/wehrtyou/jobs/{ALGO_JID}",
        "ats": "greenhouse", "age_h": 8.0, "source": "jobright-discovery",
        "pay_note": "unknown", "caveats": [], "flag": None, "skip_reason": None,
    }

    def fake_verify(_r):
        return {"live": True, "ats_confirmed": "greenhouse", "posted_ats": "2026-07-01T00:00:00.000Z",
                "pay_note": "unknown", "max_hourly": None, "edu_note": "", "api": None, "http": 200,
                "title_ats": ALGO, "ats_age_h": 2000.0}

    rh.verify_posting = fake_verify
    rh.OFFLINE = False
    kept, dropped = rh.apply_verification([dict(rec)], Counter())
    assert kept and not dropped, (kept, dropped)
    assert kept[0].get("flag") and "stale" in (kept[0]["flag"] or "").lower(), kept[0]
    assert any("stale at ATS" in c for c in kept[0].get("caveats") or []), kept[0]

    calls = []
    rh._curl = lambda url, *a, **k: calls.append(url) or (0, "")
    jr = dict(rec, url="https://jobright.ai/jobs/info/hrt-algo-2027", ats="unresolved",
              flag=None, caveats=[], skip_reason=None)
    rh.apply_verification([jr], Counter())
    assert not calls, f"Jobright-only URL must not be plain-fetched; got {calls}"
    print("extra OK: gh_jid= is Greenhouse; stale priority Jobright kept with flag; Jobright-only not fetched")


def replay(src: Path, label: str, with_board: bool | None, keep_handled=False, live=False, extra_unresolved=False):
    tmp = Path(tempfile.mkdtemp(prefix=f"hunt-replay-{label}-"))
    for name in ("simplify-summer2027.json", "simplify-newgrad.json", "jobright-ai-readme.md", "raw.txt"):
        if (src / name).exists():
            os.symlink(src / name, tmp / name) if name != "raw.txt" else shutil.copy2(src / name, tmp / name)
    for name in ("jobright-discovery.json", "jobright-ats-resolved.json"):
        shutil.copy2(src_file(src, name), tmp / name)
    if extra_unresolved:
        cards = json.loads((tmp / "jobright-discovery.json").read_text())
        cards.append({
            "company": UNRESOLVED_FIRM,
            "title": UNRESOLVED_ROLE,
            "location": "New York, NY (Onsite)",
            "posted": "8 hours ago",
            "date_posted": 1791264000.0,
            "url": UNRESOLVED_URL,
            "ats": None,
            "notes": "Quant; $100/hr - $120/hr",
            "source": "jobright",
            "swe_ai": True,
        })
        (tmp / "jobright-discovery.json").write_text(json.dumps(cards) + "\n")
    isolate_hunt_env(tmp, slot="2026-10-06-9am", live=live)
    A.set_fetcher(None if live else (fixture_fetcher(with_board) if with_board is not None else (lambda u: (0, ""))))
    sys.modules.pop("run_hunt", None)
    rh = importlib.import_module("run_hunt")
    rh.NOW = RUN_NOW if not live else rh.NOW
    if not keep_handled:  # simulate 9am: role had not been applied yet
        rh.HANDLED_JOB_IDS.pop(ALGO_JID, None)
        rh.HANDLED_ROLES[:] = [h for h in rh.HANDLED_ROLES if h[0] != "hudson river trading"]
        _orig = rh.load_applied_pairs
        rh.load_applied_pairs = lambda: {p for p in _orig() if not (p[0] == "hudson river trading" and "algorithm" in p[1])}
        _orig_ids = rh.load_submitted_ids
        rh.load_submitted_ids = lambda: _orig_ids() - {ALGO_JID}
        _orig_urls = rh.load_applied_urls
        rh.load_applied_urls = lambda: {u for u in _orig_urls() if ALGO_JID not in u}
    argv, sys.argv = sys.argv, ["run_hunt.py"] + ([] if live else ["--no-verify"])
    import io, contextlib
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            rh.main()
    finally:
        sys.argv = argv
    targets = json.loads((tmp / "apply_targets.json").read_text())
    raw = json.loads((tmp / "hunt-2026-10-06-9am.json").read_text())
    hrt_t = [t for t in targets if t["company"] == HRT and t["role"] == ALGO]
    hrt_r = [r for r in raw if r["company"] == HRT and r["role"] == ALGO]
    return tmp, targets, hrt_t, hrt_r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(DEFAULT_SRC),
                    help="run dir with jobright-discovery.json + simplify listings (default: bundled HRT-miss fixtures)")
    ap.add_argument("--live", action="store_true", help="extra replay with network: live ATS verification + careers")
    a = ap.parse_args()
    src = Path(a.src)
    if not src.exists():
        raise SystemExit(f"--src not found: {src} (bundled default is {DEFAULT_SRC})")
    extra_behavior_tests()
    isolation_from_private_root_tests()
    unit_tests(src)

    before = json.loads(src_file(src, "hunt-2026-10-06-9am.json").read_text())
    b = [r for r in before if r["company"] == HRT and r["role"] == ALGO]
    print(f"BEFORE (saved 9am output): HRT Algorithm skip_reason={b[0]['skip_reason']!r} url={b[0]['url']}; "
          f"apply_targets={[t['company'] for t in json.loads(src_file(src, 'apply_targets.json').read_text())]}")

    tmp, targets, t, r = replay(src, "board", with_board=True)
    assert t, f"A: HRT Algorithm missing from apply_targets ({r})"
    assert "jobright.ai" not in t[0]["url"] and t[0]["ats"] == "greenhouse" and ALGO_JID in t[0]["url"], t[0]
    assert PHD_JID not in t[0]["url"], t[0]
    print(f"AFTER A (careers/board recoverable): KEEP url={t[0]['url']} ats={t[0]['ats']} "
          f"priority={t[0]['priority']} flag={t[0]['flag']!r}; targets={[x['company'] for x in targets]}")
    summ = (tmp / "hunt_summary.md").read_text().split("## Flagged separately")[0]
    assert ALGO in summ.split("## Apply-worthy")[1]
    assert ALGO in (tmp / "sam_digest.md").read_text()

    tmp, targets, t, r = replay(src, "unresolved", with_board=True, extra_unresolved=True)
    assert t, f"B: HRT Algorithm missing from apply_targets ({r})"
    assert "jobright.ai" not in t[0]["url"] and t[0]["ats"] == "greenhouse" and ALGO_JID in t[0]["url"], t[0]
    assert t[0]["url"].endswith(f"/wehrtyou/jobs/{ALGO_JID}") or f"gh_jid={ALGO_JID}" in t[0]["url"], t[0]
    cit = [x for x in targets if x["company"] == UNRESOLVED_FIRM]
    assert cit, f"B: {UNRESOLVED_FIRM} missing from apply_targets ({targets})"
    assert cit[0]["priority_unresolved"] and cit[0]["needs_explicit_approval"] and "jobright.ai" in cit[0]["url"], cit[0]
    assert UNRESOLVED_ROLE in (tmp / "hunt_summary.md").read_text().split("## Apply-worthy")[1].split("## Flagged separately")[0]
    dig = (tmp / "sam_digest.md").read_text()
    assert UNRESOLVED_ROLE in dig and "⚑" in dig
    print(f"AFTER B (HRT board known): HRT KEEP url={t[0]['url']}; "
          f"{UNRESOLVED_FIRM} ⚑ url={cit[0]['url']} flag={str(cit[0]['flag'])[:90]!r}…")
    print("  digest:\n    " + "\n    ".join(dig.strip().splitlines()[:6]))

    tmp, targets, t, r = replay(src, "applied", with_board=True, keep_handled=True)
    assert not t and r and r[0]["skip_reason"] and ("handled" in r[0]["skip_reason"] or "APPLY" in r[0]["skip_reason"]), r
    print(f"AFTER C (already applied): not targeted — skip_reason={r[0]['skip_reason']!r}")
    if a.live:
        tmp, targets, t, r = replay(src, "live", with_board=None, live=True)
        assert t, f"LIVE: HRT Algorithm missing from apply_targets ({r})"
        print(f"AFTER LIVE (network, full verification): KEEP url={t[0]['url']} flag={t[0]['flag']!r}; "
              f"targets={[(x['company'], x['role'][:40]) for x in targets]}; out={tmp}")
    print("ALL OK")


if __name__ == "__main__":
    main()
