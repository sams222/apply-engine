# Hunt scripts (list-only ATS recovery)

Engine-adjacent tooling for Jobright internship hunts. These scripts **never apply, confirm, or submit**. They recover a real Greenhouse / Ashby / Lever / Workday URL when Jobright only captured `jobright.ai/jobs/info/<id>`, and they keep **priority-firm** cards on the approval list instead of burying them as `near_miss_unresolved_ats`.

Canonical tree: `scripts/hunt/` (this directory). Copy into a run dir, or set `HUNT_ART=<dir>`.

| File | Role |
| --- | --- |
| `build_jobright.py` | `raw.txt` / `hrefs.json` → `cards.json`, `jobright-discovery.json`, `jobright-ats-resolved.json` |
| `run_hunt.py` | list-only hunt → `hunt_summary.md`, `apply_targets.json`, `sam_digest.md` |
| `ats_recover.py` | Jobright-only ATS recovery (Simplify any-age → careers / known Greenhouse board) + `PRIORITY_FIRMS` / `KNOWN_CAREERS` (HRT board = `wehrtyou`) |
| `test_priority_unresolved.py` | offline regression of the 2026-10-06 HRT miss |
| `fixtures/` | Greenhouse `wehrtyou` board snapshot + synthetic HRT-miss replay inputs |

## Why this exists

Hudson River Trading's Algorithm Development Intern card was dropped as `near_miss_unresolved_ats` when the only URL was jobright.ai. HRT's Greenhouse board slug is `wehrtyou` (not `hudsonrivertrading`); the careers page is JS-rendered and does not name the board. Req **7964062** is the Quant Research intern; do not attach PhD twin **8059837** by title alone. After ATS resolve, live verification can also drop a Jobright re-surface as "stale at ATS" by `first_published` — those priority roles are kept with a caveat/flag instead.

## Behavior

1. Careers URLs with `gh_jid=` count as Greenhouse; convert to the board URL when the board is known.
2. Retry ATS recovery for Jobright-only cards: Simplify any-age → careers / known board → old board-map lookup.
3. Priority firms with still-unresolved supported ATS stay on the approval list after location/pay/skip filters, flagged (`needs_explicit_approval` / `priority_unresolved`) with the Jobright URL — never bury only as near-miss.
4. Jobright-sourced priority roles that are only "stale" by ATS publish date are kept with a caveat/flag instead of dropped.
5. Do not "verify" Jobright-only links with a plain page fetch (the Jobright app is JS).

## Regression test

From the repository root (offline, no network, no live job-site applies):

```bash
python3 scripts/hunt/test_priority_unresolved.py
```

Optional networked replay (public Greenhouse / careers GETs only; still does not apply):

```bash
python3 scripts/hunt/test_priority_unresolved.py --live
```

Exit 0 means all assertions passed. Replays use a temp dir (`HUNT_ART`, `HUNT_NO_ROOT=1`, `HUNT_OFFLINE=1`).

Private applicant files (`profile.json`, resumes, ledgers, `APPLY_LOG`, `do-not-retry.json`) are **not** used and must not be added here. Optional `HUNT_ROOT` / `HUNT_ARTS` may point at a local internship-apps tree when one exists.
