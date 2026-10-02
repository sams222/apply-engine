#!/usr/bin/env python3
"""Install the owner's private files into internship-apps/, or export the ones the engine updates.

The public repo carries no personal data. The owner hands the bot these files (in chat or
as a folder); this script puts each one where the engine looks for it and checks it loads:

  profile.json            -> internship-apps/autofill/profile.json
  <resume>.pdf            -> internship-apps/autofill/<resume>.pdf   (profile.resume_path is rewritten to it)
  PROJECT_POOL.md         -> internship-apps/PROJECT_POOL.md
  workday-accounts.json   -> internship-apps/autofill/workday-accounts.json   (optional; merged)
  submitted-ledger.json   -> internship-apps/submitted-ledger.json            (optional; merged)
  do-not-retry.json       -> internship-apps/do-not-retry.json                (optional)

Usage (from apply-engine/):
  python scripts/install-private.py PATH [PATH ...]   # files or folders, any order
  python scripts/install-private.py --check           # validate what is installed
  python scripts/install-private.py --export DEST     # copy ledger + workday accounts to DEST to send back
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE))
DATA = ENGINE.parent / "internship-apps"
AUTOFILL = DATA / "autofill"

PLACES = {
    "profile.json": AUTOFILL / "profile.json",
    "PROJECT_POOL.md": DATA / "PROJECT_POOL.md",
    "workday-accounts.json": AUTOFILL / "workday-accounts.json",
    "submitted-ledger.json": DATA / "submitted-ledger.json",
    "do-not-retry.json": DATA / "do-not-retry.json",
}
EXPORTS = ("submitted-ledger.json", "workday-accounts.json")


def _files(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for raw in paths:
        p = Path(raw).expanduser()
        if p.is_dir():
            out += sorted(f for f in p.iterdir() if f.is_file())
        elif p.is_file():
            out.append(p)
        else:
            raise SystemExit(f"not found: {p}")
    return out


def _merge_ledger(old: dict, new: dict) -> dict:
    rows = list(old.get("submitted") or [])
    seen = {(r.get("queue_id"), r.get("url")) for r in rows}
    rows += [r for r in new.get("submitted") or [] if (r.get("queue_id"), r.get("url")) not in seen]
    return {"submitted": rows}


def _merge_accounts(old: dict, new: dict) -> dict:
    tenants = dict(new.get("tenants") or {})
    tenants.update(old.get("tenants") or {})
    return {**new, "tenants": tenants}


def _write_json(dest: Path, data: dict) -> None:
    dest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def install(paths: list[str]) -> None:
    files = _files(paths)
    pdfs = [f for f in files if f.suffix.lower() == ".pdf"]
    if len(pdfs) > 1:
        raise SystemExit(f"more than one resume PDF given: {[p.name for p in pdfs]}")
    AUTOFILL.mkdir(parents=True, exist_ok=True)
    for f in files:
        if f.suffix.lower() == ".pdf":
            shutil.copyfile(f, AUTOFILL / f.name)
            print(f"installed {f.name} -> {(AUTOFILL / f.name).relative_to(ENGINE.parent)}")
            continue
        dest = PLACES.get(f.name)
        if dest is None:
            print(f"skipped {f.name} (not a file the engine uses)")
            continue
        if dest.exists() and f.name == "submitted-ledger.json":
            _write_json(dest, _merge_ledger(json.loads(dest.read_text()), json.loads(f.read_text())))
        elif dest.exists() and f.name == "workday-accounts.json":
            _write_json(dest, _merge_accounts(json.loads(dest.read_text()), json.loads(f.read_text())))
        elif dest.resolve() != f.resolve():
            shutil.copyfile(f, dest)
        print(f"installed {f.name} -> {dest.relative_to(ENGINE.parent)}")
    profile = PLACES["profile.json"]
    if pdfs and profile.exists():
        data = json.loads(profile.read_text(encoding="utf-8"))
        data["resume_path"] = str((AUTOFILL / pdfs[0].name).resolve())
        _write_json(profile, data)
        print(f"profile.resume_path -> {data['resume_path']}")


def check() -> list[str]:
    from apply_engine.cli import _assert_safe_profile
    from apply_engine.pool import load_pool
    from apply_engine.profile import load_profile

    problems: list[str] = []
    profile_path = PLACES["profile.json"]
    if not profile_path.exists():
        return [f"missing {profile_path}"]
    try:
        _assert_safe_profile(profile_path)
        profile = load_profile(profile_path)
    except SystemExit as exc:
        return [str(exc)]
    resume = Path(profile.resume_path or "")
    if not profile.resume_path or not resume.is_file():
        pdfs = sorted(AUTOFILL.glob("*.pdf"))
        hint = f" (found {pdfs[0].name}; re-run install with it)" if pdfs else ""
        problems.append(f"profile.resume_path does not point at a file: {profile.resume_path!r}{hint}")
    pool = PLACES["PROJECT_POOL.md"]
    if not pool.exists():
        problems.append(f"missing {pool}")
    else:
        try:
            load_pool(pool)
        except ValueError as exc:
            problems.append(f"{pool.name}: {exc}")
    for name in ("workday-accounts.json", "submitted-ledger.json", "do-not-retry.json"):
        path = PLACES[name]
        if path.exists():
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                problems.append(f"{name}: invalid JSON ({exc})")
    return problems


def export(dest: str) -> None:
    out = Path(dest).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    for name in EXPORTS:
        src = PLACES[name]
        if src.exists():
            shutil.copyfile(src, out / name)
            print(f"exported {out / name}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", help="private files or folders to install")
    ap.add_argument("--check", action="store_true", help="only validate the installed files")
    ap.add_argument("--export", metavar="DEST", help="copy the ledger and workday accounts to DEST")
    args = ap.parse_args()
    if args.export:
        export(args.export)
        return 0
    if args.paths:
        install(args.paths)
    elif not args.check:
        ap.error("give files/folders to install, --check, or --export DEST")
    problems = check()
    for p in problems:
        print(f"PROBLEM: {p}")
    if not problems:
        print("private files OK")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
