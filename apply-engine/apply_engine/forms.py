"""Question-driven filler for single-page ATS forms (Greenhouse, Lever, Ashby).

The page is read as a list of questions (label + widget + options); each one
is answered by `questions.resolve`, then written with the widget's own
interaction and read back. Unanswered required questions are reported so the
run parks as needs_user instead of looking complete.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from apply_engine import llm
from apply_engine.fields import is_honeypot
from apply_engine.models import JobPosting, PoolEntry, Profile
from apply_engine.questions import MONTHS, Context, Want, choose, graduation, norm, resolve, season_start_date

EXTRACT_JS = r"""
() => {
  const vis = el => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 1 && r.height > 1 && s.visibility !== 'hidden' && s.display !== 'none' && parseFloat(s.opacity || '1') > 0.05;
  };
  const txt = n => (n ? (n.innerText || n.textContent || '') : '').replace(/\s+/g, ' ').trim();
  const CONTAINER = [
    '.ashby-application-form-field-entry', '.field-wrapper', '.eeoc__question__wrapper',
    '.application-question', 'li.application-field', 'fieldset', '[role=radiogroup]', '[role=group]',
    '.form-group', '.form-field', '.question', '[class*=question_]', '[class*=Question]'
  ].join(',');
  const LABELISH = 'legend, .application-label, label.ashby-application-form-question-title, [class*=question-title], [class*=questionTitle], [class*=label]:not(input):not(option), label';
  window.__aeSeq = window.__aeSeq || 0;
  const optLabel = el => {
    let t = '';
    if (el.labels && el.labels[0]) t = txt(el.labels[0]);
    if (!t && el.closest('label')) t = txt(el.closest('label'));
    if (!t) t = el.getAttribute('aria-label') || el.value || '';
    return t.trim();
  };
  const optVisible = el => vis(el) || (el.labels && el.labels[0] && vis(el.labels[0])) || (el.closest('label') && vis(el.closest('label')));
  const boxLabel = (box, opts) => {
    for (const cand of box.querySelectorAll(LABELISH)) {
      if (cand.querySelector('input[type=radio], input[type=checkbox]')) continue;
      const t = txt(cand);
      if (t && !opts.has(t.toLowerCase()) && t.length > 1) return t;
    }
    return '';
  };
  // A sub-field inside a compound block (Ashby Education History) labels itself
  // with a sibling label or a label[for] pointing at a wrapper, not at the control.
  const nearLabel = (el, box) => {
    let node = el;
    while (node && node !== box) {
      if (node !== el && node.id) {
        const l = document.querySelector('label[for="' + CSS.escape(node.id) + '"]');
        if (l && !l.contains(el)) return txt(l);
      }
      let sib = node.previousElementSibling;
      while (sib) {
        if (sib.matches('label, legend, [class*=label], [class*=Label]') && !sib.querySelector('input, select, textarea')) {
          const t = txt(sib);
          if (t && t.length < 120) return t;
        }
        sib = sib.previousElementSibling;
      }
      node = node.parentElement;
    }
    return '';
  };
  const questionText = (el, box, optionTexts) => {
    const opts = new Set(optionTexts.map(o => o.toLowerCase()));
    if (el && !['radio', 'checkbox'].includes(el.type)) {
      let t = '';
      if (el.labels && el.labels[0]) t = txt(el.labels[0]);
      if (!t && el.getAttribute('aria-labelledby')) t = el.getAttribute('aria-labelledby').split(/\s+/).map(i => txt(document.getElementById(i))).join(' ').trim();
      if (!t) t = el.getAttribute('aria-label') || '';
      if (t && !/^(select\.{0,3}|search)$/i.test(t)) return t;
      const near = box ? nearLabel(el, box) : '';
      const head = box ? boxLabel(box, opts) : '';
      if (near && head && near !== head) return head + ' - ' + near;
      if (near) return near;
    }
    if (box) {
      const head = boxLabel(box, opts);
      if (head) return head;
      let t = txt(box);
      for (const o of optionTexts) t = t.replace(o, ' ');
      return t.replace(/\s+/g, ' ').trim();
    }
    return el ? (el.getAttribute('placeholder') || el.name || '') : '';
  };
  const labelEl = (el, box) => {
    if (el && el.labels && el.labels[0]) return el.labels[0];
    let node = el;
    while (node && node !== box) {
      let sib = node.previousElementSibling;
      while (sib) {
        if (sib.matches('label, legend, [class*=label], [class*=Label]') && !sib.querySelector('input, select, textarea')) return sib;
        sib = sib.previousElementSibling;
      }
      node = node.parentElement;
    }
    return box ? box.querySelector(LABELISH) : null;
  };
  const isReq = (el, box, label) => {
    if (el && (el.required || el.getAttribute('aria-required') === 'true')) return true;
    if (/[*\u2731]/.test((label || '').slice(-3))) return true;
    const lab = labelEl(el, box);
    if (lab && (/required/i.test(lab.className || '') || lab.querySelector('[class*=required], abbr[title=required]') || /[*\u2731]\s*$/.test(txt(lab)))) return true;
    if (box && /required/i.test(box.className || '')) return true;
    if (box && ['radio', 'checkbox'].includes((el && el.type) || '') && box.querySelector('input[required], [aria-required=true]')) return true;
    return false;
  };
  const tag = el => { if (!el.dataset.aeQ) el.dataset.aeQ = 'q' + (++window.__aeSeq); return el.dataset.aeQ; };
  // Greenhouse repeats "Start date month" in its education and employment blocks.
  const section = (el, label) => {
    const sec = el.closest('.education--container') ? 'Education'
      : el.closest('.employment-form, [class*=employment--]') ? 'Employment' : '';
    return sec && !label.toLowerCase().startsWith(sec.toLowerCase()) ? sec + ' - ' + label : label;
  };

  const groups = [];
  const grouped = new Set();
  const all = [...document.querySelectorAll('input, textarea, select, button')];
  for (const el of all) {
    if (grouped.has(el)) continue;
    const type = (el.type || '').toLowerCase();
    const tagName = el.tagName.toLowerCase();
    if (['hidden', 'submit', 'image', 'reset'].includes(type) && tagName !== 'button') continue;
    if (/recaptcha|captcha|h-captcha/i.test(el.name + ' ' + el.id)) continue;
    if (el.closest('[aria-hidden=true], header, footer, nav')) continue;
    const box = el.closest(CONTAINER);
    if (tagName === 'button') {
      const t = txt(el);
      if (!box || !/^(yes|no)$/i.test(t) || !vis(el)) continue;
      const btns = [...box.querySelectorAll('button')].filter(b => /^(yes|no)$/i.test(txt(b)) && vis(b));
      if (btns.length < 2) continue;
      btns.forEach(b => grouped.add(b));
      const gid = tag(btns[0]);
      const options = btns.map(b => txt(b));
      btns.forEach((b, i) => b.dataset.aeO = gid + ':' + i);
      const current = btns.filter(b => b.getAttribute('aria-pressed') === 'true' || /active|selected|checked/i.test(b.className || '')).map(b => txt(b));
      const label = questionText(null, box, options);
      groups.push({gid, kind: 'buttons', label, context: txt(box).slice(0, 700), options, current, required: isReq(null, box, label)});
      continue;
    }
    if (type === 'radio' || type === 'checkbox') {
      if (!optVisible(el)) continue;
      let members;
      if (type === 'radio' && el.name) members = [...document.querySelectorAll('input[type=radio]')].filter(r => r.name === el.name);
      else if (box) members = [...box.querySelectorAll('input[type=' + type + ']')];
      else members = [el];
      if (type === 'checkbox' && el.name && members.length <= 1) {
        const same = [...document.querySelectorAll('input[type=checkbox]')].filter(c => c.name === el.name);
        if (same.length > 1) members = same;
      }
      members = members.filter(optVisible);
      members.forEach(m => grouped.add(m));
      const gid = tag(members[0]);
      const options = members.map(optLabel);
      members.forEach((m, i) => m.dataset.aeO = gid + ':' + i);
      const current = members.filter(m => m.checked).map(optLabel);
      const single = type === 'checkbox' && members.length === 1;
      let label = single ? (questionText(null, box, []) || options[0]) : questionText(null, box, options);
      if (single && box && txt(box).length < 3) label = options[0];
      label = section(members[0], label);
      groups.push({gid, kind: single ? 'checkbox' : (type === 'radio' ? 'radio' : 'checkboxes'), label,
        optionLabel: single ? options[0] : '', context: txt(box || members[0].parentElement).slice(0, 700),
        options, current, required: isReq(members[0], box, label), name: el.name || ''});
      continue;
    }
    if (type === 'file') {
      const gid = tag(el);
      const label = questionText(el, box, []);
      groups.push({gid, kind: 'file', label, context: txt(box).slice(0, 300), options: [], current: el.files && el.files.length ? [el.files[0].name] : [],
        required: isReq(el, box, label), id: el.id || '', name: el.name || ''});
      continue;
    }
    if (!vis(el)) continue;
    const r = el.getBoundingClientRect();
    const isCombo = el.getAttribute('role') === 'combobox' || el.getAttribute('aria-autocomplete') === 'list' || /select__input/.test(el.className || '');
    if (!isCombo && tagName === 'input' && !el.id && !el.name && !(el.labels && el.labels.length) && box && box.querySelector('[role=combobox]')) continue;
    const gid = tag(el);
    const label = section(el, questionText(el, box, []));
    let kind = tagName === 'select' ? 'select' : tagName === 'textarea' ? 'textarea' : isCombo ? 'combobox' : (type === 'date' ? 'date' : 'text');
    let options = [];
    let current = [];
    if (kind === 'select') {
      options = [...el.options].map(o => o.text.trim());
      if (el.selectedIndex > 0) current = [el.options[el.selectedIndex].text.trim()];
    } else if (kind === 'combobox') {
      const chips = box ? [...box.querySelectorAll('[class*=multi-value__label]')].map(txt).filter(Boolean) : [];
      const shown = box && box.querySelector('[class*=single-value], [class*=singleValue], [class*=multi-value__label], [class*=multiValue]');
      if (chips.length) current = chips;
      else if (shown && txt(shown)) current = [txt(shown)];
      else if (el.value) current = [el.value];
    } else if (el.value) {
      current = [el.value];
    }
    groups.push({gid, kind, label, context: txt(box).slice(0, 700), options, current,
      required: isReq(el, box, label), id: el.id || '', name: el.name || '', placeholder: el.getAttribute('placeholder') || '',
      inputType: type, width: r.width, height: r.height, maxlength: el.maxLength > 0 ? el.maxLength : 0,
      multi: kind === 'combobox' && (/\[\]$/.test(el.id || '') || !!(box && box.querySelector('[class*=is-multi], [class*=multi-value]'))),
      dateish: /date/i.test(el.className || '') || !!el.closest('.react-datepicker-wrapper') || /pick (a )?date/i.test(el.getAttribute('placeholder') || '')});
  }
  return groups;
}
"""

VISIBLE_OPTIONS_JS = r"""
() => {
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 1 && r.height > 1 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const out = [];
  document.querySelectorAll('[data-ae-opt]').forEach(n => n.removeAttribute('data-ae-opt'));
  let nodes = [...document.querySelectorAll('[role=option]')].filter(vis);
  if (!nodes.length) nodes = [...document.querySelectorAll('.dropdown-location, .pac-item, [role=listbox] li, [class*=menu] [class*=option]')].filter(vis);
  for (const n of nodes) {
    if (!vis(n)) continue;
    if (n.querySelector('[role=option]')) continue;
    const t = (n.innerText || n.textContent || '').split('\n').map(s => s.replace(/\s+/g, ' ').trim()).filter(Boolean).join('\n');
    if (!t || t.length > 200) continue;
    n.setAttribute('data-ae-opt', String(out.length));
    out.push(t);
  }
  return out;
}
"""


PLACEHOLDERS = {"select...", "select", "select one", "--", "please select", "choose...", "choose one"}

# Conditional follow-ups ("If yes, which visa?") that only apply to an answer we did not give.
FOLLOWUP_RE = re.compile(
    r"^(if (yes|so|applicable|other|not|no)\b|if you (answered|selected|chose|responded|checked|picked)\b|if your answer)"
)

OTHER_SPECIFY = {"how_heard": "Company careers website"}


class FormFiller:
    def __init__(
        self,
        page: Any,
        *,
        profile: Profile,
        pool: list[PoolEntry],
        job: JobPosting | None,
        filled: list,
        skipped: list,
        notes: list,
        saved_answers: dict[str, str] | None = None,
    ) -> None:
        self.page = page
        self.saved = saved_answers
        self.profile = profile
        self.pool = pool
        self.job = job
        self.filled = filled
        self.skipped = skipped
        self.notes = notes
        self.ctx = Context(
            job_title=(job.title if job else ""),
            company=(job.company if job else ""),
            description=(job.description if job else ""),
            pool=pool,
        )
        self._facts: str | None = None
        self.done: set[str] = set()
        self.failed: dict[str, str] = {}
        self.chose_other: str | None = None

    # --- orchestration ---------------------------------------------------

    def run(self, passes: int = 4) -> None:
        for _ in range(passes):
            progressed = False
            for g in self.extract():
                if g["kind"] == "file":
                    continue
                if g["gid"] in self.failed:
                    # Empty comboboxes (Country* with options still loading) retry.
                    if not (g["kind"] == "combobox" and not (g.get("options") or g.get("current"))):
                        continue
                    self.failed.pop(g["gid"], None)
                if g["gid"] in self.done:
                    if not self._choice_needs_restick(g):
                        continue
                    self.done.discard(g["gid"])
                if self._fill_group(g):
                    progressed = True
            if not progressed:
                break
            self.page.wait_for_timeout(600)
        self._restick_required_radios()
        self._retry_empty_comboboxes()
        self._report_unanswered()

    def _choice_needs_restick(self, g: dict) -> bool:
        """True when a previously filled required radio/checkbox group is empty again."""
        if g["kind"] not in {"radio", "checkboxes", "buttons"}:
            return False
        if g.get("current"):
            return False
        return bool(g.get("required") or self._previous_choice(g))

    def _previous_choice(self, g: dict) -> str | None:
        label = (g.get("label") or "")[:160]
        for row in reversed(self.filled):
            if row.get("label") == label and row.get("value"):
                return str(row["value"])
        return self._saved(g) if self.saved is not None else None

    def _restick_required_radios(self) -> None:
        """Ashby confirm re-fill can uncheck required radios; re-apply before Submit."""
        for g in self.extract():
            if g["kind"] not in {"radio", "checkboxes", "buttons"}:
                continue
            if g.get("current") and not g.get("required"):
                continue
            want = self._want_for(g)
            options = g.get("options") or []
            picks = choose(options, want) if want else []
            if not picks:
                prev = self._previous_choice(g)
                if prev:
                    by_norm = {norm(o): o for o in options}
                    if norm(prev) in by_norm:
                        picks = [by_norm[norm(prev)]]
                    else:
                        hits = [o for o in options if norm(prev) in norm(o) or norm(o) in norm(prev)]
                        picks = hits[:1]
            if not picks:
                continue
            current = {norm(c) for c in g.get("current") or []}
            if norm(picks[0]) in current:
                continue
            self.done.discard(g["gid"])
            self.failed.pop(g["gid"], None)
            if want is None:
                want = Want(key="restick", text=picks[0], terms=picks)
            self._fill_choice(g, want)

    def _retry_empty_comboboxes(self) -> None:
        """Greenhouse Country* can paint with [] the first time; wait and retry US."""
        for g in self.extract():
            if g["kind"] != "combobox" or g["gid"] in self.done or g.get("current"):
                continue
            want = self._want_for(g)
            if want is None:
                continue
            self.failed.pop(g["gid"], None)
            self._fill_combobox(g, want)

    def extract(self) -> list[dict]:
        try:
            groups = self.page.evaluate(EXTRACT_JS)
        except Exception as exc:
            self.notes.append(f"form extract failed: {exc}"[:200])
            return []
        out = []
        for g in groups:
            if g["kind"] in {"text", "textarea"} and is_honeypot(
                label=g.get("label", ""), name=g.get("name", ""), element_id=g.get("id", ""),
                width=g.get("width"), height=g.get("height"),
            ):
                continue
            out.append(g)
        return out

    def facts(self) -> str:
        if self._facts is None:
            self._facts = llm.facts_block(self.profile, self.pool, self.job)
        return self._facts

    # --- per-question ----------------------------------------------------

    def _want_for(self, g: dict) -> Want | None:
        """First grounded reading of the question that also fits the widget's options."""
        label = g.get("label") or ""
        kind = g["kind"]
        options = g.get("options") or []
        weak_label = len(label) <= 3
        texts = [label if not weak_label else (g.get("context") or label)]
        if kind == "checkbox" and g.get("optionLabel"):
            texts.append(g["optionLabel"])
        # Surrounding text belongs to other questions too; only option groups whose
        # label may just be an option ("Phone") need it.
        if g.get("context") and (weak_label or kind in {"radio", "checkboxes", "buttons", "checkbox"}):
            texts.append(g["context"])
        if kind in {"radio", "checkboxes", "buttons", "select"} and options:
            texts.append(f"{label} {' / '.join(options[:12])}")
        fallback = None
        for text in texts:
            want = resolve(text, self.profile, self.ctx)
            if want is None:
                continue
            if want.leave_blank or kind not in {"radio", "checkboxes", "buttons", "select"}:
                return want
            if want.essay:
                continue
            if choose(options, want):
                return want
            if fallback is None:
                fallback = want
                # A choice answer read off the label is binding: when its options
                # don't fit, fail rather than re-read the block as another question.
                if want.terms or want.polarity is not None or want.pick:
                    return want
        return fallback

    def _fill_group(self, g: dict) -> bool:
        label = norm(g.get("label") or "")
        if FOLLOWUP_RE.search(label):
            if not g.get("required"):
                self.done.add(g["gid"])
                return False
            if re.search(r"\bother\b", label) and self.chose_other and g["kind"] in {"text", "textarea"}:
                return self._fill_other_specify(g)
        want = self._want_for(g)
        if want is not None and want.leave_blank:
            self.done.add(g["gid"])
            return False
        if want is not None and want.skip_if_optional and not g.get("required"):
            self.done.add(g["gid"])
            return False
        if want is not None and not (want.text or want.terms or want.pick or want.essay or want.select_all
                                     or want.polarity is not None):
            return self._fail(g, f"no profile value for {want.key}")
        kind = g["kind"]
        try:
            if kind in {"text", "textarea", "date"}:
                return self._fill_text(g, want)
            if kind == "select":
                return self._fill_select(g, want)
            if kind in {"radio", "checkboxes", "buttons"}:
                return self._fill_choice(g, want)
            if kind == "checkbox":
                return self._fill_single_checkbox(g, want)
            if kind == "combobox":
                return self._fill_combobox(g, want)
        except Exception as exc:
            self._fail(g, f"{kind} write error: {exc}"[:180])
        return False

    def _fill_text(self, g: dict, want: Want | None) -> bool:
        loc = self._loc(g)
        value: str | None = None
        method = "text"
        if want is not None and want.essay or (want is None and g["kind"] == "textarea"):
            if g.get("current"):
                self.done.add(g["gid"])
                return False
            value = self._essay(g)
            method = "llm-essay"
            if not value:
                return self._fail(g, "essay: no LLM answer" if llm.available() else "essay: no LLM key configured")
        elif want is not None:
            value = self._text_for(g, want)
        if not value:
            return self._fail(g, "no grounded answer" if want is None else f"no profile value for {want.key}")
        current = (g.get("current") or [""])[0]
        if norm(current) == norm(value):
            self._record(g, want.key if want else "essay", current, "already-set")
            return True
        loc.scroll_into_view_if_needed(timeout=3000)
        suggest = want is not None and want.key in {"location", "city", "school", "preferred_location"}
        if suggest or g.get("dateish"):
            loc.fill("", timeout=5000)
            loc.type(value, delay=30, timeout=10000)
        else:
            loc.fill(value, timeout=5000)
        if suggest:
            self._pick_suggestion(want)
        elif g.get("dateish"):
            loc.press("Enter")
            self.page.wait_for_timeout(200)
            self.page.keyboard.press("Escape")
        self.page.wait_for_timeout(150)
        shown = loc.input_value(timeout=2000)
        if not shown.strip() and suggest and want.key in {"location", "city"} and self.profile.city:
            loc.fill("", timeout=5000)
            loc.type(self.profile.city, delay=60, timeout=10000)
            self._pick_suggestion(want, wait_ms=6000)
            self.page.wait_for_timeout(300)
            shown = loc.input_value(timeout=2000)
        if not shown.strip():
            return self._fail(g, f"text did not stick for {want.key if want else 'essay'}")
        self._record(g, want.key if want else "essay", shown, method)
        return True

    def _text_for(self, g: dict, want: Want) -> str | None:
        placeholder = norm(g.get("placeholder", ""))
        is_date = (
            g["kind"] == "date" or g.get("inputType") == "date" or g.get("dateish")
            or re.search(r"mm\s*/\s*dd|dd\s*/\s*mm|yyyy", placeholder)
        )
        if is_date and want.key in {"graduation", "start_date"}:
            d = self._date_for(want.key)
            if d:
                if g.get("inputType") == "date":
                    return d.isoformat()
                if re.search(r"^mm\s*/\s*yyyy$", placeholder):
                    return d.strftime("%m/%Y")
                return d.strftime("%m/%d/%Y")
        if want.key == "phone" and g.get("inputType") == "tel" and self._country_code_sibling(g):
            digits = re.sub(r"\D", "", want.text or "")
            return digits[-10:] if len(digits) >= 10 else want.text
        if g.get("inputType") == "number" and want.text:
            num = re.search(r"\d[\d,]*(?:\.\d+)?", want.text)
            return num.group(0).replace(",", "") if num else None
        return want.text

    def _date_for(self, key: str) -> date | None:
        if key == "graduation":
            grad = graduation(self.profile)
            return date(grad[1], grad[0], 15) if grad else None
        return season_start_date(self.ctx)

    def _country_code_sibling(self, g: dict) -> bool:
        return "country" in norm(g.get("context", ""))

    def _fill_select(self, g: dict, want: Want | None) -> bool:
        options = g.get("options") or []
        picks = choose(options, want) if want else []
        method = "select"
        if not picks:
            picks, method = self._only_option(g, options), "only-option"
        if not picks:
            picks = self._llm_pick(g, options)
            method = "llm-pick"
        if not picks:
            return self._fail(g, "no option matched" if want else "unmapped")
        if g.get("current") and norm(g["current"][0]) == norm(picks[0]):
            self._record(g, want.key if want else "llm_pick", picks[0], "already-set")
            return True
        loc = self._loc(g)
        loc.select_option(label=picks[0], timeout=5000)
        shown = loc.evaluate("el => el.selectedIndex >= 0 ? el.options[el.selectedIndex].text.trim() : ''")
        if norm(shown) != norm(picks[0]):
            return self._fail(g, f"select did not stick (wanted {picks[0]!r}, shows {shown!r})")
        self._record(g, want.key if want else "llm_pick", shown, method)
        return True

    def _fill_choice(self, g: dict, want: Want | None) -> bool:
        options = g.get("options") or []
        multi = g["kind"] == "checkboxes"
        picks = choose(options, want) if want else []
        method = g["kind"]
        if picks and not multi:
            picks = picks[:1]
        if picks and multi and not (want and (want.select_all or want.pick)):
            picks = picks[:1]
        if not picks:
            prev = self._previous_choice(g)
            if prev:
                by_norm = {norm(o): o for o in options}
                if norm(prev) in by_norm:
                    picks, method = [by_norm[norm(prev)]], "restick"
        if not picks and not multi:
            picks, method = self._only_option(g, options), "only-option"
        if not picks:
            picks = self._llm_pick(g, options, multi=multi)
            method = "llm-pick"
        if not picks:
            return self._fail(g, "no option matched" if want else "unmapped")
        current = {norm(c) for c in g.get("current") or []}
        for pick in picks:
            if norm(pick) in current:
                continue
            idx = options.index(pick)
            self._click_option(g, idx)
        self.page.wait_for_timeout(250)
        after = self._group_state(g)
        missing = [p for p in picks if norm(p) not in {norm(a) for a in after}]
        if missing:
            return self._fail(g, f"choice did not stick: {missing}")
        self._record(g, want.key if want else "llm_pick", ", ".join(picks), method)
        return True

    def _fill_single_checkbox(self, g: dict, want: Want | None) -> bool:
        if want is None:
            if g.get("required"):
                return self._fail(g, "required checkbox not understood")
            self.done.add(g["gid"])
            return False
        should = want.polarity is True or bool(choose(g.get("options") or [], want))
        if want.polarity is False:
            should = False
        checked = bool(g.get("current"))
        if should == checked:
            self._record(g, want.key, "checked" if checked else "unchecked", "already-set")
            return True
        self._click_option(g, 0)
        self.page.wait_for_timeout(200)
        now = bool(self._group_state(g))
        if now != should:
            return self._fail(g, "checkbox did not toggle")
        self._record(g, want.key, "checked" if now else "unchecked", "checkbox")
        return True

    def _fill_combobox(self, g: dict, want: Want | None) -> bool:
        loc = self._loc(g)
        current = (g.get("current") or [""])[0]
        if current and want is not None and choose([current], want):
            self._record(g, want.key, current, "already-set")
            return True
        loc.scroll_into_view_if_needed(timeout=3000)
        loc.click(timeout=4000)
        self.page.wait_for_timeout(450)
        wait_ms = 7000 if want and want.key in {"country", "location", "city", "state"} else 4000
        options = self._wait_options(wait_ms)
        if not options:
            try:
                loc.click(timeout=4000)
            except Exception:
                pass
            options = self._wait_options(wait_ms)
        opened = options
        picks = choose(options, want) if (want and options) else []
        searches: list[str] = []
        if want is not None:
            for term in [want.search, *want.searches, *(want.terms[:3]), want.text]:
                if term and term not in searches:
                    searches.append(term)
        for term in searches:
            if picks:
                break
            loc.fill("", timeout=3000)
            loc.type(term, delay=25, timeout=8000)
            options = self._wait_options(wait_ms)
            picks = choose(options, want) if options else []
        method = "combobox"
        if not picks:
            picks = self._only_option(g, opened)
            if picks:
                method = "only-option"
                loc.fill("", timeout=3000)
                self._wait_options(1500)
        if not picks and (options or opened):
            if not options:
                loc.fill("", timeout=3000)
                options = self._wait_options(1500) or opened
            picks = self._llm_pick(g, options, multi=bool(g.get("multi")))
            method = "llm-pick"
        if not picks:
            self._abandon_combobox(loc)
            if not (options or opened):
                # Options never painted — retry on a later pass instead of locking failure.
                return False
            return self._fail(g, f"no option matched (saw {(options or opened)[:6]})" if want else "unmapped")
        if g.get("multi") and len(picks) > 1:
            return self._fill_multi_combobox(g, loc, picks, want, method)
        typed = loc.input_value(timeout=2000)
        self._click_visible_option(picks[0])
        self.page.wait_for_timeout(400)
        shown = self._combobox_value(g)
        if not self._combo_matches(shown, picks[0], typed):
            shown = self._keyboard_select(g, loc, picks[0], typed)
        if not self._combo_matches(shown, picks[0], typed):
            self._abandon_combobox(loc)
            return self._fail(g, f"combobox did not stick (wanted {picks[0]!r}, shows {shown!r})")
        self._record(g, want.key if want else "llm_pick", shown, method)
        return True

    def _fill_multi_combobox(self, g: dict, loc: Any, picks: list[str], want: Want | None, method: str) -> bool:
        for pick in picks:
            if norm(pick) in {norm(c) for c in self._combobox_chips(g)}:
                continue
            # No fill(""): clearing an empty react-select input deletes the last chip.
            loc.click(timeout=4000)
            loc.type(pick.split("\n")[0], delay=25, timeout=8000)
            options = self._wait_options()
            if not any(norm(o) == norm(pick) for o in options):
                loc.press("Escape")
                continue
            self._click_visible_option(pick)
            self.page.wait_for_timeout(300)
        loc.press("Escape")
        chips = self._combobox_chips(g)
        got = [p for p in picks if norm(p) in {norm(c) for c in chips}]
        if not got:
            return self._fail(g, f"multi-select did not stick (wanted {picks})")
        self._record(g, want.key if want else "llm_pick", ", ".join(got), method)
        return True

    def _combobox_chips(self, g: dict) -> list[str]:
        return self.page.evaluate(
            """gid => {
              const el = document.querySelector('[data-ae-q="' + gid + '"]');
              const box = el && (el.closest('.select__control, [class*=control]') || el.parentElement);
              const txt = n => (n.innerText || n.textContent || '').replace(/\\s+/g, ' ').trim();
              return box ? [...box.querySelectorAll('[class*=multi-value__label]')].map(txt).filter(Boolean) : [];
            }""",
            g["gid"],
        )

    @staticmethod
    def _combo_matches(shown: str, pick: str, typed: str = "") -> bool:
        """The widget shows the option, or a short form of it (a +1 dial code), not just our search text."""
        s, p = norm(shown), norm(pick)
        if not s:
            return False
        if p in s or norm(pick.split("\n")[0]) in s:
            return True
        return s in p and s != norm(typed)

    def _keyboard_select(self, g: dict, loc: Any, pick: str, typed: str) -> str:
        """Arrow to the option and press Enter, for menus that close on blur before a click lands."""
        loc.click(timeout=4000)
        if typed:
            loc.fill("", timeout=3000)
            loc.type(typed, delay=25, timeout=8000)
        options = self._wait_options()
        if pick not in options:
            return ""
        target = options.index(pick)
        active = self.page.evaluate(
            """() => [...document.querySelectorAll('[data-ae-opt]')].findIndex(o =>
                 o.getAttribute('aria-selected') === 'true' || /focused|active|highlight/i.test(o.className || ''))"""
        )
        if active < 0:
            loc.press("ArrowDown")
            active = 0
        for _ in range(target - active):
            loc.press("ArrowDown")
        loc.press("Enter")
        self.page.wait_for_timeout(400)
        return self._combobox_value(g)

    # --- widgets ---------------------------------------------------------

    def _loc(self, g: dict) -> Any:
        return self.page.locator(f'[data-ae-q="{g["gid"]}"]').first

    def _click_option(self, g: dict, idx: int) -> None:
        el = self.page.locator(f'[data-ae-o="{g["gid"]}:{idx}"]').first
        tag = el.evaluate("e => e.tagName.toLowerCase()")
        if tag == "button":
            el.scroll_into_view_if_needed(timeout=3000)
            el.click(timeout=4000)
            return
        label = el.evaluate_handle(
            "e => (e.labels && e.labels[0]) || e.closest('label') || e"
        ).as_element()
        target = label or el
        try:
            target.scroll_into_view_if_needed(timeout=3000)
            target.click(timeout=4000)
        except Exception:
            el.evaluate("e => e.click()")

    def _group_state(self, g: dict) -> list[str]:
        return self.page.evaluate(
            """gid => {
              const els = [...document.querySelectorAll('[data-ae-o^="' + gid + ':"]')];
              const txt = n => (n ? (n.innerText || n.textContent || '') : '').replace(/\\s+/g, ' ').trim();
              const label = e => (e.labels && e.labels[0] && txt(e.labels[0])) || (e.closest('label') && txt(e.closest('label'))) || e.getAttribute('aria-label') || e.value || txt(e);
              return els.filter(e => e.tagName === 'BUTTON'
                  ? (e.getAttribute('aria-pressed') === 'true' || /active|selected|checked/i.test(e.className || ''))
                  : e.checked).map(label);
            }""",
            g["gid"],
        )

    def _visible_options(self) -> list[str]:
        try:
            return self.page.evaluate(VISIBLE_OPTIONS_JS)
        except Exception:
            return []

    def _wait_options(self, timeout_ms: int = 4000) -> list[str]:
        waited = 0
        last: list[str] = []
        while waited < timeout_ms:
            self.page.wait_for_timeout(300)
            waited += 300
            opts = self._visible_options()
            if opts and not all(re.search(r"^(loading|searching|no (options|results))", norm(o)) for o in opts):
                if opts == last:
                    return opts
                last = opts
        return last

    def _click_visible_option(self, text: str) -> None:
        options = self._visible_options()
        idx = next((i for i, o in enumerate(options) if o == text), None)
        if idx is None:
            idx = next((i for i, o in enumerate(options) if norm(o) == norm(text)), 0)
        self.page.locator(f'[data-ae-opt="{idx}"]').first.click(timeout=4000)

    def _abandon_combobox(self, loc: Any) -> None:
        """Leave no typed search text behind that could pass for an answer."""
        try:
            loc.fill("", timeout=2000)
            loc.press("Escape")
        except Exception:
            pass

    def _combobox_value(self, g: dict) -> str:
        return self.page.evaluate(
            """gid => {
              const el = document.querySelector('[data-ae-q="' + gid + '"]');
              if (!el) return '';
              const txt = n => (n ? (n.innerText || n.textContent || '') : '').replace(/\\s+/g, ' ').trim();
              const box = el.closest('.select__control, [class*=control], .field-wrapper, .ashby-application-form-field-entry, .application-question') || el.parentElement;
              const shown = box && box.querySelector('[class*=single-value], [class*=singleValue], [class*=multi-value__label], [class*=multiValue]');
              if (shown && txt(shown)) return txt(shown);
              return el.value || '';
            }""",
            g["gid"],
        )

    def _pick_suggestion(self, want: Want, wait_ms: int = 2500) -> None:
        options = self._wait_options(wait_ms)
        if not options:
            return
        picks = choose(options, want)
        if not picks and want.key in {"location", "city"}:
            picks = [o for o in options if norm(self.profile.city) in norm(o)][:1]
        if picks:
            self._click_visible_option(picks[0])
            self.page.wait_for_timeout(300)

    # --- LLM -------------------------------------------------------------

    def _saved(self, g: dict) -> str | None:
        return (self.saved or {}).get((g.get("label") or "")[:160])

    def _essay(self, g: dict) -> str | None:
        if self.saved is not None:
            return self._saved(g)
        if not llm.available():
            return None
        question = g.get("context") or g.get("label") or ""
        if g.get("label") and g["label"] not in question:
            question = f"{g['label']}\n{question}"
        hint = ""
        if g.get("maxlength"):
            hint = f"at most {g['maxlength']} characters"
        elif g["kind"] == "text":
            hint = "a single-line text box: 1-3 sentences, under 60 words, no line breaks"
        text, issues = llm.draft_essay_checked(question[:1200], self.facts(), limit_hint=hint)
        if text and issues:
            self.notes.append(f"review essay: {(g.get('label') or '')[:80]}: {'; '.join(issues)}"[:300])
        if text and g.get("maxlength"):
            text = text[: g["maxlength"]]
        return text

    def _llm_pick(self, g: dict, options: list[str], *, multi: bool = False) -> list[str]:
        cleaned = [o for o in options if o and norm(o) not in {"select...", "select", "select one", "please select", "--"}]
        if self.saved is not None:
            wanted = [s.strip() for s in (self._saved(g) or "").split(", ")] if multi else [self._saved(g) or ""]
            by_norm = {norm(o): o for o in cleaned}
            return [by_norm[norm(w)] for w in wanted if norm(w) in by_norm]
        if not cleaned or not llm.available():
            return []
        question = g.get("label") or g.get("context") or ""
        return llm.pick_options(question[:800], cleaned, self.facts(), multi=multi)

    # --- bookkeeping -----------------------------------------------------

    def _fill_other_specify(self, g: dict) -> bool:
        text = OTHER_SPECIFY.get(self.chose_other or "")
        if not text:
            return self._fail(g, f"asks to specify 'Other' for {self.chose_other}")
        loc = self._loc(g)
        loc.fill(text, timeout=5000)
        if norm(loc.input_value(timeout=2000)) != norm(text):
            return self._fail(g, "text did not stick for other_specify")
        self._record(g, f"{self.chose_other}_other", text, "text")
        return True

    def _only_option(self, g: dict, options: list[str]) -> list[str]:
        """A required question with one real option ("Thank you", "Confirmed") has one valid answer."""
        real = [o for o in options if o and norm(o) not in PLACEHOLDERS]
        return real if g.get("required") and len(real) == 1 else []

    def _record(self, g: dict, key: str, value: str, method: str) -> None:
        if norm(value) == "other" or norm(value).startswith("other "):
            self.chose_other = key
        self.done.add(g["gid"])
        self.failed.pop(g["gid"], None)
        label = (g.get("label") or key)[:160]
        self.filled.append({"label": label, "mapped_to": key, "value": value, "method": method})

    def _fail(self, g: dict, reason: str) -> bool:
        self.failed[g["gid"]] = reason
        return False

    def _report_unanswered(self) -> None:
        final = {g["gid"]: g for g in self.extract()}
        for gid, reason in self.failed.items():
            g = final.get(gid)
            if g is None or g.get("current"):
                continue
            label = (g.get("label") or "unlabeled")[:160]
            if g.get("required"):
                if not label.rstrip().endswith("*"):
                    label += "*"
                self.notes.append(f"needs_user: required question unanswered: {label} ({reason})")
            self.skipped.append({"label": label, "reason": reason})
        for gid, g in final.items():
            if gid in self.done or gid in self.failed or g["kind"] == "file":
                continue
            if g.get("required") and not g.get("current"):
                label = (g.get("label") or "unlabeled")[:160]
                self.notes.append(f"needs_user: required question never reached: {label}")
                self.skipped.append({"label": label.rstrip("*") + "*", "reason": "not reached"})


def fill_form(
    page: Any,
    *,
    profile: Profile,
    pool: list[PoolEntry],
    job: JobPosting | None,
    filled: list,
    skipped: list,
    notes: list,
    saved_answers: dict[str, str] | None = None,
) -> None:
    FormFiller(page, profile=profile, pool=pool, job=job, filled=filled, skipped=skipped, notes=notes,
               saved_answers=saved_answers).run()


def month_name(month: int) -> str:
    return MONTHS[month - 1].capitalize()
