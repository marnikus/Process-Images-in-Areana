"""One bounded asynchronous recording for a visible captcha encounter."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any, Optional

from .models import RecordingLimits, utc_now
from .network import NetworkCollector
from .probes import drain_probe, install_probe, snapshot_probe, stop_probe
from .sanitize import clean_mapping, redact_text
from .store import RecordingStore


class CaptchaRecorder:
    """Collect DOM checkpoints/diffs and sanitized network lifecycle events."""

    def __init__(self, store: RecordingStore, ctrl: Any, encounter: dict[str, Any],
                 limits: Optional[RecordingLimits] = None):
        self.store = store
        self.ctrl = ctrl
        self.limits = limits or RecordingLimits()
        self.encounter = encounter
        self.manifest = store.create(encounter)
        self.session_id = self.manifest["session_id"]
        self.started = time.monotonic()
        self.active = False
        self._task: Optional[asyncio.Task] = None
        self._last_hash = ""
        self._last_checkpoint = 0.0
        self._counts = {"event": 0, "mutation": 0, "network": 0, "snapshot": 0}
        self._truncated: set[str] = set()
        self.network = NetworkCollector(ctrl.cdp, self._event, self.limits.max_body_chars,
                                        self._truncated.add)

    async def start(self) -> None:
        await self.ctrl.cdp.evaluate(install_probe())
        router = getattr(self.ctrl.cdp, "events", None)
        if router is not None:
            router.add(self.network.on_event)
        self.active = True
        evidence = {key: self.encounter.get(key) for key in (
            "source", "kind", "integration", "invisible", "anchor", "challenge",
            "response_fields", "sitekey_source", "page_identity")}
        await self._event("state", {"state": "detected", "evidence": evidence})
        await self._checkpoint("detected", force=True)
        self._task = asyncio.create_task(self._run())

    async def finish(self, outcome: Any,
                     report: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self.active = False
        if self._task is not None:
            await self._join_worker()
        await self._drain_mutations()
        await self.network.drain()
        await self._checkpoint("resolved", force=True)
        if report:
            await self._event("solve_report", _semantic_report(report))
        await self._event("state", self._outcome_payload(outcome))
        await self.ctrl.cdp.evaluate(stop_probe())
        self._detach_listener()
        updates = _finish_updates(outcome, self.started, self._counts, self._truncated)
        return self.store.finish(self.session_id, updates)

    async def note_outcome(self, phase: str, outcome: Any) -> None:
        payload = self._outcome_payload(outcome)
        payload.update({"state": phase, "token_at_ms": round(getattr(outcome, "token_sec", 0) * 1000),
                        "dialog_at_token": getattr(outcome, "dialog_at_token", ""),
                        "inject": getattr(outcome, "inject", "")})
        await self._event("state", payload)

    async def abort(self, reason: str) -> None:
        class Interrupted:
            status = "interrupted"
            method = ""

            def __init__(self, message: str):
                self.reason = message
        await self.finish(Interrupted(reason))

    async def _run(self) -> None:
        while self.active:
            await self._drain_mutations()
            await self.network.drain()
            await asyncio.sleep(self.limits.poll_interval_sec)

    async def _join_worker(self) -> None:
        try:
            await asyncio.wait_for(self._task, timeout=self.limits.poll_interval_sec + 1.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._task.cancel()

    async def _drain_mutations(self) -> None:
        result = await self.ctrl.cdp.evaluate(drain_probe())
        data = self._as_dict(result)
        changes = data.get("changes") if data.get("ok") else []
        if changes:
            clean = clean_mapping(changes)
            self._counts["mutation"] += len(clean)
            await self._event("mutation", {"changes": clean, "dropped": data.get("dropped", 0)})
            await self._checkpoint("mutation")
        if data.get("dropped"):
            self._truncated.add("mutations")

    async def _checkpoint(self, reason: str, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_checkpoint < self.limits.checkpoint_interval_sec:
            return
        if self._counts["snapshot"] >= self.limits.max_snapshots:
            self._truncated.add("snapshots")
            return
        data = self._as_dict(await self.ctrl.cdp.evaluate(snapshot_probe()))
        if not data.get("ok"):
            return
        html = redact_text(data.get("html", ""), self.limits.max_snapshot_chars)
        digest = hashlib.sha256(html.encode("utf-8")).hexdigest()
        if digest == self._last_hash and not force:
            return
        data.update({"html": html, "sha256": digest, "reason": reason, "at": utc_now(),
                     "offset_ms": round((now - self.started) * 1000)})
        self.store.write_snapshot(self.session_id, self._counts["snapshot"], clean_mapping(data))
        self._counts["snapshot"] += 1
        self._last_hash, self._last_checkpoint = digest, now

    async def _event(self, kind: str, payload: dict[str, Any], network: bool = False) -> None:
        if self._counts["event"] >= self.limits.max_events:
            self._truncated.add("events")
            return
        event = {"seq": self._counts["event"], "at": utc_now(),
                 "offset_ms": round((time.monotonic() - self.started) * 1000),
                 "kind": kind, **clean_mapping(payload)}
        self.store.append_event(self.session_id, event)
        self._counts["event"] += 1
        if network:
            self._counts["network"] += 1

    def _detach_listener(self) -> None:
        router = getattr(self.ctrl.cdp, "events", None)
        if router is not None:
            router.remove(self.network.on_event)

    def _finish_updates(self, outcome: Any) -> dict[str, Any]:
        return {"status": str(getattr(outcome, "status", "interrupted")),
                "outcome": str(getattr(outcome, "status", "interrupted")),
                "reason": redact_text(getattr(outcome, "reason", ""), 500),
                "method": str(getattr(outcome, "method", "")),
                "task_id": str(getattr(outcome, "task_id", "")),
                "polls": int(getattr(outcome, "polls", 0)),
                "attempts": int(getattr(outcome, "attempts", 1)),
                "elapsed_ms": round((time.monotonic() - self.started) * 1000),
                "event_count": self._counts["event"],
                "mutation_count": self._counts["mutation"],
                "network_count": self._counts["network"],
                "snapshot_count": self._counts["snapshot"],
                "truncated": sorted(self._truncated)}

    @staticmethod
    def _outcome_payload(outcome: Any) -> dict[str, Any]:
        return {"state": "recording_finished", "outcome": getattr(outcome, "status", "interrupted"),
                "method": getattr(outcome, "method", ""),
                "reason": redact_text(getattr(outcome, "reason", ""), 500)}

    @staticmethod
    def _as_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        try:
            data = json.loads(value) if isinstance(value, str) else {}
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


def _finish_updates(outcome: Any, started: float, counts: dict[str, int],
                    truncated: set[str]) -> dict[str, Any]:
    status = str(getattr(outcome, "status", "interrupted"))
    return {"status": status, "outcome": status,
            "reason": redact_text(getattr(outcome, "reason", ""), 500),
            "method": str(getattr(outcome, "method", "")),
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "event_count": counts["event"], "mutation_count": counts["mutation"],
            "network_count": counts["network"], "snapshot_count": counts["snapshot"],
            "truncated": sorted(truncated)}


def _semantic_report(report: dict[str, Any]) -> dict[str, Any]:
    """Keep diagnostic milestones while excluding raw/public token identifiers."""
    keys = ("status", "reason", "method", "task_type", "polls", "detect_to_solve_s",
            "dialog_at_token", "inject", "page_error", "acceptance", "stale",
            "solve_total_s", "integration", "anchor", "challenge", "sitekey_source",
            "page_identity", "invisible")
    payload = {key: report.get(key) for key in keys}
    payload["field_evidence"] = report.get("response_fields")
    token = report.get("token")
    payload["solution_ready_at_s"] = token.get("at_s") if isinstance(token, dict) else None
    return payload
