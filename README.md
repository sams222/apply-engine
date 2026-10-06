# apply-engine

Public apply-engine for unattended internship applications. After a hunt lands a job URL, the CLI in [`apply-engine/`](apply-engine/) tailors a truthful resume, fills Greenhouse / Ashby / Lever / Workday, and **hard-stops before Submit**.

See [`apply-engine/README.md`](apply-engine/README.md) for setup, CLI, and tests.

## Hunt ATS recovery (`scripts/hunt/`)

List-only Jobright tooling lives under [`scripts/hunt/`](scripts/hunt/). It recovers a real ATS URL when Jobright only captured `jobright.ai`, and it keeps priority-firm cards (e.g. Hudson River Trading Algorithm Development Intern) on the approval list instead of dropping them as `near_miss_unresolved_ats`.

Offline regression (no network, nothing applied):

```bash
python3 scripts/hunt/test_priority_unresolved.py
```

Optional `--live` replays against public Greenhouse/careers endpoints only. Details: [`scripts/hunt/README.md`](scripts/hunt/README.md).
