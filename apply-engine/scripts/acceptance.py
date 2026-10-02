#!/usr/bin/env python3
"""Acceptance run: three demo fills with screenshots and a proven filled log.

Spec acceptance is "fill.py sha256[:12] + 3 demo screenshots (ashby, greenhouse,
workday past My Information) with matching filled-log". This script produces
exactly that, against the local fixtures, using the REAL profile so the values
the spec calls out (NY / 10001 / phone digits / previous_employee=No) are
actually exercised.

    python scripts/acceptance.py [--out DIR]

Writes per ATS:   <out>/<ats>/screenshot.png
                  <out>/<ats>/review.json      (filled log + dom snapshot + fingerprint)
and overall:      <out>/ACCEPTANCE.json

Exits non-zero if any demo fails its checks, clicks submit, or drifts.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apply_engine import fingerprint, readback  # noqa: E402
from apply_engine.guard import CONFIRM_ENV  # noqa: E402
from apply_engine.jd import fetch_job_from_text  # noqa: E402
from apply_engine.pdf import render_pdf  # noqa: E402
from apply_engine.pool import load_pool  # noqa: E402
from apply_engine.profile import load_profile  # noqa: E402
from apply_engine.tailor import tailor  # noqa: E402
from apply_engine.util import dump_json  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
POOL = ROOT / "examples" / "PROJECT_POOL.md"

DEMOS = [
    {
        "ats": "greenhouse",
        "url": "https://job-boards.greenhouse.io/acme/jobs/1234567",
        "fixture": FIXTURES / "greenhouse.html",
        "must_fill": ["first_name", "last_name", "email", "resume"],
    },
    {
        "ats": "ashby",
        "url": "https://jobs.ashbyhq.com/acme/00000000-0000-0000-0000-000000000000/application",
        "fixture": FIXTURES / "ashby-application.html",
        "must_fill": ["full_name", "email", "resume"],
    },
    {
        "ats": "workday",
        "url": "https://acme.wd1.myworkdayjobs.com/en-US/careers/job/NYC/Software-Engineering-Intern_R1",
        "fixture": FIXTURES / "workday.html",
        # "past My Information": these only exist once the wizard is on that step.
        "must_fill": [
            "first_name", "last_name", "email", "phone",
            "state", "postal_code", "previous_employee",
            "school", "degree", "field_of_study", "resume",
        ],
    },
]


def real_profile() -> Path:
    """The real profile, wherever the data tree lives on this box."""
    for cand in (
        ROOT.parent / "internship-apps" / "autofill" / "profile.json",
        Path("/workspace/internship-apps/autofill/profile.json"),
    ):
        if cand.exists():
            return cand
    raise SystemExit("no internship-apps data tree found; cannot run acceptance on the real profile")


def run_demo(demo: dict, out_dir: Path, profile, pool, tmp: Path) -> dict:
    from apply_engine.fill import fill_application

    import os
    os.environ.pop(CONFIRM_ENV, None)           # never submit from acceptance
    os.environ.setdefault("WORKDAY_DEFAULT_PASSWORD", "acceptance-only-not-a-real-password")

    ats = demo["ats"]
    dest = out_dir / ats
    dest.mkdir(parents=True, exist_ok=True)

    job = fetch_job_from_text(demo["url"], "Software Engineering Intern", "Acme", "React Native / TypeScript intern")
    tailored = tailor(profile, pool, job)
    pdf = render_pdf(tailored, tmp / f"{ats}-resume.pdf")

    artifact = fill_application(
        url=demo["url"],
        profile=profile,
        resume=tailored,
        resume_path=pdf,
        profile_path=str(real_profile()),
        pool_path=str(POOL),
        queue_id=f"acceptance-{ats}",
        html=demo["fixture"].read_text(encoding="utf-8"),
        submit=False,
        screenshot_path=dest / "screenshot.png",
        tenant_map_path=tmp / "workday-accounts.json",
    )

    item = {**artifact.to_dict(), "fingerprint": fingerprint.stamp()}
    dump_json(dest / "review.json", item)

    mapped = {r.get("mapped_to"): r.get("value") for r in artifact.filled if isinstance(r, dict)}
    snapshot = (item.get("extra") or {}).get("dom_snapshot") or []
    problems = (item.get("extra") or {}).get("readback_problems") or []

    failures: list[str] = []
    if artifact.submit_clicked:
        failures.append("submit_clicked is True")
    missing = [k for k in demo["must_fill"] if not mapped.get(k)]
    if missing:
        failures.append(f"not filled: {', '.join(missing)}")
    if problems:
        failures.append(f"readback drift: {problems}")
    if not (dest / "screenshot.png").exists():
        failures.append("no screenshot")

    # The values the spec singles out.
    if ats == "workday":
        if mapped.get("state") != "New York":
            failures.append(f"state readback {mapped.get('state')!r} != 'New York'")
        if mapped.get("postal_code") != "10001":
            failures.append(f"postal {mapped.get('postal_code')!r} != 10001")
        if mapped.get("previous_employee") != "No":
            failures.append(f"previous_employee {mapped.get('previous_employee')!r} != No")
        if not readback.digits(str(mapped.get("phone") or "")).endswith(readback.digits(profile.phone)[-10:]):
            failures.append(f"phone digits mismatch: {mapped.get('phone')!r} vs {profile.phone!r}")
        blob = json.dumps(item)
        if "acceptance-only-not-a-real-password" in blob:
            failures.append("password leaked into review.json")

    return {
        "ats": ats,
        "status": artifact.status,
        "submit_clicked": artifact.submit_clicked,
        "screenshot": str(dest / "screenshot.png"),
        "review": str(dest / "review.json"),
        "filled_count": len(artifact.filled),
        "filled": mapped,
        "dom_controls": len(snapshot),
        "readback_problems": problems,
        "ok": not failures,
        "failures": failures,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "artifacts" / "acceptance"))
    args = ap.parse_args()

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / "_tmp"
    tmp.mkdir(exist_ok=True)

    profile = load_profile(real_profile())
    pool = load_pool(POOL)

    results = [run_demo(d, out_dir, profile, pool, tmp) for d in DEMOS]
    stamp = fingerprint.stamp()
    summary = {
        "status": "acceptance_pass" if all(r["ok"] for r in results) else "acceptance_fail",
        "fingerprint": stamp,
        "profile": str(real_profile()),
        "demos": results,
    }
    dump_json(out_dir / "ACCEPTANCE.json", summary)

    for r in results:
        mark = "PASS" if r["ok"] else "FAIL"
        print(f"[{mark}] {r['ats']:<11} status={r['status']:<15} filled={r['filled_count']:<3} "
              f"dom_controls={r['dom_controls']:<3} submit_clicked={r['submit_clicked']}")
        for f in r["failures"]:
            print(f"         ! {f}")
    print(f"\nfill  sha256[:12] = {stamp['fill']}")
    print(f"tree  sha256[:12] = {stamp['tree']}  ({stamp['files']} files)")
    print(f"artifacts: {out_dir}")
    print(f"APPLY_ENGINE_RESULT: {json.dumps({k: v for k, v in summary.items() if k != 'demos'}, separators=(',', ':'))}")
    return 0 if summary["status"] == "acceptance_pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
