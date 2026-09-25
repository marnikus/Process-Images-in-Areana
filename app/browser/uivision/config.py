"""The Firefox-auto configuration — one validation, one spec builder (2026-09-25).

Moved here from `app/ui/panels/firefox_auto.py` so the live dispatch lane
(`app/services/firefox_lane.py`) can build the SAME validated `RunSpec` the
window saves — services may import `browser`, never `ui` (layer rule). The
panel re-exports every name (its tests keep importing `fa.…`), and
`firefox_lane` reads `inter_run_delay_sec` as the machine-wide gap between
pool jobs (owner's user-defined 3 s delay; one control, RULE 10).

Imports: `persistence` defaults + sibling uivision modules only — duck-typed
`bridge.config`, no Qt.
"""

from __future__ import annotations

CONFIG_KEY = "firefox_auto"
STORAGE_MODES = ("xfile", "browser")
TIMEOUT_RANGE = (15, 600)
PAUSE_RANGE = (500, 30000)
WAIT_TIMEOUT_RANGE = (10, 300)  # the wait-for-tab timeout when skip_no_match is off
INTER_RUN_DELAY_RANGE = (0, 30)  # seconds between runs (0 = no delay)
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
    cfg["inter_run_delay_sec"] = _clamp_int(row.get("inter_run_delay_sec"),
                                            INTER_RUN_DELAY_RANGE, cfg["inter_run_delay_sec"])
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
                   wait_timeout_sec=int(cfg.get("wait_timeout_sec", 60)),
                   inter_run_delay_sec=int(cfg.get("inter_run_delay_sec", 3)))


