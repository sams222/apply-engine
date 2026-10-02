from __future__ import annotations

from pathlib import Path


def resolve_paths(
    *,
    profile: str | None = None,
    pool: str | None = None,
    queue: str | None = None,
    log: str | None = None,
    resumes: str | None = None,
    cwd: Path | None = None,
) -> dict[str, Path]:
    cwd = cwd or Path.cwd()
    intern = cwd / "internship-apps"
    if not intern.exists():
        parent = cwd.parent / "internship-apps"
        if parent.exists():
            intern = parent
    examples = Path(__file__).resolve().parent.parent / "examples"

    def pick(explicit: str | None, *candidates: Path, fallback: Path) -> Path:
        if explicit:
            return Path(explicit).expanduser().resolve()
        for cand in candidates:
            if cand.exists():
                return cand.resolve()
        return fallback.resolve()

    return {
        "profile": pick(
            profile,
            intern / "autofill" / "profile.json",
            cwd / "profile.json",
            examples / "profile.json",
            fallback=examples / "profile.json",
        ),
        "pool": pick(
            pool,
            intern / "PROJECT_POOL.md",
            cwd / "PROJECT_POOL.md",
            examples / "PROJECT_POOL.md",
            fallback=examples / "PROJECT_POOL.md",
        ),
        "queue": pick(
            queue,
            intern / "apply-queue.json",
            cwd / "apply-queue.json",
            cwd / "queue" / "apply-queue.json",
            fallback=(intern if intern.exists() else cwd) / "apply-queue.json",
        ),
        "log": pick(
            log,
            intern / "APPLY_LOG.md",
            cwd / "APPLY_LOG.md",
            fallback=(intern if intern.exists() else cwd) / "APPLY_LOG.md",
        ),
        "resumes": Path(resumes).expanduser().resolve() if resumes else (intern / "resumes" if intern.exists() else cwd / "resumes"),
        "queue_dir": (intern / "apply-engine-queue" if intern.exists() else cwd / "queue"),
        "do_not_retry": (
            intern / "do-not-retry.json"
            if intern.exists()
            else cwd / "do-not-retry.json"
        ),
        "workday_accounts": (
            intern / "autofill" / "workday-accounts.json"
            if intern.exists()
            else (cwd / "queue" / "workday-accounts.json")
        ),
    }
