"""do-not-retry: companies the engine refuses to open at all.

Some boards have already burned a real application, rejected us, or proved
unfillable (Motorola's blank Workday shell). Re-running them wastes a slot and
risks a duplicate submission, so the refusal happens *before* the browser
launches or a PDF is rendered — not as a late failure inside fill.

The list is the union of:
  * SEED — motorola / doordash / bedrock, required by the engine spec
  * <data-tree>/do-not-retry.json — an operator-editable list

Both are matched against the company name and against host + path, because the
company only appears in the URL path on shared boards
(job-boards.greenhouse.io/<org>/jobs/<id>).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

# Required by spec. Kept in code so a missing/emptied JSON file cannot silently
# re-enable them.
SEED: tuple[str, ...] = ("motorola", "doordash", "bedrock")


@dataclass(frozen=True)
class Blocked:
    """Why a URL was refused."""

    token: str
    matched: str
    source: str

    def reason(self) -> str:
        return (
            f"do_not_retry: {self.token!r} matches {self.matched!r} "
            f"(source: {self.source})"
        )


def _norm(text: str) -> str:
    """Lowercase and strip separators so 'Motorola Solutions' == 'motorolasolutions'."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def load_blocklist(path: Path | None = None) -> dict[str, str]:
    """Token -> source. SEED always present; file entries layered on top."""
    tokens: dict[str, str] = {_norm(t): "seed" for t in SEED if _norm(t)}
    if path and Path(path).exists():
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # A corrupt operator file must not drop the seed refusals.
            return tokens
        entries = raw.get("companies", []) if isinstance(raw, dict) else raw
        if isinstance(entries, list):
            for entry in entries:
                token = _norm(str(entry))
                if token:
                    tokens.setdefault(token, str(path))
    return tokens


def _haystacks(url: str, company: str = "") -> list[tuple[str, str]]:
    """(normalized text, human label) pairs a token may match against."""
    out: list[tuple[str, str]] = []
    if company:
        out.append((_norm(company), company))
    if url:
        parts = urlsplit(url if "//" in url else f"//{url}")
        host = parts.netloc or ""
        if host:
            out.append((_norm(host), host))
        # First two path segments carry the org slug on shared boards.
        segments = [s for s in (parts.path or "").split("/") if s][:2]
        for seg in segments:
            out.append((_norm(seg), seg))
    return [(h, label) for h, label in out if h]


def check(url: str, company: str = "", path: Path | None = None) -> Blocked | None:
    """Return why this job is refused, or None when it may proceed."""
    tokens = load_blocklist(path)
    for haystack, label in _haystacks(url, company):
        for token, source in tokens.items():
            if token and token in haystack:
                return Blocked(token=token, matched=label, source=source)
    return None


def result_payload(blocked: Blocked, url: str, company: str = "") -> dict:
    """APPLY_ENGINE_RESULT body for a refusal. Same contract as every other exit."""
    return {
        "status": "do_not_retry",
        "url": url,
        "company": company,
        "blocked_token": blocked.token,
        "matched": blocked.matched,
        "source": blocked.source,
        "submit_clicked": False,
        "notes": [blocked.reason(), "not retryable; remove from do-not-retry.json to re-enable"],
    }
