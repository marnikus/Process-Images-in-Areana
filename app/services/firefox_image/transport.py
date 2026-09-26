"""Run one image-job phase through Ui.Vision (I-65).

Writes this phase's macro, then reuses the identify lane's lock, gap and
Sequence. Never calls `runner.provision()` — that would overwrite the file
with the demo macro. `storage=browser` answers blocked before any write.
A missing Firefox binary answers blocked before any write too.

Imports: browser uivision + sibling firefox_lane. No Qt.
"""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass, replace

from app.browser.uivision import autorun, config as uv_config, file_dialog, launch, macro, paths
from app.browser.uivision import job_macro
from app.browser.uivision.runner import RunSeams
from app.browser.uivision.sequence import Sequence, StepRecorder
from app.services import firefox_lane as lane

_MARK = re.compile(r"ARENA_JOB=(\{.*\})")
_CLICKS = {
    "upload": job_macro.add_files_target,
    "clear": job_macro.remove_file_target,
    "submit": job_macro.send_target,
    "new_chat": job_macro.new_chat_target,
}


def parse_job_reply(lines) -> dict:
    """The last rendered `ARENA_JOB=` echo, or {} when the savelog has none."""
    for line in reversed(tuple(lines or ())):
        found = _MARK.search(str(line))
        if not found:
            continue
        try:
            data = json.loads(found.group(1))
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    return {}


def firefox_ready(bridge) -> bool:
    """True when the configured (or discovered) binary is a real file."""
    binary = launch.resolve_binary(uv_config.load_config(bridge).get("binary", ""))
    return launch.binary_exists(binary)


def _click_target(phase: str) -> str:
    """cmd_var2 for the find-rect. Probe phases click nothing."""
    maker = _CLICKS.get(phase)
    return maker() if maker else ""


def _phase_spec(bridge, page, phase: str):
    """The window's spec, aimed at Arena_ImageJob and this phase's click."""
    spec = uv_config.build_spec(bridge, lane._job_config(bridge, page))
    return replace(spec, macro=job_macro.MACRO_NAME, target=_click_target(phase))


def provision_phase(spec, phase: str, payload: dict) -> str:
    """Write this phase's macro (not the demo) and the shared autorun page."""
    target = paths.macro_file(paths.home(spec.home), job_macro.MACRO_NAME)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(macro.to_json(job_macro.build_job_macro(phase, payload)), encoding="utf-8")
    paths.logs_dir(spec.config_dir).mkdir(parents=True, exist_ok=True)
    return str(autorun.write_page(paths.autorun_file(spec.config_dir)))


def _log_path(config_dir, phase: str) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return str(paths.logs_dir(config_dir) / f"image-{phase}-{stamp}.txt")


def _quiet(step: str, message: str, level: str = "info") -> None:
    """Phase steps stay in the debug log — the job runner words the user line."""
    return None


def _blocked(message: str) -> dict:
    return {"kind": "blocked", "message": message, "data": {}}


@dataclass
class PhaseCall:
    """One phase invocation — keeps `run_phase` inside the parameter budget."""

    bridge: object
    page: object
    phase: str
    payload: dict
    spec: object = None


def _start_dialog_fill(phase: str, payload: dict, home):
    """Windows only. The thread uses the queue absolute path, not keystrokes."""
    if phase != "upload" or sys.platform != "win32":
        return None
    return file_dialog.start_fill(str((payload or {}).get("path") or ""), file_dialog.result_file(home))


def _dialog_failure(reply: dict, home, ran_fill: bool) -> dict:
    """A filler miss is named. A missing file means the helper never finished."""
    if not ran_fill:
        return reply
    reason = file_dialog.read_result(file_dialog.result_file(home))
    if reason == "ok":
        return reply
    if reason in ("", "waiting") and reply.get("kind") != "ok":
        return reply
    failed = dict(reply)
    failed["kind"] = "error"
    failed["message"] = reason if reason not in ("", "waiting") else "File Upload dialog was not open"
    return failed


async def _execute_phase(call: PhaseCall) -> tuple:
    """Write, then run, under the machine lock. Returns (kind, message, lines)."""
    spec, phase, payload = call.spec, call.phase, call.payload
    run = lane.image_run(spec, call.page, _log_path(spec.config_dir, phase))

    async def work():
        lane._fresh(run)
        worker = _start_dialog_fill(phase, payload, paths.home(spec.home))
        stop = lambda: bool(getattr(call.bridge, "_cancel_requested", False))
        seq = Sequence(spec, RunSeams(stop=stop), StepRecorder(_quiet))
        seq.page = provision_phase(spec, phase, payload)
        try:
            result = await seq.execute([run])
        finally:
            if worker is not None:
                worker.join(timeout=2)
        return result.kind, result.message, tuple(result.lines)

    return await lane.exclusive(call.bridge, work)


def _kind_of(phase: str, kind: str) -> str:
    """A lost submit ack is uncertain — the runner must not click again."""
    if phase == "submit" and kind != "ok":
        return "uncertain"
    return kind


async def run_phase(call: PhaseCall, execute=None) -> dict:
    """One phase. Browser storage and a missing binary never write a macro."""
    spec = call.spec or _phase_spec(call.bridge, call.page, call.phase)
    if spec.storage != "xfile":
        return _blocked("image job needs hard-drive macro storage (xfile)")
    if execute is None and not firefox_ready(call.bridge):
        return _blocked("no firefox binary")
    ready = PhaseCall(call.bridge, call.page, call.phase, call.payload or {}, spec)
    kind, message, lines = await (execute or _execute_phase)(ready)
    reply = {"kind": _kind_of(call.phase, kind), "message": message, "data": parse_job_reply(lines)}
    ran_fill = execute is None and call.phase == "upload" and sys.platform == "win32"
    return _dialog_failure(reply, paths.home(spec.home), ran_fill)


class MacroTransport:
    """The production transport: one `act` per phase, shared with the tests' fake."""

    def __init__(self, bridge, page, execute=None):
        self.bridge = bridge
        self.page = page
        self._execute = execute

    async def act(self, phase: str, payload: dict) -> dict:
        call = PhaseCall(self.bridge, self.page, phase, payload or {})
        return await run_phase(call, execute=self._execute)
