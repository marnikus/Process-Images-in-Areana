"""Ui.Vision settings, the tab-pattern match, and the demo run.

Sits between the "Firefox auto with Extension" window and the browser leaves:
reads the operator's configuration, decides which URL the macro should open,
and reports the run in words the window can show.

The tab pattern is the control element the user asked for: rather than the app
hunting through Firefox's tabs (which would need exactly the debugger access
this feature removes), the operator states the URL pattern, and the macro's
`open` command puts a matching tab in front. The pattern is matched against the
app's own URL rows so the two stay consistent.

Layer: services — composes `browser/uivision`; no Qt, no UI imports.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from ..browser.uivision.command_url import MacroRun, build_autorun_url
from ..browser.uivision.macro import NEW_CHAT_XPATH, new_chat_macro
from ..browser.uivision.runner import DEFAULT_TIMEOUT_S, MacroOutcome, run_macro

__all__ = ["UiVisionConfig", "config_from_settings", "matching_urls", "pick_url",
           "url_of", "match_report",
           "demo_macro_json", "build_run", "preview_url", "run_demo", "DEFAULT_MACRO",
           "SETTING_KEYS"]

DEFAULT_MACRO = "Python_XClick_Demo"

SETTING_KEYS = {
    "uivision_html_path": "",            # …/ui.vision.html (the extension's autorun page)
    "uivision_macro": DEFAULT_MACRO,
    "uivision_log_path": "",             # absolute → Ui.Vision writes it directly
    "uivision_firefox_path": "firefox",
    "uivision_tab_pattern": "arena.ai",  # which tab the macro should open
    "uivision_target": NEW_CHAT_XPATH,   # what XClick aims at
    "uivision_timeout_s": DEFAULT_TIMEOUT_S,
}


class UiVisionConfig:
    """The operator's Ui.Vision setup, with the gaps it still has."""

    def __init__(self, values: Dict[str, Any]):
        self.html_path = str(values.get("uivision_html_path", "") or "")
        self.macro = str(values.get("uivision_macro", "") or DEFAULT_MACRO)
        self.log_path = str(values.get("uivision_log_path", "") or "")
        self.firefox_path = str(values.get("uivision_firefox_path", "") or "firefox")
        self.tab_pattern = str(values.get("uivision_tab_pattern", "") or "")
        self.target = str(values.get("uivision_target", "") or NEW_CHAT_XPATH)
        self.timeout_s = _as_float(values.get("uivision_timeout_s"), DEFAULT_TIMEOUT_S)

    def missing(self) -> List[str]:
        """What the operator still has to fill in before a run can work."""
        gaps = []
        if not self.html_path:
            gaps.append("ui.vision.html path")
        if not self.log_path:
            gaps.append("log file path")
        if not self.macro:
            gaps.append("macro name")
        return gaps

    @property
    def is_ready(self) -> bool:
        return not self.missing()

    def as_dict(self) -> Dict[str, Any]:
        """The values, for the window's form."""
        return {"uivision_html_path": self.html_path, "uivision_macro": self.macro,
                "uivision_log_path": self.log_path, "uivision_firefox_path": self.firefox_path,
                "uivision_tab_pattern": self.tab_pattern, "uivision_target": self.target,
                "uivision_timeout_s": self.timeout_s}


def _as_float(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if number > 0 else fallback


def config_from_settings(settings: Any) -> UiVisionConfig:
    """Build the config from a dict-like or attribute-style settings object."""
    values = {}
    for key, default in SETTING_KEYS.items():
        if isinstance(settings, dict):
            values[key] = settings.get(key, default)
        else:
            values[key] = getattr(settings, key, default)
    return UiVisionConfig(values)


def url_of(row: Any) -> str:
    """The URL a row carries — `UrlRow.url`, a dict's `url`, or a plain string.

    The app stores `core.models.UrlRow` dataclasses. An earlier version fell
    back to `str(row)` for unknown shapes, which silently "matched" a UrlRow
    through its *repr* (the repr contains the url) and then handed that repr on
    as if it were a URL. Anything without a real url is now empty, so it cannot
    match at all (I-66, RULE 4: no plausible-looking wrong answer).
    """
    if isinstance(row, str):
        return row
    if isinstance(row, dict):
        return str(row.get("url") or "")
    return str(getattr(row, "url", "") or "")


def matching_urls(urls: Any, pattern: str) -> List[str]:
    """Every configured URL containing `pattern` (case-insensitive).

    An empty pattern matches nothing rather than everything — a blank control
    field must not silently select an arbitrary tab (RULE 4).
    """
    needle = str(pattern or "").strip().lower()
    if not needle:
        return []
    return [url for url in (url_of(row) for row in urls or [])
            if url and needle in url.lower()]


_REPORT_LIMIT = 5  # URLs to name before summarising; keeps one log line readable


def match_report(urls: Any, pattern: str) -> str:
    """Why the pattern found nothing, in terms the operator can act on.

    "no tab matches the pattern" is what made I-66 unactionable: it looks
    identical whether the pattern is wrong, the list is empty, or the app is
    reading the wrong store. This names the pattern, the row count, and the
    URLs actually compared.
    """
    needle = str(pattern or "").strip()
    if not needle:
        return "the tab pattern is empty — type the URL (or part of it) to open"
    known = [u for u in (url_of(row) for row in urls or []) if u]
    if not known:
        return (f"pattern '{needle}' matched nothing — the app knows no URL rows yet; "
                f"add the tab to the URL list, or type a full https:// URL as the pattern")
    shown = ", ".join(known[:_REPORT_LIMIT])
    extra = f" (+{len(known) - _REPORT_LIMIT} more)" if len(known) > _REPORT_LIMIT else ""
    return f"pattern '{needle}' matched none of {len(known)} URL(s): {shown}{extra}"


def pick_url(urls: Any, pattern: str) -> str:
    """The URL the macro should open: the first match, else the pattern itself.

    A pattern that is already a full URL is usable as-is, which is what makes
    the window work before any URL rows exist.
    """
    matches = matching_urls(urls, pattern)
    if matches:
        return matches[0]
    text = str(pattern or "").strip()
    return text if text.startswith(("http://", "https://")) else ""


def demo_macro_json(config: UiVisionConfig) -> str:
    """The macro source for the operator to import into Ui.Vision.

    `url` and `target` stay as `${!cmd_var1}` / `${!cmd_var2}` so one stored
    macro serves every run — the app supplies both on the command line.
    """
    return json.dumps(new_chat_macro(name=config.macro), indent=2, ensure_ascii=False)


def build_run(config: UiVisionConfig, url: str) -> MacroRun:
    """The macro invocation: the tab URL and the click target as cmd_var1/2."""
    return MacroRun(macro=config.macro, html_path=config.html_path,
                    log_path=config.log_path, cmd_vars=[url, config.target])


def preview_url(config: UiVisionConfig, url: str) -> str:
    """The autorun URL this configuration would open (for the window to show)."""
    return build_autorun_url(build_run(config, url))


async def run_demo(config: UiVisionConfig, url: str, urls: Any = ()) -> MacroOutcome:
    """Run the configured macro against `url` and return its logged outcome.

    `urls` is only used to explain a failed match (I-66) — the run itself needs
    nothing but the resolved URL.
    """
    if not config.is_ready:
        return MacroOutcome(state="failed", message="; ".join(config.missing()))
    if not url:
        return MacroOutcome(state="failed", message=match_report(urls, config.tab_pattern))
    return await run_macro(build_run(config, url), config.firefox_path, config.timeout_s)
