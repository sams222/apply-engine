# Apply-engine (Applier)
Private apply-engine for Jordan Avery's Grok Bot **Applier**. After hunting lands a job URL, this CLI:

1. Loads `profile.json` + `PROJECT_POOL.md`
2. Tailors a **truthful** resume (reorder / emphasize real pool entries only — never invent GPA, employers, or projects)
3. Writes `resumes/<company>-<slug>.pdf`
4. Opens the apply URL in Playwright, detects Greenhouse / Ashby / Lever / **Workday** (generic fallback), and fills from profile + grounded answers
5. **Hard-stops before Submit.** Writes a review artifact and exits 0 with `waiting_confirm`
6. `confirm --queue-id` is the **only** command that may click Submit (Applier may call it immediately after `apply`)

Jobright, browser extensions, and stock PDF autofill are **not** resume customization. This package is.


## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
# or: pip install -r requirements.txt pytest
playwright install chromium
```


```bash
python -m apply_engine --help
python -m pytest
python -m apply_engine demo
```

`demo` tailors against a fake React Native JD, fills the local Greenhouse-like fixture, and proves Submit was not clicked.

## CLI

```bash
python -m apply_engine tailor --jd-url URL --out resumes/company-slug.pdf
python -m apply_engine fill --url URL --resume PATH --profile PATH --queue-id ID
python -m apply_engine apply --url URL          # tailor + fill, then park
python -m apply_engine status
python -m apply_engine confirm --queue-id ID    # only place that may submit
python -m apply_engine detect --url URL
python -m apply_engine fingerprint             # this tree's identity
```

Every command prints JSON and a final `APPLY_ENGINE_RESULT: {...}` line for Applier to parse.

### Typical path (job URL → parked form)

```bash
python -m apply_engine apply \
  --url "https://job-boards.greenhouse.io/linkedin/jobs/5079761" \
  --profile examples/profile.json \
  --pool examples/PROJECT_POOL.md \
  --queue apply-queue.json \
  --log APPLY_LOG.md
```

That command:

- Fetches the JD (Greenhouse Job Board API when the host matches)
- Scores pool entries against the JD and writes a PDF under `resumes/`
- Fills First Name / Email / Resume / mapped selects
- Screenshots `queue/<id>/screenshot.png`
- Appends `APPLY_LOG.md`
- Exits 0 with `"status": "waiting_confirm"` and `"submit_clicked": false`

Then a human reviews the form (or the screenshot + `queue/<id>/review.json`). Only then:

```bash
python -m apply_engine confirm --queue-id ID --queue apply-queue.json
```

`confirm` re-opens the URL, fills again, and clicks Submit. It sets `APPLY_ENGINE_CONFIRM=1` in-process; `fill` / `apply` never set that flag.

`--headed` keeps Chromium visible.

## Dry-run against a public Greenhouse board

LinkedIn hosts a public Greenhouse **test** posting (not a real job) that is useful as a live ATS dry-run:

<https://job-boards.greenhouse.io/linkedin/jobs/5079761>

```bash
python -m apply_engine detect --url "https://job-boards.greenhouse.io/linkedin/jobs/5079761"
# {"url": "...", "ats": "greenhouse"}

python -m apply_engine tailor \
  --jd-url "https://job-boards.greenhouse.io/linkedin/jobs/5079761" \
  --profile examples/profile.json \
  --pool examples/PROJECT_POOL.md

python -m apply_engine apply \
  --url "https://job-boards.greenhouse.io/linkedin/jobs/5079761" \
  --profile examples/profile.json \
  --pool examples/PROJECT_POOL.md
```

Use the example profile (`@example.com`). Do **not** run `confirm` on a posting you do not intend to submit. `apply` already stops at review.

If the live board is down, `python -m apply_engine demo` is the same pipeline against `tests/fixtures/greenhouse.html`.

## How Applier (Grok Bot) should call this

The bot already owns hunting plus:

| File | Role |
| --- | --- |
| `internship-apps/autofill/profile.json` | Source of truth for identity, school, work auth, EEO |
| `internship-apps/PROJECT_POOL.md` | Truthful project / intern / program bullets |
| `internship-apps/apply-queue.json` | Queue (`{"items":[...]}` or a bare list) |
| `internship-apps/APPLY_LOG.md` | Append-only log |

If those paths exist, they are auto-detected. Otherwise pass flags.

`internship-apps/` is gitignored: it holds the applicant's personal data. Put the
private files in place with `python scripts/install-private.py FOLDER` (see the
script's docstring and `BOT_HANDOFF.md`); `--check` validates them and `--export DEST`
copies out the submission ledger and Workday account map, which the engine updates.

```bash
python -m apply_engine apply \
  --url "$JOB_URL" \
  --profile internship-apps/autofill/profile.json \
  --pool internship-apps/PROJECT_POOL.md \
  --queue internship-apps/apply-queue.json \
  --log internship-apps/APPLY_LOG.md \
  --queue-id "$QUEUE_ID"
```

Parse `APPLY_ENGINE_RESULT`. On `waiting_confirm`, Applier should call `confirm` immediately (autonomous apply is authorized). The engine still requires that explicit `confirm` command and `APPLY_ENGINE_CONFIRM=1`; `apply` never submits on its own.

```bash
python -m apply_engine confirm --queue-id "$QUEUE_ID" --queue internship-apps/apply-queue.json
```

**Which resume gets attached:** `apply` sends `profile.resume_path` — the
candidate's own resume. Tailoring still runs on every apply (it grounds the
open-ended answers and records which real pool entries matched the JD), but its
generated PDF is opt-in via `--tailored-resume`, because the generated document
was thinner and more dated than the real one. If `resume_path` is missing the
run errors out rather than substituting a previously generated PDF.

Optional leftover essays: set `GROK_API_KEY` (xAI) or `OPENAI_API_KEY`. The LLM is fact-locked to profile + pool and must return `SKIP` rather than invent. Deterministic field maps always win for Greenhouse / Ashby / Lever / Workday name / email / phone / LinkedIn / GitHub / work-auth / sponsorship / EEO / resume.

## Workday

Workday hosts (`*.myworkdayjobs.com`, `*.wd1.myworkdayjobs.com`, `wd5.myworkdayjobs.com`, …) detect as `workday`.

Account create / sign-in (every tenant, same credentials):

| | |
| --- | --- |
| Email | `jordan.avery@example.org` (or `profile.email` when set — they should match) |
| Password | **only** from env `WORKDAY_DEFAULT_PASSWORD` |

The password is never written to git, review JSON, or `workday-accounts.json`. If the env var is missing, `apply` / `fill` exit 2 with `APPLY_ENGINE_RESULT` `status: error` and do not invent a password.

```bash
export WORKDAY_DEFAULT_PASSWORD='…'
python -m apply_engine apply --url "https://acme.wd1.myworkdayjobs.com/en-US/careers/job/NYC/Intern_R1"
python -m apply_engine confirm --queue-id "$QUEUE_ID"
```

Tenant emails (no passwords) are stored at `internship-apps/autofill/workday-accounts.json` when that tree exists, otherwise `queue/workday-accounts.json`, so the next visit to the same host can prefer Sign In.

The wizard walks My Information → Experience (resume PDF) → Education → EEO/self-ID when present → Review. Next/Continue is allowed; **Submit Application** still requires `confirm`.

If the wizard stepper shows **Create Account/Sign In** but email/password have not painted (blank shell / late iframe), the engine waits for the widgets, reloads the live Workday page once, then tries the **header** Sign In link. It does not click in-form Sign In while Verify New Password is showing, does not continue the wizard, and strips `workday-auth` filled rows unless My Information is reached.

Standalone Sign In walls (`/login`, `/private/login`, heading **Sign In** with one password and no Verify New Password) are filled whenever they appear — apply entry, mid-wizard redirects, confirm re-open, and post-apply My Applications / private-area bounces — using `profile.email` and `WORKDAY_DEFAULT_PASSWORD`. Selectors prefer `data-automation-id="email"` / `"password"`; honeypots (`beecatcher`, website traps) stay empty. When `workday-accounts.json` already has this tenant email, Sign In is preferred over Create Account.


**Limits:** CAPTCHA, email verification, and 2FA still block unattended apply. The engine records a note and parks at `waiting_confirm` instead of guessing. Greenhouse / Ashby / Lever paths are unchanged.

## Data shapes

See `examples/profile.json` and `examples/PROJECT_POOL.md`.
Profile fields: `full_name`, `first_name`, `last_name`, `email`, `phone`, `linkedin`, `github`, `location`, `city`, `state`, `country`, `school`, `degree`, `gpa`, `graduation`, `work_authorized_us`, `need_sponsorship`, `eeo.{gender,race_ethnicity,veteran,disability}`, `resume_path`, `preferred_locations`.

`gpa` is omitted in the example on purpose. If it is `null`, the engine leaves GPA fields blank.

Pool entries are `## Title` sections with `kind:` (`experience` / `project` / `program`), `tags:`, and `-` bullets. Tailoring scores tags against the JD and reorders. Skills printed on the PDF are an intersection of **real** pool/profile skills with the JD — leftover JD terms such as Kubernetes are dropped unless they already exist in the pool.

## Tests

```bash
python -m pytest
```

- ATS host/HTML heuristics including Workday (`tests/test_ats_detect.py`)
- Tailor keyword selection from the pool given `tests/fixtures/fake_jd.md` (`tests/test_tailor.py`)
- Submit guard: fill never clicks Submit; `submit=True` requires `APPLY_ENGINE_CONFIRM=1` (`tests/test_no_submit.py`)
- Workday: password env required, never stored; wizard fixture does not submit without confirm; blank Create Account/Sign In shell wait/reload/header recovery (`tests/test_workday.py`); standalone `/private/login` Sign In fill leaves the beecatcher empty (`tests/test_workday_standalone_signin.py`)

## do-not-retry

Some companies must never be opened again — a burned application, a rejection,
or a board that has proven unfillable. The engine refuses them **before** a
browser launches or a PDF is rendered:

```bash
python -m apply_engine apply --url "https://careers.doordash.com/jobs/1"
# APPLY_ENGINE_RESULT: {"status":"do_not_retry","blocked_token":"doordash",...}
# exit code 3
```

`motorola`, `doordash`, and `bedrock` are hard-coded as `SEED` in
`apply_engine/retry_policy.py`; emptying or corrupting the JSON file cannot
re-enable them. Add more in `internship-apps/do-not-retry.json`:

```json
{"companies": ["initech", "acme"]}
```

Matching is on normalized company name, host, and the first two path segments,
so `job-boards.greenhouse.io/bedrockrobotics/jobs/1` is caught by `bedrock`.

**Exit codes:** `0` waiting_confirm / submitted · `1` fill failure ·
`2` config error (e.g. missing Workday password) · `3` do_not_retry.

## Filled-log vs screenshot

The engine's worst failure is a filled log that claims success while the
screenshot shows an empty form (9372e5: auth rows claimed email/password while
the screenshot showed an empty Sign In). `confirm` trusts that log, so the two
must agree.

At screenshot time the engine also snapshots every rendered control value
(`extra.dom_snapshot`) and diffs it against the filled log
(`extra.readback_problems`). On a multi-step Workday wizard it additionally
screenshots **each step before Next**, with a matching value snapshot, so a
field counts as proven when some step screenshot actually shows it:

```
queue/<id>/screenshot.png                 final render
queue/<id>/step-0-my-information.png      My Information, filled
queue/<id>/step-1-step-1.png              …
```

`confirm` refuses outright when the log and the pixels disagree on `state`,
`postal_code`, `phone`, `previous_employee`, `email`, or name. Passwords are
snapshotted as `[present]`, never as text.

## Fingerprint — one tree, one identity

Two trees drifted in the field: the box ran `fill.py` `f93d71de91e9` mid-waymo
while the shouted go was `fe0309ebfb29`, and nothing tied a screenshot to the
code that produced it. Every review artifact now carries a `fingerprint` block:

```bash
python -m apply_engine fingerprint
# {"fill": "<sha256(fill.py)[:12]>", "tree": "<sha256 over all source)[:12]>", "files": "58"}

python -m apply_engine fingerprint --manifest   # per-file hashes, to diff a drifted tree
```

`fill` is the legacy acceptance token. `tree` is the real identity: it covers
every source file with its path, ignores caches and artifacts, and is
independent of filesystem walk order. Quote `tree` when reporting a run.

## Acceptance

```bash
python scripts/acceptance.py
```

Runs the three demo fills (greenhouse, ashby, workday **past My Information**)
against the local fixtures using the **real** profile, so the values the spec
singles out are genuinely exercised — NY rendering as "New York", postal 10001,
phone digits, `previous_employee=No`, Country Phone Code left empty, and the
Workday password absent from `review.json`. Each demo writes
`artifacts/acceptance/<ats>/{screenshot.png,review.json}`; the run fails if any
field is unfilled, any readback drifts, or submit is ever clicked.

## Hard constraints

- Never treat Jobright / extension autofill as resume customization
- Never submit without `python -m apply_engine confirm --queue-id ID`
- Deterministic field maps first; LLM only for leftover open-ended questions
- Never open a do-not-retry company (motorola / doordash / bedrock are seeded)
- Never confirm when the filled log disagrees with the screenshot
- Quote the `tree` fingerprint, not an ad-hoc hash of one file

## Workday UI readback

**UI-readback policy:** a field is counted in `filled` only if the widget value after settle matches. `filled[].value` is that **readback** (button / input / selected option), never the intended profile string. Profile `state: "NY"` therefore logs `"New York"` when the State control shows New York.

Workday custom selects use four strategies (native → type-to-filter → click-scan → keyboard); each one re-reads the control. PromptSelect: JS-click → wait `promptOption` / `[role=option]` / `listItem` → substring pick → else type `searchBox` → ESC. `read_state_widget` only reads a control whose aria-label / `data-automation-id` contains state|province|region (Workday `addressSection_countryRegion` included) and never City or Country Phone Code. Option lists with `len<=1` or only `+1` codes are skipped so phone-code is not mistaken for State. Degree tries Bachelor + `BS` / `BA` / `B.S.` / `Bachelors`. Field of Study uses the **last** matching control, Playwright-clicks the option, `mouse.click`s outside, and verifies the panel closed. Previously-worked Yes/No is scoped to that `formField`; after No, employee-id/manager must stay hidden. Postal is written only after State readback matches. Phone fills `phone-number` only (never Country Phone Code) and logs the input’s digits.
