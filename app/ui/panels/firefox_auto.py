"""Firefox-auto panel — the "Firefox auto with Extension" window (I-63).

Owns the 4 slots of the Ui.Vision framework test: read/save the config and
run/stop one test (delegated to `app/browser/uivision.runner`, lazy browser
import per panel convention). Every step of a run is logged (RULE 2) and
streamed to the window over `firefox_auto_updated` (RULE 5); the stop flag
is checked between phases and inside the poll (RULE 7).

The config helpers themselves moved to `app/services/firefox_config.py`
(2026-09-25, design D-6) so the pool's Firefox job lane can build the same
`RunSpec` without services importing this panel — the names are re-exported
here, so slots, tests and the frozen 141-slot surface are untouched.
"""

import json
import logging

from app.services.firefox_config import (  # noqa: F401 — re-exported API (D-6)
    CONFIG_KEY,
    PROFILE_LIST_KEY,
    SKIP_NO_MATCH_KEY,
    STORAGE_MODES,
    TEXT_FIELDS,
    build_spec,
    load_config,
    paths_info,
    validate_config,
)
from app.services.run_state import schedule_coro
from app.ui.qt_compat import Slot

log = logging.getLogger("arena")


def emit_status(bridge, payload: dict) -> None:
    """One JSON status to the window (best effort — the log line already happened)."""
    try:
        bridge.firefox_auto_updated.emit(json.dumps(payload, ensure_ascii=False))
    except Exception:
        pass


def _reporter(bridge):
    """The runner's report callback: log line (RULE 2) + status stream (RULE 5)."""
    def report(step: str, message: str, level: str = "info") -> None:
        bridge._log(f"🦊 {step}: {message}", level)
        emit_status(bridge, {"kind": "step", "step": step, "message": message, "level": level})
    return report


def _defaults() -> dict:
    """Defaults for the error payloads (the config module owns the source)."""
    return validate_config({})


async def do_run_test(bridge) -> None:
    """One framework test end to end; the window sees every step and the verdict."""
    from app.browser.uivision.runner import RunSeams, run_test
    try:
        cfg = load_config(bridge)
        spec = build_spec(bridge, cfg)
        bridge._firefox_auto_stop = False
        report = _reporter(bridge)
        search = f"title “{cfg['pattern']}” + URL “{cfg['url_pattern']}”"
        report("run", f"framework test — macro {cfg['macro']}, search {search}, "
                      f"target {cfg['target'][:60]}")
        seams = RunSeams(stop=lambda: bool(getattr(bridge, "_firefox_auto_stop", False)))
        result = await run_test(spec, report, seams)
        emit_status(bridge, {"kind": "result", "result": result.kind, "message": result.message,
                             "lines": list(result.lines),
                             "steps": [list(step) for step in result.steps]})
    except Exception as e:
        bridge._log(f"🦊 Firefox-auto run failed: {e}", "error")
        emit_status(bridge, {"kind": "result", "result": "blocked", "message": str(e)})
    finally:
        bridge._firefox_auto_running = False


class FirefoxAutoMixin:
    """The slots of the Firefox-auto window: config get/save, test run/stop, profiles."""

    @Slot(result=str)
    def get_firefox_auto_config(self):
        """Config + file paths + running flag for the window's paint/restore."""
        try:
            cfg = load_config(self)
            return json.dumps({"ok": True, "config": cfg, "paths": paths_info(self, cfg),
                               "running": bool(getattr(self, "_firefox_auto_running", False))},
                              ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e), "config": _defaults(),
                               "running": False}, ensure_ascii=False)

    @Slot(str, result=str)
    def save_firefox_auto_config(self, config_json: str):
        """Validate → persist → say what was saved (a bad macro name is refused by name)."""
        try:
            data = json.loads(config_json or "{}")
        except Exception as e:
            return json.dumps({"ok": False, "error": f"unreadable JSON: {e}"})
        try:
            cfg = validate_config(data)
        except ValueError as e:
            self._log(f"🦊 config refused: {e}", "warn")
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
        self.config.set_state(**{CONFIG_KEY: cfg})
        paths = paths_info(self, cfg)
        self._log(f"🦊 Firefox-auto config saved — pattern “{cfg['pattern']}”, macro {cfg['macro']}, "
                  f"storage {cfg['storage']}", "success")
        emit_status(self, {"kind": "saved", "config": cfg, "paths": paths})
        return json.dumps({"ok": True, "config": cfg, "paths": paths}, ensure_ascii=False)

    @Slot(result=str)
    def run_firefox_auto_test(self):
        """Start one run (non-blocking); a second run while one is live is refused."""
        if getattr(self, "_firefox_auto_running", False):
            return json.dumps({"ok": False, "error": "a test run is already in progress"})
        self._firefox_auto_running = True
        self._firefox_auto_stop = False
        emit_status(self, {"kind": "running"})
        schedule_coro(self, do_run_test(self))
        return json.dumps({"ok": True, "state": "running"})

    @Slot(result=str)
    def stop_firefox_auto_test(self):
        """Set the stop flag — the runner honours it on its next phase/poll check."""
        if not getattr(self, "_firefox_auto_running", False):
            return json.dumps({"ok": False, "error": "no run in progress"})
        self._firefox_auto_stop = True
        self._log("🦊 stop requested — the run ends on its next check", "warn")
        return json.dumps({"ok": True, "state": "stopping"})

    @Slot(result=str)
    def show_firefox_profiles(self):
        """List every OPEN Firefox profile (the lock probe decides — bug #4)."""
        try:
            from app.browser.uivision import profiles as uiv_profiles
            rows = uiv_profiles.list_profiles()
            cfg = load_config(self)
            selected = cfg.get(PROFILE_LIST_KEY, [])
            return json.dumps({"ok": True, "profiles": rows,
                               "selected": selected,
                               "skip_no_match": cfg.get(SKIP_NO_MATCH_KEY, False)},
                              ensure_ascii=False)
        except Exception as e:
            self._log(f"🦊 profile list failed: {e}", "error")
            return json.dumps({"ok": False, "error": str(e),
                               "profiles": [], "selected": []}, ensure_ascii=False)
