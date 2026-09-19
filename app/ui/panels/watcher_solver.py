"""Watcher solver slots — the Captcha Watcher (SDK solver) lifecycle + key.

Second Watcher mixin (RULE 16: ≤15 methods per class — the passive-watcher
mixin already owns 10 slots). Owns the ONLY UI entry points to the captcha
solver:

    watcher_start / watcher_stop / watcher_status   — the solve loop
    set_captcha_api_key / get_captcha_api_key       — config/2captcha.json (0600, masked)
    captcha_balance                                  — one-shot SDK balance

Wiring rules:
* the loop runs on the bridge's bg loop via `schedule_coro` (never
  `asyncio.create_task` from the Qt thread);
* tabs come from the page pool (app-owned pages only — RULE 20) and JS is
  evaluated through the pool's per-tab CDP client;
* the Watcher window's ON/OFF (`start_watcher`/`stop_watcher`) calls
  `solver_start`/`solver_stop` so one switch controls solving;
* the raw key never crosses the WebChannel — only the masked form.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.services.run_state import schedule_coro
from app.ui.qt_compat import Slot

KEY_MIN_LEN = 16


def key_store(bridge):
    """Single owner of config/2captcha.json (shared with the legacy status slot)."""
    from app.services.captcha.key_store import CaptchaKeyStore
    return CaptchaKeyStore(str(bridge.config.dir))


def load_api_key(bridge) -> str:
    try:
        return key_store(bridge).load().api_key
    except Exception:
        return ""


def save_api_key(bridge, key: str) -> Dict[str, Any]:
    """Persist the key (empty clears it); keeps the other stored fields."""
    from app.services.captcha.key_store import CaptchaKeyStore, CaptchaSettings
    store = key_store(bridge)
    current = store.load()
    key = (key or "").strip()
    if key and len(key) < KEY_MIN_LEN:
        return {"ok": False, "error": f"key too short (<{KEY_MIN_LEN} chars)"}
    store.save(CaptchaSettings(enabled=False, api_key=key,
                               solve_timeout_sec=current.solve_timeout_sec))
    return {"ok": True, "has_key": bool(key), "masked_key": CaptchaKeyStore.mask(key)}


def make_solver(bridge):
    """Fresh SdkSolver bound to the stored key (None when no key)."""
    from app.services.captcha_watcher import SdkSolver
    key = load_api_key(bridge)
    if not key:
        return None
    timeout = key_store(bridge).load().solve_timeout_sec
    return SdkSolver(key, timeout_sec=timeout)


def pool_tabs(bridge) -> List[Dict[str, str]]:
    """Connected pool pages as [{id, url}] — the only tabs the Watcher may touch."""
    pool = getattr(bridge, "_page_pool", None)
    if pool is None:
        return []
    try:
        pages = pool.status_snapshot().get("pages", [])
    except Exception:
        return []
    return [{"id": str(p.get("tab_id") or ""), "url": str(p.get("url") or "")}
            for p in pages if p.get("tab_id") and p.get("is_connected", True)]


def _client_for(bridge, tab_id: str):
    pool = getattr(bridge, "_page_pool", None)
    client = pool.get_clients(tab_id)[0] if pool is not None else None
    if client is not None:
        return client
    cdp = getattr(bridge, "cdp", None)
    if cdp is not None and getattr(cdp, "_current_tab_id", "") == tab_id:
        return cdp
    return None


async def evaluate_on_tab(bridge, tab_id: str, js: str) -> Any:
    """Runtime.evaluate on the pool client of `tab_id` (None when unattached)."""
    client = _client_for(bridge, tab_id)
    if client is None or not getattr(client, "is_connected", False):
        return None
    return await client.evaluate(js)


def on_solver_status(bridge, payload: Dict[str, Any]) -> None:
    """Watcher → UI (signal is optional: tests build bare bridges)."""
    sig = getattr(bridge, "captcha_watcher_status", None)
    if sig is None:
        return
    try:
        sig.emit(json.dumps(payload, ensure_ascii=False))
    except Exception:
        pass


def captcha_watcher(bridge):
    """Lazy per-bridge CaptchaWatcher (cached as bridge._captcha_watcher)."""
    watcher = getattr(bridge, "_captcha_watcher", None)
    if watcher is not None:
        return watcher
    from app.services.captcha_watcher import CaptchaWatcher, WatcherDeps
    deps = WatcherDeps(
        tabs=lambda: pool_tabs(bridge),
        evaluate=lambda tab_id, js: evaluate_on_tab(bridge, tab_id, js),
        solver_factory=lambda: make_solver(bridge),
        log=lambda m, l="info": bridge._log(m, l),
        on_status=lambda p: on_solver_status(bridge, p),
    )
    watcher = bridge._captcha_watcher = CaptchaWatcher(deps)
    return watcher


def solver_start(bridge) -> Dict[str, Any]:
    """Schedule the solve loop on the bg loop (idempotent)."""
    watcher = captcha_watcher(bridge)
    if watcher.running:
        return {"ok": True, "running": True, "note": "already running"}
    if not load_api_key(bridge):
        bridge._log("🛡️ Captcha Watcher: no 2Captcha key — the app will NOT solve captchas "
                    "(set a key in the Captcha window)", "warn")
        return {"ok": False, "running": False, "error": "no api key"}
    schedule_coro(bridge, watcher.run_forever())
    return {"ok": True, "running": True}


def solver_stop(bridge) -> Dict[str, Any]:
    watcher = getattr(bridge, "_captcha_watcher", None)
    if watcher is None:
        return {"ok": True, "running": False}
    watcher.stop()
    return {"ok": True, "running": False}


def solver_follow(bridge, enabled: bool) -> Optional[Dict[str, Any]]:
    """Keep the solver in step with the Watcher switch; never raises."""
    try:
        return solver_start(bridge) if enabled else solver_stop(bridge)
    except Exception as e:
        try:
            bridge._log(f"Captcha Watcher follow failed: {e}", "warn")
        except Exception:
            pass
        return None


async def _balance_job(bridge) -> None:
    solver = make_solver(bridge)
    balance = await solver.balance() if solver is not None else None
    watcher = captcha_watcher(bridge)
    watcher._status.balance = balance
    if balance is None:
        bridge._log("2Captcha balance: unavailable (no key, SDK missing or API error)", "warn")
    else:
        bridge._log(f"2Captcha balance ${balance:.2f}", "info")
    on_solver_status(bridge, watcher.status())


class WatcherSolverMixin:
    """Captcha Watcher (SDK solver) slots — see module docstring."""

    @Slot(result=str)
    def watcher_start(self):
        try:
            return json.dumps(solver_start(self))
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def watcher_stop(self):
        try:
            return json.dumps(solver_stop(self))
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def watcher_status(self):
        try:
            return json.dumps({"ok": True, **captcha_watcher(self).status()}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def set_captcha_api_key(self, key: str):
        """Store the key locally (masked reply); never logs the raw key."""
        try:
            result = save_api_key(self, key)
            if result.get("ok"):
                self._log(f"🔐 2Captcha key {'saved' if result['has_key'] else 'cleared'} "
                          f"({result['masked_key'] or 'empty'})", "success")
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def get_captcha_api_key(self):
        try:
            from app.services.captcha.key_store import CaptchaKeyStore
            key = load_api_key(self)
            return json.dumps({"ok": True, "has_key": bool(key),
                               "masked_key": CaptchaKeyStore.mask(key)})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def captcha_balance(self):
        """Fire-and-forget balance fetch; result lands in watcher_status().balance."""
        try:
            if not load_api_key(self):
                return json.dumps({"ok": False, "error": "no api key"})
            schedule_coro(self, _balance_job(self))
            return json.dumps({"ok": True, "pending": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})
