"""Recording redaction — secrets never reach the disk (RULE 20).

Two layers: the snapshot probe redacts recaptcha fields IN THE PAGE before
bytes cross CDP; this module is defense-in-depth on the stored text plus the
URL redaction used for network events. Pure functions, stdlib only.
"""

from __future__ import annotations

import re

MAX_FIELD = 400  # bound for any single stored string value
MAX_HTML_LINE = 2000  # snapshot lines beyond this are clipped on store

# textarea/input named or id'd like a recaptcha response field: blank the
# inner text / value attribute (the probe already did this in-page).
_RE_FIELD_BODY = re.compile(
    r'(<textarea[^>]*(?:name|id)="g-recaptcha-response[^"]*"[^>]*>)(.*?)(</textarea>)',
    re.IGNORECASE | re.DOTALL)
_RE_FIELD_VALUE = re.compile(
    r'(<input[^>]*(?:name|id)="g-recaptcha-response[^"]*"[^>]*value=")([^"]*)(")',
    re.IGNORECASE)

_RECAPTCHA_HOST = re.compile(r"(?:^|\.)(?:google\.com|gstatic\.com|recaptcha\.net)$",
                             re.IGNORECASE)
# credential-bearing query params on ANY host
_SECRET_PARAMS = re.compile(
    r"(token|session|auth|key|signature|secret|password|bft|^k$|^cb$)", re.IGNORECASE)


def bound_str(value: object, limit: int = MAX_FIELD) -> str:
    """Bounded one-line string for stored event fields."""
    text = str(value if value is not None else "")
    return text.replace("\n", " ")[:limit]


def redact_dom_html(html: str) -> str:
    """Blank recaptcha response field contents in serialized DOM text."""
    if not html or "g-recaptcha-response" not in html:
        return html
    html = _RE_FIELD_BODY.sub(lambda m: m.group(1) + "[REDACTED]" + m.group(3), html)
    return _RE_FIELD_VALUE.sub(lambda m: m.group(1) + "[REDACTED]" + m.group(3), html)


def _host_of(url: str) -> str:
    try:
        from urllib.parse import urlsplit
        return (urlsplit(url).hostname or "").lower()
    except Exception:
        return ""


def redact_url(url: str) -> str:
    """recaptcha-family URLs keep host/path/param NAMES only; other URLs keep
    path + non-credential params (values of secret-looking params -> '*')."""
    url = bound_str(url, 600)
    try:
        from urllib.parse import urlsplit, parse_qsl, urlencode
        parts = urlsplit(url)
    except Exception:
        return url[:120]
    host = (parts.hostname or "").lower()
    base = f"{parts.scheme}://{host}{parts.path}" if parts.scheme else url.split("?")[0]
    if not parts.query:
        return base
    recaptcha = bool(_RECAPTCHA_HOST.search(host)) or "/recaptcha/" in parts.path
    pairs = []
    for name, value in parse_qsl(parts.query, keep_blank_values=True):
        if recaptcha or _SECRET_PARAMS.search(name or ""):
            pairs.append((name, "*"))
        else:
            pairs.append((name, value[:60]))
    return base + "?" + urlencode(pairs, safe="*")[:300]
