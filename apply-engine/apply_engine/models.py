from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any


def _to_dict(obj: Any) -> Any:
    if is_dataclass(obj):
        return {k: _to_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [_to_dict(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    return obj


@dataclass
class EEO:
    gender: str = ""
    race_ethnicity: str = ""
    veteran: str = ""
    disability: str = ""


@dataclass
class Profile:
    full_name: str
    first_name: str
    last_name: str
    email: str
    phone: str = ""
    linkedin: str = ""
    github: str = ""
    website: str = ""
    location: str = ""
    city: str = ""
    state: str = ""
    country: str = ""
    school: str = ""
    degree: str = ""
    gpa: str | None = None
    graduation: str = ""
    education_start: str = ""
    work_authorized_us: bool | None = None
    need_sponsorship: bool | None = None
    eeo: EEO = field(default_factory=EEO)
    resume_path: str = ""
    preferred_locations: list[str] = field(default_factory=list)
    address_line1: str = ""
    postal_code: str = ""
    how_heard: str = ""
    field_of_study: str = ""
    previous_employee: bool = False
    requires_housing: bool | None = None
    skills: list[str] = field(default_factory=list)
    available_from: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def contact_bits(self) -> list[str]:
        bits = [self.email]
        if self.phone:
            bits.append(self.phone)
        if self.linkedin:
            bits.append(self.linkedin)
        if self.github:
            bits.append(self.github)
        if self.location:
            bits.append(self.location)
        return bits


@dataclass
class PoolEntry:
    title: str
    kind: str
    tags: list[str]
    bullets: list[str]
    source: str = ""
    company: str = ""
    role: str = ""
    location: str = ""
    start: str = ""
    end: str = ""

    @property
    def id(self) -> str:
        return self.title.strip().lower()


@dataclass
class JobPosting:
    url: str
    title: str = ""
    company: str = ""
    location: str = ""
    description: str = ""
    ats: str = "generic"
    apply_url: str = ""
    source: str = ""

    def slug(self) -> str:
        from apply_engine.util import slugify

        base = slugify(self.title) or "role"
        company = slugify(self.company) or "company"
        return f"{company}-{base}"


@dataclass
class TailoredResume:
    profile: Profile
    job: JobPosting
    skills: list[str]
    experience: list[PoolEntry]
    projects: list[PoolEntry]
    programs: list[PoolEntry]
    scores: dict[str, int]
    matched_keywords: list[str]
    unused_jd_terms: list[str]

    def all_entries(self) -> list[PoolEntry]:
        return [*self.experience, *self.projects, *self.programs]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "company": self.job.company,
            "title": self.job.title,
            "url": self.job.url,
            "ats": self.job.ats,
            "skills": self.skills,
            "experience": [e.title for e in self.experience],
            "projects": [e.title for e in self.projects],
            "programs": [e.title for e in self.programs],
            "scores": self.scores,
            "matched_keywords": self.matched_keywords,
            "unused_jd_terms": self.unused_jd_terms,
            "invented": False,
        }


@dataclass
class FieldFill:
    label: str
    mapped_to: str
    value: str
    method: str


@dataclass
class ReviewArtifact:
    id: str
    status: str
    url: str
    ats: str
    resume_path: str
    profile_path: str
    pool_path: str
    filled: list[dict[str, Any]]
    skipped: list[dict[str, str]]
    screenshot: str = ""
    submit_clicked: bool = False
    notes: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _to_dict(self)
