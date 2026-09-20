"""Watcher solver slots — the Captcha Watcher (SDK solver) lifecycle + key.

Second Watcher mixin (RULE 16: ≤15 methods per class — the passive-watcher
mixin already owns 10 slots). Owns the ONLY UI entry points to the captcha
solver:

    watcher_start / watcher_stop / watcher_status   — the solve loop
    set_captcha_api_key / get_captcha_api_key       — config/captcha_solvers.json (0600, masked)
    set_captcha_provider                             — active provider (2captcha | capmonster), B10
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
    """Single owner of config/captcha_solvers.json (shared with the legacy status slot)."""
    from app.services.captcha.key_store import CaptchaKeyStore
    return CaptchaKeyStore(str(bridge.config.dir))


def load_settings(bridge):
    """Stored solver settings (defaults when the file is missing/corrupt)."""
    from app.services.captcha.key_store import CaptchaSettings
    try:
        return key_store(bridge).load()
    except Exception:
        return CaptchaSettings()


def load_api_key(bridge) -> str:
    """Key of the ACTIVE provider ('' when none)."""
    return load_settings(bridge).api_key


def key_reply(settings) -> Dict[str, Any]:
    """UI payload: active provider + per-provider masked keys (raw keys never leave)."""
    from app.services.captcha.key_store import CaptchaKeyStore
    from app.services.captcha_watcher.providers import provider_label, providers_summary
    key = settings.api_key
    providers = []
    for p in providers_summary():
        k = settings.key_for(p["id"])
        providers.append({**p, "has_key": bool(k), "masked_key": CaptchaKeyStore.mask(k)})
    return {"ok": True, "has_key": bool(key), "masked_key": CaptchaKeyStore.mask(key),
            "provider": settings.provider, "provider_label": provider_label(settings.provider),
            "providers": providers}


def save_api_key(bridge, key: str) -> Dict[str, Any]:
    """Persist the ACTIVE provider's key (empty clears it); other providers untouched."""
    store = key_store(bridge)
    current = store.load()
    key = (key or "").strip()
    if key and len(key) < KEY_MIN_LEN:
        return {"ok": False, "error": f"key too short (<{KEY_MIN_LEN} chars)"}
    updated = current.with_key(current.provider, key)
    updated.enabled = False
    store.save(updated)
    return key_reply(updated)


def save_provider(bridge, provider: str) -> Dict[str, Any]:
    """Switch the active provider (keys stay per provider)."""
    from app.services.captcha_watcher.providers import PROVIDERS
    pid = str(provider or "").strip().lower()
    if pid not in PROVIDERS:
        return {"ok": False, "error": f"unknown provider '{provider}' (known: {', '.join(PROVIDERS)})"}
    store = key_store(bridge)
    updated = store.load().with_provider(pid)
    updated.enabled = False
    store.save(updated)
    return key_reply(updated)


def make_solver(bridge):
    """Fresh SdkSolver bound to the active provider + its stored key (None when no key)."""
    from app.services.captcha_watcher import SdkSolver
    settings = load_settings(bridge)
    if not settings.api_key:
        return None
    return SdkSolver(settings.api_key, timeout_sec=settings.solve_timeout_sec,
                     provider=settings.provider)


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


def push_solver_status(bridge) -> None:
    """Re-emit the Watcher status (provider label/key state) when a watcher exists."""
    watcher = getattr(bridge, "_captcha_watcher", None)
    if watcher is not None:
        on_solver_status(bridge, watcher.status())


def solver_start(bridge) -> Dict[str, Any]:
    """Schedule the solve loop on the bg loop (idempotent)."""
    watcher = captcha_watcher(bridge)
    if watcher.running:
        return {"ok": True, "running": True, "note": "already running"}
    settings = load_settings(bridge)
    if not settings.api_key:
        from app.services.captcha_watcher.providers import provider_label
        bridge._log(f"🛡️ Captcha Watcher: no {provider_label(settings.provider)} key — the app will "
                    "NOT solve captchas (set a key in the Captcha window)", "warn")
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
    label = solver.provider_label if solver is not None else "solver"
    balance = await solver.balance() if solver is not None else None
    watcher = captcha_watcher(bridge)
    watcher._status.balance = balance
    if balance is None:
        bridge._log(f"{label} balance: unavailable (no key, SDK missing or API error)", "warn")
    else:
        bridge._log(f"{label} balance ${balance:.2f}", "info")
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
        """Store the ACTIVE provider's key locally (masked reply); never logs the raw key."""
        try:
            result = save_api_key(self, key)
            if result.get("ok"):
                self._log(f"🔐 {result['provider_label']} key {'saved' if result['has_key'] else 'cleared'} "
                          f"({result['masked_key'] or 'empty'})", "success")
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def set_captcha_provider(self, provider: str):
        """Switch the solving provider (2captcha | capmonster); each keeps its own key (B10)."""
        try:
            result = save_provider(self, provider)
            if result.get("ok"):
                self._log(f"🛡️ Captcha provider: {result['provider_label']} "
                          f"({'key set' if result['has_key'] else 'no key yet'})", "info")
                push_solver_status(self)
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def get_captcha_api_key(self):
        """Active provider + per-provider masked keys (raw keys never cross the channel)."""
        try:
            return json.dumps(key_reply(load_settings(self)))
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
