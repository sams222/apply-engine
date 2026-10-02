"""One tree, one fingerprint.

Two trees drifted in the field: the box ran fill.py f93d71de91e9 mid-waymo while
the shouted go was fe0309ebfb29. Nobody could tell which code produced which
screenshot, because the only identifier in play was an ad-hoc hash of one file.

So the engine now stamps two values into every review artifact:

  fill      sha256(apply_engine/fill.py)[:12]  — the legacy acceptance token
  tree      sha256 over every source file, path included  — the real identity

`tree` is what settles "which code ran". It covers the whole package plus tests,
is order-independent of the filesystem, and ignores caches and artifacts.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent

# Directories that never affect behavior.
_SKIP_DIRS = {
    "__pycache__", ".git", ".venv", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "dist", "build", "queue", "resumes", "artifacts",
    "playwright-report", "test-results", "agent-tools",
}

# What the fingerprint covers: code and the fixtures/tests that pin it.
_INCLUDE_SUFFIXES = {".py", ".html", ".toml", ".txt", ".md", ".json"}


def _iter_source_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.suffix.lower() not in _INCLUDE_SUFFIXES:
            continue
        out.append(path)
    # Sort by POSIX-relative path so the hash does not depend on walk order.
    return sorted(out, key=lambda p: p.relative_to(root).as_posix())


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def fill_fingerprint() -> str:
    """sha256(fill.py)[:12] — the token the acceptance criteria names."""
    return file_sha256(PACKAGE_ROOT / "fill.py")[:12]


def tree_fingerprint(root: Path | None = None) -> str:
    """sha256 over path+content of every source file. The tree's real identity."""
    root = Path(root) if root else REPO_ROOT
    h = hashlib.sha256()
    for path in _iter_source_files(root):
        rel = path.relative_to(root).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()[:12]


def stamp(root: Path | None = None) -> dict[str, str]:
    """The fingerprint block embedded in review.json and printed by `fingerprint`."""
    root = Path(root) if root else REPO_ROOT
    return {
        "fill": fill_fingerprint(),
        "tree": tree_fingerprint(root),
        "files": str(len(_iter_source_files(root))),
    }


def manifest(root: Path | None = None) -> list[dict[str, str]]:
    """Per-file hashes, so a drifted tree can be diffed instead of guessed at."""
    root = Path(root) if root else REPO_ROOT
    return [
        {"path": p.relative_to(root).as_posix(), "sha256": file_sha256(p)[:12]}
        for p in _iter_source_files(root)
    ]
