from __future__ import annotations

import argparse
import json
import re
import os
import sys
import uuid
from pathlib import Path

from apply_engine import __version__
from apply_engine.detect import detect_ats
from apply_engine.guard import CONFIRM_ENV, SubmitBlockedError
from apply_engine.jd import fetch_job, fetch_job_from_text
from apply_engine.paths import resolve_paths
from apply_engine.pool import load_pool
from apply_engine.profile import load_profile
from apply_engine.pdf import render_pdf
from apply_engine import fingerprint, gate, retry_policy
from apply_engine.queue import append_log, format_log_entry, get_item, load_queue, upsert_item, write_review
from apply_engine.tailor import assert_truthful, tailor
from apply_engine.util import dump_json, now_iso, slugify
from apply_engine.workday import WorkdayConfigError, require_password


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m apply_engine",
        description="Applier apply-engine: tailor a truthful resume, fill ATS forms, hard-stop before submit.",
    )
    parser.add_argument("--version", action="version", version=f"apply-engine {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_tailor = sub.add_parser("tailor", help="Fetch a JD and write a tailored resume PDF")
    _add_common(p_tailor)
    p_tailor.add_argument("--jd-url", required=True)
    p_tailor.add_argument("--jd-text", help="Optional local JD file instead of fetching")
    p_tailor.add_argument("--out", help="Output PDF path")

    p_fill = sub.add_parser("fill", help="Open apply URL, fill fields, stop before submit")
    _add_common(p_fill)
    p_fill.add_argument("--url", required=True)
    p_fill.add_argument("--resume", help="Resume PDF to attach (default: latest tailored)")
    p_fill.add_argument("--queue-id", help="Queue id to update")
    p_fill.add_argument("--headed", action="store_true")
    p_fill.add_argument("--allow-req", action="append", default=[], help="Req/job id that may proceed past a company-level do-not-retry")
    p_fill.add_argument("--allow-url", action="append", default=[], help="URL that may proceed past a company-level do-not-retry")

    p_apply = sub.add_parser("apply", help="Tailor + fill, then park for review (never submits)")
    _add_common(p_apply)
    p_apply.add_argument("--url", required=True)
    p_apply.add_argument("--queue-id")
    p_apply.add_argument("--headed", action="store_true")
    p_apply.add_argument("--out", help="Output PDF path")
    p_apply.add_argument(
        "--tailored-resume",
        action="store_true",
        help="Attach a generated resume built from PROJECT_POOL instead of profile.resume_path",
    )
    p_apply.add_argument("--jd-text")
    p_apply.add_argument("--allow-req", action="append", default=[], help="Req/job id that may proceed past a company-level do-not-retry")
    p_apply.add_argument("--allow-url", action="append", default=[], help="URL that may proceed past a company-level do-not-retry")

    p_status = sub.add_parser("status", help="List apply-queue items")
    _add_common(p_status)

    p_confirm = sub.add_parser("confirm", help="ONLY command that may click Submit")
    _add_common(p_confirm)
    p_confirm.add_argument("--queue-id", required=True)
    p_confirm.add_argument("--headed", action="store_true")

    p_gate = sub.add_parser("gate", help="Say whether a waiting item may be submitted unattended, and why not")
    _add_common(p_gate)
    p_gate.add_argument("--queue-id", required=True)
    p_gate.add_argument("--daily-cap", type=int, default=gate.DEFAULT_DAILY_CAP)

    p_auto = sub.add_parser("auto-confirm", help="Confirm only the waiting items the gate passes; write a digest")
    _add_common(p_auto)
    p_auto.add_argument("--max", type=int, default=5, help="Most submissions this run")
    p_auto.add_argument("--daily-cap", type=int, default=gate.DEFAULT_DAILY_CAP)
    p_auto.add_argument("--dry-run", action="store_true")

    p_approve = sub.add_parser("approve", help="(owner only, interactive) approve one fill's drafted answers")
    _add_common(p_approve)
    p_approve.add_argument("--queue-id", required=True)

    p_digest = sub.add_parser("digest", help="Write and print the day's submitted / waiting-on-you summary")
    _add_common(p_digest)
    p_digest.add_argument("--date", help="YYYY-MM-DD (default today)")

    p_detect = sub.add_parser("detect", help="Print ATS guess for a URL")
    p_detect.add_argument("--url", required=True)

    p_demo = sub.add_parser("demo", help="Local Greenhouse-like form: fill and hard-stop")
    _add_common(p_demo)

    p_fp = sub.add_parser("fingerprint", help="Print this tree's identity (fill + tree sha256)")
    p_fp.add_argument("--manifest", action="store_true", help="Also print per-file hashes")

    args = parser.parse_args(argv)
    try:
        return _dispatch(args, parser)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001
        # Applier parses APPLY_ENGINE_RESULT. An unhandled traceback is
        # unparseable, so every failure exits through the same contract.
        _emit(
            {
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "cmd": getattr(args, "cmd", ""),
                "url": getattr(args, "url", "") or getattr(args, "jd_url", "") or "",
                "submit_clicked": False,
            }
        )
        return 1


def _dispatch(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.cmd == "detect":
        print(json.dumps({"url": args.url, "ats": detect_ats(args.url)}, indent=2))
        return 0
    if args.cmd == "fingerprint":
        payload = dict(fingerprint.stamp())
        if args.manifest:
            payload["manifest"] = fingerprint.manifest()
        _emit(payload)
        return 0
    if args.cmd == "demo":
        return cmd_demo(args)
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd == "tailor":
        return cmd_tailor(args)
    if args.cmd == "fill":
        return cmd_fill(args, submit=False)
    if args.cmd == "apply":
        return cmd_apply(args)
    if args.cmd == "confirm":
        return cmd_confirm(args)
    if args.cmd == "gate":
        return cmd_gate(args)
    if args.cmd == "auto-confirm":
        return cmd_auto_confirm(args)
    if args.cmd == "digest":
        return cmd_digest(args)
    if args.cmd == "approve":
        return cmd_approve(args)
    parser.error("unknown command")
    return 2


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--profile")
    p.add_argument("--pool")
    p.add_argument("--queue")
    p.add_argument("--log")
    p.add_argument("--resumes")


def cmd_tailor(args: argparse.Namespace) -> int:
    paths = resolve_paths(profile=args.profile, pool=args.pool, queue=args.queue, log=args.log, resumes=args.resumes)
    profile = load_profile(paths["profile"])
    pool = load_pool(paths["pool"])
    job = _job_from_args(args)
    tailored = tailor(profile, pool, job)
    assert_truthful(tailored, pool)
    out = Path(args.out) if getattr(args, "out", None) else paths["resumes"] / f"{job.slug()}.pdf"
    pdf = render_pdf(tailored, out)
    sidecar = pdf.with_suffix(".json")
    dump_json(sidecar, {**tailored.to_public_dict(), "pdf": str(pdf)})
    _emit(
        {
            "status": "tailored",
            "pdf": str(pdf),
            "sidecar": str(sidecar),
            "company": job.company,
            "title": job.title,
            "ats": job.ats,
            "projects": [e.title for e in tailored.projects],
            "matched_keywords": tailored.matched_keywords,
        }
    )
    return 0


def _reviewed_answers(review_dir: Path) -> dict[str, str]:
    """LLM-written answers from review.json (as reviewed, possibly hand-edited), keyed by label."""
    try:
        review = json.loads((review_dir / "review.json").read_text())
    except (OSError, ValueError):
        return {}
    return {
        str(row.get("label", "")): str(row.get("value", ""))
        for row in review.get("filled") or []
        if row.get("value") and (
            str(row.get("method", "")).startswith("llm")
            or str(row.get("method", "")) in {
                "radio", "checkboxes", "buttons", "select", "combobox", "already-set", "restick", "only-option",
            }
        )
    }


def cmd_fill(args: argparse.Namespace, submit: bool) -> int:
    from apply_engine.fill import fill_application

    paths = resolve_paths(profile=args.profile, pool=args.pool, queue=args.queue, log=args.log, resumes=args.resumes)
    profile = load_profile(paths["profile"])
    load_pool(paths["pool"])
    url = args.url
    blocked = _do_not_retry_error(url, paths, allow_reqs=getattr(args, "allow_req", None), allow_urls=getattr(args, "allow_url", None))
    if blocked:
        _emit(blocked)
        return 3
    err = _workday_env_error(url)
    if err:
        _emit(err)
        return 2
    queue_id = getattr(args, "queue_id", None) or _new_id(url)
    job = fetch_job(url)
    resume_path = _real_resume(paths, profile)
    if resume_path is None or not resume_path.exists():
        missing = resume_path or Path(profile.resume_path or "<profile.resume_path unset>")
        raise SystemExit(f"resume not found: {missing}. Set profile.resume_path to the real resume.")

    review_dir = paths["queue_dir"] / queue_id
    screenshot = review_dir / "screenshot.png"
    try:
        artifact = fill_application(
            url=url,
            profile=profile,
            resume=None,
            resume_path=resume_path,
            profile_path=str(paths["profile"]),
            pool_path=str(paths["pool"]),
            queue_id=queue_id,
            headed=bool(getattr(args, "headed", False)),
            screenshot_path=screenshot,
            submit=submit,
            tenant_map_path=paths["workday_accounts"],
            job=job,
            saved_answers=_reviewed_answers(review_dir) if submit else None,
            pre_submit=_pre_submit_check(getattr(args, "reviewed_item", None) or {}) if submit else None,
        )
    except WorkdayConfigError as exc:
        _emit(exc.to_result(url=url))
        return 2
    payload = _store(paths, artifact, extra={"job_title": job.title, "company": job.company})
    if artifact.status == "submitted":
        gate.record_submission(paths, {"id": artifact.id, "company": job.company, "job_title": job.title, "url": url})
    _emit(payload)
    return 0 if artifact.status in {"waiting_confirm", "submitted"} else 1


def cmd_apply(args: argparse.Namespace) -> int:
    paths = resolve_paths(profile=args.profile, pool=args.pool, queue=args.queue, log=args.log, resumes=args.resumes)
    profile = load_profile(paths["profile"])
    load_pool(paths["pool"])
    url = getattr(args, "url", None) or getattr(args, "jd_url", None)
    blocked = _do_not_retry_error(url, paths, allow_reqs=getattr(args, "allow_req", None), allow_urls=getattr(args, "allow_url", None))
    if blocked:
        _emit(blocked)
        return 3
    err = _workday_env_error(url)
    if err:
        _emit(err)
        return 2
    job = _job_from_args(args)
    # The JD may name a blocked company the URL did not.
    blocked = _do_not_retry_error(
        job.url or url,
        paths,
        job.company,
        allow_reqs=getattr(args, "allow_req", None),
        allow_urls=getattr(args, "allow_url", None),
    )
    if blocked:
        _emit(blocked)
        return 3
    earlier = gate.previous_submission(paths, job.url or url, job.company, job.title)
    if earlier:
        _emit({"status": "already_submitted", "url": job.url or url, "company": job.company,
               "previous_queue_id": earlier.get("queue_id"), "submitted_at": earlier.get("submitted_at"),
               "submit_clicked": False})
        return 3
    # Attach the candidate's own resume. Tailoring is a separate command.
    attach = _real_resume(paths, profile)
    if attach is None or not attach.exists():
        attach = attach or Path(profile.resume_path or "<profile.resume_path unset>")
        _emit(
            {
                "status": "error",
                "error": f"resume not found: {attach}. Set profile.resume_path to the real resume.",
                "url": job.url or url,
                "submit_clicked": False,
            }
        )
        return 2

    from apply_engine.fill import fill_application

    queue_id = args.queue_id or _new_id(job.url)
    review_dir = paths["queue_dir"] / queue_id
    try:
        artifact = fill_application(
            url=job.apply_url or job.url,
            profile=profile,
            resume=None,
            resume_path=attach,
            profile_path=str(paths["profile"]),
            pool_path=str(paths["pool"]),
            queue_id=queue_id,
            headed=bool(args.headed),
            screenshot_path=review_dir / "screenshot.png",
            submit=False,
            tenant_map_path=paths["workday_accounts"],
            job=job,
        )
    except WorkdayConfigError as exc:
        _emit(exc.to_result(url=job.url))
        return 2
    payload = _store(
        paths,
        artifact,
        extra={"job_title": job.title, "company": job.company, "pdf": str(attach)},
    )
    _emit(payload)
    return 0



def _do_not_retry_error(
    url: str,
    paths: dict,
    company: str = "",
    allow_reqs: list[str] | None = None,
    allow_urls: list[str] | None = None,
) -> dict | None:
    """Refuse blocked jobs before a browser or PDF is ever created."""
    if not url:
        return None
    blocked = retry_policy.check(
        url,
        company,
        paths.get("do_not_retry"),
        allow_reqs=allow_reqs,
        allow_urls=allow_urls,
    )
    if blocked is None:
        return None
    return retry_policy.result_payload(blocked, url, company)


def _assert_safe_profile(path: Path) -> Path:
    """Refuse demo/example profiles so confirm cannot overwrite real fills."""
    resolved = Path(path).expanduser().resolve()
    parts = {p.lower() for p in resolved.parts}
    if "examples" in parts and resolved.name == "profile.json":
        raise SystemExit(
            f"refusing demo profile {resolved}. Pass --profile to internship-apps/autofill/profile.json "
            "or ensure the queue item stores that profile_path from apply."
        )
    if not resolved.exists():
        raise SystemExit(f"profile not found: {resolved}")
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"cannot read profile {resolved}: {exc}") from exc
    email = str(data.get("email") or "")
    phone = str(data.get("phone") or "")
    linkedin = str(data.get("linkedin") or "")
    github = str(data.get("github") or "")
    bad = []
    if "example.com" in email.lower():
        bad.append(f"email={email!r}")
    if re.search(r"555[-.\s]?0?100\b", phone):
        bad.append(f"phone={phone!r}")
    if re.search(r"linkedin\.com/in/jordan-avery-demo/?$", linkedin, re.I):
        bad.append(f"linkedin={linkedin!r} (demo)")
    if re.search(r"github\.com/jordanavery/?$", github, re.I):
        bad.append(f"github={github!r} (demo)")
    if bad:
        raise SystemExit(f"refusing placeholder contact in {resolved}: " + ", ".join(bad))
    return resolved


# Rows that prove nothing about the application itself.
_NON_APPLICATION_KEYS = {"workday_password", "email", "workday_auth", ""}


def _assert_application_filled(item: dict) -> None:
    """Refuse confirm when nothing but auth was filled.

    A Workday run that signs in and then hits a soft-fail page still reports
    waiting_confirm with an empty skipped list, so neither the required-field
    guard nor the readback guard fires. Confirming that would submit a blank
    application.
    """
    filled = item.get("filled") or []
    real = {
        str(row.get("mapped_to") or "")
        for row in filled
        if isinstance(row, dict) and str(row.get("mapped_to") or "") not in _NON_APPLICATION_KEYS
    }
    if len(real) >= 3:
        return
    raise SystemExit(
        "refusing confirm: only "
        + (", ".join(sorted(real)) if real else "auth")
        + " was filled — the application form was never completed. "
        "Re-run apply and review the screenshot."
    )


def _assert_readback_clean(item: dict) -> None:
    """Refuse confirm when the filled log disagrees with the rendered form.

    The screenshot is the reviewer's evidence. If the log claims a value the
    form never showed, confirm would submit something nobody reviewed.
    """
    problems = ((item.get("extra") or {}).get("readback_problems")) or []
    if not problems:
        return
    lines = [
        f"{p.get('mapped_to')}: logged {p.get('logged')!r} but form showed {p.get('shown')!r}"
        for p in problems
        if isinstance(p, dict)
    ]
    raise SystemExit(
        "refusing confirm: filled log does not match the screenshot: "
        + "; ".join(lines[:6])
        + ". Re-run apply and review before confirming."
    )


def _assert_confirmable(item: dict) -> None:
    """Block confirm when required fields were skipped on the waiting_confirm fill."""
    skipped = item.get("skipped") or []
    blockers: list[str] = []
    for raw in skipped:
        if isinstance(raw, dict):
            label = str(raw.get("label") or "")
            reason = str(raw.get("reason") or "")
        else:
            label, reason = str(raw), ""
        low = label.lower().strip()
        if not low or low.startswith("unknown"):
            continue
        from apply_engine.fields import is_noise_field

        if is_noise_field(label):
            continue
        # Hidden Google reCAPTCHA textarea is filled by the widget on submit — never a confirm blocker.
        if "captcha" in low or "recaptcha" in low or "g-recaptcha" in low:
            continue
        if label.rstrip().endswith("*"):
            blockers.append(label)
            continue
        if low in {"name", "first_name", "last_name", "full_name", "country", "citizenship status"}:
            blockers.append(label)
            continue
        # Avoid false positives like "company name(s)" in long optional prompts.
        import re as _re
        if reason == "unmapped" and (
            _re.search(r"\b(country|citizen|citizenship|relocat|authoriz)\b", low)
            or _re.search(r"^(name|full name|first name|last name)\b", low)
        ):
            blockers.append(label)
    if blockers:
        uniq = list(dict.fromkeys(blockers))
        raise SystemExit(
            "refusing confirm: required/identity fields still skipped: "
            + "; ".join(uniq[:12])
            + ("…" if len(uniq) > 12 else "")
            + ". Leave as waiting_confirm/needs_user and fix mapping."
        )

_DRIFT_SKIP_METHODS = {"file", "workday-auth", "fail"}
_DRIFT_SKIP_KEYS = {"today", "workday_password", "password", "email"}


def _norm_value(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _answer_drift(reviewed: dict, fresh: dict) -> list[str]:
    """Answers the confirm refill typed differently from the reviewed fill."""
    def by_label(rows: list) -> dict[str, dict]:
        return {str(r.get("label") or "")[:160]: r for r in rows or [] if isinstance(r, dict)
                and str(r.get("method") or "") not in _DRIFT_SKIP_METHODS
                and str(r.get("mapped_to") or "") not in _DRIFT_SKIP_KEYS}

    before, after = by_label(reviewed.get("filled")), by_label(fresh.get("filled"))
    out = []
    for label, row in before.items():
        now = after.get(label)
        if now is None:
            if str(row.get("method") or "").startswith("llm"):
                out.append(f"reviewed answer not typed: {label[:80]}")
            continue
        if _norm_value(now.get("value")) != _norm_value(row.get("value")):
            out.append(f"answer changed: {label[:80]}: reviewed {str(row.get('value'))[:40]!r}, "
                       f"now {str(now.get('value'))[:40]!r}")
    return out


def _pre_submit_check(reviewed: dict):
    def check(fresh: dict) -> list[str]:
        out: list[str] = []
        for guard in (_assert_confirmable, _assert_readback_clean, _assert_application_filled):
            try:
                guard(fresh)
            except SystemExit as exc:
                out.append(str(exc))
        out += [f"fill note: {str(n)[:120]}" for n in fresh.get("notes") or []
                if re.search(r"needs_user|captcha", str(n), re.I)]
        if reviewed:
            out += _answer_drift(reviewed, fresh)
        return out

    return check


def cmd_gate(args: argparse.Namespace) -> int:
    paths = resolve_paths(profile=args.profile, pool=args.pool, queue=args.queue, log=args.log, resumes=args.resumes)
    item = get_item(paths["queue"], args.queue_id)
    reasons = _gate_reasons(item, paths, args.daily_cap)
    _emit({"queue_id": args.queue_id, "ok": not reasons, "blockers": reasons})
    return 0 if not reasons else 1


def _gate_reasons(item: dict, paths: dict, daily_cap: int) -> list[str]:
    reasons = gate.blockers(item, paths, daily_cap=daily_cap)
    for guard in (_assert_confirmable, _assert_readback_clean, _assert_application_filled):
        try:
            guard(item)
        except SystemExit as exc:
            reasons.append(str(exc))
    return list(dict.fromkeys(reasons))


def cmd_auto_confirm(args: argparse.Namespace) -> int:
    """Submit every waiting item the gate passes, up to the caps; report the rest."""
    paths = resolve_paths(profile=args.profile, pool=args.pool, queue=args.queue, log=args.log, resumes=args.resumes)
    items = [i for i in load_queue(paths["queue"]).get("items") or [] if i.get("status") == "waiting_confirm"]
    results: dict[str, list[str]] = {}
    submitted, attempted = [], 0
    for item in sorted(items, key=lambda i: str(i.get("updated_at") or "")):
        qid = str(item.get("id"))
        reasons = _gate_reasons(item, paths, args.daily_cap)
        if not reasons and attempted >= args.max:
            reasons = [f"--max {args.max} reached for this run"]
        if reasons or args.dry_run:
            results[qid] = reasons or ["dry run: would submit"]
            continue
        attempted += 1
        ns = argparse.Namespace(profile=args.profile, pool=args.pool, queue=str(paths["queue"]), log=args.log,
                                resumes=args.resumes, queue_id=qid, headed=False)
        try:
            cmd_confirm(ns)
        except SystemExit as exc:
            results[qid] = [f"confirm refused: {exc}"]
            continue
        after = get_item(paths["queue"], qid)
        if after.get("status") == "submitted":
            submitted.append(qid)
        else:
            results[qid] = [str(n)[:160] for n in after.get("notes") or [] if "needs_user" in str(n)] or [
                f"confirm ended as {after.get('status')}"]
    text = gate.digest(paths, gate_results=results)
    out = gate.write_digest(paths, text)
    _emit({"submitted": submitted, "held": results, "digest": str(out), "dry_run": bool(args.dry_run)})
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    """The owner signs off on the drafted essays and LLM-picked answers of one fill. Interactive only."""
    paths = resolve_paths(profile=args.profile, pool=args.pool, queue=args.queue, log=args.log, resumes=args.resumes)
    item = get_item(paths["queue"], args.queue_id)
    if not sys.stdin.isatty():
        raise SystemExit("approve must be run by a person at a terminal")
    print(f"\n{item.get('company')}: {item.get('job_title')}\n{item.get('url')}\nscreenshot: {item.get('screenshot')}\n")
    for row in item.get("filled") or []:
        if str(row.get("method") or "").startswith("llm"):
            print(f"--- {row.get('label')}\n{row.get('value')}\n")
    typed = input(f"Type the company name ({item.get('company')}) to approve, anything else to cancel: ")
    if typed.strip().lower() != str(item.get("company") or "").strip().lower():
        print("not approved")
        return 1
    item["approval"] = gate.approval_stamp(item)
    upsert_item(paths["queue"], item)
    write_review(paths["queue_dir"] / str(item["id"]), item)
    print("approved; auto-confirm may now submit it")
    return 0


def cmd_digest(args: argparse.Namespace) -> int:
    from datetime import datetime

    paths = resolve_paths(profile=args.profile, pool=args.pool, queue=args.queue, log=args.log, resumes=args.resumes)
    day = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else None
    text = gate.digest(paths, day)
    out = gate.write_digest(paths, text, day)
    print(text)
    print(f"APPLY_ENGINE_RESULT: {json.dumps({'digest': str(out)})}")
    return 0


def cmd_confirm(args: argparse.Namespace) -> int:
    paths = resolve_paths(profile=args.profile, pool=args.pool, queue=args.queue, log=args.log, resumes=args.resumes)
    item = get_item(paths["queue"], args.queue_id)
    if item.get("status") not in {"waiting_confirm", "fill_error", "submit_failed"}:
        raise SystemExit(f"queue item {args.queue_id} is {item.get('status')}, not waiting_confirm")
    blocked = _do_not_retry_error(
        str(item.get("url") or ""), paths, str(item.get("company") or "")
    )
    if blocked:
        _emit(blocked)
        return 3
    earlier = gate.previous_submission(paths, str(item.get("url") or ""), str(item.get("company") or ""),
                                       str(item.get("job_title") or ""), exclude_id=args.queue_id)
    if earlier:
        raise SystemExit(f"refusing confirm: this posting was already submitted as {earlier.get('queue_id')} "
                         f"on {str(earlier.get('submitted_at'))[:10]}")

    # Prefer paths saved on the queue item from apply/fill — never re-resolve to examples/.
    profile_path = item.get("profile_path") or args.profile or str(paths["profile"])
    pool_path = item.get("pool_path") or args.pool or str(paths["pool"])
    profile_path = str(_assert_safe_profile(Path(profile_path)))
    _assert_confirmable(item)
    _assert_readback_clean(item)
    _assert_application_filled(item)

    os.environ[CONFIRM_ENV] = "1"
    try:
        ns = argparse.Namespace(
            profile=profile_path,
            pool=str(Path(pool_path).expanduser().resolve()),
            queue=str(paths["queue"]),
            log=str(paths["log"]),
            resumes=str(paths["resumes"]),
            url=item["url"],
            resume=item.get("resume_path"),
            queue_id=args.queue_id,
            headed=bool(args.headed),
            reviewed_item=item,
        )
        return cmd_fill(ns, submit=True)
    except SubmitBlockedError as exc:
        print(f"submit blocked: {exc}", file=sys.stderr)
        return 2
    finally:
        os.environ.pop(CONFIRM_ENV, None)


def cmd_status(args: argparse.Namespace) -> int:
    paths = resolve_paths(profile=args.profile, pool=args.pool, queue=args.queue, log=args.log, resumes=args.resumes)
    queue = load_queue(paths["queue"])
    items = queue.get("items") or []
    rows = [
        {
            "id": i.get("id"),
            "status": i.get("status"),
            "ats": i.get("ats"),
            "url": i.get("url"),
            "submit_clicked": i.get("submit_clicked", False),
        }
        for i in items
    ]
    _emit({"queue": str(paths["queue"]), "count": len(rows), "items": rows})
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    from apply_engine.fill import fill_application

    paths = resolve_paths(profile=args.profile, pool=args.pool, queue=args.queue, log=args.log, resumes=args.resumes)
    profile = load_profile(paths["profile"])
    pool = load_pool(paths["pool"])
    fixture = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "greenhouse.html"
    html = fixture.read_text(encoding="utf-8")
    jd = (
        "Software Engineering Intern. React Native, Expo, Firebase, and maps. "
        "Also TypeScript/Node multi-agent tooling a plus."
    )
    job = fetch_job_from_text(
        url="https://job-boards.greenhouse.io/demo/jobs/1",
        title="Software Engineering Intern",
        company="demo",
        description=jd,
    )
    tailored = tailor(profile, pool, job)
    assert_truthful(tailored, pool)
    pdf = render_pdf(tailored, paths["resumes"] / "demo-software-engineering-intern.pdf")
    queue_id = "demo-local"
    artifact = fill_application(
        url="https://job-boards.greenhouse.io/demo/jobs/1",
        profile=profile,
        resume=tailored,
        resume_path=pdf,
        profile_path=str(paths["profile"]),
        pool_path=str(paths["pool"]),
        queue_id=queue_id,
        headed=False,
        screenshot_path=paths["queue_dir"] / queue_id / "screenshot.png",
        html=html,
        submit=False,
    )
    if artifact.submit_clicked:
        raise SubmitBlockedError("demo submitted — guard failed")
    payload = _store(paths, artifact, extra={"pdf": str(pdf), "demo": True})
    _emit(payload)
    return 0


def _workday_env_error(url: str) -> dict | None:
    if detect_ats(url) != "workday":
        return None
    try:
        require_password()
    except WorkdayConfigError as exc:
        return exc.to_result(url=url)
    return None


def _job_from_args(args: argparse.Namespace):
    url = getattr(args, "jd_url", None) or getattr(args, "url")
    jd_text = getattr(args, "jd_text", None)
    if jd_text:
        text = Path(jd_text).read_text(encoding="utf-8")
        return fetch_job_from_text(url, title="", company="", description=text)
    return fetch_job(url)


def _real_resume(paths: dict, profile) -> Path | None:
    """The candidate's own resume file. No silent substitution.

    _default_resume falls back to "newest PDF in resumes/", which is a
    previously generated one -- exactly what this path exists to avoid. When
    the real resume is missing we return None and the caller errors out.
    """
    raw = (profile.resume_path or "").strip()
    if not raw:
        return None
    direct = Path(raw)
    if direct.exists():
        return direct
    local = Path(paths["profile"]).parent / direct.name
    return local if local.exists() else None


def _default_resume(paths: dict, url: str, profile) -> Path:
    if profile.resume_path:
        p = Path(profile.resume_path)
        if p.exists():
            return p
        # The profile stores a deployment-absolute path
        # (/workspace/internship-apps/autofill/...), which does not exist on a
        # checkout. Re-resolve the same file inside whichever data tree we
        # actually loaded the profile from, rather than silently falling
        # through to the newest tailored PDF.
        local = Path(paths["profile"]).parent / p.name
        if local.exists():
            return local
    resumes = sorted(paths["resumes"].glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    if resumes:
        return resumes[0]
    return paths["resumes"] / f"{slugify(url)}.pdf"


def _new_id(url: str) -> str:
    from apply_engine.detect import parse_company_from_url, parse_job_id

    ats = detect_ats(url)
    company = slugify(parse_company_from_url(url, ats)) or "job"
    jid = slugify(parse_job_id(url, ats)) or uuid.uuid4().hex[:8]
    return f"{ats}-{company}-{jid}-{uuid.uuid4().hex[:6]}"


def _store(paths: dict, artifact, extra: dict | None = None) -> dict:
    extra = extra or {}
    # One tree, one fingerprint: every review.json and screenshot carries the
    # identity of the code that produced it.
    fp = fingerprint.stamp()
    item = {
        **artifact.to_dict(),
        **extra,
        "fingerprint": fp,
        "profile_sha": gate.profile_sha(artifact.profile_path or paths["profile"]),
        "updated_at": now_iso(),
    }
    upsert_item(paths["queue"], item)
    write_review(paths["queue_dir"] / artifact.id, item)
    append_log(paths["log"], format_log_entry(item))
    return {
        "status": artifact.status,
        "queue_id": artifact.id,
        "ats": artifact.ats,
        "resume": artifact.resume_path,
        "review": str(paths["queue_dir"] / artifact.id / "review.json"),
        "screenshot": artifact.screenshot,
        "submit_clicked": artifact.submit_clicked,
        "filled": [f.get("mapped_to") for f in artifact.filled],
        "skipped": [s.get("label") for s in artifact.skipped],
        "fingerprint": fp,
        **extra,
    }


def _emit(payload: dict) -> None:
    print(json.dumps(payload, indent=2))
    print(f"APPLY_ENGINE_RESULT: {json.dumps(payload, separators=(',', ':'))}")
