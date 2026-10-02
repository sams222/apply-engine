from __future__ import annotations

import json
import os
import re
from pathlib import Path

from apply_engine.models import JobPosting, PoolEntry, Profile, TailoredResume

KEY_DIR = Path("~/.config/apply-engine").expanduser()

# name, env vars, key file, OpenAI-compatible base URL, default model, model env var
PROVIDERS = (
    ("gemini", ("GEMINI_API_KEY", "GOOGLE_API_KEY"), "gemini-key",
     "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash", "GEMINI_MODEL"),
    ("deepseek", ("DEEPSEEK_API_KEY",), "deepseek-key", "https://api.deepseek.com", "deepseek-chat", "DEEPSEEK_MODEL"),
    ("grok", ("GROK_API_KEY", "XAI_API_KEY"), "grok-key", "https://api.x.ai/v1", "grok-3", "GROK_MODEL"),
    ("openai", ("OPENAI_API_KEY",), "openai-key", "https://api.openai.com/v1", "gpt-4o-mini", "OPENAI_MODEL"),
)

STYLE_GUIDE = (Path(__file__).parent / "prompts" / "essay_style.md").read_text(encoding="utf-8")

ESSAY_RULES = """You write one answer for a job application, as the candidate, in first person.
Use ONLY facts from FACTS. Never invent employers, projects, skills, metrics, dates, or GPA.
Do not add details FACTS does not state: no frequency ("daily", "every day"), no team size or
"my team" unless FACTS says it was a team, no willingness (travel, relocation, hours) or
authorization claims unless the question asks for them.
Do not invent the candidate's inner experience: no "the hard part was", "this taught me", "the first time I",
"what mattered to me", no claims about what he has NOT done, unless PROJECT NOTES say so. Describe
what the work did and why it is relevant; interest is shown by specifics, not by narrated feelings.
If the question asks about something the candidate read, watched, used, or thinks of (an article,
coverage, a product feature, a book) and FACTS do not name it, reply exactly SKIP.
Default to 3-5 sentences (under 120 words) unless the question asks for a different length.
If FACTS cannot support an honest answer, reply exactly SKIP.
Never supply a username, handle, account ID, test score, or reference contact; reply SKIP when asked for one.
Reply with the answer text only: no preamble, no quotes, no notes.
Follow this style guide:

"""

ESSAY_SYSTEM = ESSAY_RULES + STYLE_GUIDE

PICK_SYSTEM = """You answer one multiple-choice job-application question for the candidate.
Choose only from OPTIONS, copying option text exactly. Base the choice on FACTS and the posting.
If the question asks for a fact that FACTS does not establish, reply SKIP instead of guessing.
Never pick "Other" or a catch-all as a guess; pick it only when FACTS show no listed option fits.
Reply with JSON only: {"choices": ["<option>", ...]} (one choice unless MULTI is true) or {"choices": []} to skip."""


def provider() -> tuple[str, str, str, str] | None:
    """(name, key, base, model) for the first configured provider."""
    forced = (os.environ.get("APPLY_ENGINE_LLM") or "").strip().lower()
    for name, envs, keyfile, base, model, model_env in PROVIDERS:
        if forced and forced != name:
            continue
        key = next((os.environ[e] for e in envs if os.environ.get(e)), "")
        if not key:
            path = KEY_DIR / keyfile
            if path.exists():
                key = path.read_text(encoding="utf-8").strip()
        if key:
            return name, key, base, os.environ.get(model_env, model)
    return None


def available() -> bool:
    return provider() is not None


def _yes_no(value: object) -> str:
    return "unknown" if value is None else "yes" if value else "no"


def facts_block(profile: Profile, pool: list[PoolEntry], job: JobPosting | None) -> str:
    lines = [
        f"Name: {profile.full_name}",
        f"School: {profile.school}, {profile.degree}, graduating {profile.graduation}",
        f"GPA: {profile.gpa or 'do not state a GPA'}",
        f"Location: {profile.location}",
        f"Willing to relocate: {_yes_no((profile.extra or {}).get('willing_to_relocate'))}; "
        f"willing to work on-site: {_yes_no((profile.extra or {}).get('willing_onsite'))}; "
        f"preferred locations in order: {', '.join(profile.preferred_locations or []) or 'none stated'}",
        f"US work authorized: {profile.work_authorized_us}; needs sponsorship: {profile.need_sponsorship}",
    ]
    if profile.skills:
        lines.append(f"Skills: {', '.join(profile.skills)}")
    lines.append("Experience and projects:")
    for e in pool:
        head = e.title
        if e.company or e.role:
            head = f"{e.role} at {e.company}" if e.role else e.company
        span = f" ({e.start} - {e.end})" if e.start else ""
        tags = f" [tags: {', '.join(e.tags)}]" if e.tags else ""
        lines.append(f"- {head}{span} ({e.kind}){tags}")
        for b in e.bullets:
            lines.append(f"    * {b}")
    extra = profile.extra or {}
    project_notes = extra.get("project_notes") or {}
    if project_notes:
        lines.append("")
        lines.append("PROJECT NOTES (the candidate's own write-ups: why the projects were built, what was hard; \"team\" projects must be described as team work):")
        for name, note in project_notes.items():
            lines.append(f"- {name}: {note}")
    if extra.get("motivations"):
        lines.append("")
        lines.append(f"WHAT THE CANDIDATE WANTS FROM AN INTERNSHIP (their words): {extra['motivations']}")
    if job is not None:
        company_notes = extra.get("company_notes") or {}
        company = (job.company or "").lower()
        note = next((v for k, v in company_notes.items() if k.lower() in company or company in k.lower()), None) if company else None
        if note:
            lines.append("")
            lines.append(f"COMPANY NOTES (the candidate's own reasons for {job.company}): {note}")
        lines.append("")
        lines.append(f"POSTING: {job.title} at {job.company}")
        desc = re.sub(r"\s+", " ", job.description or "").strip()
        if desc:
            lines.append(desc[:6000])
    return "\n".join(lines)


def draft_essay(question: str, facts: str, *, limit_hint: str = "") -> str | None:
    return draft_essay_checked(question, facts, limit_hint=limit_hint)[0]


def draft_essay_checked(question: str, facts: str, *, limit_hint: str = "", attempts: int = 3) -> tuple[str | None, list[str]]:
    """Draft, lint against the style guide, and send back for rewrites. Returns (text, remaining problems)."""
    from apply_engine.essay_lint import problems as lint

    posting = facts.split("POSTING:", 1)[1] if "POSTING:" in facts else ""
    user = f"FACTS:\n{facts}\n\nQUESTION:\n{question}"
    if limit_hint:
        user += f"\n\nLENGTH: {limit_hint}"
    best: tuple[str | None, list[str]] = (None, [])
    prompt = user
    for _ in range(attempts):
        text = _chat(ESSAY_SYSTEM, prompt, temperature=0.7)
        if not text:
            break
        text = text.strip().strip('"').strip()
        if not text or text.upper().startswith("SKIP"):
            return (best if best[0] else (None, []))
        found = lint(text, posting=posting, question=question, facts=facts.split("POSTING:", 1)[0])
        if best[0] is None or len(found) < len(best[1]):
            best = (text, found)
        if not found:
            break
        prompt = (
            f"{user}\n\nYOUR PREVIOUS DRAFT:\n{text}\n\nIt breaks the style guide:\n"
            + "\n".join(f"- {p}" for p in found)
            + "\n\nRewrite it from scratch, fixing every point. Same facts only."
        )
    return best


def pick_options(question: str, options: list[str], facts: str, *, multi: bool = False) -> list[str]:
    user = (
        f"FACTS:\n{facts}\n\nQUESTION:\n{question}\n\nOPTIONS:\n"
        + "\n".join(f"- {o}" for o in options)
        + f"\n\nMULTI: {'true' if multi else 'false'}"
    )
    text = _chat(PICK_SYSTEM, user, temperature=0.0)
    if not text:
        return []
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return []
    try:
        choices = json.loads(m.group(0)).get("choices") or []
    except (ValueError, AttributeError):
        return []
    valid = [c for c in choices if c in options]
    return valid if multi else valid[:1]


def draft_answer(question: str, profile: Profile, resume: TailoredResume) -> str | None:
    return draft_essay(question, facts_block(profile, resume.all_entries(), resume.job))


def _chat(system: str, user: str, *, temperature: float) -> str | None:
    found = provider()
    if found is None:
        return None
    name, key, base, model = found
    import httpx

    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": temperature,
    }
    try:
        with httpx.Client(timeout=90.0) as client:
            resp = client.post(
                f"{base.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        return str(data["choices"][0]["message"]["content"])
    except Exception:
        return None
