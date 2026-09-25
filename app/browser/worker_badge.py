"""Worker-id badge for pooled tabs — the JS text only (D-4).

Owns: one small, click-transparent, top-middle overlay that says
``#<worker_no>`` plus the full tab id, so a Chrome tab can be matched to a
row in the app's worker list at a glance. Idempotent: re-running the JS
replaces the previous badge (attribute-tagged), so a reconciler pass may
re-assert it after a page navigation wiped it.

Firefox (2026-09-25): the Ui.Vision identify macro reuses the same body through
`build_badge_js_from` with in-page expressions (`<n># <account>`), so the two
browsers share one look and one de-duplication attribute.

Imports: stdlib only. Nobody here talks to CDP — `services.live.worker_badges`
evaluates what this module builds. Kept out of `dom_highlight.py`, which is
already the largest browser leaf (RULE 18.2).
"""

from __future__ import annotations

import json
from collections import namedtuple
from dataclasses import dataclass

WORKER_ATTR = "data-arena-worker"
BADGE_Z = 2147483645  # one below the watcher overlay: the wait popup must win


@dataclass(frozen=True)
class WorkerBadgeSpec:
    worker_no: int
    tab_id: str
    label: str = ""  # optional extra (e.g. window title); appended after the id


_BADGE_CSS = (
    "position:fixed;left:50%;top:0;transform:translateX(-50%);"
    f"z-index:{BADGE_Z};pointer-events:none;user-select:none;"
    "display:flex;align-items:center;gap:8px;padding:2px 10px 3px;"
    "border-radius:0 0 8px 8px;background:rgba(15,23,42,0.88);"
    "border:1px solid rgba(148,163,184,0.5);border-top:none;"
    "font:600 12px/1.3 system-ui,-apple-system,Segoe UI,sans-serif;color:#e2e8f0;"
    "box-shadow:0 2px 8px rgba(0,0,0,0.45)"
)
_NO_CSS = "font-size:14px;color:#fbbf24;letter-spacing:0.5px"
_ID_CSS = "font:500 11px/1.3 ui-monospace,Menlo,Consolas,monospace;color:#cbd5e1"


# The badge's three values as JS *expressions* (not text) — one parameter object:
# `no` (the number span), `text` (the id/name span), `tag` (the WORKER_ATTR value).
# Chrome passes JSON literals (`build_worker_badge_js`); the Firefox identify macro
# passes in-page expressions, because its account name is only known inside the
# page (`uivision.identify`). Same style, same attribute, same replace-before-insert
# — so both browsers can never show two badges.
BadgeExprs = namedtuple("BadgeExprs", "no text tag")


def build_worker_badge_js(spec: WorkerBadgeSpec) -> str:
    """Insert (or replace) the badge; text goes through `textContent` (no HTML)."""
    return build_badge_js_from(BadgeExprs(no=json.dumps("#" + str(spec.worker_no)),
                                          text=json.dumps(_id_text(spec)),
                                          tag=json.dumps(str(spec.worker_no))))


def build_badge_js_from(exprs: BadgeExprs) -> str:
    """The ONE badge body (Chrome + Firefox) — see `BadgeExprs`."""
    return f"""(() => {{
  document.querySelectorAll('[{WORKER_ATTR}]').forEach(e => e.remove());
  const box = document.createElement('div');
  box.setAttribute({json.dumps(WORKER_ATTR)}, {exprs.tag});
  box.style.cssText = {json.dumps(_BADGE_CSS)};
  const no = document.createElement('span');
  no.style.cssText = {json.dumps(_NO_CSS)};
  no.textContent = {exprs.no};
  const id = document.createElement('span');
  id.style.cssText = {json.dumps(_ID_CSS)};
  id.textContent = {exprs.text};
  box.appendChild(no); box.appendChild(id);
  (document.body || document.documentElement).appendChild(box);
  return 'ok';
}})()"""


def build_worker_badge_clear_js() -> str:
    """Remove the badge (and only the badge) from the page."""
    return (f"(() => {{ document.querySelectorAll('[{WORKER_ATTR}]')"
            ".forEach(e => e.remove()); return 'ok'; })()")


def _id_text(spec: WorkerBadgeSpec) -> str:
    return f"{spec.tab_id}  ·  {spec.label}" if spec.label else spec.tab_id
