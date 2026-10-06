# scripts/

Engine-adjacent tooling that is not part of the apply-engine package.

- **`scripts/hunt/`** — list-only Jobright hunt ATS recovery (priority-firm silent-drop fix). Offline regression:

```bash
python3 scripts/hunt/test_priority_unresolved.py
```

Optional `--live` hits public ATS/careers endpoints only and never applies. See `scripts/hunt/README.md`.
