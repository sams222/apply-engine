"""Filled-log vs screenshot reconciliation.

The engine's worst failure mode is a filled log that claims success while the
screenshot shows an empty form — it happened on Workday auth (9372e5: filled
claimed email/password while the screenshot showed an empty Sign In). A log that
disagrees with the pixels is worse than no log, because `confirm` trusts it.

So at screenshot time we also snapshot every form control's *rendered* value.
`reconcile` then diffs the filled log against that snapshot, and `confirm`
refuses when the two disagree on a value the spec calls out (NY / 10001, phone
digits, previous_employee=No).

Passwords are captured as presence-only, never as text.
"""

from __future__ import annotations

import re
from typing import Any

# Values that mean "nothing was actually chosen".
_EMPTY = {"", "select one", "select...", "choose...", "-", "--", "none", "select"}

# Collected at screenshot time: every control a reviewer can see in the PNG.
SNAPSHOT_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  const text = (el) => (el ? (el.innerText || el.textContent || '').trim() : '');

  const labelFor = (el) => {
    const wideLegal = (s) => /legal name/i.test(s) && /first name/i.test(s) && /last name/i.test(s);
    const auto = el.getAttribute('data-automation-id') || '';
    const fromAid = /firstName/i.test(auto) ? 'First Name' : (/lastName/i.test(auto) ? 'Last Name' : '');
    const aria = el.getAttribute('aria-label');
    if (aria && !wideLegal(aria)) return aria.trim();
    const ref = el.getAttribute('aria-labelledby');
    if (ref) {
      const parts = ref.split(/\s+/).map(id => text(el.ownerDocument.getElementById(id)));
      const joined = parts.filter(Boolean).join(' ').trim();
      if (joined && !wideLegal(joined)) return joined;
    }
    if (el.id) {
      const lab = el.ownerDocument.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (lab) {
        const t = text(lab);
        if (t && !wideLegal(t)) return t;
      }
    }
    const wrap = el.closest('label');
    if (wrap) {
      const t = text(wrap);
      if (t && !wideLegal(t)) return t;
    }
    if (fromAid) return fromAid;
    if (auto && !wideLegal(auto)) return auto;
    return el.getAttribute('placeholder') || el.getAttribute('name') || el.id || '';
  };

  const visible = (el) => {
    const r = el.getBoundingClientRect();
    // Either dimension at zero means nothing a human can see. Walmart's bot
    // trap is 1x0 with display:block/visibility:visible, and an && here
    // would have counted it as shown.
    if (r.width <= 1 || r.height <= 1) return false;
    const cs = el.ownerDocument.defaultView.getComputedStyle(el);
    return cs.visibility !== 'hidden' && cs.display !== 'none';
  };

  const push = (row) => {
    const key = `${row.tag}|${row.type}|${row.label}|${row.name}|${row.id}|${row.type === 'toggle' ? row.value : ''}`;
    if (seen.has(key)) return;
    seen.add(key);
    out.push(row);
  };

  const scan = (root) => {
    root.querySelectorAll('input, select, textarea').forEach((el) => {
      const type = (el.getAttribute('type') || el.type || 'text').toLowerCase();
      if (type === 'hidden') return;
      let value = '';
      if (type === 'password') {
        value = el.value ? '[present]' : '';
      } else if (type === 'checkbox' || type === 'radio') {
        value = el.checked ? (labelFor(el) || el.value || 'on') : '';
      } else if (el.tagName.toLowerCase() === 'select') {
        const opt = el.selectedOptions && el.selectedOptions[0];
        value = opt ? (opt.textContent || opt.value || '').trim() : '';
      } else if (type === 'file') {
        value = el.files && el.files.length ? el.files[0].name : '';
      } else {
        value = el.value || '';
      }
      push({
        tag: el.tagName.toLowerCase(),
        type,
        label: labelFor(el),
        name: el.getAttribute('name') || '',
        id: el.id || '',
        value: String(value).trim(),
        checked: !!el.checked,
        visible: visible(el),
      });
    });

    // Workday / Ashby custom widgets: the chosen value lives in button text.
    root.querySelectorAll('button[aria-haspopup], [role="combobox"], [role="listbox"]').forEach((el) => {
      push({
        tag: 'widget',
        type: el.getAttribute('role') || 'button',
        label: labelFor(el),
        name: el.getAttribute('data-automation-id') || '',
        id: el.id || '',
        value: text(el) || el.value || '',
        checked: false,
        visible: visible(el),
      });
    });

    // React-select (Greenhouse) renders the choice beside the input, not in it.
    root.querySelectorAll('[class*="single-value"], [class*="singleValue"], [class*="multi-value__label"]').forEach((el) => {
      const input = el.closest('[class*="control"]') && el.closest('[class*="control"]').querySelector('input');
      push({
        tag: 'widget',
        type: 'select-value',
        label: input ? labelFor(input) : '',
        name: '',
        id: input ? input.id : '',
        value: text(el),
        checked: false,
        visible: visible(el),
      });
    });

    // Ashby Yes/No toggles.
    root.querySelectorAll('button[aria-pressed="true"], button[class*="active"], button[class*="selected"]').forEach((el) => {
      const t = text(el);
      if (!/^(yes|no)$/i.test(t)) return;
      push({ tag: 'widget', type: 'toggle', label: labelFor(el), name: '', id: el.id || '', value: t, checked: true, visible: visible(el) });
    });
  };

  scan(document);
  document.querySelectorAll('iframe').forEach((f) => {
    try { if (f.contentDocument) scan(f.contentDocument); } catch (e) {}
  });
  return out;
}
"""


def capture(page: Any) -> list[dict]:
    """Snapshot rendered control values. Never raises — a failed snapshot is [],
    which reconcile() reports as unverified rather than as a false match."""
    try:
        rows = page.evaluate(SNAPSHOT_JS)
    except Exception:
        return []
    return [r for r in rows if isinstance(r, dict)]


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def digits(value: str) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _is_empty(value: str) -> bool:
    return _norm(value) in _EMPTY


def _values(snapshot: list[dict]) -> list[str]:
    return [str(r.get("value") or "") for r in snapshot if not _is_empty(str(r.get("value") or ""))]


def _present(needle: str, snapshot: list[dict]) -> bool:
    """Is this value visible anywhere in the rendered form?"""
    want = _norm(needle)
    if not want:
        return False
    for shown in _values(snapshot):
        seen = _norm(shown)
        if want == seen or want in seen or seen in want:
            return True
    return False


def _phone_present(phone: str, snapshot: list[dict]) -> bool:
    """Phone matches on digits — the widget reformats (212) 555-0147 freely."""
    want = digits(phone)
    if not want:
        return False
    tail = want[-10:]
    for shown in _values(snapshot):
        if tail and tail in digits(shown):
            return True
    return False


# Values the spec singles out, because these are the ones that silently revert.
# Live Walmart claimed city="New York" in the filled log while the rendered
# Address block showed City empty, and the check waved it through because city
# was not listed here. Anything the reviewer is expected to eyeball belongs in
# this list.
CRITICAL = (
    "state", "postal_code", "phone", "previous_employee", "email",
    "first_name", "last_name", "city", "address_line1", "country", "how_heard",
)


def reconcile(filled: list[dict], snapshot: list[dict]) -> list[dict]:
    """Rows whose logged value is not visible in the snapshot.

    Returns [] when the log and the render agree. An empty snapshot yields a
    single 'unverified' row rather than silent agreement.
    """
    if not snapshot:
        return [{"mapped_to": "*", "reason": "no dom snapshot captured", "logged": "", "shown": ""}]

    problems: list[dict] = []
    for row in filled:
        if not isinstance(row, dict):
            continue
        key = str(row.get("mapped_to") or "")
        logged = str(row.get("value") or "")
        if key not in CRITICAL:
            continue
        if not logged or logged == "[redacted]":
            continue
        ok = _phone_present(logged, snapshot) if key == "phone" else _present(logged, snapshot)
        if not ok:
            problems.append(
                {
                    "mapped_to": key,
                    "reason": "logged value not visible in rendered form",
                    "logged": logged,
                    "shown": "; ".join(_values(snapshot)[:8]),
                }
            )
    return problems
