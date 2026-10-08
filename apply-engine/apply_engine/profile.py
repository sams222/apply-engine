from __future__ import annotations

from pathlib import Path

from apply_engine.models import EEO, Profile
from apply_engine.util import parse_bool, split_name


REQUIRED = ("email",)


def load_profile(path: str | Path) -> Profile:
    path = Path(path)
    raw = _read(path)
    if not isinstance(raw, dict):
        raise ValueError(f"profile must be a JSON object: {path}")

    full_name = str(raw.get("full_name") or raw.get("name") or "").strip()
    first = str(raw.get("first_name") or "").strip()
    last = str(raw.get("last_name") or "").strip()
    if not first and not last and full_name:
        first, last = split_name(full_name)
    if not full_name:
        full_name = " ".join(p for p in (first, last) if p)

    email = str(raw.get("email") or "").strip()
    if not email:
        raise ValueError("profile.email is required")
    if not full_name:
        raise ValueError("profile.full_name or first_name+last_name is required")

    eeo_raw = raw.get("eeo") or {}
    if not isinstance(eeo_raw, dict):
        eeo_raw = {}
    eeo = EEO(
        gender=str(eeo_raw.get("gender") or ""),
        race_ethnicity=str(eeo_raw.get("race_ethnicity") or eeo_raw.get("race") or ""),
        veteran=str(eeo_raw.get("veteran") or ""),
        disability=str(eeo_raw.get("disability") or ""),
    )

    gpa = raw.get("gpa")
    if gpa is None or str(gpa).strip() in {"", "null", "none"}:
        gpa_s = None
    else:
        gpa_s = str(gpa).strip()

    known = {
        "full_name",
        "name",
        "first_name",
        "last_name",
        "email",
        "phone",
        "linkedin",
        "github",
        "website",
        "location",
        "city",
        "state",
        "country",
        "school",
        "degree",
        "gpa",
        "graduation",
        "education_start",
        "work_authorized_us",
        "need_sponsorship",
        "eeo",
        "resume_path",
        "preferred_locations",
        "skills",
        "available_from",
        "address_line1",
        "postal_code",
        "how_heard",
        "field_of_study",
        "major",
        "previous_employee",
        "requires_housing",
    }
    extra = {k: v for k, v in raw.items() if k not in known and k != "extra"}
    nested = raw.get("extra")
    if isinstance(nested, dict):
        for k, v in nested.items():
            extra.setdefault(k, v)

    skills = raw.get("skills") or []
    if isinstance(skills, str):
        skills = [s.strip() for s in skills.split(",") if s.strip()]
    preferred = raw.get("preferred_locations") or []
    if isinstance(preferred, str):
        preferred = [s.strip() for s in preferred.split(",") if s.strip()]

    return Profile(
        full_name=full_name,
        first_name=first,
        last_name=last,
        email=email,
        phone=str(raw.get("phone") or ""),
        linkedin=str(raw.get("linkedin") or ""),
        github=str(raw.get("github") or ""),
        website=str(raw.get("website") or ""),
        location=str(raw.get("location") or ""),
        city=str(raw.get("city") or ""),
        state=str(raw.get("state") or ""),
        country=str(raw.get("country") or ""),
        school=str(raw.get("school") or ""),
        degree=str(raw.get("degree") or ""),
        gpa=gpa_s,
        graduation=str(raw.get("graduation") or ""),
        education_start=str(raw.get("education_start") or ""),
        work_authorized_us=parse_bool(raw.get("work_authorized_us")),
        need_sponsorship=parse_bool(raw.get("need_sponsorship")),
        eeo=eeo,
        resume_path=str(raw.get("resume_path") or ""),
        preferred_locations=[str(x) for x in preferred],
        skills=[str(x) for x in skills],
        available_from=str(raw.get("available_from") or ""),
        address_line1=str(raw.get("address_line1") or ""),
        postal_code=str(raw.get("postal_code") or ""),
        how_heard=str(raw.get("how_heard") or ""),
        field_of_study=str(raw.get("field_of_study") or raw.get("major") or "").strip(),
        previous_employee=(parse_bool(raw.get("previous_employee")) is True),
        requires_housing=parse_bool(raw.get("requires_housing")),
        extra=extra,
    )


def _read(path: Path) -> object:
    import json

    return json.loads(path.read_text(encoding="utf-8"))
