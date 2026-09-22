"""Firefox auto with Extension panel — Ui.Vision config, macro source, test run.

Owns the 4 slots of the "Firefox auto with Extension" window. Thin slots
delegate to module funcs; imports go panels -> services/core only.

The run slot returns immediately with the launch decision and reports the
logged verdict afterwards, because polling the Ui.Vision log can take the full
timeout and must never block the UI thread.
"""

import json

from app.services import uivision_service as service
from app.services.run_state import schedule_coro
from app.ui.qt_compat import Slot


def config_of(bridge):
    """The saved Ui.Vision configuration for this app."""
    return service.config_from_settings(_settings_of(bridge))


def _settings_of(bridge) -> dict:
    """The stored values behind the window's form ({} when config is absent)."""
    config = getattr(bridge, "config", None)
    if config is None or not hasattr(config, "get_state"):
        return {}
    return {key: config.get_state(key, default) for key, default in service.SETTING_KEYS.items()}


def _urls_of(bridge):
    """The app's URL rows, used to resolve the tab pattern."""
    getter = getattr(bridge, "_url_rows", None)
    if callable(getter):
        try:
            return getter()
        except Exception:
            return []
    return getattr(bridge, "url_rows", []) or []


def settings_json(bridge) -> str:
    """Form values + the tab the pattern currently resolves to."""
    try:
        config = config_of(bridge)
        url = service.pick_url(_urls_of(bridge), config.tab_pattern)
        payload = config.as_dict()
        payload.update({"matched_url": url, "missing": config.missing(),
                        "ready": config.is_ready and bool(url)})
        return json.dumps(payload, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e), "ready": False})


def save_settings(bridge, payload: str) -> str:
    """Persist the form; unknown keys are ignored rather than written."""
    try:
        values = json.loads(payload or "{}")
        config = getattr(bridge, "config", None)
        known = {k: values[k] for k in service.SETTING_KEYS if k in values}
        if known and config is not None:
            config.set_state(**known)
        bridge._log("🦊 Ui.Vision settings saved", "info")
        return settings_json(bridge)
    except Exception as e:
        return json.dumps({"error": str(e), "ready": False})


def macro_source(bridge) -> str:
    """The macro JSON to import into Ui.Vision (XClick, never Click)."""
    try:
        return json.dumps({"ok": True, "macro": service.demo_macro_json(config_of(bridge))})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


def _outcome_json(outcome, url: str) -> str:
    """A macro outcome as the window's result payload."""
    return json.dumps({"ok": outcome.ok, "state": outcome.state,
                       "message": outcome.message, "url": url,
                       "lines": (outcome.lines or [])[-20:]}, ensure_ascii=False)


async def run_test(bridge) -> None:
    """Launch the demo macro and emit what the Ui.Vision log said."""
    config = config_of(bridge)
    url = service.pick_url(_urls_of(bridge), config.tab_pattern)
    bridge._log(f"🦊 Ui.Vision macro '{config.macro}' → {url or '(no tab match)'}", "info")
    outcome = await service.run_demo(config, url)
    level = "info" if outcome.ok else "warn"
    bridge._log(f"🦊 Ui.Vision {outcome.state}: {outcome.message}", level)
    bridge.uivision_result.emit(_outcome_json(outcome, url))


def start_test(bridge) -> str:
    """Schedule the macro run on the background loop; report the hand-off."""
    config = config_of(bridge)
    gaps = config.missing()
    if gaps:
        return json.dumps({"ok": False, "state": "failed", "message": "; ".join(gaps)})
    schedule_coro(bridge, run_test(bridge))
    return json.dumps({"ok": True, "state": "running", "message": f"macro {config.macro} started"})


class UiVisionMixin:
    """Ui.Vision config (`get/save`), macro source, and the XClick test run."""

    @Slot(result=str)
    def get_uivision_settings(self):
        """Form values + the tab the pattern resolves to, for the first paint."""
        return settings_json(self)

    @Slot(str, result=str)
    def save_uivision_settings(self, payload):
        """Persist the window's form and echo the refreshed state back."""
        return save_settings(self, payload)

    @Slot(result=str)
    def get_uivision_macro(self):
        """The macro JSON the operator imports into the Ui.Vision extension."""
        return macro_source(self)

    @Slot(result=str)
    def run_uivision_test(self):
        """Start the XClick demo; the verdict arrives on `uivision_result`.

        Polling the log can take the whole timeout, so the slot returns as soon
        as the run is scheduled and never blocks the UI thread.
        """
        return start_test(self)
