from __future__ import annotations

import os
import re
from typing import Callable

from apply_engine.models import Profile, TailoredResume
from apply_engine.util import normalize_label

AnswerFn = Callable[[str, Profile, TailoredResume], str | None]


def answer_open_ended(question: str, profile: Profile, resume: TailoredResume) -> str | None:
    """Grounded templates first. Optional LLM only for leftovers, still fact-locked."""
    q = normalize_label(question)
    for pred, fn in TEMPLATES:
        if pred(q):
            return fn(question, profile, resume)
    return maybe_llm(question, profile, resume)


def _why(_q: str, profile: Profile, resume: TailoredResume) -> str:
    top = _top_project(resume)
    company = resume.job.company or "this team"
    role = resume.job.title or "this role"
    skill = resume.matched_keywords[0] if resume.matched_keywords else (resume.skills[0] if resume.skills else "software")
    return (
        f"I'm {profile.full_name}, a {profile.degree or 'CS'} student at {profile.school or 'my university'}. "
        f"{role} at {company} lines up with work I already shipped on {top}, especially {skill}. "
        "I want to keep building production software on a team that ships."
    )


def _project(_q: str, profile: Profile, resume: TailoredResume) -> str:
    entry = None
    if resume.projects:
        entry = resume.projects[0]
    elif resume.experience:
        entry = resume.experience[0]
    if not entry:
        return f"{profile.full_name} builds software listed in the attached resume."
    bullets = " ".join(entry.bullets[:2])
    return f"{entry.title}: {bullets}".strip()


def _cover(_q: str, profile: Profile, resume: TailoredResume) -> str:
    return _why(_q, profile, resume)


def _start(_q: str, profile: Profile, _resume: TailoredResume) -> str | None:
    return profile.available_from or None


def _location(_q: str, profile: Profile, _resume: TailoredResume) -> str | None:
    if profile.preferred_locations:
        return profile.preferred_locations[0]
    return profile.location or None


def maybe_llm(question: str, profile: Profile, resume: TailoredResume) -> str | None:
    try:
        from apply_engine.llm import available, draft_answer

        if not available():
            return None
        return draft_answer(question, profile, resume)
    except Exception:
        return None


def _top_project(resume: TailoredResume) -> str:
    if resume.projects:
        return resume.projects[0].title
    if resume.experience:
        return resume.experience[0].title
    return "the projects on my resume"


def _match(*needles: str) -> Callable[[str], bool]:
    def inner(q: str) -> bool:
        return any(n in q for n in needles)

    return inner


TEMPLATES: list[tuple[Callable[[str], bool], AnswerFn]] = [
    (_match("why do you want", "why this", "why are you interested", "why our", "what interests you"), _why),
    (_match("cover letter", "coverletter"), _cover),
    (_match("tell us about", "describe a project", "proud of", "walk us through a project", "favorite project"), _project),
    (_match("start date", "available to start", "when can you start"), _start),
    (_match("where are you located", "current location", "preferred location", "desired location"), _location),
]


def looks_open_ended(label: str) -> bool:
    q = normalize_label(label)
    if len(q.split()) < 4:
        return False
    return bool(
        re.search(
            r"why |tell us|describe |cover letter|what interests|walk us|essay|in 200|in 150",
            q,
        )
    )
