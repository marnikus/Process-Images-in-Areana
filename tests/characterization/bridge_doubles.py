"""Test doubles for the bridge run-batch pipeline (roadmap W1.1).

One shared harness, reused by every bridge phase:
- ``RecordingBridge``  — stands in for ``self`` inside ``Bridge._do_run_batch``
  (the 29 self-attributes the method touches), recording every log line,
  action status, signal and state change.
- ``FakeArenaCtrl``    — stands in for ``CDPArenaController`` (monkeypatch
  ``app.browser.cdp_arena.CDPArenaController``): scripted per-call results.
- ``FakeSignal``       — records ``.emit(*args)``.

The doubles record a TRACE; golden tests assert the trace shape, so the
1,209-LOC ``_do_run_batch`` can be refactored (W1.3–W1.5) with proof of
identical observable behaviour.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable

from app.core.action_blocks import default_stack
from app.core.models import AppState, ImageItem, UrlRow


class FakeSignal:
    def __init__(self, name: str, trace: list):
        self._name, self._trace = name, trace

    def emit(self, *args):
        self._trace.append(("signal", self._name, *args))


class FakeCDP:
    """Async evaluate() speaking the visual_click probe protocol.

    Returns a JSON string that parses as a successful find/click probe
    (found, total, index, text, visible, clickable, clicked, rect)."""

    def __init__(self, probe_result: dict | None = None):
        import json as _json
        self._probe = _json.dumps(probe_result if probe_result is not None else {
            "found": True, "total": 1, "index": 0, "text": "target",
            "visible": True, "clickable": True, "disabled": False,
            "clicked": True, "highlighted": False,
            "rect": {"x": 1, "y": 1, "width": 10, "height": 10},
            "candidates": [],
        })

    async def evaluate(self, js, *args, **kwargs):
        return self._probe


class FakeArenaCtrl:
    """Scripted CDPArenaController double.

    ``script`` maps method name -> return value (or callable). Unknown
    methods record themselves and succeed with True."""

    def __init__(self, cdp, log_callback=None, script: dict | None = None):
        self.cdp, self.log_callback = cdp, log_callback
        self.script = script or {}
        self.trace: list = []
        self.calls: list = []

    def __getattr__(self, name):
        async def method(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            self.trace.append(("ctrl", name))
            if name in self.script:
                result = self.script[name]
                return result(self, *args, **kwargs) if callable(result) else result
            return True
        return method


def completed_wait_result(cid: str, src: str = "https://r2/out.png"):
    """Real wait_for_new_output contract: ("completed", payload)."""
    check = {"src": src, "width": 1024, "height": 1024, "spinning": False,
             "associatedJobId": cid, "expectedJobId": cid,
             "allNew": 1, "mismatchDetails": []}
    return ("completed", {
        "new_src": src, "check": check,
        "associatedJobId": cid, "expectedJobId": cid,
        "jobFound": True, "orderCheck": "ok", "jobTop": 100, "prevJobTop": 50,
        "nextJobTop": None, "validAbove": 0, "invalidAbove": 0,
        "allNew": 1, "belowCount": 0, "allJobs": 1,
    })


class RecordingBridge:
    """Minimal ``self`` for ``Bridge._do_run_batch`` — records everything."""

    def __init__(self, images: list[ImageItem] | None = None,
                 urls: list[UrlRow] | None = None,
                 prompt: str = "make [JOB-ID] blue",
                 stack=None, ctrl_script: dict | None = None,
                 stop_requested: Callable[[], bool] | None = None):
        self.trace: list = []
        self._ctrl_script = ctrl_script or {}
        self._stop_flag = stop_requested or (lambda: False)
        url = UrlRow.create("https://arena.ai/x", enabled=True)
        url.link_tab("tab-1")
        self.state = AppState(
            prompt={"user_prompt": prompt},
            settings=SimpleNamespace(
                output={"suffix": "_AI", "overwrite": False,
                        "preserve_format": True,
                        "unique_suffix_template": "{base}_AI_{n}{ext}"},
                timeouts={"generation": 3},
            ),
            images=images if images is not None else [],
            urls=urls if urls is not None else [url],
        )
        self.config = SimpleNamespace(get_state=lambda k, d=None, **kw: d)
        self.cdp = FakeCDP()
        self._page_pool = None
        self._run_state_value = "running"
        self._cancel_requested = False
        self._pause_requested = False
        self._stack = stack if stack is not None else default_stack()
        self.job_started = FakeSignal("job_started", self.trace)
        self.job_finished = FakeSignal("job_finished", self.trace)
        self.highlight_rect = FakeSignal("highlight_rect", self.trace)

    @property
    def _run_state(self):
        return self._run_state_value

    @_run_state.setter
    def _run_state(self, value):
        if value != self._run_state_value:
            self.trace.append(("state", value))
        self._run_state_value = value

    # ---- stores / selectors -------------------------------------------------
    def _get_enabled_urls(self):
        return [u for u in self.state.urls if u.enabled]

    def _get_selected_images(self):
        return list(self.state.images)

    def _get_action_blocks(self):
        return list(self._stack)

    async def _select_run_tab(self, current, allowed):
        return "tab-1"

    def _pool_summary(self):
        return "fake-no-pool"

    # ---- emissions (all recorded) --------------------------------------------
    def _log(self, msg, level="info"):
        self.trace.append(("log", level, str(msg)))

    def _emit_job_action_status(self, job_id, block, status, message="", rect=None):
        self.trace.append(("action", getattr(block, "block_id", "?"), status))

    def _emit_arena_state(self):
        self.trace.append(("emit", "arena_state"))

    def _emit_action_blocks(self):
        self.trace.append(("emit", "action_blocks"))

    def _emit_pool_status(self):
        self.trace.append(("emit", "pool_status"))

    # ---- run control ----------------------------------------------------------
    def _run_stop_requested(self, tab_id):
        return bool(self._stop_flag())

    def _stop_reason(self, tab_id):
        return "user_stop"

    def _save_arena(self, *a, **kw):
        self.trace.append(("save", "arena"))

    def _start_tab_image(self, tab_id, img):
        self.trace.append(("start", getattr(img, "relative_path", "?")))

    async def _finish_primary_tab(self, ctrl, tab_id):
        self.trace.append(("finish", tab_id))

    async def _ensure_pool_page(self, tab_id):
        return None

    async def _settle_boundary_captcha(self, *a, **kw):
        return None

    async def _settle_captcha_at(self, *a, **kw):
        return None

    def _settle_stuck_primary(self, tab_id):
        return None

    def make_ctrl(self, cdp, log_callback=None):
        return FakeArenaCtrl(cdp, log_callback, self._ctrl_script)


def make_image(path, name: str = "pic.png", selected: bool = True) -> ImageItem:
    return ImageItem.from_scan_dict(
        {"absolute_path": str(path), "relative_path": name, "filename": name,
         "base_name": name.rsplit(".", 1)[0], "extension": name.rsplit(".", 1)[-1],
         "size": 100, "mtime": 1.0, "fingerprint": f"fp-{name}"},
        selected=selected,
    )


def compact_trace(trace: list) -> list:
    """Trace with log payloads and volatile ids stripped (golden form)."""
    out = []
    for entry in trace:
        kind = entry[0]
        if kind == "log":
            out.append(("log", entry[1]))
        else:
            out.append(tuple(entry))
    return out


def action_trace(trace: list) -> list:
    """Only the (block, status) sequence — the core golden."""
    return [e for e in compact_trace(trace) if e[0] in ("action", "signal")]
