#!/usr/bin/env python3
"""Run a command with WORKDAY_DEFAULT_PASSWORD. Never prints it.

Load order:
1) process env
2) /home/box/agent-data/box-secrets.json
3) /home/box/agent-data/shared-secrets/WORKDAY_DEFAULT_PASSWORD (agent-local durable fallback)
4) ~/.config/apply-engine/workday-password (this machine)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BOX_SECRETS = Path("/home/box/agent-data/box-secrets.json")
FALLBACK = Path("/home/box/agent-data/shared-secrets/WORKDAY_DEFAULT_PASSWORD")
# Local dev / any machine that is not the agent box. Keep it 0600.
LOCAL = Path.home() / ".config" / "apply-engine" / "workday-password"


def _from_box_secrets() -> str | None:
    if not BOX_SECRETS.exists():
        return None
    try:
        data = json.loads(BOX_SECRETS.read_text())
    except Exception:
        return None
    sec = data.get("secrets") or {}
    v = sec.get("WORKDAY_DEFAULT_PASSWORD")
    if isinstance(v, str) and v.strip():
        return v
    if isinstance(v, dict):
        for k in ("value", "secret", "password", "token"):
            if isinstance(v.get(k), str) and v[k].strip():
                return v[k]
    return None


def _from_fallback() -> str | None:
    if not FALLBACK.exists():
        return None
    try:
        v = FALLBACK.read_text().strip("\n")
    except Exception:
        return None
    return v if v.strip() else None


def _from_local() -> str | None:
    if not LOCAL.exists():
        return None
    try:
        v = LOCAL.read_text().strip("\n")
    except Exception:
        return None
    return v if v.strip() else None


def load() -> str | None:
    if os.environ.get("WORKDAY_DEFAULT_PASSWORD"):
        return os.environ["WORKDAY_DEFAULT_PASSWORD"]
    return _from_box_secrets() or _from_fallback() or _from_local()


def mirror_from_box_if_possible() -> bool:
    """If box-secrets has the value and fallback missing/empty, copy it (never print)."""
    v = _from_box_secrets()
    if not v:
        return False
    FALLBACK.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    FALLBACK.write_text(v)
    os.chmod(FALLBACK, 0o600)
    return True


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--mirror":
        ok = mirror_from_box_if_possible()
        # presence only
        print("mirrored" if ok else "nothing_to_mirror")
        print("fallback", "set" if _from_fallback() else "missing")
        print("box", "set" if _from_box_secrets() else "missing")
        return 0 if ok or _from_fallback() else 1
    if len(sys.argv) >= 2 and sys.argv[1] == "--presence":
        print("box", "set" if _from_box_secrets() else "missing")
        print("fallback", "set" if _from_fallback() else "missing")
        print("local", "set" if _from_local() else "missing")
        print("env", "set" if os.environ.get("WORKDAY_DEFAULT_PASSWORD") else "missing")
        return 0 if load() else 1
    if len(sys.argv) < 2:
        print("usage: with-workday-secret.py [--mirror|--presence|<cmd> ...]", file=sys.stderr)
        return 2
    # opportunistic mirror whenever box has it
    mirror_from_box_if_possible()
    pw = load()
    env = os.environ.copy()
    if not pw:
        print("WORKDAY_DEFAULT_PASSWORD missing", file=sys.stderr)
        return 1
    env["WORKDAY_DEFAULT_PASSWORD"] = pw
    os.execvpe(sys.argv[1], sys.argv[1:], env)


if __name__ == "__main__":
    raise SystemExit(main())
