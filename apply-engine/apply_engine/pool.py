from __future__ import annotations

import re
from pathlib import Path

from apply_engine.models import PoolEntry

KIND_ALIASES = {
    "project": "project",
    "projects": "project",
    "experience": "experience",
    "job": "experience",
    "work": "experience",
    "internship": "experience",
    "intern": "experience",
    "program": "program",
    "programs": "program",
    "activity": "program",
}


def load_pool(path: str | Path) -> list[PoolEntry]:
    text = Path(path).read_text(encoding="utf-8")
    return parse_pool(text)


def parse_pool(text: str) -> list[PoolEntry]:
    chunks = re.split(r"^##\s+", text, flags=re.M)
    entries: list[PoolEntry] = []
    for chunk in chunks[1:]:
        lines = [ln.rstrip() for ln in chunk.strip().splitlines()]
        if not lines:
            continue
        title = lines[0].strip()
        kind = ""
        tags: list[str] = []
        bullets: list[str] = []
        body: list[str] = []
        meta: dict[str, str] = {}
        for line in lines[1:]:
            stripped = line.strip()
            lower = stripped.lower()
            if lower.startswith("kind:"):
                kind = KIND_ALIASES.get(stripped.split(":", 1)[1].strip().lower(), "project")
            elif lower.startswith("tags:"):
                tags = [t.strip().lower() for t in stripped.split(":", 1)[1].split(",") if t.strip()]
            elif any(lower.startswith(prefix) for prefix in ("company:", "role:", "location:", "start:", "end:")):
                key, _, val = stripped.partition(":")
                meta[key.strip().lower()] = val.strip()
            elif stripped.startswith("- "):
                bullets.append(stripped[2:].strip())
            elif stripped.startswith("* "):
                bullets.append(stripped[2:].strip())
            elif stripped:
                body.append(stripped)
        if not kind:
            kind = _infer_kind(title, tags)
        if not bullets and body:
            bullets = body
            body = []
        entries.append(
            PoolEntry(
                title=title,
                kind=kind,
                tags=tags,
                bullets=bullets,
                source="\n".join(body),
                company=meta.get("company", ""),
                role=meta.get("role", ""),
                location=meta.get("location", ""),
                start=meta.get("start", ""),
                end=meta.get("end", ""),
            )
        )
    if not entries:
        raise ValueError("PROJECT_POOL.md has no ## entries")
    return entries


def dated_work(entries: list[PoolEntry]) -> list[PoolEntry]:
    """Jobs with a company, role, and start date.

    Projects are never employment. Undated entries are skipped so the filler
    does not invent a start or end. Programs stay eligible when the resume
    lists them under Experience and the pool carries those dates.
    """
    rows: list[PoolEntry] = []
    for entry in entries:
        if entry.kind == "project":
            continue
        if entry.company.strip() and entry.role.strip() and entry.start.strip():
            rows.append(entry)
    return rows


def _infer_kind(title: str, tags: list[str]) -> str:
    blob = f"{title} {' '.join(tags)}".lower()
    if any(k in blob for k in ("intern", "internship", "swe at", "software engineer")):
        return "experience"
    if any(k in blob for k in ("tech prep", "v-swep", "career prep", "fellowship", "bootcamp")):
        return "program"
    return "project"
