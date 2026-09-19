"""One bounded asynchronous recording for a visible captcha encounter."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any, Optional

from .milestones import MILESTONE_PHASES, build_milestone
from .models import RecordingLimits, utc_now
from .network import NetworkCollector
from .probes import drain_probe, install_probe, snapshot_probe, stop_probe
from .sanitize import clean_mapping, redact_text
from .store import RecordingStore


async def drain_mutations(rec: "CaptchaRecorder") -> None:
    """Drain the page-side queue into one mutation event (+ truncation flag)."""
    data = as_dict(await rec.ctrl.cdp.evaluate(drain_probe()))
    changes = data.get("changes") if data.get("ok") else []
    if changes:
        clean = clean_mapping(changes)
        rec._counts["mutation"] += len(clean)
        await rec._event("mutation", {"changes": clean, "dropped": data.get("dropped", 0)})
        await rec._checkpoint("mutation")
    if data.get("dropped"):
        rec._truncated.add("mutations")


def checkpoint_gate(rec: "CaptchaRecorder", force: bool) -> str:
    """Why a checkpoint is skipped: 'interval', 'cap', or '' when it may run."""
    if not force and time.monotonic() - rec._last_checkpoint < rec.limits.checkpoint_interval_sec:
        return "interval"
    if rec._counts["snapshot"] >= rec.limits.max_snapshots:
        rec._truncated.add("snapshots")
        return "cap"
    return ""


async def write_checkpoint(rec: "CaptchaRecorder", reason: str, force: bool = False) -> None:
    """Snapshot the DOM when due and the digest moved (bounded, hash-deduped)."""
    if checkpoint_gate(rec, force):
        return
    now = time.monotonic()
    data = as_dict(await rec.ctrl.cdp.evaluate(snapshot_probe()))
    if not data.get("ok"):
        return
    html = redact_text(data.get("html", ""), rec.limits.max_snapshot_chars)
    digest = hashlib.sha256(html.encode("utf-8")).hexdigest()
    if digest == rec._last_hash and not force:
        return
    data.update({"html": html, "sha256": digest, "reason": reason, "at": utc_now(),
                 "offset_ms": round((now - rec.started) * 1000)})
    rec.store.write_snapshot(rec.session_id, rec._counts["snapshot"], clean_mapping(data))
    rec._counts["snapshot"] += 1
    rec._last_hash, rec._last_checkpoint = digest, now


async def write_event(rec: "CaptchaRecorder", kind: str, payload: dict[str, Any],
                      network: bool = False) -> None:
    """Append one bounded timeline event; past the cap the timeline is truncated."""
    if rec._counts["event"] >= rec.limits.max_events:
        rec._truncated.add("events")
        return
    event = {"seq": rec._counts["event"], "at": utc_now(),
             "offset_ms": round((time.monotonic() - rec.started) * 1000),
             "kind": kind, **clean_mapping(payload)}
    rec.store.append_event(rec.session_id, event)
    rec._counts["event"] += 1
    if network:
        rec._counts["network"] += 1


def detach_listener(rec: "CaptchaRecorder") -> None:
    """Unsubscribe from the CDP router so a later session starts clean."""
    router = getattr(rec.ctrl.cdp, "events", None)
    if router is not None:
        router.remove(rec.network.on_event)


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
        self.network.close()
        await self._checkpoint("resolved", force=True)
        if report:
            await self._event("solve_report", _semantic_report(report))
        await self._event("state", self._outcome_payload(outcome))
        await self._milestone_event("final", outcome)
        # the worker is joined; the page-side agent is disconnected so a later
        # encounter on the same page cannot inherit a stale queue
        await self.ctrl.cdp.evaluate(stop_probe())
        self._detach_listener()
        return self.store.finish(self.session_id, finish_updates(self, outcome))

    async def note_outcome(self, phase: str, outcome: Any) -> None:
        payload = self._outcome_payload(outcome)
        payload.update({"state": phase, "token_at_ms": round(getattr(outcome, "token_sec", 0) * 1000),
                        "dialog_at_token": getattr(outcome, "dialog_at_token", ""),
                        "inject": getattr(outcome, "inject", "")})
        await self._event("state", payload)
        await self._milestone_event(phase, outcome)

    def _offset_ms(self) -> int:
        return round((time.monotonic() - self.started) * 1000)

    async def _milestone_event(self, phase: str, outcome: Any) -> None:
        """D2: persist a bounded token-free milestone; fail closed on violation."""
        milestone_phase = _milestone_phase_for(phase)
        if milestone_phase is None:
            return
        try:
            payload = build_milestone(milestone_phase, outcome, offset_ms=self._offset_ms())
        except ValueError:
            await self._event("milestone_skipped",
                              {"phase": milestone_phase, "why": "token-free check failed"})
            return
        await self._event("milestone", payload)

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
        await drain_mutations(self)

    async def _checkpoint(self, reason: str, force: bool = False) -> None:
        await write_checkpoint(self, reason, force)

    async def _event(self, kind: str, payload: dict[str, Any], network: bool = False) -> None:
        await write_event(self, kind, payload, network)

    def _detach_listener(self) -> None:
        detach_listener(self)

    @staticmethod
    def _outcome_payload(outcome: Any) -> dict[str, Any]:
        return {"state": "recording_finished", "outcome": getattr(outcome, "status", "interrupted"),
                "method": getattr(outcome, "method", ""),
                "reason": redact_text(getattr(outcome, "reason", ""), 500)}


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

def finish_updates(rec: "CaptchaRecorder", outcome: Any) -> dict[str, Any]:
    """Bounded manifest updates from a finished recording."""
    counts = rec._counts
    return {"status": str(getattr(outcome, "status", "interrupted")),
            "outcome": str(getattr(outcome, "status", "interrupted")),
            "reason": redact_text(getattr(outcome, "reason", ""), 500),
            "method": str(getattr(outcome, "method", "")),
            "task_id": str(getattr(outcome, "task_id", "")),
            "polls": int(getattr(outcome, "polls", 0)),
            "attempts": int(getattr(outcome, "attempts", 1)),
            "elapsed_ms": round((time.monotonic() - rec.started) * 1000),
            "event_count": counts["event"],
            "mutation_count": counts["mutation"],
            "network_count": counts["network"],
            "snapshot_count": counts["snapshot"],
            "dropped_events": rec.network.dropped_events,
            "truncated": sorted(rec._truncated)}


def as_dict(value: Any) -> dict[str, Any]:
    """Best-effort dict view of a CDP evaluate result (JSON strings included)."""
    if isinstance(value, dict):
        return value
    try:
        data = json.loads(value) if isinstance(value, str) else {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _milestone_phase_for(phase: str) -> Optional[str]:
    """Map recorder phases onto milestone phases (unknown phases write nothing)."""
    if phase in MILESTONE_PHASES:
        return phase
    if phase == "auto_attempt_finished":
        return "auto_finished"
    return None
