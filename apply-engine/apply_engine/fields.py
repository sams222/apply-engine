from __future__ import annotations

import re

from apply_engine.models import Profile
from apply_engine.util import normalize_label

# Specific keys first so "name" does not steal "first name".
FIELD_ALIASES: list[tuple[str, tuple[str, ...]]] = [
    ("first_name", ("first name", "given name", "first_name", "fname", "preferred first name")),
    ("last_name", ("last name", "family name", "surname", "last_name", "lname")),
    ("email", ("email", "e mail", "email address")),
    ("phone", ("phone number", "phone-number", "mobile", "tel", "telephone", "phone")),
    ("linkedin", ("linkedin profile", "linkedin url", "linkedin")),
    ("github", ("github url", "github profile", "github")),
    ("website", ("website", "portfolio", "personal website", "portfolio url")),
    # Address Line 1 is required on Workday and had no alias at all, so the
    # profile's street address could never reach any application.
    ("address_line1", ("address line 1", "street address", "address line1", "addressline1")),
    ("city", ("city", "city / town", "city/town")),
    ("state", ("state", "state / province", "province", "region", "currently reside")),
    ("postal_code", ("postal code", "zip", "zip code", "postal")),
    ("country", ("country",)),
    ("location", ("location", "current location", "where are you located")),
    ("school", ("school", "university", "college", "institution")),
    ("degree", ("degree", "degree type")),
    ("field_of_study", ("field of study", "major", "discipline", "area of study", "concentration")),
    ("gpa", ("gpa", "grade point")),
    ("graduation", ("graduation", "grad year", "expected graduation", "graduation date")),
    ("education_start", ("first year attended", "education start", "started school", "enrollment date")),
    ("resume", ("resume", "resume/cv", "cv", "attach resume", "upload resume")),
    ("cover_letter", ("cover letter", "coverletter")),
    ("full_name", ("full name", "first and last name", "first & last name", "legal name", "your name", "candidate name")),
    # Do NOT use bare "work authorization" — Waymo "Do you require work authorization?" means sponsorship.
    ("work_authorized_us", ("authorized to work", "legally authorized", "eligible to work", "right to work", "work authorized")),
    ("need_sponsorship", ("require work authorization", "require sponsorship", "visa sponsorship", "need sponsorship", "h1b", "h-1b", "need visa")),
    # Not bare "not applicable": Workday EEO dropdowns show that as their current value.
    ("sponsorship_type", ("work authorization sponsorship",)),
    ("how_heard", ("how did you hear", "how did you hear about", "how heard")),
    ("previous_employee", ("previous employee", "former employee", "alphabet employee", "worked at alphabet")),
    ("export_license", ("export license",)),
    ("policy_ack", ("candidate privacy", "privacy policy", "acknowledge the above", "outside assistance", "artificial intelligence")),
    ("gender", ("gender", "sex")),
    ("race_ethnicity", ("race", "ethnicity", "race ethnicity")),
    ("veteran", ("veteran", "protected veteran")),
    ("disability", ("disability", "disability status")),
]

# Video.js caption / cookie / job-alert chrome that must not block preflight.
NOISE_FIELD_LABELS = frozenset(
    {
        "color",
        "opacity",
        "font size",
        "text edge style",
        "font family",
        "departments",
        "locations",
        "please choose the department(s)",
        "please choose the location(s)",
        "strictly necessary cookies",
        "performance cookies",
        "search",
        "allow strictly necessary cookies",
        "allow performance cookies",
    }
)

_MONTH_NAME_TO_NUM = {
    "january": "1",
    "jan": "1",
    "february": "2",
    "feb": "2",
    "march": "3",
    "mar": "3",
    "april": "4",
    "apr": "4",
    "may": "5",
    "june": "6",
    "jun": "6",
    "july": "7",
    "jul": "7",
    "august": "8",
    "aug": "8",
    "september": "9",
    "sep": "9",
    "sept": "9",
    "october": "10",
    "oct": "10",
    "november": "11",
    "nov": "11",
    "december": "12",
    "dec": "12",
}


# Bot traps. Workday ships a hidden "beecatcher" input on its auth form, named
# `website` and labelled "for robots only" — a field only automation would fill.
# Filling one marks the application as a bot, so these are never mapped.
HONEYPOT_AUTOMATION_IDS = ("beecatcher",)
HONEYPOT_LABEL_MARKERS = (
    "for robots only",
    "do not enter if you're human",
    "do not enter if you are human",
    "leave this field blank",
    "leave this field empty",
    "if you are human",
)
HONEYPOT_NAMES = ("beecatcher", "honeypot", "bot-field", "bot_field")


def is_honeypot(
    label: str = "",
    name: str = "",
    element_id: str = "",
    automation_id: str = "",
    width: float | None = None,
    height: float | None = None,
) -> bool:
    """True when this control is a bot trap rather than a real question.

    Detected three ways, because any one of them can be absent:
      * automation id / name Workday and common form kits use for traps
      * label text that tells a human not to fill it
      * a zero-area box that no human could type into (width or height 0)
    """
    blob = " ".join([label or "", name or "", element_id or "", automation_id or ""]).lower()
    if any(token in blob for token in HONEYPOT_AUTOMATION_IDS):
        return True
    if any(token in (name or "").strip().lower() for token in HONEYPOT_NAMES):
        return True
    if any(marker in (label or "").lower() for marker in HONEYPOT_LABEL_MARKERS):
        return True
    # A control a human cannot see or click. CSS may still call it "visible":
    # Walmart's trap is display:block, visibility:visible, opacity:1, sized 1x0.
    if width is not None and height is not None:
        if width <= 1 or height <= 1:
            return True
    return False


# How Did You Hear About Us: we arrive via the company's own careers page every
# time, so answer that. Ordered by how commonly ATS option lists spell it.
HOW_HEARD_PRIMARY = "Company Website"
HOW_HEARD_CAREER_TERMS = (
    "Company Website",
    "Company Career Site",
    "Careers Page",
    "Career Site",
    "Careers Website",
    "Corporate Website",
    "Company Site",
    "Employer Website",
    "Organization Website",
    "Company Careers",
    "Website",
)


def is_noise_field(label: str = "", name: str = "", element_id: str = "", placeholder: str = "") -> bool:
    """Decorative / off-form widgets (Video.js captions, job-alert multi-selects, cookies)."""
    if is_honeypot(label=label, name=name, element_id=element_id):
        return True
    eid = (element_id or "").strip().lower()
    if eid.startswith("vjs_") or "vjs_select" in eid:
        return True
    if eid.endswith("-selectized") and normalize_label(label or "") in {"departments", "locations"}:
        return True
    lab = normalize_label(label or "")
    if lab in NOISE_FIELD_LABELS:
        return True
    # Bare caption option values sometimes surface without a real application label.
    if lab in {"white", "black", "opaque", "semi transparent", "transparent"} and not (name or "").strip():
        return True
    _ = placeholder
    return False


def map_field(label: str, name: str = "", element_id: str = "", placeholder: str = "") -> str | None:
    from apply_engine.workday_widgets import is_country_phone_code_field

    if is_noise_field(label, name, element_id, placeholder):
        return None
    if is_country_phone_code_field(label, name, element_id, placeholder):
        return None
    blob = normalize_label(" ".join([label, name.replace("_", " "), element_id.replace("_", " "), placeholder]))
    if not blob:
        return None
    # Ashby Name / First and Last Name: match on label alone (UUID ids pollute blob).
    label_norm = normalize_label(label or "")
    if label_norm in {"name", "first and last name", "first last name", "first & last name"}:
        return "full_name"
    sys_id = (name or element_id or "").strip().lower()
    if sys_id in {"_systemfield_name", "systemfield_name"}:
        return "full_name"

    # Waymo / Greenhouse-embed grounded question overrides (before generic aliases).
    special = _map_special_question(label_norm, placeholder=normalize_label(placeholder or ""))
    if special:
        return special

    for key, aliases in FIELD_ALIASES:
        for alias in aliases:
            if alias == blob or blob.startswith(alias + " ") or f" {alias} " in f" {blob} ":
                return key
    # Greenhouse classic name attributes
    lowered = (name or element_id).lower()
    if is_country_phone_code_field(automation_id=lowered):
        return None
    for key, _ in FIELD_ALIASES:
        if lowered == key or lowered.endswith(f"[{key}]") or lowered.endswith(f"_{key}"):
            return key
    return None


def _map_special_question(label_norm: str, *, placeholder: str = "") -> str | None:
    if not label_norm and placeholder == "yyyy":
        return "graduation_year"
    if not label_norm and placeholder == "mm":
        return "graduation_month"
    if "end date" in label_norm:
        if "year" in label_norm or placeholder == "yyyy":
            return "graduation_year"
        return "graduation_month"
    if placeholder == "yyyy":
        return "graduation_year"
    if placeholder == "mm" and ("end" in label_norm or "grad" in label_norm or not label_norm):
        return "graduation_month"

    # Authorized-without-sponsorship (West Monroe / Greenhouse) is not need_sponsorship.
    if (
        "without" in label_norm
        and "sponsor" in label_norm
        and any(t in label_norm for t in ("authori", "eligible", "able to work", "permitted"))
    ):
        return "work_authorized_without_sponsorship"

    # Sponsorship vs work-authorized (Waymo wording).
    if "require work authorization" in label_norm or (
        "work authorization" in label_norm and "sponsorship" in label_norm
    ):
        if "what kind" in label_norm or "not applicable" in label_norm:
            return "sponsorship_type"
        if "require" in label_norm:
            return "need_sponsorship"

    if "how did you hear" in label_norm:
        return "how_heard"
    if "export license" in label_norm:
        return "export_license"
    if "alphabet" in label_norm and any(
        t in label_norm for t in ("employee", "intern", "vendor", "contractor", "temp")
    ):
        return "previous_employee"
    if "acknowledge" in label_norm or "artificial intelligence" in label_norm or "outside assistance" in label_norm:
        if any(
            t in label_norm
            for t in ("privacy", "artificial intelligence", "outside assistance", "ai tools", "generative")
        ):
            return "policy_ack"
    if "currently reside" in label_norm or ("state" in label_norm and "reside" in label_norm):
        return "state"
    if "legal name" in label_norm and "government" in label_norm:
        return "full_name"
    return None


def profile_value(profile: Profile, key: str) -> str | None:
    if key == "first_name":
        return profile.first_name or None
    if key == "last_name":
        return profile.last_name or None
    if key == "full_name":
        return profile.full_name or None
    if key == "email":
        return profile.email or None
    if key == "phone":
        return profile.phone or None
    if key == "postal_code":
        return profile.postal_code or None
    if key == "address_line1":
        return (
            profile.address_line1
            or str((profile.extra or {}).get("address_line1") or "")
            or None
        )
    if key == "field_of_study":
        return profile.field_of_study or None
    if key == "linkedin":
        return profile.linkedin or None
    if key == "github":
        return profile.github or None
    if key == "website":
        return profile.website or profile.github or None
    if key == "city":
        return profile.city or None
    if key == "state":
        return profile.state or None
    if key == "country":
        return profile.country or None
    if key == "location":
        return profile.location or None
    if key == "school":
        return profile.school or None
    if key == "degree":
        return profile.degree or None
    if key == "gpa":
        return profile.gpa  # never invent
    if key == "graduation":
        return profile.graduation or None
    if key == "education_start":
        return profile.education_start or None
    if key == "graduation_month":
        return _graduation_month(profile.graduation)
    if key == "graduation_year":
        return _graduation_year(profile.graduation)
    if key == "work_authorized_us":
        return _yes_no(profile.work_authorized_us)
    if key == "need_sponsorship":
        return _yes_no(profile.need_sponsorship)
    if key == "work_authorized_without_sponsorship":
        if profile.work_authorized_us is True and profile.need_sponsorship is False:
            return "Yes"
        if profile.work_authorized_us is False or profile.need_sponsorship is True:
            return "No"
        return None
    if key == "sponsorship_type":
        if profile.need_sponsorship is False:
            return "Not applicable"
        return None
    if key == "how_heard":
        # We always reach these postings through the company's own careers page
        # (the hunter hands us a boards/Workday URL), so that is the truthful
        # answer. A profile value stays available as a fallback for boards whose
        # list has no company-site option.
        return HOW_HEARD_PRIMARY
    if key == "previous_employee":
        if profile.previous_employee:
            return None  # do not auto-fill yes-path follow-ups
        return "Never"
    if key == "export_license":
        # Grounded for US-authorized candidates who need no sponsorship.
        if profile.work_authorized_us and profile.need_sponsorship is False:
            return "No"
        return None
    if key == "policy_ack":
        return "I acknowledge"
    if key == "gender":
        return profile.eeo.gender or None
    if key == "race_ethnicity":
        return profile.eeo.race_ethnicity or None
    if key == "veteran":
        return profile.eeo.veteran or None
    if key == "disability":
        return profile.eeo.disability or None
    return None


def _graduation_year(graduation: str | None) -> str | None:
    s = (graduation or "").strip()
    if not s:
        return None
    m = re.search(r"(20\d{2}|19\d{2})", s)
    return m.group(1) if m else None


def _graduation_month(graduation: str | None) -> str | None:
    s = (graduation or "").strip()
    if not s:
        return None
    low = s.lower()
    for name, num in _MONTH_NAME_TO_NUM.items():
        if re.search(rf"\b{re.escape(name)}\b", low):
            return num
    # Numeric month at start: 05/2028 or 5/2028
    m = re.match(r"^(0?[1-9]|1[0-2])\b", s)
    if m:
        return str(int(m.group(1)))
    return None


def _yes_no(value: bool | None) -> str | None:
    if value is None:
        return None
    return "Yes" if value else "No"



URL_PROFILE_KEYS = frozenset({"linkedin", "github", "website"})

# Controls that can hold a profile URL (not how-heard checkboxes / radios / hidden ids).
_URL_INPUT_TYPES = frozenset({"", "text", "url", "search", "email"})


def is_url_profile_key(key: str) -> bool:
    return (key or "") in URL_PROFILE_KEYS


def is_url_capable_control(tag: str = "", input_type: str = "", role: str = "") -> bool:
    """True for text-like inputs/textareas suitable for LinkedIn/GitHub/website URLs."""
    tag_l = (tag or "").lower()
    type_l = (input_type or "").lower()
    role_l = (role or "").lower()
    if type_l in {"checkbox", "radio", "hidden", "submit", "button", "file", "image", "reset"}:
        return False
    if tag_l == "textarea":
        return True
    if tag_l == "select":
        return False
    if tag_l in {"input", ""}:
        return type_l in _URL_INPUT_TYPES
    if role_l in {"textbox", "combobox", "searchbox"}:
        return True
    return False


def looks_like_phone_or_id_bleed(value: str) -> bool:
    """True when readback is digits (option ids / phone) rather than a URL."""
    s = (value or "").strip()
    if not s:
        return False
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) >= 8 and len(digits) >= len(s) - 3:
        # Mostly digits with optional +()- spaces — not a profile URL.
        if "://" not in s and "linkedin." not in s.lower() and "github." not in s.lower():
            return True
    return False


def normalize_profile_url(url: str) -> str:
    s = (url or "").strip()
    if not s:
        return ""
    low = s.lower()
    if low.startswith("http://"):
        s = "https://" + s[7:]
        low = s.lower()
    if low.startswith("https://www."):
        s = "https://" + s[12:]
        low = s.lower()
    return s.rstrip("/")


def url_readback_matches(observed: str, intended: str) -> bool:
    """Sticky URL check: reject phone/option-id bleed; require URL-shaped match."""
    if looks_like_phone_or_id_bleed(observed):
        return False
    obs = normalize_profile_url(observed)
    exp = normalize_profile_url(intended)
    if not obs or not exp:
        return False
    if obs == exp:
        return True
    obs_l, exp_l = obs.lower(), exp.lower()
    if obs_l == exp_l:
        return True
    # Allow missing scheme on either side once normalized.
    if obs_l.endswith(exp_l.split("://", 1)[-1]) or exp_l.endswith(obs_l.split("://", 1)[-1]):
        # Require a path-ish URL host marker for profile keys.
        if any(h in obs_l for h in ("linkedin.com", "github.com", "http://", "https://")) or "/" in obs_l:
            return True
    # Substring commit used elsewhere — only if observed still looks like a URL.
    if "://" in obs_l or "." in obs_l:
        if exp_l in obs_l or obs_l in exp_l:
            return True
        exp_path = exp_l.split("://", 1)[-1]
        obs_path = obs_l.split("://", 1)[-1]
        if exp_path and (exp_path in obs_path or obs_path in exp_path):
            return True
    return False


def profile_url_forms(key: str, value: str) -> list[str]:
    """URL spellings to try, best first.

    Workday validates LinkedIn strictly: live Walmart rejected
    https://linkedin.com/in/<handle> with "Invalid LinkedIn URL" and wants the
    www. host. Other boards accept either, so offer www first and keep the
    profile's own spelling as a fallback.
    """
    raw = (value or "").strip()
    if not raw:
        return []
    out: list[str] = []

    def add(item: str) -> None:
        if item and item not in out:
            out.append(item)

    if key == "linkedin":
        m = re.search(r"linkedin\.com/(.+)$", raw, re.I)
        if m:
            path = m.group(1).strip("/")
            add(f"https://www.linkedin.com/{path}")
        add(raw)
    elif key == "github":
        m = re.search(r"github\.com/(.+)$", raw, re.I)
        if m:
            add(f"https://github.com/{m.group(1).strip('/')}")
        add(raw)
    else:
        add(raw)
    return out


def value_candidates(key: str, desired: str, profile: Profile | None = None) -> list[str]:
    """Expand a profile value into select-option search terms (state NY→New York, how-heard, etc.)."""
    out: list[str] = []
    seen: set[str] = set()

    def add(item: str) -> None:
        item = (item or "").strip()
        if not item:
            return
        low = item.lower()
        if low in seen:
            return
        seen.add(low)
        out.append(item)

    add(desired)
    if key == "state" and profile is not None:
        from apply_engine.workday_widgets import state_search_terms

        for term in state_search_terms(profile):
            add(term)
    if key == "how_heard":
        low = (desired or "").lower()
        # Careers-page spellings first, in the order ATS option lists use them.
        # Company Website / Career Site beat Relish Careers / job-board names.
        for term in HOW_HEARD_CAREER_TERMS:
            add(term)
        if profile is not None and getattr(profile, "extra", None):
            company = str((profile.extra or {}).get("company") or "").strip()
            if company:
                add(f"{company} Careers")
                add(f"{company} Website")
        fallback = str(getattr(profile, "how_heard", "") or "").strip()
        low = f"{low} {fallback.lower()}".strip()
        if "facebook" in low or "twitter" in low or "instagram" in low or low == "social media":
            add("Social Media")
            add("Facebook")
        if "linkedin" in low:
            add("LinkedIn")
        if "handshake" in low:
            add("Handshake")
        if "indeed" in low:
            add("Indeed")
        if "glassdoor" in low:
            add("Glassdoor")
        if "careers" in low or "company site" in low or "website" in low:
            add("Careers Page")
        if "friend" in low or "word of mouth" in low or "referral" in low:
            add("Word of Mouth")
        if fallback:
            add(fallback)
        # Last resort: we did come from the careers page, so when the list
        # offers no company option at all, "Other" is the honest choice.
        add("Other")
    if key == "previous_employee":
        add("Never worked")
        add("No")
    if key == "policy_ack":
        add("I acknowledge")
        add("acknowledge")
    if key == "sponsorship_type":
        add("Not applicable")
        add("Not Applicable")
        add("N/A")
    if key in {"need_sponsorship", "work_authorized_us", "work_authorized_without_sponsorship", "export_license"}:
        add(desired)
    return out


def pick_select_option(options: list[str], desired: str) -> str | None:
    if not desired:
        return None
    want = desired.strip().lower()
    cleaned = [o for o in options if str(o or "").strip()]
    for opt in cleaned:
        if opt.strip().lower() == want:
            return opt
    # Careers-page answers are spelled per tenant ("Walmart Careers",
    # "Company Career Site", "Corporate Website"). Prefer Company Website /
    # Career Site over Relish Careers when both exist.
    if want in {t.lower() for t in HOW_HEARD_CAREER_TERMS}:
        from apply_engine.questions import _how_heard_score

        ranked = sorted(cleaned, key=lambda o: -_how_heard_score(o))
        if ranked and _how_heard_score(ranked[0]) > 0:
            return ranked[0]
        for opt in cleaned:
            low = opt.strip().lower()
            if "career" in low and "relish" not in low:
                return opt
        for opt in cleaned:
            low = opt.strip().lower()
            if ("company" in low or "corporate" in low or "employer" in low) and (
                "site" in low or "website" in low
            ):
                return opt
    # Yes/No variants — exact token match only (avoid "no" ⊂ "not applicable" unless no Yes/No exist).
    if want in {"yes", "true"}:
        for opt in cleaned:
            if opt.strip().lower() in {"yes", "true", "y"}:
                return opt
    if want in {"no", "false"}:
        for opt in cleaned:
            if opt.strip().lower() in {"no", "false", "n"}:
                return opt
    # State abbreviation / canon
    try:
        from apply_engine.workday_widgets import canonicalize_state

        want_canon = canonicalize_state(desired)
        if want_canon:
            for opt in cleaned:
                if canonicalize_state(opt) == want_canon:
                    return opt
    except Exception:
        pass
    for opt in cleaned:
        ol = opt.lower()
        if want in ol or ol in want:
            return opt
    decline = [o for o in cleaned if "decline" in o.lower() or "don't wish" in o.lower() or "do not wish" in o.lower()]
    if decline and want in {"", "decline"}:
        return decline[0]
    return None


def select_readback_matches(observed: str, intended: str, *, key: str = "") -> bool:
    """Sticky select/yes-no check with state / acknowledge / Not-applicable synonyms."""
    obs = (observed or "").strip()
    exp = (intended or "").strip()
    if not obs or not exp:
        return False
    if obs.lower() == exp.lower():
        return True
    if pick_select_option([obs], exp) is not None:
        return True
    # Intended No / Not applicable synonym when key is sponsorship_type
    if key == "sponsorship_type":
        if "not applicable" in obs.lower() and "not applicable" in exp.lower():
            return True
    if key == "policy_ack" and "acknowledge" in obs.lower() and "acknowledge" in exp.lower():
        return True
    if key == "previous_employee" and "never" in obs.lower() and "never" in exp.lower():
        return True
    if key == "how_heard":
        # Facebook ↔ Social Media (Facebook...)
        if "facebook" in exp.lower() and ("facebook" in obs.lower() or "social media" in obs.lower()):
            return True
    if key == "state":
        try:
            from apply_engine.workday_widgets import canonicalize_state

            return bool(canonicalize_state(obs) and canonicalize_state(obs) == canonicalize_state(exp))
        except Exception:
            return False
    return False
