"""Worker-id badge for pooled tabs — the JS text only (D-4).

Owns: one small, click-transparent, top-middle overlay that says
``#<worker_no>`` plus the full tab id, so a Chrome tab can be matched to a
row in the app's worker list at a glance. Idempotent: re-running the JS
replaces the previous badge (attribute-tagged), so a reconciler pass may
re-assert it after a page navigation wiped it.

Imports: stdlib only. Nobody here talks to CDP — `services.live.worker_badges`
evaluates what this module builds. Kept out of `dom_highlight.py`, which is
already the largest browser leaf (RULE 18.2).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

WORKER_ATTR = "data-arena-worker"
BADGE_Z = 2147483645  # one below the watcher overlay: the wait popup must win
FIREFOX_ATTR = "data-arena-firefox-worker"
FIREFOX_BADGE_Z = BADGE_Z  # same layer as Chrome badge; watcher still wins


@dataclass(frozen=True)
class WorkerBadgeSpec:
    worker_no: int
    tab_id: str
    label: str = ""  # optional extra (e.g. window title); appended after the id


@dataclass(frozen=True)
class FirefoxBadgeSpec:
    worker_no: int
    account: str
    tab_id: str = ""  # stable id for debugging, not shown in overlay text
    profile: str = ""  # fallback when account unknown, not shown separately


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


def build_worker_badge_js(spec: WorkerBadgeSpec) -> str:
    """Insert (or replace) the badge; text goes through `textContent` (no HTML)."""
    return f"""(() => {{
  document.querySelectorAll('[{WORKER_ATTR}]').forEach(e => e.remove());
  const box = document.createElement('div');
  box.setAttribute({json.dumps(WORKER_ATTR)}, {json.dumps(str(spec.worker_no))});
  box.style.cssText = {json.dumps(_BADGE_CSS)};
  const no = document.createElement('span');
  no.style.cssText = {json.dumps(_NO_CSS)};
  no.textContent = {json.dumps("#" + str(spec.worker_no))};
  const id = document.createElement('span');
  id.style.cssText = {json.dumps(_ID_CSS)};
  id.textContent = {json.dumps(_id_text(spec))};
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


def _firefox_text(spec: FirefoxBadgeSpec) -> str:
    name = (spec.account or spec.profile or spec.tab_id or "").strip()
    return f"{int(spec.worker_no)}# {name}" if name else f"{int(spec.worker_no)}#"


def build_firefox_badge_js(spec: FirefoxBadgeSpec) -> str:
    """Insert (or replace) the Firefox overlay: ``<visual number># <account>``.

    Reuses Chrome badge visual style (centered top, same CSS constants) but
    uses ``FIREFOX_ATTR`` so Chrome and Firefox badges never clash, and the
    text is ``N# account`` per Firefox spec (not ``#N alias``). Idempotent:
    re-running removes the previous overlay, never duplicates.
    """
    text = _firefox_text(spec)
    return f"""(() => {{
  document.querySelectorAll('[{FIREFOX_ATTR}]').forEach(e => e.remove());
  const box = document.createElement('div');
  box.setAttribute({json.dumps(FIREFOX_ATTR)}, {json.dumps(str(spec.worker_no))});
  box.style.cssText = {json.dumps(_BADGE_CSS)};
  const label = document.createElement('span');
  label.style.cssText = {json.dumps(_NO_CSS + ";font-size:13px;color:#e2e8f0")};
  label.textContent = {json.dumps(text)};
  box.appendChild(label);
  (document.body || document.documentElement).appendChild(box);
  return 'ok';
}})()"""


def build_firefox_badge_clear_js() -> str:
    """Remove the Firefox overlay (and only the Firefox overlay)."""
    return (f"(() => {{ document.querySelectorAll('[{FIREFOX_ATTR}]')"
            ".forEach(e => e.remove()); return 'ok'; })()")
