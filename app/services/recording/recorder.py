"""RecordingService — lifecycle of per-tab captcha session recordings.

Starts AFTER the captcha is confirmed ON, stops when the solve edge is
known (success, error, or stop). Fail-open end to end (RULE 9): a broken
probe or store never disturbs the captcha flow. UI payloads live in
payloads.py; CDP probe I/O lives in proberun.py (RULE 18 sizes).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from . import proberun
from .sanitizer import bound_str
from .session import OUTCOMES, RecordingSession
from .store import RecordingStore


class RecordingService:
    """Owns active per-tab sessions + the on-disk store."""

    def __init__(self, root: str, log=None):
        self.store = RecordingStore(root)
        self._log = log or (lambda msg, level="info": None)
        self._active: Dict[str, RecordingSession] = {}
        self._enabled = self._load_enabled()

    # ---- settings -----------------------------------------------------

    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, on: bool) -> None:
        self._enabled = bool(on)
        self._save_enabled()

    # ---- lifecycle ----------------------------------------------------

    async def start(self, ctrl: Any, tab_id: str, detect: Dict[str, str]) -> Optional[RecordingSession]:
        """Open a session (detect = url/trigger/kind/sitekey from the probe)."""
        if not self._enabled or str(tab_id) in self._active:
            return self._active.get(str(tab_id))
        session = RecordingSession.create(tab_id, detect)
        html = await proberun.snapshot_html(ctrl)
        if not self.store.create(session, html):
            self._log(f"🎬 recording start failed for tab {str(tab_id)[:12]} (dir busy?)", "warn")
            return None
        self._active[str(tab_id)] = session
        await self._install(ctrl)
        self.store.append_event(session, "state",
                                {"note": f"detected via {detect.get('trigger', '')}",
                                 "url": bound_str(str(detect.get("url") or ""), 300),
                                 "detect_kind": str(detect.get("kind") or "")})
        self._log(f"🎬 recording started {session.id} (tab {str(tab_id)[:12]})", "info")
        return session

    async def edge(self, ctrl: Any, tab_id: str, note: str, snapshot: bool = False) -> None:
        """Flush buffers + state marker; optionally a full snapshot."""
        session = self._active.get(str(tab_id))
        if session is None:
            return
        await proberun.flush_into(ctrl, self.store, session)
        self.store.append_event(session, "state", {"note": bound_str(note, 120)})
        if snapshot:
            await self.snapshot(ctrl, tab_id, note)

    async def snapshot(self, ctrl: Any, tab_id: str, note: str) -> None:
        session = self._active.get(str(tab_id))
        if session is None:
            return
        html = await proberun.snapshot_html(ctrl)
        if html:
            self.store.add_snapshot(session, html)
            self._log(f"🎬 snapshot #{session.counters.get('snapshots', 0) - 1} ({note})", "info")

    def stop(self, tab_id: str, outcome: str, method: str = "") -> None:
        session = self._active.pop(str(tab_id), None)
        if session is None:
            return
        session.finalize(outcome if outcome in OUTCOMES else "none", method)
        self.store.finalize(session)
        self._log(f"🎬 recording stopped {session.id} outcome={session.outcome} "
                  f"events={session.counters.get('events', 0)}", "info")

    # ---- probe install (fail-open) ------------------------------------

    async def _install(self, ctrl: Any) -> None:
        err = await proberun.install(ctrl)
        if err:
            self._log(f"🎬 recorder probe install skipped: {err}", "warn")

    # ---- enabled flag persistence --------------------------------------

    def _cfg_path(self) -> Path:
        return self.store.root / "settings.json"

    def _load_enabled(self) -> bool:
        try:
            data = json.loads(self._cfg_path().read_text(encoding="utf-8"))
            return bool(data.get("enabled", True)) if isinstance(data, dict) else True
        except Exception:
            return True  # default ON

    def _save_enabled(self) -> None:
        try:
            self.store.root.mkdir(parents=True, exist_ok=True)
            (self._cfg_path()).write_text(json.dumps({"enabled": self._enabled}),
                                          encoding="utf-8")
        except Exception as e:
            self._log(f"🎬 recording settings not saved: {e}", "warn")
