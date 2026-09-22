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


def matching_urls(urls: Any, pattern: str) -> List[str]:
    """Every configured URL containing `pattern` (case-insensitive).

    An empty pattern matches nothing rather than everything — a blank control
    field must not silently select an arbitrary tab (RULE 4).
    """
    needle = str(pattern or "").strip().lower()
    if not needle:
        return []
    found = []
    for row in urls or []:
        url = str((row.get("url") if isinstance(row, dict) else row) or "")
        if needle in url.lower():
            found.append(url)
    return found


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


async def run_demo(config: UiVisionConfig, url: str) -> MacroOutcome:
    """Run the configured macro against `url` and return its logged outcome."""
    if not config.is_ready:
        return MacroOutcome(state="failed", message="; ".join(config.missing()))
    if not url:
        return MacroOutcome(state="failed", message="no tab matches the pattern")
    return await run_macro(build_run(config, url), config.firefox_path, config.timeout_s)
