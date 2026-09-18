"""Page-error detection — fail jobs fast on limit banners and page errors.

The wait loop scans alert/toast/error regions each poll; any NEW text
matching ERROR_PATTERNS aborts the wait so the job finishes FAILED
(retryable) instead of stalling until the generation timeout.
Baseline = corpus captured at wait start; stale banners are ignored.
Stdlib-only leaf: safe to import from browser/ via `..utils`.
"""

from __future__ import annotations

import re

# Case-insensitive signals: limits, quotas, generation/send failures.
ERROR_PATTERNS = (
    r"limit\s+reached",
    r"reached\s+(your|the)\s+limit",
    r"usage\s+limit",
    r"daily\s+limit",
    r"rate\s*-?\s*limit",
    r"too\s+many\s+requests",
    r"quota\s+exceeded",
    r"out\s+of\s+(credits|quota)",
    r"free\s+(tier|plan)\s+limit",
    r"upgrade\s+(your\s+plan|to\s+continue)",
    r"try\s+again\s+(later|in\s+\d+|tomorrow)",
    r"come\s+back\s+(later|tomorrow)",
    r"something\s+went\s+wrong",
    r"trace\s*id",
    r"failed\s+to\s+(generate|send|create|upload|process)",
    r"generation\s+failed",
    r"couldn'?t\s+(generate|create|process|complete)",
    r"unable\s+to\s+(generate|process|complete)",
    r"temporarily\s+unavailable",
    r"service\s+unavailable",
    r"internal\s+error",
    r"message\s+(failed|not\s+sent|not\s+delivered)",
    r"\berror\s+generating\b",
)

_COMPILED = [re.compile(p, re.IGNORECASE) for p in ERROR_PATTERNS]

MAX_LINE = 160


class PageErrorAbort(Exception):
    """Raised by the output poll to abort the wait on a page error."""


def _fresh_lines(corpus: str, baseline: str) -> list:
    """Corpus lines not already present at wait start (stale-safe)."""
    if not corpus or not isinstance(corpus, str):
        return []
    base = set(ln.strip() for ln in (baseline or "").split("\n")) if baseline else set()
    return [ln.strip() for ln in corpus.split("\n") if ln.strip() and ln.strip() not in base]


def match_page_error(corpus: str, baseline: str = "") -> str:
    """First fresh error line as 'Page error: ...', else ''."""
    for line in _fresh_lines(corpus, baseline):
        for rx in _COMPILED:
            if rx.search(line):
                return f"Page error: {line[:MAX_LINE]}"
    return ""


def build_error_scan_js() -> str:
    """JS: joined text of alert/toast/error regions (truncated)."""
    return """(() => {
  const sel = '[role="alert"],[role="alertdialog"],[aria-live="assertive"],'
    + '[class*="toast"],[data-toast],[class*="Toast"],'
    + '[class*="error-banner"],[class*="error-toast"],[class*="alert-banner"]';
  const out = [];
  document.querySelectorAll(sel).forEach(el => {
    const t = (el.innerText || "").trim().replace(/\\s+/g, " ");
    if (t) out.push(t.slice(0, 300));
  });
  try {
    const divs = document.querySelectorAll("div");
    let hits = 0;
    for (let i = 0; i < divs.length && i < 8000 && hits < 3; i++) {
      const t = (divs[i].innerText || "").trim();
      if (!t || t.length > 500) continue;
      if (t.toLowerCase().indexOf("trace id") !== -1) { out.push(t.slice(0, 300)); hits++; }
    }
  } catch (e) {}
  return out.slice(0, 13).join("\\n").slice(0, 4000);
})()"""
