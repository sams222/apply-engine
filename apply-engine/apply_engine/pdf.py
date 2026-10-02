from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

from apply_engine.models import PoolEntry, TailoredResume


class ResumePDF(FPDF):
    def footer(self) -> None:  # noqa: N802
        return


def render_pdf(resume: TailoredResume, out_path: str | Path) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    profile = resume.profile
    job = resume.job

    pdf = ResumePDF(format="Letter")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    pdf.set_margins(16, 14, 16)

    pdf.set_font("Helvetica", "B", 16)
    _block(pdf, _latin(profile.full_name), h=8)

    pdf.set_font("Helvetica", "", 9)
    _block(pdf, _latin("  |  ".join(profile.contact_bits())), h=4.2)
    pdf.ln(1)

    _heading(pdf, "Education")
    edu = _education_line(profile)
    if edu:
        pdf.set_font("Helvetica", "", 10)
        _block(pdf, _latin(edu), h=5)
    else:
        pdf.set_font("Helvetica", "I", 9)
        _block(pdf, "Education details are listed in the candidate profile.", h=5)

    if resume.skills:
        _heading(pdf, "Skills")
        pdf.set_font("Helvetica", "", 10)
        _block(pdf, _latin("  |  ".join(resume.skills)), h=5)

    if resume.experience:
        _heading(pdf, "Experience")
        for entry in resume.experience:
            _entry(pdf, entry)

    if resume.projects:
        _heading(pdf, "Projects")
        for entry in resume.projects:
            _entry(pdf, entry)

    if resume.programs:
        _heading(pdf, "Programs")
        for entry in resume.programs:
            _entry(pdf, entry)

    # No provenance footer. "Tailored for <Company> - <Role>. Only real
    # projects from the pool; nothing invented." was being printed on the PDF
    # the employer opens -- an internal note addressed to us, on an outgoing
    # document, naming the company we tailored for. The truthfulness guarantee
    # belongs in review.json, not on the resume.

    pdf.output(str(out))
    return out


def _education_line(profile) -> str:
    bits = [b for b in (profile.school, profile.degree) if b]
    line = " - ".join(bits)
    extras = []
    if profile.gpa:
        extras.append(f"GPA {profile.gpa}")
    if profile.graduation:
        extras.append(profile.graduation)
    if extras:
        line = f"{line}  |  {' | '.join(extras)}" if line else " | ".join(extras)
    return line


def _heading(pdf: FPDF, text: str) -> None:
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 11)
    _block(pdf, text.upper(), h=6)
    y = pdf.get_y()
    pdf.set_draw_color(40, 40, 40)
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.ln(1)


def _entry(pdf: FPDF, entry: PoolEntry) -> None:
    pdf.set_font("Helvetica", "B", 10)
    _block(pdf, _latin(entry.title), h=5)
    pdf.set_font("Helvetica", "", 10)
    for bullet in entry.bullets:
        _block(pdf, _latin(f"- {bullet}"), h=4.6)
    pdf.ln(1)


def _block(pdf: FPDF, text: str, h: float) -> None:
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(pdf.epw, h, text or "")


# Core fonts are latin-1 only, so map the punctuation that actually shows up in
# pool text instead of letting "replace" stamp a literal "?" into the resume
# ("career programming ? not full-time employment" shipped to live Walmart).
_PUNCT = {
    "\u2014": " - ",   # em dash
    "\u2013": "-",     # en dash
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2026": "...",
    "\u00a0": " ",
    "\u2022": "-",
    "\u2212": "-",
}


def _latin(text: str) -> str:
    out = text or ""
    for bad, good in _PUNCT.items():
        out = out.replace(bad, good)
    return out.encode("latin-1", "replace").decode("latin-1")
