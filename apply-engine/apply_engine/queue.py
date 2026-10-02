from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from apply_engine.util import dump_json, load_json, now_iso


def load_queue(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"items": []}
    raw = load_json(path)
    if isinstance(raw, list):
        return {"items": raw}
    if isinstance(raw, dict) and "items" in raw:
        return raw
    if isinstance(raw, dict):
        return {"items": [raw]}
    raise ValueError(f"unsupported queue shape: {path}")


def save_queue(path: Path, queue: dict[str, Any]) -> None:
    dump_json(path, queue)


@contextmanager
def _locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name(f".{path.name}.lock"), "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield


def upsert_item(path: Path, item: dict[str, Any]) -> dict[str, Any]:
    with _locked(path):
        return _upsert(path, item)


def _upsert(path: Path, item: dict[str, Any]) -> dict[str, Any]:
    queue = load_queue(path)
    items: list[dict[str, Any]] = list(queue.get("items") or [])
    qid = item["id"]
    replaced = False
    for i, existing in enumerate(items):
        if existing.get("id") == qid:
            merged = {**existing, **item}
            items[i] = merged
            replaced = True
            item = merged
            break
    if not replaced:
        items.append(item)
    queue["items"] = items
    save_queue(path, queue)
    return item


def get_item(path: Path, queue_id: str) -> dict[str, Any]:
    queue = load_queue(path)
    for item in queue.get("items") or []:
        if item.get("id") == queue_id:
            return item
    raise KeyError(f"queue id not found: {queue_id}")


def append_log(path: Path, lines: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(lines.rstrip() + "\n\n")


def format_log_entry(item: dict[str, Any]) -> str:
    filled = item.get("filled") or []
    names = []
    for row in filled:
        if isinstance(row, dict):
            names.append(str(row.get("mapped_to") or row.get("label") or ""))
        else:
            names.append(str(row))
    skipped = item.get("skipped") or []
    skip_s = ", ".join(
        (s.get("label") if isinstance(s, dict) else str(s)) for s in skipped[:12]
    )
    return "\n".join(
        [
            f"## {now_iso()}  {item.get('status')}  {item.get('id')}",
            f"- url: {item.get('url')}",
            f"- ats: {item.get('ats')}",
            f"- resume: {item.get('resume_path')}",
            f"- filled: {', '.join(n for n in names if n)}",
            f"- skipped: {skip_s}",
            f"- submit_clicked: {item.get('submit_clicked', False)}",
        ]
    )


def write_review(review_dir: Path, artifact: dict[str, Any]) -> Path:
    review_dir.mkdir(parents=True, exist_ok=True)
    out = review_dir / "review.json"
    dump_json(out, artifact)
    return out
