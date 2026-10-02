"""Mechanical checks for application answers that read as machine-written or as a resume recap.

The rules mirror prompts/essay_style.md. A draft that trips them is sent back to the
model once or twice with the problems listed; whatever still fails is flagged for review.
"""

from __future__ import annotations

import re

BANNED = (
    r"innovative", r"cutting[- ]edge", r"industry[- ]leading", r"world[- ]class", r"revolutioni[sz]e",
    r"game[- ]chang", r"at the forefront", r"mission resonates", r"resonates? with me", r"aligns? (with|perfectly)",
    r"passionate", r"passion for", r"excited to (apply|join|contribute)", r"thrilled", r"\bleverag", r"synerg",
    r"i am confident", r"i'm confident", r"great fit", r"perfect fit", r"unique blend", r"diverse skill ?set",
    r"fast[- ]paced", r"hit the ground running", r"make an impact", r"meaningful impact", r"drawn to",
    r"exactly the kind of", r"end[- ]to[- ]end", r"\bdeeply\b", r"\btruly\b", r"\bthrive", r"\bjourney\b",
    r"tapestry", r"\bdelve", r"\bnavigat", r"\bfoster", r"not only\b.{0,60}\bbut also", r"whether it'?s\b.{0,40}\bor\b",
    r"grow as an engineer", r"alongside (experienced|talented|world)", r"eager to", r"i would love the opportunity",
    r"honed", r"skill ?set", r"robust", r"seamless", r"empower",
)
_BANNED_RE = [(p, re.compile(p, re.I)) for p in BANNED]

TECH_WORDS = re.compile(
    r"\b(python|pandas|numpy|scikit-learn|pytorch|typescript|javascript|node\.?js|react( native)?|expo|firebase|"
    r"php|sql|fastapi|mediapipe|gemini|elevenlabs|ffmpeg|git|rest|sse|cnn|google maps)\b",
    re.I,
)


# Claims about the candidate's inner experience or history that only his own notes can support.
ANECDOTES = (
    r"the (hard|hardest|tricky|trickiest|difficult) part", r"the (first|only) (time|project|thing)", r"first time i",
    r"taught me", r"i (learned|realized|discovered|noticed) (that|how)", r"what (mattered|matters) (most )?to me",
    r"i (haven't|have not|never) (worked|used|built|done|touched)", r"i've never", r"most of the work was",
    r"i keep (coming back|poking|thinking)", r"i kept", r"i got (frustrated|stuck|hooked)", r"i fell in love",
    r"(ever since|since i was)", r"i've always", r"i have always", r"i use .{0,30} (every day|daily|constantly)",
    r"\bdaily\b", r"\bevery day\b", r"my team\b", r"\bwe (built|shipped|designed|won)\b",
    r"i (built|made|started) [\w .+-]{1,30} because", r"i wanted to (see|know|find out|prove|learn)",
    r"the part i (care|cared) about", r"forced me to", r"(made|got) me (want|realize|think|interested|curious)",
    r"(showed|shown|showing) me", r"i keep (running into|hitting|seeing|finding)",
    r"my (user ?name|handle) is", r"i (really |genuinely |deeply )?care (a lot )?about", r"i (built|did|wrote|handled|owned|led) the [a-z ]{0,30}(layers?|side|parts?|pieces?)\b",
)

# (claim, evidence): an ANECDOTES hit is fine when the facts contain the evidence pattern.
SUPPORTED_BY = (
    (r"my team|\bwe (built|shipped|designed|won)\b", r"team (hackathon )?project"),
    (r"hard|tricky|difficult", r"hard parts?:"),
    (r"learned|realized", r"lessons?:"),
)


def experience_names(facts: str) -> list[str]:
    """Project and employer names from the FACTS experience lines ("- Role at Company (...)")."""
    names = []
    for head in re.findall(r"^- ([^(\[\n:]+?)(?: \(| \[)", facts or "", re.M):
        name = head.rsplit(" at ", 1)[-1].strip().lower()
        if len(name) > 2 and name not in names:
            names.append(name)
    return names


def problems(text: str, *, posting: str = "", question: str = "", facts: str = "") -> list[str]:
    """Human-readable reasons this draft breaks the style guide. Empty means it passes."""
    out: list[str] = []
    low = text.lower()
    post = (posting or "").lower()
    known = (facts or "").lower()
    for pat in ANECDOTES:
        m = re.search(pat, low)
        supported = m and (m.group(0) in known or any(
            re.search(claim, m.group(0)) and re.search(evidence, known) for claim, evidence in SUPPORTED_BY))
        if m and not supported:
            out.append(f'unsupported claim "{m.group(0)}": FACTS never say this; state only what the project does')
    for name, note in re.findall(r"^- ([\w.-]+): (.*team (?:hackathon )?project.*)$", facts or "", re.M | re.I):
        if re.search(rf"\bi (single-handedly |solo )?(built|made|created|wrote) {re.escape(name.lower())}\b", low):
            out.append(f'says "I built {name}" but {name} was a team project; say "we built" or name his part only if FACTS do')
    if re.search(r"[\u2014\u2013]|\s--\s", text):
        out.append("uses an em/en dash; use a period or comma")
    for pat, rx in _BANNED_RE:
        m = rx.search(low)
        if m and not (pat in {r"end[- ]to[- ]end", r"robust", r"fast[- ]paced"} and m.group(0) in post):
            out.append(f'stock phrase "{m.group(0)}"')
    if re.search(r"\?(\s|$)", text):
        out.append("rhetorical question")
    if "!" in text:
        out.append("exclamation mark")
    metrics = re.findall(r"\d+(\.\d+)?\s*%|\b\d{2,}\+", text)
    if len(metrics) > 1:
        out.append("more than one metric")
    asks_tech = re.search(r"technolog|tools|stack|languages|frameworks", question or "", re.I)
    tech = {m.group(0).lower() for m in TECH_WORDS.finditer(text)}
    if not asks_tech and len(tech) > 3:
        out.append(f"lists {len(tech)} technologies; keep to two unless asked")
    projects = [n for n in experience_names(facts) if n in low]
    if not asks_tech and len(projects) > 2:
        out.append(f"mentions {len(projects)} experiences; pick one or two and go deeper")
    if re.match(r"\s*i (want|would like) to (work|join|intern) (at|with|for)\b", low):
        out.append('opens with "I want to work at X"; open with something specific about the company')
    return out
