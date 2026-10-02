"""What an unattended bot may submit, and what has already been submitted.

`confirm` is the only command that clicks Submit. `auto-confirm` runs it only for
queue items this module finds clean; everything else waits for the owner. The ledger
records every submission so no posting is ever submitted twice, whichever queue
file or queue id the second attempt uses.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from apply_engine import fingerprint
from apply_engine.detect import detect_ats, parse_company_from_url, parse_job_id
from apply_engine.queue import load_queue
from apply_engine.util import dump_json, load_json, now_iso

DEFAULT_DAILY_CAP = 10

# Answers an LLM guessed from a list of options must never be submitted unseen on these.
SENSITIVE = re.compile(
    r"authori[sz]|sponsor|visa|citizen|immigra|gender|\brace\b|ethnic|hispanic|latin|veteran|militar|disab|"
    r"sexual|transgender|pronoun|relocat|resid|clearance|felon|convict|criminal|government|official|"
    r"conflict of interest|relative|related to|family|salary|\bpay\b|compensation|wage|certif|attest|"
    r"signature|years of age|\bage\b|background check|drug|non-?compete|export|sanction|"
    r"intend to work|work (from|out of)|\boffice\b|\bhub\b|location",
    re.I,
)

# Notes that mean the fill itself asked for a human.
_STOP_NOTES = re.compile(r"needs_user|review essay|readback:|captcha|\bfailed:", re.I)


# --- identity ---------------------------------------------------------------

def job_keys(url: str, company: str = "", title: str = "") -> list[str]:
    """Stable identities for one posting: the ATS job id, the bare URL, and company+title."""
    keys: list[str] = []
    parsed = urlparse(url or "")
    gh = parse_qs(parsed.query).get("gh_jid")
    if gh:
        keys.append(f"greenhouse:{gh[0]}")
    ats = detect_ats(url) if url else ""
    try:
        jid = parse_job_id(url, ats) if url else ""
        slug = parse_company_from_url(url, ats) if url else ""
    except Exception:  # noqa: BLE001
        jid, slug = "", ""
    if ats and jid:
        keys.append(f"{ats}:{(slug or '').lower()}:{jid.lower()}")
    if parsed.netloc:
        keys.append("url:" + (parsed.netloc + parsed.path).lower().rstrip("/"))
    if company and title:
        keys.append("role:" + re.sub(r"[^a-z0-9]+", " ", f"{company} | {title}".lower()).strip())
    return list(dict.fromkeys(keys))


def profile_sha(path: str | Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]
    except OSError:
        return ""


# --- ledger -----------------------------------------------------------------

def ledger_path(paths: dict) -> Path:
    return Path(paths["queue_dir"]).parent / "submitted-ledger.json"


def load_ledger(paths: dict) -> list[dict[str, Any]]:
    path = ledger_path(paths)
    if not path.exists():
        return []
    raw = load_json(path)
    return list(raw.get("submitted") or []) if isinstance(raw, dict) else []


def record_submission(paths: dict, item: dict[str, Any]) -> None:
    from apply_engine.queue import _locked

    path = ledger_path(paths)
    with _locked(path):
        rows = load_ledger(paths)
        rows.append({
            "queue_id": item.get("id"),
            "company": item.get("company"),
            "title": item.get("job_title"),
            "url": item.get("url"),
            "keys": job_keys(str(item.get("url") or ""), str(item.get("company") or ""), str(item.get("job_title") or "")),
            "submitted_at": now_iso(),
        })
        dump_json(path, {"submitted": rows})


def previous_submission(paths: dict, url: str, company: str = "", title: str = "",
                        exclude_id: str | None = None) -> dict[str, Any] | None:
    """The earlier submission of this posting, from the ledger or any queue item marked submitted."""
    wanted = set(job_keys(url, company, title))
    for row in load_ledger(paths):
        if row.get("queue_id") != exclude_id and wanted & set(row.get("keys") or []):
            return row
    queue = load_queue(Path(paths["queue"])) if Path(paths["queue"]).exists() else {"items": []}
    for item in queue.get("items") or []:
        if item.get("id") == exclude_id or item.get("status") != "submitted":
            continue
        keys = job_keys(str(item.get("url") or ""), str(item.get("company") or ""), str(item.get("job_title") or ""))
        if wanted & set(keys):
            return {"queue_id": item.get("id"), "url": item.get("url"), "submitted_at": item.get("updated_at")}
    return None


def submitted_on(paths: dict, day: date) -> list[dict[str, Any]]:
    return [r for r in load_ledger(paths) if str(r.get("submitted_at") or "").startswith(day.isoformat())]


# --- the gate ---------------------------------------------------------------

def approval_stamp(item: dict[str, Any]) -> dict[str, str]:
    """What the owner approved: this exact fill, from this build and this profile."""
    return {"tree": str((item.get("fingerprint") or {}).get("tree") or ""), "profile_sha": str(item.get("profile_sha") or ""),
            "updated_at": str(item.get("updated_at") or ""), "approved_at": now_iso()}


def approved(item: dict[str, Any]) -> bool:
    stamp = item.get("approval") or {}
    return bool(stamp) and all(stamp.get(k) == str(v) for k, v in (
        ("tree", (item.get("fingerprint") or {}).get("tree") or ""),
        ("profile_sha", item.get("profile_sha") or ""),
        ("updated_at", item.get("updated_at") or ""),
    ))


def blockers(item: dict[str, Any], paths: dict, *, daily_cap: int = DEFAULT_DAILY_CAP,
             today: date | None = None) -> list[str]:
    """Reasons this queue item may not be submitted without the owner looking at it. Empty means go."""
    out: list[str] = []
    today = today or date.today()
    if item.get("status") != "waiting_confirm":
        out.append(f"status is {item.get('status')}, not waiting_confirm")
    stamp = item.get("fingerprint") or {}
    if stamp.get("tree") != fingerprint.stamp().get("tree"):
        out.append("filled by an older engine build; re-run apply first")
    if item.get("profile_sha") != profile_sha(item.get("profile_path") or paths["profile"]):
        out.append("profile changed since this fill; re-run apply first")
    for note in item.get("notes") or []:
        if _STOP_NOTES.search(str(note)):
            out.append(f"fill note: {str(note)[:160]}")
    if not approved(item):
        for row in item.get("filled") or []:
            method = str(row.get("method") or "")
            label = str(row.get("label") or "")
            if method == "llm-essay":
                out.append(f"drafted essay needs your approval: {label[:90]}")
            elif method.startswith("llm") and SENSITIVE.search(label):
                out.append(f"LLM guessed a sensitive answer: {label[:90]} -> {str(row.get('value'))[:60]}")
    attached = any(str(r.get("method") or "") == "file" for r in item.get("filled") or []) or any(
        "resume already attached" in str(n) for n in item.get("notes") or [])
    if not attached:
        out.append("no proof the current resume is attached")
    if (item.get("extra") or {}).get("readback_problems"):
        out.append("readback disagrees with the screenshot")
    earlier = previous_submission(paths, str(item.get("url") or ""), str(item.get("company") or ""),
                                  str(item.get("job_title") or ""), exclude_id=item.get("id"))
    if earlier:
        out.append(f"already submitted as {earlier.get('queue_id')} on {str(earlier.get('submitted_at'))[:10]}")
    if len(submitted_on(paths, today)) >= daily_cap:
        out.append(f"daily cap of {daily_cap} submissions reached")
    return list(dict.fromkeys(out))


# --- digest -----------------------------------------------------------------

def digest(paths: dict, day: date | None = None, gate_results: dict[str, list[str]] | None = None) -> str:
    """Markdown summary for the owner: what went in today and what is waiting on them."""
    day = day or date.today()
    queue = load_queue(Path(paths["queue"])) if Path(paths["queue"]).exists() else {"items": []}
    items = queue.get("items") or []
    lines = [f"# Apply digest {day.isoformat()}", ""]
    sent = submitted_on(paths, day)
    lines.append(f"## Submitted today ({len(sent)})")
    lines += [f"- {r.get('company')}: {r.get('title')} ({r.get('queue_id')})" for r in sent] or ["- none"]
    lines.append("")
    waiting = [i for i in items if i.get("status") in {"needs_user", "waiting_confirm", "submit_failed", "fill_error"}]
    lines.append(f"## Waiting on you ({len(waiting)})")
    for i in sorted(waiting, key=lambda i: str(i.get("updated_at") or ""), reverse=True):
        reasons = (gate_results or {}).get(str(i.get("id"))) or [
            str(n)[:160] for n in (i.get("notes") or []) if _STOP_NOTES.search(str(n))
        ]
        head = f"- **{i.get('company') or '?'}**: {i.get('job_title') or i.get('url')} [{i.get('status')}] `{i.get('id')}`"
        lines.append(head)
        lines += [f"    - {r}" for r in reasons[:4]]
    if not waiting:
        lines.append("- none")
    else:
        lines += ["", "Approve drafted answers yourself with "
                  "`python -m apply_engine approve --queue-id ID`; the bot submits approved items on its next run."]
    lines.append("")
    return "\n".join(lines)


def write_digest(paths: dict, text: str, day: date | None = None) -> Path:
    day = day or date.today()
    out = Path(paths["queue_dir"]).parent / "digests" / f"{day.isoformat()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out
