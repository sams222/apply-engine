"""Question text -> grounded answer, independent of any ATS widget.

`resolve` classifies an application question and returns a `Want`: the text
to type, or the option terms to pick, derived only from the profile, the
project pool, and the posting. Widgets live in `forms.py`; this module never
touches a page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from apply_engine.models import PoolEntry, Profile

MONTHS = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)


@dataclass
class Context:
    job_title: str = ""
    company: str = ""
    description: str = ""
    pool: list[PoolEntry] = field(default_factory=list)
    today: date = field(default_factory=date.today)


@dataclass
class Want:
    key: str
    text: str | None = None
    terms: list[str] = field(default_factory=list)
    polarity: bool | None = None
    pick: Callable[[list[str]], list[str]] | None = None
    select_all: bool = False
    essay: bool = False
    search: str | None = None
    searches: list[str] = field(default_factory=list)
    leave_blank: bool = False
    skip_if_optional: bool = False


def norm(text: str) -> str:
    t = (text or "").lower().replace("\u2019", "'").replace("\u2013", "-").replace("\u2014", "-")
    t = re.sub(r"[\u2731*]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    # Greenhouse/Workday labels often ship as "Address Line 1:*" / "City:".
    return t.rstrip(":* ").strip()


def _extra(profile: Profile, key: str, default=None):
    return (profile.extra or {}).get(key, default)


def _bool(profile: Profile, key: str, default: bool | None = None) -> bool | None:
    raw = _extra(profile, key)
    return raw if isinstance(raw, bool) else default


# --- derived facts ---------------------------------------------------------


def parse_month_year(text: str) -> tuple[int, int] | None:
    low = norm(text)
    m = re.search(r"\b(" + "|".join(m[:3] for m in MONTHS) + r")[a-z]*\.?\s+(\d{4})\b", low)
    if m:
        return MONTHS.index(next(x for x in MONTHS if x.startswith(m.group(1)))) + 1, int(m.group(2))
    m = re.search(r"\b(0?[1-9]|1[0-2])\s*/\s*(?:\d{1,2}\s*/\s*)?(\d{4})\b", low)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def graduation(profile: Profile) -> tuple[int, int] | None:
    return parse_month_year(profile.graduation)


def class_standing(profile: Profile, today: date) -> str | None:
    grad = graduation(profile)
    if not grad:
        return None
    month, year = grad
    academic_end = today.year + (1 if today.month >= 7 else 0)
    years_left = year - academic_end + (0 if month >= 5 else -1) + 1
    return {1: "Senior", 2: "Junior", 3: "Sophomore", 4: "Freshman"}.get(years_left)


def current_role(pool: list[PoolEntry]) -> PoolEntry | None:
    for entry in pool:
        if entry.kind != "project" and entry.company and norm(entry.end) in {"present", "current", "now"}:
            return entry
    return None


def internship_count(pool: list[PoolEntry]) -> int:
    return sum(1 for e in pool if e.kind != "project" and re.search(r"\bintern", e.role or "", re.I))


def years_experience(pool: list[PoolEntry], today: date) -> int:
    starts = [parse_month_year(e.start) for e in pool if e.kind != "project" and e.start]
    starts = [s for s in starts if s]
    if not starts:
        return 0
    month, year = min(starts, key=lambda s: (s[1], s[0]))
    return max(0, (today.year - year) * 12 + today.month - month) // 12


def season_start_date(ctx: Context) -> date | None:
    from apply_engine.workday_widgets import season_start

    info = season_start(ctx.job_title, ctx.description[:600], today=ctx.today)
    if not info:
        return None
    return date(int(info["year"]), int(info["month_num"]), int(info["day"]))


def home_city_terms(profile: Profile) -> list[str]:
    out = []
    for item in [profile.city, *profile.preferred_locations]:
        item = (item or "").strip()
        if item and item.lower() not in {o.lower() for o in out}:
            out.append(item)
    if any(o.lower() == "new york" for o in out):
        out.insert(out.index(next(o for o in out if o.lower() == "new york")) + 1, "NYC")
    return out


def state_name(profile: Profile) -> str:
    from apply_engine.workday_widgets import state_search_label

    return state_search_label(profile) or profile.state


# --- option pickers --------------------------------------------------------


def _pick_graduation(profile: Profile) -> Callable[[list[str]], list[str]]:
    def pick(options: list[str]) -> list[str]:
        grad = graduation(profile)
        if not grad:
            return []
        month, year = grad
        exact, season_hits, same_year, ranges = [], [], [], []
        season = {12: "winter", 1: "winter", 4: "spring", 5: "spring", 6: "summer", 8: "summer", 9: "fall"}.get(month, "")
        for opt in options:
            low = norm(opt)
            parsed = parse_month_year(opt)
            if parsed == (month, year):
                exact.append(opt)
            elif re.search(rf"\b{year}\b", low) and len(re.findall(r"\b(?:19|20)\d{2}\b", low)) == 1:
                if parsed is None and season and season in low:
                    season_hits.append(opt)
                elif parsed is None:
                    same_year.append(opt)
            else:
                years = [int(y) for y in re.findall(r"\b(20\d{2})\b", low)]
                if len(years) == 2 and years[0] <= year <= years[1]:
                    ranges.append(opt)
        return exact + season_hits + same_year + ranges

    return pick


def _pick_number(n: int) -> Callable[[list[str]], list[str]]:
    def pick(options: list[str]) -> list[str]:
        for opt in options:
            low = norm(opt)
            nums = [int(x) for x in re.findall(r"\d+", low)]
            if not nums:
                if n == 0 and re.search(r"\b(none|no|zero)\b", low):
                    return [opt]
                continue
            if len(nums) == 1 and "+" in low and n >= nums[0]:
                return [opt]
            if len(nums) == 1 and re.search(r"(less than|under|<)", low) and n < nums[0]:
                return [opt]
            if len(nums) == 1 and re.search(r"(more than|over|>)", low) and n > nums[0]:
                return [opt]
            if len(nums) == 1 and nums[0] == n:
                return [opt]
            if len(nums) >= 2 and nums[0] <= n <= nums[1]:
                return [opt]
        return []

    return pick


def _rank(q: str) -> int:
    return 2 if re.search(r"\b(second|2nd)\b", q) else 3 if re.search(r"\b(third|3rd)\b", q) else 1


def _pick_locations(profile: Profile, rank: int = 1) -> Callable[[list[str]], list[str]]:
    terms = home_city_terms(profile)

    def pick(options: list[str]) -> list[str]:
        out = []
        for term in terms:
            for opt in options:
                if phrase_in(norm(term), norm(opt)) and opt not in out:
                    out.append(opt)
                    break
        anywhere = [o for o in options if re.search(r"open to (working (in|at|from) )?any|^any (office|location)|^either$|no preference", norm(o))]
        fallback = anywhere[:1] if _bool(profile, "willing_to_relocate") else []
        if rank > 1:
            return out[rank - 1:rank] or fallback
        return out or fallback

    return pick


_HOW_HEARD_BOARD_RE = re.compile(
    r"relish|linkedin|indeed|glassdoor|handshake|ziprecruiter|monster|referral|recruiter"
)
_HOW_HEARD_COMPANY_RE = re.compile(
    r"company (career site|careers?( page| site| website)?|website|site)|"
    r"corporate (web)?site|career site|careers (page|website|site)|employer website"
)


def _how_heard_score(option: str) -> int:
    """Higher is better. Company/Corporate Website beat a generic Career Site."""
    low = norm(option)
    if _HOW_HEARD_BOARD_RE.search(low):
        return 0
    if re.search(
        r"company website|corporate website|company career site|"
        r"company careers (page|site|website)|employer website",
        low,
    ):
        return 4
    if re.search(r"^career site$|^careers page$|^careers site$|^career page$|^career website$", low):
        return 3
    if _HOW_HEARD_COMPANY_RE.search(low):
        return 3
    if re.search(r"\bwebsite\b", low):
        return 2
    if re.search(r"career", low):
        return 1
    if re.search(r"^other\b", low):
        return 0
    return -1


def _pick_how_heard(options: list[str]) -> list[str]:
    ranked = sorted(options, key=lambda o: -_how_heard_score(o))
    if ranked and _how_heard_score(ranked[0]) > 0:
        return [ranked[0]]
    boards = [o for o in options if _HOW_HEARD_BOARD_RE.search(norm(o)) and "career" in norm(o)]
    if boards:
        return boards[:1]
    others = [o for o in options if re.search(r"^other\b", norm(o))]
    return others[:1]


# --- matching --------------------------------------------------------------


def phrase_in(needle: str, hay: str) -> bool:
    if not needle:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", hay) is not None


_NO_RE = re.compile(
    r"^(no\b|none\b|not\b|n/?a\b|never\b|i (do|am|have|will|would|did) not\b|i don't\b|i'm not\b|"
    r"i haven't\b|i won't\b|i have never\b|false\b)"
)
_YES_RE = re.compile(
    r"^(yes\b|y\b|true\b|i (am|do|have|will|would|can|agree|acknowledge|consent|certify|understand|confirm)\b|i'm\b|"
    r"confirm(ed)?\b|agreed?\b|acknowledged?\b|accept(ed)?\b)"
)
_DECLINE_RE = re.compile(r"decline|prefer not|don't wish|do not wish|choose not|not to (say|disclose|answer)|rather not")


def option_polarity(option: str) -> bool | None:
    low = norm(option)
    if _DECLINE_RE.search(low):
        return None
    if _NO_RE.search(low):
        return False
    if _YES_RE.search(low):
        return True
    return None


def choose(options: list[str], want: Want) -> list[str]:
    """Options to select, best first. Empty when nothing is grounded."""
    cleaned = [o for o in options if (o or "").strip() and norm(o) not in {"select...", "select", "select one", "--", "please select"}]
    if not cleaned:
        return []
    if want.select_all:
        return cleaned
    if want.pick:
        picked = [o for o in want.pick(cleaned) if o in cleaned]
        if picked:
            return picked
    for term in want.terms:
        t = norm(term)
        for opt in cleaned:
            if norm(opt) == t:
                return [opt]
    for term in want.terms:
        t = norm(term)
        hits = [o for o in cleaned if norm(o).startswith(t) and phrase_in(t, norm(o))]
        if hits:
            return [min(hits, key=len)]
    for term in want.terms:
        t = norm(term)
        hits = [o for o in cleaned if phrase_in(t, norm(o)) and option_polarity(o) is not False]
        if hits:
            return [min(hits, key=len)]
    if want.polarity is not None:
        hits = [o for o in cleaned if option_polarity(o) is want.polarity]
        if hits:
            return [min(hits, key=len)]
    return []


# --- rules -----------------------------------------------------------------


def _yn(key: str, value: bool | None, *extra_terms: str) -> Want | None:
    if value is None:
        return None
    text = "Yes" if value else "No"
    return Want(key=key, text=text, terms=[text, *extra_terms], polarity=value)


Rule = Callable[[str, Profile, Context], Want | None]


def _rules() -> list[tuple[re.Pattern, Rule]]:
    R: list[tuple[str, Rule]] = []

    def add(pattern: str, fn: Rule) -> None:
        R.append((pattern, fn))

    add(r"portfolio password|password or access code|access codes?\b",
        lambda q, p, c: Want(key="portfolio_password", text="N/A", terms=["N/A", "Not applicable", "None"]))
    add(r"other than .{0,3}none of the above",
        lambda q, p, c: Want(key="followup_not_applicable", text="Not applicable",
                             terms=["Not applicable", "N/A", "None of these apply"], polarity=False))
    # Consent / marketing checkboxes before anything that shares words with them.
    add(r"\b(sms|text message|text messages|texting|receive texts?)\b",
        lambda q, p, c: _yn("sms_opt_in", bool(_bool(p, "sms_opt_in", False))))
    add(r"(contact me|keep me|notify me|email me|send me).{0,60}(future|other|new|relevant) (job|role|opportunit|position)|talent (community|network|pool)|future opportunities",
        lambda q, p, c: Want(key="marketing_opt_in", leave_blank=True))

    # Identity
    add(r"^(legal )?first name|^given name|^first name", lambda q, p, c: Want(key="first_name", text=p.first_name))
    add(r"^preferred (first )?name|^nickname|name you (prefer|go by)",
        lambda q, p, c: Want(key="preferred_name", text=str(_extra(p, "preferred_name") or p.first_name)))
    add(r"^(legal )?last name|^family name|^surname", lambda q, p, c: Want(key="last_name", text=p.last_name))
    add(r"^middle name", lambda q, p, c: Want(key="middle_name", leave_blank=True))
    add(r"^(full |legal |your )?name$|^full (legal )?name|^first and last name|^candidate name|(state|enter|provide) your (full )?(legal )?name|^legal name",
        lambda q, p, c: Want(key="full_name", text=p.full_name))
    add(r"^pronouns?\b|what pronouns|preferred pronouns",
        lambda q, p, c: Want(key="pronouns", text=str(_extra(p, "pronouns") or ""),
                             terms=_pronoun_terms(str(_extra(p, "pronouns") or ""))) if _extra(p, "pronouns") else None)
    add(r"pronounc", lambda q, p, c: Want(key="name_pronunciation", leave_blank=True))

    # Compound education blocks label sub-fields "<block> - <field>"; claim them before
    # the internship start-date rule sees "Start Date".
    add(r"^education( history)?\s*-\s*(school|university|institution)", lambda q, p, c: _school_want(p))
    add(r"^education( history)?\s*-\s*start", lambda q, p, c: _month_year_want("education_start", p.education_start, q))
    add(r"^education( history)?\s*-\s*(end|graduation)", lambda q, p, c: _month_year_want("graduation", p.graduation, q))
    add(r"^education( history)?\s*-\s*degree", lambda q, p, c: _degree_want(p))
    add(r"^employment\s*-\s*(company|employer)",
        lambda q, p, c: Want(key="employment_company", text=current_role(c.pool).company) if current_role(c.pool) else None)
    add(r"^employment\s*-\s*(title|role|position)$|^employment\s*-\s*job title",
        lambda q, p, c: Want(key="employment_title", text=current_role(c.pool).role) if current_role(c.pool) else None)
    add(r"^employment\s*-\s*(current|i currently work)",
        lambda q, p, c: _yn("employment_current", current_role(c.pool) is not None))
    add(r"^employment\s*-\s*start",
        lambda q, p, c: _month_year_want("employment_start", current_role(c.pool).start, q) if current_role(c.pool) else None)
    # A current role has no end date; Greenhouse keeps the field marked required but
    # accepts it empty once "Current role" is ticked.
    add(r"^employment\s*-\s*end",
        lambda q, p, c: Want(key="employment_end", leave_blank=True) if current_role(c.pool) else None)
    add(r"still (a )?student|currently (a )?student|currently (attending|enrolled)\??$|^i currently attend",
        lambda q, p, c: _yn("enrolled", _future(graduation(p), c.today)))

    add(r"^date$|^today'?s date|^(signature|signed) date|^date signed|^current date",
        lambda q, p, c: Want(key="today", text=c.today.strftime("%m/%d/%Y")))
    add(r"^(signature|electronic signature|e-?signature|sign here|your signature)$",
        lambda q, p, c: Want(key="signature", text=p.full_name))
    add(r"e-?mail", lambda q, p, c: Want(key="email", text=p.email))
    add(r"phone device type|device type",
        lambda q, p, c: Want(key="phone_device_type", text="Mobile",
                             terms=["Mobile Phone", "Mobile", "Cell Phone", "Cellular", "Cell"]))
    add(r"^(phone|mobile|cell|telephone)|phone number", lambda q, p, c: Want(key="phone", text=p.phone))
    add(r"^country$|^country of residence|^phone country|^country\b.{0,20}\b(code|residence)?$|which country (do|are) you (live|reside|located)",
        lambda q, p, c: Want(key="country", text="United States",
                             terms=["United States", "United States of America", "USA", "US", "United States +1", "+1"],
                             search="United States"))

    # Location / address
    add(r"address line 2|apt|suite", lambda q, p, c: Want(key="address_line2", leave_blank=True))
    add(r"^(street )?address( line 1)?$|street address|mailing address|home address",
        lambda q, p, c: Want(key="address_line1", text=p.address_line1))
    add(r"zip|postal", lambda q, p, c: Want(key="postal_code", text=p.postal_code))
    add(r"^state( / province| or province|/province)?$|^province|state of residence|which state",
        lambda q, p, c: Want(key="state", text=state_name(p), terms=[state_name(p), p.state], search=state_name(p)))
    add(r"^city$|^city / town|which city",
        lambda q, p, c: Want(key="city", text=p.city, terms=[p.city], search=p.city))
    add(r"(which|what) (conference|event|career fair|hackathon|meetup)s? (did|have) you (attend|go)|did you attend (the|a|any)",
        lambda q, p, c: Want(key="event_attended", text="None",
                             terms=["I did not attend", "Did not attend", "None", "Not applicable", "N/A"], polarity=False))
    add(r"(first|second|third|1st|2nd|3rd) (location|office) preference|location preference.{0,10}(first|second|third|#?[123])|(location|office|hub).{0,40}(most interested|prefer)|interested in (working|work) (out of|from|at|in)|any of the following (office|location|hub)s?|(office|hub|location)s? (would you|do you) prefer|prefer(red)? (office|hub|work location|location)|which (office|hub|location)s?|location preference|interested in (working|relocating) (from|to|in)|where would you (like|prefer) to work",
        lambda q, p, c: Want(key="preferred_location", text=p.location or p.city,
                             pick=_pick_locations(p, _rank(q)), terms=home_city_terms(p) if _rank(q) == 1 else []))
    add(r"^(current )?location|what is your (current )?location|where are you (currently )?(located|based)|current (city|residence)|where do you (currently )?(live|reside)|(city|state) (do|are) you (currently )?(live|reside)",
        lambda q, p, c: Want(key="location", text=p.location or p.city,
                             terms=[p.location, f"{p.city}, {state_name(p)}", p.city, "United States", "United States of America"],
                             search=p.city))

    # Links
    add(r"linkedin", lambda q, p, c: Want(key="linkedin", text=p.linkedin) if p.linkedin else None)
    add(r"github", lambda q, p, c: Want(key="github", text=p.github) if p.github else None)
    add(r"portfolio|personal (web)?site|^website|other website|^url\b|blog",
        lambda q, p, c: Want(key="website", text=p.website or p.github) if (p.website or p.github) else None)
    add(r"twitter|x\.com|instagram|facebook profile|dribbble|behance|stack ?overflow|kaggle|google scholar",
        lambda q, p, c: Want(key="other_link", leave_blank=True))

    # Legal / eligibility. "Authorized … without visa sponsorship" is NOT
    # need_sponsorship: that wording asks whether the candidate can already
    # work for any employer without a visa. Answer Yes when authorized AND
    # need_sponsorship is False. Must run before the sponsorship rule, which
    # would otherwise match the word "sponsor" and answer No.
    add(r"(authori[sz]ed|legally (authori[sz]ed|eligible|able|permitted)|eligible to work).{0,120}without.{0,40}((visa )?sponsor|work permit|employer support)|"
        r"without.{0,40}((visa )?sponsorship|work permit|employer support).{0,80}(authori[sz]ed|eligible|able|permitted)",
        lambda q, p, c: _authorized_without_sponsorship_want(p))
    add(r"^(?!.*(sponsor|requir|need|h-?1b|\bopt\b|\bcpt\b|employer support|work permit)).*(authori[sz]ed to work|legally (authori[sz]ed|eligible|able|permitted) to work)",
        lambda q, p, c: _yn("work_authorized_us", p.work_authorized_us))
    add(r"sponsor|visa|h-?1b|\bopt\b|\bcpt\b|immigration (support|status)|require.{0,40}(work )?authori[sz]ation|employment authori[sz]ation.{0,30}(need|require)|employer support|work permit",
        lambda q, p, c: _yn("need_sponsorship", p.need_sponsorship, "None", "Not applicable", "N/A", "I do not require", "No, I do not"))
    add(r"authori[sz]ed to work|legally (authori[sz]ed|eligible|able|permitted)|eligible to work|right to work|work (lawfully|legally)|lawfully (work|employed)|permitted to work",
        lambda q, p, c: _yn("work_authorized_us", p.work_authorized_us))
    add(r"u\.?s\.? person|export (control|administration)|\bitar\b|deemed export",
        lambda q, p, c: _yn("us_person", True if _bool(p, "us_citizen") else None, "U.S. Person", "US Person", "U.S. Citizen"))
    add(r"citizenship|citizen of|are you a (u\.?s\.?|united states) citizen|u\.?s\.? citizen",
        lambda q, p, c: Want(key="citizenship", text="U.S. Citizen",
                             terms=["U.S. Citizen", "US Citizen", "United States Citizen", "Citizen", "United States",
                                    "United States of America", "Yes"], polarity=True) if _bool(p, "us_citizen") else None)
    add(r"(currently|presently) (hold|have|possess).{0,40}clearance|active.{0,20}clearance|do you have.{0,30}clearance|clearance level|type of clearance",
        lambda q, p, c: Want(key="security_clearance", text="None",
                             terms=["None", "No", "N/A", "NA", "Not applicable", "No clearance", "I do not have"], polarity=False))
    add(r"(obtain|eligible|able|willing).{0,50}clearance|clearance.{0,40}(obtain|eligib)",
        lambda q, p, c: _yn("clearance_eligible", _bool(p, "clearance_eligible", bool(_bool(p, "us_citizen")))))
    add(r"18 years|at least 18|over 18|over the age of 18|legal age|age of majority|of age\b",
        lambda q, p, c: _yn("age_18", True))

    # History with the company. Government-official and conflict questions mention
    # relatives and employers, so they go before the family rule.
    add(r"government official|public official|politically exposed",
        lambda q, p, c: _yn("government_official_relative", _bool(p, "government_official_relative"))
        if re.search(r"relative|family", q) else _yn("government_official", _bool(p, "government_official")))
    add(r"conflict of interest|close personal relationship with (a )?senior",
        lambda q, p, c: _yn("conflict_of_interest", _bool(p, "conflict_of_interest")))
    add(r"\b(relatives?|family members?|related to|spouse|domestic partner)\b.{0,80}(employ|work|company|currently)|(employ|work).{0,60}\b(relatives?|family members?)\b",
        lambda q, p, c: Want(key="family_at_employer", text="No", terms=["No", "None"], polarity=False))
    add(r"refer(red|ral)|who referred|employee referral",
        lambda q, p, c: Want(key="referral", leave_blank=True) if re.search(r"name|who|email", q) else
        Want(key="referral", text="No", terms=["No", "No referral", "None"], polarity=False))
    add(r"(previously|ever|currently|formerly|have you) (been )?(worked|employed|work|interned|an employee|a (current|former)).{0,80}|former employee|current or former|(worked|interned) (for|at|with) (us|this company)|prior employment with",
        lambda q, p, c: _yn("previous_employee", bool(p.previous_employee)))
    add(r"previously applied|applied (to|with|for) .{0,30}before|interviewed with .{0,30} before",
        lambda q, p, c: _yn("previously_applied", False))
    add(r"non-?compete|non-?solicit|restrictive covenant|agreement.{0,60}(prevent|restrict|prohibit)|bound by",
        lambda q, p, c: _yn("non_compete", False))
    add(r"convicted|conviction|felony|misdemeanor|criminal (record|history|offense)|pleaded guilty",
        lambda q, p, c: _yn("felony_conviction", _bool(p, "felony_conviction")))
    add(r"background (check|screen|investigation)",
        lambda q, p, c: _yn("background_check_consent", _bool(p, "background_check_consent")))
    add(r"drug (test|screen)",
        lambda q, p, c: _yn("drug_test_consent", _bool(p, "drug_test_consent")))

    # Work logistics
    add(r"do you (currently )?(reside|live) in|are you (currently )?(located|based|living|residing) in",
        lambda q, p, c: _reside_want(p, q))
    add(r"relocat",
        lambda q, p, c: Want(key="willing_to_relocate", text="Yes", terms=["Yes"], polarity=True, select_all=True)
        if _bool(p, "willing_to_relocate") and re.search(r"(all|which|select|indicate).{0,40}(locations?|cities|offices?)(\(s\))?", q)
        else _yn("willing_to_relocate", _bool(p, "willing_to_relocate")))
    add(r"(able|willing|available) to work (from|at|in|out of) .{0,40}\b(hub|office|campus)\b",
        lambda q, p, c: _yn("willing_onsite", bool(_bool(p, "willing_onsite")) and bool(_bool(p, "willing_to_relocate"))))
    add(r"on-?site|in[- ]office|in[- ]person|hybrid|commute|anchor days|days (a|per) week|return to office|work from (the|our) office",
        lambda q, p, c: _yn("willing_onsite", _bool(p, "willing_onsite")))
    add(r"willing to travel|travel (requirement|up to)", lambda q, p, c: _yn("willing_to_travel", _bool(p, "willing_to_travel")))
    add(r"(salary|compensation|pay|hourly rate|wage).{0,30}(expect|requirement|desired|range)|desired (salary|pay|compensation)|expected (salary|pay|compensation)",
        lambda q, p, c: _pay_want(p, c))
    add(r"final year of (study|school|college|university|your)|end[- ]of[- ]stud(y|ies)|last year of (study|school|college|university)",
        lambda q, p, c: _yn("final_year", class_standing(p, c.today) == "Senior") if class_standing(p, c.today) else None)
    add(r"full[- ]time (role|employment|position|job|offer|opportunit)",
        lambda q, p, c: _fulltime_start_want(p, q))
    add(r"available for (a|an) (\d+|six|three|four|five|twelve)[- ]month|(\d+|six|twelve)[- ]month (internship|co-?op|placement)",
        lambda q, p, c: _yn("long_internship", _bool(p, "available_six_month_internship")))
    add(r"in (the )?process with other (companies|employers)|other (offers|interviews|processes)|time[- ]sensitive|competing offers?|offer deadline",
        lambda q, p, c: _yn("time_sensitive", _bool(p, "time_sensitive_offers")))
    add(r"academic requirements",
        lambda q, p, c: Want(key="academic_requirements", text="No", terms=["No", "None"], polarity=False))
    add(r"(earliest|when).{0,40}(start|available|availability)|start date|available to (start|begin)",
        lambda q, p, c: _start_want(p, c))
    add(r"(high school|secondary school) name|name of (your )?(high|secondary) school|which high school",
        lambda q, p, c: Want(key="high_school_name", text=str(_extra(p, "high_school_name")),
                             terms=[str(_extra(p, "high_school_name"))], search=str(_extra(p, "high_school_name")))
        if _extra(p, "high_school_name") else Want(key="high_school_name"))
    add(r"\b(second|another|alternate|additional) (cohort|internship term|term|session|season)\b(?! (of|and) )",
        lambda q, p, c: Want(key="alternate_terms", text=", ".join(_extra(p, "alternate_terms")),
                             terms=list(_extra(p, "alternate_terms")))
        if _extra(p, "alternate_terms") else Want(key="alternate_terms", text="No",
                                                   terms=["not pursuing another", "No"], polarity=False))
    add(r"(high school|secondary school).{0,30}(graduat|year)",
        lambda q, p, c: Want(key="high_school_graduation_year", text=str(_extra(p, "high_school_graduation_year")),
                             terms=[str(_extra(p, "high_school_graduation_year"))]) if _extra(p, "high_school_graduation_year") else None)
    add(r"(percent(age)?|%|how much) of (your )?time.{0,40}(cod|program|engineer)",
        lambda q, p, c: Want(key="coding_time_share", text=str(_extra(p, "coding_time_share")), terms=[str(_extra(p, "coding_time_share"))])
        if _extra(p, "coding_time_share") else None)
    add(r"do you have (a|an) .{1,30} account|what is your .{1,30} username",
        lambda q, p, c: _account_want(p, q))
    add(r"(internship|program|intern) (dates|timeline|term|season)|which (term|season|cohort)|(summer|fall|spring|winter) \d{4}.{0,40}\?",
        lambda q, p, c: _season_want(c))
    add(r"time ?zone", lambda q, p, c: Want(key="timezone", text="Eastern Time (ET)",
                                             terms=["Eastern", "EST", "ET", "America/New_York"]) if norm(p.state) in {"ny", "new york"} else None)

    # Education. Window questions ("between December 2027 and August 2028")
    # must answer Yes/No, not type the graduation month.
    add(r"graduat.{0,40}between|between .{0,40}graduat",
        lambda q, p, c: _grad_window_want(p, q))
    add(r"(expected )?graduation (date|year|month|term)|"
        r"(expected |anticipated )?(date|month|year|term) of graduation|"
        r"when (will|do) you (expect to )?graduate|"
        r"expected (grad|completion)|"
        r"grad(uation)? (date|year)|class of",
        lambda q, p, c: _graduation_want(p, q))
    add(r"\bgpa\b|grade point", lambda q, p, c: Want(key="gpa", text=p.gpa, terms=_gpa_terms(p.gpa)) if p.gpa else None)
    add(r"(when did you|date you|when you) (begin|start|began|started|enroll).{0,60}(degree|program|studies|school|college|university)",
        lambda q, p, c: _month_year_want("education_start", p.education_start, q))
    add(r"(when do you|when will you|date you) (expect to |plan to |anticipate )?(complete|finish|graduate).{0,60}(degree|program|studies)?|expected (completion|end) date",
        lambda q, p, c: _graduation_want(p, q))
    add(r"(currently )?enrolled|current(ly)? a student|are you a student|pursuing (a|an)",
        lambda q, p, c: _enrolled_want(p, q))
    add(r"(class|academic) (standing|year|level)|year (in|of) (school|study|college|university)|current year|what year are you",
        lambda q, p, c: Want(key="class_standing", text=class_standing(p, c.today) or "",
                             terms=[class_standing(p, c.today) or "", *_standing_aliases(class_standing(p, c.today))])
        if class_standing(p, c.today) else None)
    add(r"^(current|present) (school|university|college|institution)|^(school|university|college|institution)( name)?$|(school|university|college|institution) (are )?(you|do you) (attend|currently)|which (school|university|college)|name of (school|university|college|institution)|^education$|(university|school|college) are you (currently )?attending",
        lambda q, p, c: _school_want(p))
    add(r"degree (type|level|program)|^degree$|highest (level of )?(degree|education)|level of (education|study)|what degree|degree are you (pursuing|seeking)",
        lambda q, p, c: _degree_want(p))
    add(r"\bmajor\b(?! life)|field of study|area of study|discipline|concentration|program of study",
        lambda q, p, c: Want(key="field_of_study", text=p.field_of_study or "Computer Science",
                             terms=[p.field_of_study or "Computer Science", "Computer Science", "CS"], search="Computer Science"))
    add(r"\bgpa\b|grade point", lambda q, p, c: Want(key="gpa", text=p.gpa, terms=_gpa_terms(p.gpa)) if p.gpa else None)
    add(r"coursework|relevant courses|courses (you('ve| have)|taken)", lambda q, p, c: Want(key="coursework", essay=True))

    # Experience
    add(r"how many.{0,30}internships|number of.{0,20}internships|prior internships",
        lambda q, p, c: Want(key="internship_count", text=str(internship_count(c.pool)), pick=_pick_number(internship_count(c.pool)),
                             terms=[str(internship_count(c.pool))]))
    add(r"years of.{0,40}experience|how many years|how long have you",
        lambda q, p, c: Want(key="years_experience", text=str(years_experience(c.pool, c.today)),
                             pick=_pick_number(years_experience(c.pool, c.today)), terms=[str(years_experience(c.pool, c.today))]))
    add(r"(current|previous|most recent|present) (or (previous|most recent|past) )?(job |position )?title",
        lambda q, p, c: Want(key="current_title", text=current_role(c.pool).role) if current_role(c.pool) else None)
    add(r"\b(sat|act|gre|gmat)\b.{0,60}\bscores?\b|\bscores?\b.{0,40}\b(sat|act|gre|gmat)\b",
        lambda q, p, c: Want(key="test_scores", text=str(_extra(p, "test_scores")))
        if _extra(p, "test_scores") else Want(key="test_scores", leave_blank=True))
    add(r"may we contact (your )?(current |previous |present )?employer|contact your (current )?employer",
        lambda q, p, c: _yn("contact_current_employer", _bool(p, "contact_current_employer")))
    add(r"^(current|most recent) (company|employer)|^(company|employer)$|current (company|employer|organization)|(current|previous|most recent) (or (previous|most recent|past) )?employer",
        lambda q, p, c: Want(key="current_company", text=(current_role(c.pool).company if current_role(c.pool) else p.school)))
    add(r"^(current|most recent) (title|job title|role|position)|^(title|job title)$",
        lambda q, p, c: Want(key="current_title", text=(current_role(c.pool).role if current_role(c.pool) else "Student")))
    add(r"(programming|scripting|coding|software) languages?|languages?.{0,30}(experience|familiar|comfortable|worked with)|tech(nical)? stack|technologies (do you|are you)",
        lambda q, p, c: _tech_want(p, c))
    add(r"(most|first|second|third|top) (choice|preference)|second choice|third choice|most interested in|(which|what).{0,40}(area|team|track|opportunit|role|domain|focus)|(type|kind) of (engineering |software )?(role|team|work|position)",
        lambda q, p, c: _ranked_pref_want(p, q, "role_preferences"))
    add(r"(most )?important factors|what (matters|is (most )?important) to you|what do you (value|look for) (most )?in",
        lambda q, p, c: _ranked_pref_want(p, q, "internship_priorities", multi=True))
    add(r"how you use ai|ai tools today|your use of (ai|generative ai)",
        lambda q, p, c: Want(key="ai_tool_usage", text=str(_extra(p, "ai_tool_usage")), terms=[str(_extra(p, "ai_tool_usage"))])
        if _extra(p, "ai_tool_usage") else None)
    add(r"languages?.{0,20}(speak|spoken|fluent|proficien)|what languages|language proficiency|language skill",
        lambda q, p, c: Want(key="languages", text=", ".join(l.get("language", "") for l in (_extra(p, "languages") or [])) or "English",
                             terms=[l.get("language", "") for l in (_extra(p, "languages") or [])] or ["English"]))

    # Sourcing
    add(r"how did you (first )?(hear|find|learn|discover|come across|connect)|where have you (first )?(heard|learned|seen)|how you (first )?(heard|found|learned|discovered)|where did you (first )?(hear|find|learn|see)|source of (application|referral)|how were you referred|referral source",
        lambda q, p, c: Want(key="how_heard", text="Company website", pick=_pick_how_heard,
                             terms=["Company Website", "Company Career Site", "Careers Page", "Career Site", "Website"]))

    # Voluntary self-identification
    add(r"transgender|gender identity.{0,40}(different|same)|identify as trans",
        lambda q, p, c: _yn("transgender", _bool(p, "transgender")))
    add(r"sexual orientation|lgbt",
        lambda q, p, c: Want(key="sexual_orientation", text=str(_extra(p, "sexual_orientation")),
                             terms=_orientation_terms(str(_extra(p, "sexual_orientation"))),
                             polarity=False if re.search(r"lgbt", q) else None)
        if _extra(p, "sexual_orientation") else None)
    add(r"hispanic|latin[oax]",
        lambda q, p, c: _hispanic_or_race_want(q, p))
    add(r"\brace\b|ethnicity|ethnic (group|background)", lambda q, p, c: _race_want(p))
    add(r"\bgender\b|\bsex\b", lambda q, p, c: Want(key="gender", text=p.eeo.gender, terms=_gender_terms(p.eeo.gender)) if p.eeo.gender else None)
    add(r"veteran|military service|armed forces", lambda q, p, c: _veteran_want(p))
    add(r"disabilit", lambda q, p, c: _disability_want(p))

    # Acknowledgements (after sms / marketing so those stay unchecked)
    add(r"acknowledge|\bpolicy\b|i agree|agree to|consent|certify|attest|confirm (that|i)|i have read|i understand|privacy (policy|notice)|terms (and|&) conditions|accurate and complete|true and complete",
        lambda q, p, c: Want(key="acknowledgement", text="Yes", terms=["Yes", "I agree", "I acknowledge", "I consent", "I understand", "Agree", "Acknowledge", "Confirm"], polarity=True))

    # Essays
    add(r"cover letter|^additional information|anything else (you('d| would) like|we should)|^(additional )?comments",
        lambda q, p, c: Want(key="essay", essay=True, skip_if_optional=True))
    add(r"why (do you|are you|would you|this|our|us)|what (excites|interests|draws|attracts|motivates)|tell us|describe|d[ée]crivez|pour quelle raison|explain|share (something|a|an|about|with|your)|proud of|you('ve| have) built|what makes you|walk us through|what are (some|your)|what is (a|your)|how (would|do|have) you|in (\d+|a few) (words|sentences)",
        lambda q, p, c: Want(key="essay", essay=True))

    return [(re.compile(pat, re.I), fn) for pat, fn in R]


_RULES = None


def resolve(question: str, profile: Profile, ctx: Context) -> Want | None:
    """Grounded answer for one question, or None when nothing in the profile answers it."""
    global _RULES
    if _RULES is None:
        _RULES = _rules()
    q = norm(question)
    if not q:
        return None
    head = _head(q)
    # "How do you identify? (gender identity)": the essay-looking head must not
    # beat a specific rule that only the full text satisfies.
    essays = []
    for scope in (head, q):
        for pattern, fn in _RULES:
            if pattern.search(scope):
                want = fn(scope, profile, ctx)
                if want is None:
                    continue
                if want.essay:
                    essays.append(want)
                    continue
                return want
    return essays[0] if essays else None


def _head(q: str) -> str:
    """The question sentence itself, without the explanatory paragraph around it."""
    q = re.sub(r"\b(e\.g|i\.e|etc|vs|approx|incl)\.", lambda m: m.group(1).replace(".", ""), q)
    parts = [s.strip() for s in re.split(r"(?<=[.?!])\s+|\n+", q) if s.strip()]
    questions = [s for s in parts if s.endswith("?")]
    if questions:
        return questions[-1] if len(questions[-1]) > 12 else questions[0]
    return q[:200]


# --- rule helpers ----------------------------------------------------------


def _gender_terms(gender: str) -> list[str]:
    low = norm(gender)
    if low in {"male", "man"}:
        return ["Male", "Man", "Cisgender man", "Cis man"]
    if low in {"female", "woman"}:
        return ["Female", "Woman", "Cisgender woman", "Cis woman"]
    return [gender]


def _authorized_without_sponsorship_want(p: Profile) -> Want | None:
    """Yes only when already US-authorized and no visa sponsorship is needed."""
    if p.work_authorized_us is True and p.need_sponsorship is False:
        return _yn("work_authorized_without_sponsorship", True)
    if p.work_authorized_us is False or p.need_sponsorship is True:
        return _yn("work_authorized_without_sponsorship", False)
    return None


def _month_years_in(text: str) -> list[tuple[int, int]]:
    """Every month-year pair in `text`, in order."""
    found: list[tuple[int, int]] = []
    low = norm(text)
    pat = re.compile(r"\b(" + "|".join(m[:3] for m in MONTHS) + r")[a-z]*\.?\s+(\d{4})\b")
    for m in pat.finditer(low):
        month = MONTHS.index(next(x for x in MONTHS if x.startswith(m.group(1)))) + 1
        found.append((month, int(m.group(2))))
    return found


def _grad_window_want(p: Profile, q: str) -> Want | None:
    grad = graduation(p)
    if not grad:
        return None
    bounds = _month_years_in(q)
    if len(bounds) < 2:
        return None
    start, end = bounds[0], bounds[1]
    gm, gy = grad
    inside = (start[1], start[0]) <= (gy, gm) <= (end[1], end[0])
    return _yn("graduation_window", inside)


def _hispanic_or_race_want(q: str, p: Profile) -> Want | None:
    """Hispanic Yes/No, unless this is a race multi-select that lists White/Asian/etc."""
    if re.search(r"\brace\b|ethnicity|ethnic (group|background)|select all that apply", q):
        return _race_want(p)
    if re.search(r"\b(white|asian|african american|american indian|two or more races)\b", q):
        return _race_want(p)
    return _yn("hispanic_latino", _bool(p, "hispanic_latino"), "Not Hispanic or Latino", "No, not Hispanic or Latino")


def _pronoun_terms(value: str) -> list[str]:
    parts = [s.strip() for s in re.split(r"\s*/\s*", value) if s.strip()]
    if not parts:
        return [value]
    return [value, "/".join(s.title() for s in parts), " / ".join(parts), parts[0].title()]


def _orientation_terms(value: str) -> list[str]:
    if norm(value) in {"heterosexual", "straight", "heterosexual or straight"}:
        return [value, "Heterosexual", "Straight", "Heterosexual or straight"]
    return [value]


def _race_terms_list(race: str) -> list[str]:
    terms = [race]
    if norm(race) == "white":
        terms += ["White (Not Hispanic or Latino)", "White", "Caucasian", "White (United States of America)"]
    return terms


def _pick_race(profile: Profile) -> Callable[[list[str]], list[str]]:
    needles = [norm(t) for t in _race_terms_list(profile.eeo.race_ethnicity) if t]

    def pick(options: list[str]) -> list[str]:
        exact = [o for o in options if norm(o) in needles]
        if exact:
            return exact[:1]
        hits = [o for o in options if any(n and phrase_in(n, norm(o)) for n in needles)]
        return [min(hits, key=len)] if hits else []

    return pick


def _race_want(p: Profile) -> Want | None:
    race = p.eeo.race_ethnicity
    if not race:
        return None
    terms = _race_terms_list(race)
    if norm(race) == "white" and _bool(p, "hispanic_latino") is False:
        terms.insert(0, "White (Not Hispanic or Latino)")
    return Want(key="race_ethnicity", text=race, terms=terms, pick=_pick_race(p))


def _veteran_want(p: Profile) -> Want | None:
    vet = p.eeo.veteran
    if not vet:
        return None
    if "not" in norm(vet):
        return Want(key="veteran", text="No",
                    terms=[vet, "I am not a protected veteran", "I am not a veteran", "I am NOT a veteran", "Not a veteran",
                           "Not a protected veteran", "No"], polarity=False)
    return Want(key="veteran", text=vet, terms=[vet])


def _disability_want(p: Profile) -> Want | None:
    dis = p.eeo.disability
    if not dis:
        return None
    if re.search(r"\b(do not|don't|no)\b", norm(dis)):
        return Want(key="disability", text="No",
                    terms=[dis, "No, I do not have a disability and have not had one in the past", "No, I don't have a disability",
                           "No, I do not have a disability", "I do not have a disability", "No"], polarity=False)
    return Want(key="disability", text=dis, terms=[dis])


def _degree_want(p: Profile) -> Want:
    deg = p.degree or ""
    science = re.search(r"science|b\.?s\b", deg, re.I)
    terms = [deg]
    if science:
        terms += ["Bachelor of Science", "Bachelor's of Science", "B.S.", "BS", "Bachelor's Degree", "Bachelor's", "Bachelors",
                  "Undergraduate/Bachelors", "Undergraduate", "Bachelor"]
    else:
        terms += ["Bachelor's Degree", "Bachelor's", "Bachelors", "Undergraduate", "Bachelor"]
    return Want(key="degree", text="Bachelor's" if not deg else deg, terms=terms)


def _gpa_terms(gpa: str | None) -> list[str]:
    if not gpa:
        return []
    try:
        g = float(gpa)
    except ValueError:
        return [gpa]
    out = [gpa, f"{g:.2f}", f"{g:.1f}"]
    if g >= 3.5:
        out += ["3.5 - 4.0", "3.5-4.0", "3.5+", "Above 3.5", "3.5 or above"]
    if g >= 3.0:
        out += ["3.0 - 3.49", "3.0+", "Above 3.0", "3.0 or above"]
    return out


def _standing_aliases(standing: str | None) -> list[str]:
    return {
        "Freshman": ["First year", "1st year", "Year 1"],
        "Sophomore": ["Second year", "2nd year", "Year 2"],
        "Junior": ["Third year", "3rd year", "Year 3"],
        "Senior": ["Fourth year", "4th year", "Year 4"],
    }.get(standing or "", [])


def _graduation_want(p: Profile, q: str) -> Want | None:
    grad = graduation(p)
    if not grad:
        return None
    month, year = grad
    name = MONTHS[month - 1].capitalize()
    numeric = _numeric_date_format(q, month, year)
    if numeric:
        text = numeric
    elif re.search(r"\byear\b", q) and not re.search(r"\bmonth\b", q):
        text = str(year)
    elif re.search(r"\bmonth\b", q) and not re.search(r"\byear\b", q):
        text = name
    else:
        text = f"{name} {year}"
    terms = [f"{name} {year}", f"{name[:3]} {year}", f"{month:02d}/{year}", str(year)]
    if text == name:
        terms = [name, name[:3], *terms]
    return Want(key="graduation", text=text, terms=terms, pick=_pick_graduation(p))


def _future(when: tuple[int, int] | None, today: date) -> bool:
    return when is not None and (when[1], when[0]) >= (today.year, today.month)


def _numeric_date_format(q: str, month: int, year: int) -> str | None:
    """MM/YY or MM/YYYY when the question spells out the format."""
    if re.search(r"mm\s*/\s*yyyy", q):
        return f"{month:02d}/{year}"
    if re.search(r"mm\s*/\s*yy\b", q):
        return f"{month:02d}/{year % 100:02d}"
    return None


def _month_year_want(key: str, raw: str, q: str = "") -> Want | None:
    parsed = parse_month_year(raw)
    if not parsed:
        return None
    month, year = parsed
    name = MONTHS[month - 1].capitalize()
    numeric = _numeric_date_format(q, month, year)
    if numeric:
        return Want(key=key, text=numeric, terms=[numeric, f"{name} {year}"])
    if re.search(r"\byear\b", q) and not re.search(r"\bmonth\b", q):
        return Want(key=key, text=str(year), terms=[str(year)])
    if re.search(r"\bmonth\b", q) and not re.search(r"\byear\b", q):
        return Want(key=key, text=name, terms=[name, name[:3], f"{month:02d}"])
    return Want(key=key, text=f"{name} {year}", terms=[name, name[:3], str(year), f"{name} {year}"])


def _school_key(text: str) -> str:
    s = norm(text)
    s = re.sub(r"[^a-z ]+", " ", s)
    s = re.sub(r"\b(the|of|at)\b", " ", s)
    return " ".join(s.split())


def _school_want(p: Profile) -> Want | None:
    if not p.school:
        return None
    aliases = [p.school, *[str(a) for a in (_extra(p, "school_aliases") or [])]]
    keys = [_school_key(a) for a in aliases if _school_key(a)]
    anchors = [_school_key(a) for a in (_extra(p, "school_anchors") or [])]

    def pick(options: list[str]) -> list[str]:
        exact = [o for o in options if _school_key(o) in keys]
        if exact:
            return exact[:1]
        contains = [o for o in options if any(k and k in _school_key(o) for k in keys)]
        if contains:
            return [min(contains, key=len)]
        if anchors:
            anchored = [o for o in options if all(a in _school_key(o) for a in anchors)]
            if anchored:
                return [min(anchored, key=len)]
        other = [o for o in options if re.search(r"^other\b|not listed", norm(o))]
        return other[:1]

    # Short custom school lists skip HSU; "Other" is the honest answer there.
    searches = [str(s) for s in (_extra(p, "school_searches") or [])] + ["Other"]
    return Want(key="school", text=p.school, terms=[], pick=pick, search=aliases[1] if len(aliases) > 1 else p.school,
                searches=searches)


def _enrolled_want(p: Profile, q: str) -> Want | None:
    grad = graduation(p)
    if not grad:
        return None
    wants_bachelor = re.search(r"bachelor|undergrad", q)
    wants_grad = re.search(r"master|phd|ph\.d|doctor|mba|graduate (degree|program|student)", q) and not wants_bachelor
    if wants_grad:
        return _yn("enrolled", False)
    return _yn("enrolled", True, "Full-time", "Full time")


_MONEY = r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*(k\b)?"
_PAY_RANGE_RE = re.compile(
    _MONEY + r"\s*(?:usd)?\s*(?:/\s*(?:hr|hour)|per hour|an hour|hourly)?\s*(?:-|to|and)\s*" + _MONEY
    + r"\s*(?:usd)?\s*(/\s*(?:hr|hour)|per hour|an hour|hourly|/\s*(?:yr|year)|per year|annually|a year)?",
    re.I,
)


def posted_pay_floor(description: str) -> str | None:
    """Low end of the first pay range in the posting, formatted with its unit."""
    m = _PAY_RANGE_RE.search((description or "").replace("\u2013", "-").replace("\u2014", "-"))
    if not m:
        return None
    low = float(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1)
    unit = (m.group(5) or "").lower()
    hourly = "h" in unit or (not unit and low < 500)
    amount = f"{low:,.2f}".rstrip("0").rstrip(".") if hourly else f"{low:,.0f}"
    return f"${amount}/hour" if hourly else f"${amount}/year"


def _pay_want(p: Profile, c: Context) -> Want:
    text = posted_pay_floor(c.description) or str(_extra(p, "desired_pay") or _extra(p, "desired_pay_fallback") or "")
    if not text:
        return Want(key="desired_pay", leave_blank=True)
    return Want(key="desired_pay", text=text, terms=[text])


US_PLACES = ("united states", "u.s.", "us", "usa", "america")


def _reside_want(p: Profile, q: str) -> Want | None:
    places = [norm(m.group(1)).strip(" .") for m in
              re.finditer(r"(?:reside|live|located|based|living|residing) in (?:the )?([a-z .,'-]{2,60}?)(?=\?|$| or | and |,| for | to )", q)]
    if not places:
        return None
    home = {norm(x) for x in (p.city, p.state, state_name(p), p.location, "nyc", "new york city") if x}
    here = any(place in US_PLACES or any(h and (h == place or phrase_in(h, place) or phrase_in(place, h)) for h in home)
               for place in places)
    if here:
        return Want(key="resides_in", text="Yes", terms=["Yes", "I currently reside", "I already reside", "I reside", "I live"],
                    polarity=True)
    if _bool(p, "willing_to_relocate"):
        return Want(key="resides_in", text="No", terms=["willing to relocate", "No, but I am willing to relocate", "relocate"])
    return _yn("resides_in", False)


def _account_want(p: Profile, q: str) -> Want | None:
    accounts = {norm(k): v for k, v in (_extra(p, "accounts") or {}).items()}
    m = re.search(r"(?:a|an|your) ([a-z0-9 .-]{1,30}?) (?:account|username)", q)
    if not m:
        return None
    if norm(m.group(1)) not in accounts:
        # Never let the essay writer guess a username.
        return Want(key=f"account:{norm(m.group(1))}")
    value = accounts[norm(m.group(1))]
    return Want(key="account", text=str(value) if value else "No", terms=["Yes"] if value else ["No"],
                polarity=bool(value))


def _fulltime_start_want(p: Profile, q: str) -> Want | None:
    grad = graduation(p)
    if not grad:
        return None
    month, year = grad
    cutoff = re.search(r"\b(before|by|prior to)\s+(.{3,20}?\d{4})", q)
    if cutoff and parse_month_year(cutoff.group(2)):
        cm, cy = parse_month_year(cutoff.group(2))
        return _yn("fulltime_start", (year, month) < (cy, cm))
    after = month % 12 + 1
    after_year = year + (1 if month == 12 else 0)
    name, next_name = MONTHS[month - 1].capitalize(), MONTHS[after - 1].capitalize()
    return Want(key="fulltime_start", text=f"{next_name} {after_year}", pick=_pick_graduation(p),
                terms=[f"{next_name} {after_year}", next_name, "After graduation", "Upon graduation", f"{name} {year}"])


KNOWN_LANGUAGES = (
    "python", "java", "javascript", "typescript", "c", "c++", "c#", "go", "golang", "rust", "ruby", "php", "sql",
    "kotlin", "swift", "scala", "r", "matlab", "perl", "shell", "bash", "html", "css", "objective-c", "dart", "node.js",
)


def programming_languages(p: Profile, pool: list[PoolEntry]) -> list[str]:
    """Languages named in the pool or profile skills, in first-mention order."""
    tags = {norm(t) for e in pool for t in e.tags} | {norm(s) for s in (getattr(p, "skills", None) or [])}
    tags = {"node.js" if t in {"node", "nodejs"} else t for t in tags}
    text = " ".join(" ".join([*e.tags, *e.bullets]) for e in pool).lower()
    text = re.sub(r"\bnode(\.js)?\b", "node.js", text)
    found = []
    for lang in KNOWN_LANGUAGES:
        # One- and two-letter names ("C", "R", "Go") collide with prose; trust only exact tags for them.
        if lang in tags or (len(lang) > 2 and re.search(rf"(?<![a-z0-9+#.]){re.escape(lang)}(?![a-z0-9+#])", text)):
            found.append(lang)
    return found


def _tech_want(p: Profile, c: Context) -> Want | None:
    langs = programming_languages(p, c.pool)
    if not langs:
        return None
    keys = set(langs)

    def pick(options: list[str]) -> list[str]:
        out = []
        for opt in options:
            parts = {s.strip() for s in re.split(r"[,/]| and ", norm(opt)) if s.strip()}
            if parts & keys and opt not in out:
                out.append(opt)
        return out

    return Want(key="programming_languages", text=", ".join(l.capitalize() if len(l) > 3 else l.upper() for l in langs),
                pick=pick, searches=langs)


def _squash(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", norm(text).replace("full-stack", "fullstack").replace("full stack", "fullstack")).split())


_PREF_ALIASES = {
    "applied ai": ["ai", "ai ml", "machine learning", "ml", "artificial intelligence", "ai engineering", "ml engineering"],
    "data engineering": ["data", "data science", "data infrastructure", "data platform", "analytics engineering"],
    "fullstack": ["fullstack engineering", "product engineering", "web"],
}


def _ranked_pref_want(p: Profile, q: str, key: str, *, multi: bool = False) -> Want | None:
    prefs = [str(x) for x in (_extra(p, key) or [])]
    if not prefs:
        return None
    rank = 2 if re.search(r"\bsecond\b", q) else 3 if re.search(r"\bthird\b", q) else 1

    def pick(options: list[str]) -> list[str]:
        ordered = []
        for pref in prefs:
            names = {_squash(pref), *(_squash(a) for a in _PREF_ALIASES.get(_squash(pref), []))}
            for opt in options:
                o = _squash(opt)
                if any(n == o or re.search(rf"\b{re.escape(n)}\b", o) for n in names) and opt not in ordered:
                    ordered.append(opt)
                    break
        if multi:
            return ordered
        return ordered[rank - 1:rank]

    return Want(key=key, text=prefs[rank - 1] if len(prefs) >= rank else None, pick=pick,
                searches=prefs if multi else prefs[rank - 1:rank])


def _start_want(p: Profile, c: Context) -> Want | None:
    start = season_start_date(c)
    if not start:
        return Want(key="start_date", text=p.available_from, terms=[p.available_from]) if p.available_from else None
    name = MONTHS[start.month - 1].capitalize()
    return Want(key="start_date", text=f"{name} {start.year}",
                terms=[f"{name} {start.year}", f"{name[:3]} {start.year}", start.strftime("%m/%d/%Y"), str(start.year)])


def _season_want(c: Context) -> Want | None:
    from apply_engine.workday_widgets import season_start

    info = season_start(c.job_title, c.description[:600], today=c.today)
    if not info:
        return None
    label = f"{info['season'].capitalize()} {info['year']}"
    return Want(key="season", text=label, terms=[label, info["season"].capitalize()])
