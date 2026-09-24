"""Firefox-auto panel — the "Firefox auto with Extension" window (I-63).

Owns the 4 slots of the Ui.Vision framework test: read/save the config (one
`firefox_auto` dict in session.json, validated and clamped on both ends,
RULE 13) and run/stop one test (delegated to `app/browser/uivision.runner`,
lazy browser import per panel convention). Every step of a run is logged
(RULE 2) and streamed to the window over `firefox_auto_updated` (RULE 5); the
stop flag is checked between phases and inside the poll (RULE 7).
"""

import json
import logging

from app.services.run_state import schedule_coro
from app.ui.qt_compat import Slot

log = logging.getLogger("arena")

CONFIG_KEY = "firefox_auto"
STORAGE_MODES = ("xfile", "browser")
TIMEOUT_RANGE = (15, 600)
PAUSE_RANGE = (500, 30000)
WAIT_TIMEOUT_RANGE = (10, 300)  # the wait-for-tab timeout when skip_no_match is off
# Retired 2026-09-23: the macro never opens a URL, so "url" is no longer a
# field — validate rebuilds from the defaults, so an old "url" key in
# session.json is dropped instead of riding back in (RULE 10's dead-key
# corollary; pinned by tests/test_firefox_auto_panel.py). Its successor is
# "url_pattern" (2026-09-24): a tab-matching filter, never a page to open.
TEXT_FIELDS = ("pattern", "url_pattern", "target", "home", "binary")
# 2026-09-24: profile selection + skip-no-match — the panel's two new controls
PROFILE_LIST_KEY = "selected_profiles"
SKIP_NO_MATCH_KEY = "skip_no_match"


def _defaults() -> dict:
    """The one source of the default config (session.json's own default dict)."""
    from app.persistence.config_manager import DEFAULT_SESSION
    return dict(DEFAULT_SESSION[CONFIG_KEY])


def _clamp_int(value, bounds, fallback: int) -> int:
    try:
        return max(bounds[0], min(bounds[1], int(value)))
    except Exception:
        return fallback


def validate_config(data) -> dict:
    """Sanitize one config dict: text trimmed, numbers clamped, storage one of two.

    Raises ValueError only where a wrong value would corrupt a file path — the
    macro name (the builder's grammar is the single owner of that rule).
    """
    from app.browser.uivision import macro as uiv_macro
    row = dict(data or {})
    cfg = _defaults()               # rebuild: a retired "url" key dies with the old dict
    for key in TEXT_FIELDS:
        cfg[key] = str(row.get(key, cfg[key]) or "").strip()
    cfg["macro"] = uiv_macro.validate_macro_name(row.get("macro", cfg["macro"]))
    storage = str(row.get("storage", cfg["storage"]) or "").strip().lower()
    cfg["storage"] = storage if storage in STORAGE_MODES else _defaults()["storage"]
    cfg["timeout_sec"] = _clamp_int(row.get("timeout_sec"), TIMEOUT_RANGE, cfg["timeout_sec"])
    cfg["pause_ms"] = _clamp_int(row.get("pause_ms"), PAUSE_RANGE, cfg["pause_ms"])
    cfg[PROFILE_LIST_KEY] = _validate_profiles(row.get(PROFILE_LIST_KEY, cfg[PROFILE_LIST_KEY]))
    cfg[SKIP_NO_MATCH_KEY] = bool(row.get(SKIP_NO_MATCH_KEY, cfg[SKIP_NO_MATCH_KEY]))
    cfg["wait_timeout_sec"] = _clamp_int(row.get("wait_timeout_sec"),
                                         WAIT_TIMEOUT_RANGE, cfg["wait_timeout_sec"])
    return cfg


def _validate_profiles(value) -> list:
    """The profile list: non-blank trimmed strings, deduped, order preserved."""
    if not isinstance(value, list):
        return []
    seen, out = set(), []
    for item in value:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def load_config(bridge) -> dict:
    """The stored dict merged over the defaults — tolerant of old files (RULE 13).

    A stored macro name that cannot be a file name falls back to the default
    instead of breaking the load; every other field heals itself in validate.
    """
    from app.browser.uivision import macro as uiv_macro
    cfg = _defaults()
    try:
        stored = bridge.config.get_state(CONFIG_KEY, {}) or {}
        if isinstance(stored, dict):
            cfg.update({key: stored[key] for key in cfg if key in stored})
    except Exception:
        pass
    try:
        uiv_macro.validate_macro_name(cfg.get("macro", ""))
    except ValueError:
        cfg["macro"] = uiv_macro.DEFAULT_MACRO_NAME
    return validate_config(cfg)


def _config_dir(bridge) -> str:
    """Absolute on purpose: the autorun page rides a file:/// URL (RULE 4)."""
    from pathlib import Path
    return str(Path(getattr(bridge.config, "dir", "config")).expanduser().resolve())


def paths_info(bridge, cfg) -> dict:
    """The files one run touches — the window shows where they live (RULE 4)."""
    from app.browser.uivision import paths as uiv_paths
    config_dir = _config_dir(bridge)
    home = uiv_paths.home(cfg["home"])
    if cfg["storage"] == "xfile":
        macro_file = uiv_paths.macro_file(home, cfg["macro"])
    else:
        macro_file = uiv_paths.runtime_dir(config_dir) / uiv_paths.MACROS_DIR / f"{cfg['macro']}.json"
    return {"home": str(home), "macro_file": str(macro_file),
            "autorun_file": str(uiv_paths.autorun_file(config_dir)),
            "log_dir": str(uiv_paths.logs_dir(config_dir))}


def build_spec(bridge, cfg):
    """The runner's argument object — the validated config plus the app's dirs."""
    from app.browser.uivision.runner import RunSpec
    return RunSpec(pattern=cfg["pattern"], target=cfg["target"],
                   macro=cfg["macro"], storage=cfg["storage"], home=cfg["home"],
                   binary=cfg["binary"], timeout_sec=cfg["timeout_sec"],
                   pause_ms=cfg["pause_ms"], config_dir=_config_dir(bridge),
                   url_pattern=cfg["url_pattern"],
                   selected_profiles=tuple(cfg.get(PROFILE_LIST_KEY, ())),
                   skip_no_match=bool(cfg.get(SKIP_NO_MATCH_KEY, False)),
                   wait_timeout_sec=int(cfg.get("wait_timeout_sec", 60)))


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
    """The 4 slots of the Firefox-auto window: config get/save, test run/stop."""

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
        """List every readable Firefox profile with its open tabs for the UI."""
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
