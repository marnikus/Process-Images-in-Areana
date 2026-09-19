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

# Strong rate/limit/quota signals only — the subset that justifies a long
# back-off. Generic failures (something went wrong / generation failed /
# service unavailable) are deliberately excluded so a transient error does not
# burn the full rate-limit penalty.
RATE_LIMIT_PATTERNS = (
    r"rate\s*-?\s*limit",
    r"limit\s+reached",
    r"reached\s+(your|the)\s+limit",
    r"usage\s+limit",
    r"daily\s+limit",
    r"too\s+many\s+requests",
    r"quota\s+exceeded",
    r"out\s+of\s+(credits|quota)",
    r"free\s+(tier|plan)\s+limit",
)

_RATE_LIMIT_COMPILED = [re.compile(p, re.IGNORECASE) for p in RATE_LIMIT_PATTERNS]

# Dead-request signature only (see match_dead_generation): the generation died
# because a captcha modal held the request open — the site says "try again" and
# one bounded resubmit is the honest remedy. Kept narrow on purpose.
DEAD_GENERATION_PATTERNS = (
    r"something\s+went\s+wrong\s+while\s+generating",
)

_DEAD_GENERATION_COMPILED = [re.compile(p, re.IGNORECASE) for p in DEAD_GENERATION_PATTERNS]

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


def is_rate_limit_error(text: str) -> bool:
    """True when a job-error string carries a rate/limit/quota signal."""
    if not text or not isinstance(text, str):
        return False
    return any(rx.search(text) for rx in _RATE_LIMIT_COMPILED)


def match_dead_generation(text: str) -> str:
    """Non-empty when a `Page error: …` line is the site's dead-request toast.

    Design `2026-09-18-dead-generation-toast-revival` §4.1: a generation request
    held hostage by the captcha modal dies server-side and the site asks the
    human to "try again" — exactly what the bounded revival does. Every other
    ERROR_PATTERN (limits, quotas, trace ids) stays terminal and must never be
    revived, so this is deliberately a *narrower* pattern set.
    """
    if not text or not isinstance(text, str):
        return ""
    for rx in _DEAD_GENERATION_COMPILED:
        if rx.search(text):
            return text[:MAX_LINE]
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
