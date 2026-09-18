"""One bounded asynchronous recording for a visible captcha encounter.

The recorder owns the lifecycle (install probes, poll, checkpoint, close) and
delegates the three bounded concerns to leaf modules: `budget` decides what may
still be written, `proberun` performs the page round trips, `milestones` names
the semantic edges. Terminal evidence is reserved, so a slow encounter can never
cost the comparison its edges.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any, Optional

from . import milestones
from .budget import Budget
from .models import RecordingLimits, utc_now
from .network import NetworkCollector
from .proberun import ProbeRunner
from .sanitize import clean_mapping, redact_text
from .store import RecordingStore

_EVIDENCE_KEYS = ("source", "kind", "integration", "invisible", "anchor", "challenge",
                  "response_fields", "sitekey_source", "page_identity")


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
        self.budget = Budget(self.limits)
        self.probes = ProbeRunner(ctrl.cdp)
        self._task: Optional[asyncio.Task] = None
        self._stopped = asyncio.Event()
        self._last_hash = ""
        self._last_checkpoint = 0.0
        self._base_ms = 0
        self._live: list[dict[str, Any]] = []
        self.network = NetworkCollector(ctrl.cdp, self._event, self.limits.max_body_chars,
                                        self.budget.mark)

    async def start(self) -> None:
        await self.probes.install()
        router = getattr(self.ctrl.cdp, "events", None)
        if router is not None:
            router.add(self.network.on_event)
        self.active = True
        await self.milestone("detected", _detected_data(self.encounter))
        await self._checkpoint("detected", force=True)
        self._task = asyncio.create_task(self._run())

    async def milestone(self, phase: str, data: Optional[dict[str, Any]] = None) -> int:
        """Stamp one named edge from the live path; unknown phases are ignored."""
        if phase not in milestones.PHASES:
            return -1
        offset = round((time.monotonic() - self.started) * 1000)
        self._live.append({"phase": phase, "offset_ms": offset})
        if phase == "detected":
            self._base_ms = offset
        self.budget.counts["milestone"] += 1
        await self._event("milestone", {"phase": phase, "offset_ms": offset,
                                        "data": clean_mapping(data or {})})
        return offset

    async def finish(self, outcome: Any,
                     report: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self.active = False
        self._stopped.set()
        if self._task is not None:
            await self._join_worker()
        await self._drain_mutations()
        await self.network.drain()
        await self._checkpoint("resolved", force=True)
        if report:
            await self._event("solve_report", _semantic_report(report))
        await self._write_derived(outcome, report)
        await self._event("state", _outcome_payload(outcome))
        await self.probes.stop()
        self._detach_listener()
        self.budget.counts.update(self.network.summary())
        updates = _finish_updates(outcome, time.monotonic() - self.started,
                                  self.budget, self.probes)
        return self.store.finish(self.session_id, updates)

    async def note_outcome(self, phase: str, outcome: Any) -> None:
        """Keep the coarse phase marker (legacy log continuity), bounded."""
        await self._event("state", _note_payload(phase, outcome))

    async def abort(self, reason: str) -> None:
        await self.finish(_Interrupted(reason))

    async def _run(self) -> None:
        while self.active:
            await self._drain_mutations()
            await self.network.drain()
            await self._wait_cycle()

    async def _wait_cycle(self) -> None:
        """Wait one cadence, or wake at once when the recorder is closed.

        Waiting on an Event (never `asyncio.sleep`) cannot starve the event loop
        when a caller replaces sleep with a non-suspending stub.
        """
        try:
            await asyncio.wait_for(self._stopped.wait(), timeout=self.limits.poll_interval_sec)
        except asyncio.TimeoutError:
            pass

    async def _join_worker(self) -> None:
        await _join_task(self._task, self.limits.poll_interval_sec + 1.0)

    async def _write_derived(self, outcome: Any, report: Optional[dict[str, Any]]) -> None:
        """Persist the named edges no live stamp covered (provider + terminal)."""
        for row in milestones.derive(outcome, report or {}, self._live, self._base_ms):
            self.budget.counts["milestone"] += 1
            await self._event("milestone", row)

    async def _drain_mutations(self) -> None:
        data = await self.probes.drain()
        changes = data.get("changes") if data.get("ok") else []
        if changes:
            clean = clean_mapping(changes)
            self.budget.counts["mutation"] += len(clean)
            await self._event("mutation", {"changes": clean, "dropped": data.get("dropped", 0)})
            await self._checkpoint("mutation")
        if data.get("dropped"):
            self.budget.mark("mutations")

    async def _checkpoint(self, reason: str, force: bool = False) -> None:
        """Write a DOM checkpoint; the reserved tail is kept for forced edges."""
        now = time.monotonic()
        if not force and now - self._last_checkpoint < self.limits.checkpoint_interval_sec:
            return
        if not self.budget.allow_snapshot(force):
            self.budget.mark("snapshots")
            return
        data = await self.probes.snapshot()
        if not data.get("ok"):
            return
        html = redact_text(data.get("html", ""), self.limits.max_snapshot_chars)
        digest = hashlib.sha256(html.encode("utf-8")).hexdigest()
        if digest == self._last_hash and not force:
            return
        data.update({"html": html, "sha256": digest, "reason": reason, "at": utc_now(),
                     "offset_ms": round((now - self.started) * 1000)})
        self.store.write_snapshot(self.session_id, self.budget.counts["snapshot"],
                                  clean_mapping(data))
        self.budget.count_snapshot(force)
        self._last_hash, self._last_checkpoint = digest, now

    async def _event(self, kind: str, payload: dict[str, Any], network: bool = False) -> None:
        if not self.budget.allow_event(kind):
            return
        event = {"seq": self.budget.counts["event"], "at": utc_now(),
                 "offset_ms": round((time.monotonic() - self.started) * 1000),
                 "kind": kind, **clean_mapping(payload)}
        self.store.append_event(self.session_id, event)
        self.budget.counts["event"] += 1
        if network:
            self.budget.counts["network"] += 1

    def _detach_listener(self) -> None:
        router = getattr(self.ctrl.cdp, "events", None)
        if router is not None:
            router.remove(self.network.on_event)


class _Interrupted:
    """Outcome-shaped carrier for an abort (keeps SolveOutcome out of this module)."""

    def __init__(self, reason: str):
        self.status = "interrupted"
        self.method = ""
        self.reason = reason


def _detected_data(encounter: dict[str, Any]) -> dict[str, Any]:
    """Encounter identity carried by the opening edge (no page content)."""
    return {"kind": encounter.get("kind", ""),
            "evidence": {key: encounter.get(key) for key in _EVIDENCE_KEYS}}


def _note_payload(phase: str, outcome: Any) -> dict[str, Any]:
    """Coarse phase marker payload (legacy log continuity), bounded."""
    payload = _outcome_payload(outcome)
    payload.update({"state": phase, "token_at_s": round(getattr(outcome, "token_sec", 0), 1),
                    "dialog_at_token": getattr(outcome, "dialog_at_token", ""),
                    "inject": redact_text(getattr(outcome, "inject", ""), 200)})
    return payload


async def _join_task(task: Optional[asyncio.Task], timeout: float) -> None:
    try:
        await asyncio.wait_for(task, timeout=timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()


def _outcome_payload(outcome: Any) -> dict[str, Any]:
    return {"state": "recording_finished", "outcome": getattr(outcome, "status", "interrupted"),
            "method": getattr(outcome, "method", ""),
            "reason": redact_text(getattr(outcome, "reason", ""), 500)}


def _finish_updates(outcome: Any, elapsed: float, budget: Budget,
                    probes: ProbeRunner) -> dict[str, Any]:
    status = str(getattr(outcome, "status", "interrupted"))
    counts = budget.counts
    return {"status": status, "outcome": status,
            "reason": redact_text(getattr(outcome, "reason", ""), 500),
            "method": str(getattr(outcome, "method", "")),
            "acceptance": milestones.acceptance_state(outcome),
            "elapsed_ms": round(elapsed * 1000),
            "event_count": counts["event"], "mutation_count": counts["mutation"],
            "network_count": counts["network"], "snapshot_count": counts["snapshot"],
            "milestone_count": counts["milestone"], "probe_errors": probes.calls["error"],
            "bodies_captured": counts.get("bodies_captured", 0),
            "bodies_skipped": counts.get("bodies_skipped", 0),
            "network_dropped": counts.get("queued_dropped", 0),
            "truncated": budget.truncated_list()}


def _semantic_report(report: dict[str, Any]) -> dict[str, Any]:
    """Keep diagnostic milestones while excluding raw/public token identifiers."""
    keys = ("status", "reason", "method", "task_type", "polls", "detect_to_solve_s",
            "dialog_at_token", "inject", "postinject", "preinject", "continue",
            "page_error", "acceptance", "stale", "solve_total_s", "integration",
            "anchor", "challenge", "sitekey_source", "page_identity", "invisible")
    payload = {key: report.get(key) for key in keys}
    payload["field_evidence"] = report.get("response_fields")
    token = report.get("token")
    payload["solution_ready_at_s"] = token.get("at_s") if isinstance(token, dict) else None
    return payload
