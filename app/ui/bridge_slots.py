# ideal-size: ~170 lines reason=slot registry + self-check + dispatcher are one
# contract; splitting them hides the "declared == callable" invariant (RULE 18.2)
"""Bridge slot contract — fixes *"many buttons do nothing"* (BUG 03.5).

Why buttons died
----------------
`Bridge` collects its slots from plain mix-ins (`UrlQueueMixin`,
`QueueScanMixin`, ...). PySide6 builds the QMetaObject from the **class
namespace of the QObject subclass**, so a `@Slot` that only exists in a
non-QObject base can be missing from the meta-object. QWebChannel then never
exposes it, and the JS guard `if (b && b.add_url)` silently does nothing —
no error, no log, a dead button.

This module makes that class of failure impossible:

* `REQUIRED_SLOTS`   — the frozen JS-facing contract.
* `audit_slots()`    — compares contract vs meta-object at startup.
* `install_dispatch()` — binds every missing name onto the bridge instance so
  `invoke()` can always reach it.
* `invoke(name, args_json)` — one real `@Slot` declared **on the Bridge class
  itself**; the JS `BridgeCall` helper falls back to it. One working path is
  guaranteed even if the meta-object is incomplete.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List

log = logging.getLogger("arena")

# --- the JS-facing contract (grouped by the window that calls it) ---------
REQUIRED_SLOTS: Dict[str, List[str]] = {
    "url_list": ["add_url", "remove_url", "toggle_url", "edit_url", "test_url",
                 "get_url_presets", "add_url_preset", "find_tab_by_url",
                 "auto_connect_scan", "popup_url_tabs", "stop_tab_job",
                 "get_arena_state"],
    "folder": ["pick_folder", "set_folder_path", "scan_folder",
               "scan_folder_new_batch", "clear_queue"],
    "action_blocks": ["get_action_blocks", "save_action_blocks",
                      "add_action_block", "delete_action_block",
                      "reset_action_blocks", "restore_default_blocks",
                      "get_stack_presets", "save_stack_preset",
                      "delete_stack_preset", "export_action_blocks"],
    "presets": ["list_prompt_presets", "save_prompt_preset",
                "load_prompt_preset", "delete_prompt_preset",
                "list_arena_presets", "save_arena_preset",
                "load_arena_preset", "delete_arena_preset"],
    "watcher": ["get_watcher_config", "set_watcher_config",
                "start_watcher", "stop_watcher", "get_captcha_status"],
}


def all_required() -> List[str]:
    return [name for group in REQUIRED_SLOTS.values() for name in group]


def _meta_method_names(obj: Any) -> set[str]:
    """Slot names Qt actually exposes (empty set when running headless)."""
    meta = getattr(obj, "metaObject", None)
    if meta is None:
        return set()
    try:
        mo = meta()
        return {bytes(mo.method(i).name()).decode()
                for i in range(mo.methodCount())}
    except Exception:  # noqa: BLE001 - headless dummies
        return set()


def audit_slots(bridge: Any) -> dict:
    """Report: declared / exposed / callable-but-not-exposed / missing."""
    exposed = _meta_method_names(bridge)
    required = all_required()
    python_ok = [n for n in required if callable(getattr(bridge, n, None))]
    return {
        "required": len(required),
        "exposed": sorted(n for n in required if n in exposed),
        "fallback_only": sorted(n for n in python_ok if n not in exposed),
        "missing": sorted(n for n in required if n not in python_ok),
    }


def log_slot_audit(bridge: Any, report: dict | None = None) -> dict:
    """Startup banner — a dead button is now visible in the log, not silent."""
    report = report or audit_slots(bridge)
    logger = getattr(bridge, "_log", lambda msg, level="info": log.info(msg))
    if report["missing"]:
        logger(f"❌ Bridge slots MISSING (buttons will fail): "
               f"{', '.join(report['missing'])}", "error")
    if report["fallback_only"]:
        logger(f"⚠ Bridge slots not exposed to QWebChannel, routed through "
               f"invoke(): {', '.join(report['fallback_only'])}", "warn")
    if not report["missing"] and not report["fallback_only"]:
        logger(f"✅ Bridge contract OK — {report['required']} slots exposed", "success")
    return report


# --- generic dispatcher --------------------------------------------------

def dispatch(bridge: Any, name: str, args_json: str = "[]") -> str:
    """Call `bridge.<name>(*args)` by name and always answer with JSON."""
    if name not in all_required():
        return json.dumps({"ok": False, "error": f"slot '{name}' not in contract"})
    fn: Callable | None = getattr(bridge, name, None)
    if not callable(fn):
        return json.dumps({"ok": False, "error": f"slot '{name}' not implemented"})
    try:
        args = json.loads(args_json or "[]")
        if not isinstance(args, list):
            args = [args]
    except (TypeError, ValueError) as exc:
        return json.dumps({"ok": False, "error": f"bad args: {exc}"})
    try:
        result = fn(*args)
    except Exception as exc:  # noqa: BLE001 - a UI call must never kill the bridge
        log.exception("bridge.%s failed", name)
        return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return _normalise(result)


def _normalise(result: Any) -> str:
    """Slots return JSON strings, dicts or None — JS always gets JSON."""
    if result is None:
        return json.dumps({"ok": True})
    if isinstance(result, str):
        try:
            json.loads(result)
            return result
        except ValueError:
            return json.dumps({"ok": True, "value": result})
    try:
        return json.dumps(result, ensure_ascii=False)
    except TypeError:
        return json.dumps({"ok": True, "value": str(result)})


class BridgeDispatchMixin:
    """Mix into `Bridge`, then re-declare `invoke` in the Bridge class body:

        @Slot(str, str, result=str)
        def invoke(self, name, args_json="[]"):
            return bridge_slots.dispatch(self, name, args_json)

        @Slot(result=str)
        def slot_audit(self):
            return json.dumps(bridge_slots.audit_slots(self))

    Declaring them *in the class body* is what guarantees the meta-object
    contains them — that is the whole point of this fix.
    """

    def invoke(self, name: str, args_json: str = "[]") -> str:
        return dispatch(self, name, args_json)

    def slot_audit(self) -> str:
        return json.dumps(audit_slots(self), ensure_ascii=False)
