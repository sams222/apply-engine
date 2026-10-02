from __future__ import annotations

import re
from collections import Counter

from apply_engine.models import JobPosting, PoolEntry, Profile, TailoredResume

# JD tokens we notice only to rank real pool entries. Never copied onto the resume
# unless they already exist as pool tags or profile.skills.
TOKEN_RE = re.compile(r"[a-z][a-z0-9+#.]{1,}", re.I)
STOP = {
    "and",
    "the",
    "for",
    "with",
    "you",
    "our",
    "are",
    "will",
    "this",
    "that",
    "from",
    "have",
    "your",
    "job",
    "role",
    "team",
    "work",
    "about",
    "plus",
    "etc",
    "including",
    "using",
    "into",
    "their",
    "such",
    "ability",
    "experience",
    "requirements",
    "preferred",
    "responsibilities",
    "qualifications",
    "intern",
    "internship",
    "student",
    "summer",
}


def tailor(profile: Profile, pool: list[PoolEntry], job: JobPosting) -> TailoredResume:
    jd = (job.description or "") + " " + (job.title or "")
    jd_l = jd.lower()

    scores: dict[str, int] = {}
    matched: list[str] = []
    for entry in pool:
        score, hits = score_entry(entry, jd_l)
        scores[entry.title] = score
        matched.extend(hits)

    def sort_key(entry: PoolEntry) -> tuple[int, int]:
        return (scores.get(entry.title, 0), -pool.index(entry))

    experience = sorted([e for e in pool if e.kind == "experience"], key=sort_key, reverse=True)
    projects = sorted([e for e in pool if e.kind == "project"], key=sort_key, reverse=True)
    programs = sorted([e for e in pool if e.kind == "program"], key=sort_key, reverse=True)

    pool_skill_set = _pool_skills(pool, profile)
    jd_tokens = _jd_tokens(jd_l)
    ranked_skills = _select_skills(pool_skill_set, jd_l, jd_tokens, projects + experience + programs)
    unused = sorted(t for t in jd_tokens if t not in {s.lower() for s in pool_skill_set} and len(t) > 3)

    return TailoredResume(
        profile=profile,
        job=job,
        skills=ranked_skills,
        experience=experience,
        projects=projects,
        programs=programs,
        scores=scores,
        matched_keywords=list(dict.fromkeys(matched)),
        unused_jd_terms=unused[:12],
    )


def score_entry(entry: PoolEntry, jd_l: str) -> tuple[int, list[str]]:
    hits: list[str] = []
    score = 0
    for tag in entry.tags:
        if tag and tag in jd_l:
            score += 4
            hits.append(tag)
    title_l = entry.title.lower()
    if len(title_l) > 3 and title_l in jd_l:
        score += 3
        hits.append(title_l)
    for word in re.findall(r"[a-z0-9]{4,}", title_l):
        if word in jd_l and word not in STOP:
            score += 1
            hits.append(word)
    blob = " ".join(entry.bullets).lower()
    for tag in entry.tags:
        # extra bump when the JD echoes a bullet skill already on the entry
        if tag and tag in jd_l and tag in blob:
            score += 1
    return score, hits


def _pool_skills(pool: list[PoolEntry], profile: Profile) -> list[str]:
    skills: list[str] = []
    seen: set[str] = set()
    for item in [*profile.skills, *[t for e in pool for t in e.tags]]:
        key = item.strip()
        if not key:
            continue
        low = key.lower()
        if low in seen:
            continue
        seen.add(low)
        skills.append(key)
    return skills


def _jd_tokens(jd_l: str) -> set[str]:
    tokens = {t.lower() for t in TOKEN_RE.findall(jd_l)}
    return {t for t in tokens if t not in STOP}


def _select_skills(
    pool_skills: list[str],
    jd_l: str,
    jd_tokens: set[str],
    ranked_entries: list[PoolEntry],
) -> list[str]:
    matched: list[str] = []
    rest: list[str] = []
    for skill in pool_skills:
        low = skill.lower()
        if low in jd_l or any(tok in jd_tokens and tok in low.split() for tok in low.split()):
            matched.append(skill)
        else:
            rest.append(skill)
    # Preserve pool order for matched, then remaining real skills from top entries.
    extra: list[str] = []
    seen = {s.lower() for s in matched}
    for entry in ranked_entries:
        for tag in entry.tags:
            if tag not in seen:
                extra.append(tag)
                seen.add(tag)
    # Display names: prefer original profile/pool casing from pool_skills
    pretty = {s.lower(): s for s in pool_skills}
    ordered = []
    for s in matched + extra:
        pretty_s = pretty.get(s.lower(), s)
        if pretty_s not in ordered:
            ordered.append(pretty_s)
    return ordered


def keyword_overlap_report(pool: list[PoolEntry], jd_text: str) -> dict[str, int]:
    jd_l = jd_text.lower()
    return {e.title: score_entry(e, jd_l)[0] for e in pool}


def assert_truthful(resume: TailoredResume, pool: list[PoolEntry]) -> None:
    allowed = {e.id for e in pool}
    for entry in resume.all_entries():
        if entry.id not in allowed:
            raise ValueError(f"tailor invented an entry: {entry.title}")
    allowed_skills = {s.lower() for e in pool for s in e.tags}
    allowed_skills.update(s.lower() for s in resume.profile.skills)
    for skill in resume.skills:
        if skill.lower() not in allowed_skills:
            raise ValueError(f"tailor invented a skill: {skill}")
    if resume.profile.gpa is None:
        # GPA must stay absent; callers must not fill it in later.
        pass
    _ = Counter(resume.scores)
