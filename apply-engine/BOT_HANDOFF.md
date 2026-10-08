# Apply-engine: operating instructions for an unattended bot

You apply the owner of this checkout to internships with this engine. You never click Submit
yourself: `auto-confirm` submits only what its gate passes, and everything else
waits for the owner. Follow this file exactly. When something here does not cover a
case, stop and report it in the digest instead of improvising.

## Setup (once per fresh checkout)

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/pip install -e "apply-engine[dev]"
.venv/bin/python -m playwright install --with-deps chromium
cd apply-engine
export PY=../.venv/bin/python
export WD=scripts/with-workday-secret.py
```

Secrets come from the platform's secret settings as environment variables,
`WORKDAY_DEFAULT_PASSWORD` and `DEEPSEEK_API_KEY`. Check they exist with
`test -n "$WORKDAY_DEFAULT_PASSWORD" && test -n "$DEEPSEEK_API_KEY" && echo ok`;
never echo their values. Workday Sign In walls (`/private/login` and the apply
wizard) use that password automatically; never type it into the browser yourself.

## Private files (every session)

This repository is public and contains no personal data. The owner sends you
their private files in chat: `profile.json`, the resume PDF, `PROJECT_POOL.md`,
and, once they exist, `submitted-ledger.json` and `workday-accounts.json`
(`do-not-retry.json` is optional). Save them to one folder outside the repo,
for example `/tmp/private/`, keeping those exact file names, then:

```bash
$PY scripts/install-private.py /tmp/private/
```

It places each file under `../internship-apps/`, points the profile at the
resume, and prints `private files OK`. If it prints any `PROBLEM:` line, stop and
send the owner that output. Profile, project pool, queue, and log paths then
resolve automatically; do not pass other paths. Never commit, push, paste into a
public place, or quote the contents of these files.

`submitted-ledger.json` records every submission and is what stops a posting
from being submitted twice; `workday-accounts.json` records which Workday
tenants already have an account. Your workspace does not keep them, so at the
end of every session that ran `auto-confirm` or `apply`:

```bash
$PY scripts/install-private.py --export /tmp/private-out/
```

and send the owner both files from `/tmp/private-out/` along with the digest.
If you did not receive `submitted-ledger.json` at the start of a session but the
owner has sent one before, ask for it and do not run `auto-confirm` until you
have it.

## The only commands you may run

| Purpose | Command |
|---|---|
| Fill one posting and park it for review | `$PY $WD $PY -m apply_engine apply --url URL` |
| Submit everything the gate passes | `$PY $WD $PY -m apply_engine auto-confirm --max 5` |
| Preview what would be submitted | `$PY -m apply_engine auto-confirm --dry-run` |
| Why one item is held | `$PY -m apply_engine gate --queue-id ID` |
| Today's summary for the owner | `$PY -m apply_engine digest` |
| List the queue | `$PY -m apply_engine status` |

Every command prints one `APPLY_ENGINE_RESULT: {json}` line. Parse that line; do
not scrape the rest of the output.

## Never

- Run `confirm` or `approve`. `approve` is the owner's; `confirm` bypasses the gate.
- Read, print, copy, or `cat` anything under `~/.config/apply-engine/`, and never
  print environment variables. The wrapper `$WD` passes the Workday password to
  the engine; you never need to see it.
- Edit `internship-apps/autofill/profile.json`, `PROJECT_POOL.md`,
  `do-not-retry.json`, or any file under `apply-engine/`. The engine itself
  updates `workday-accounts.json` and `submitted-ledger.json`; you only export them.
- `git add` or commit anything under `internship-apps/`.
- Pass `--tailored-resume` or `--headed`.
- Run more than 3 `apply` commands at once, or apply to the same URL twice in a day.
- Fill in, type into, or submit any application form outside this engine.
- Create accounts on job sites yourself.

## Choosing postings

Apply only to postings that are all of:

- an internship or co-op for Summer 2027, Fall 2027, or Winter/Spring 2027-2028
  (check the profile for other terms the owner accepts);
- open to undergraduates (skip PhD-only and MBA-only roles);
- software, applied AI / ML, data engineering, or full-stack work, in that order
  of preference (skip sales, design, finance, and hardware roles unless the owner asks);
- on Greenhouse, Lever, Ashby, or Workday.

Skip a posting if `apply` exits with status `do_not_retry`, `already_submitted`, or `needs_browser`.

## What each result means

| status | Do this |
|---|---|
| `waiting_confirm` | Nothing. `auto-confirm` decides. |
| `needs_user` | Do not retry, except once for "form not ready", "timeout", or "error page". It appears in the digest for the owner. |
| `needs_browser` | Hand off. Do not retry in this engine (Greenhouse HTTP 406 / WAF). It appears in the digest for the owner. |
| `already_submitted`, `do_not_retry` | Skip. Never retry. |
| `error` | Retry once, later. If it fails again, leave it for the digest. |

## Daily routine

1. Collect up to 15 new postings that match the rules above.
2. Run `apply` for each (at most 3 in parallel).
3. Run `auto-confirm --max 5`. It will not exceed 10 submissions per day, will not
   submit a posting twice, and holds anything with drafted essays, LLM-guessed
   legal/EEO/location answers, stale fills, missing resume, or unanswered
   required questions.
4. Run `digest` and send the owner the contents of the file it names
   (`internship-apps/digests/YYYY-MM-DD.md`).

The owner approves held items at their own terminal. Approved items go out on your next
`auto-confirm` run, provided the engine and profile have not changed since; if
they have, the gate asks for a fresh `apply`, which you should run.

## Recommended for the owner

Give the bot only the two secrets above and the private files listed under
"Private files", and nothing else from this machine. It needs no write access
to the repository.
