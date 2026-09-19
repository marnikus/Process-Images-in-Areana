"""Fakes for batch characterization: FakeCDP, scripted FakeCtrl, signals.

No real Chrome, no real Qt, no network. FS only under pytest tmp_path.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional


class Recorder:
    """Signal stand-in: records emit() calls."""

    def __init__(self):
        self.calls: List[tuple] = []

    def emit(self, *args):
        self.calls.append(tuple(args))

    def connect(self, *args, **kwargs):
        pass


class _Sig:
    def connect(self, *args, **kwargs):
        pass


class FakeCDP:
    """Minimal CDP client: attrs the batch loop reads + scripted evaluate."""

    def __init__(self, tab_id: str = "tab1", eval_script: Optional[list] = None):
        self.is_connected = True
        self._current_tab_id = tab_id
        self._current_ws_url = "ws://127.0.0.1:9222/devtools/page/tab1"
        self._current_title = "Arena"
        self._current_url = "https://arena.ai/chat"
        self.connected = _Sig()
        self.disconnected = _Sig()
        self.error = _Sig()
        self._eval_script = list(eval_script or [])
        self._eval_default = {"found": True, "rect": {"x": 1, "y": 2, "width": 10, "height": 10}}
        self.eval_calls: List[str] = []

    async def connect(self, ws_url: str) -> bool:
        return True

    async def fetch_tabs(self):
        return []

    async def evaluate(self, js: str) -> str:
        self.eval_calls.append(js[:60])
        if self._eval_script:
            res = self._eval_script.pop(0)
        else:
            res = self._eval_default
        return res if isinstance(res, str) else json.dumps(res)


class FakeCtrl:
    """Scripted CDPArenaController stand-in. Records calls, never sleeps."""

    def __init__(self, script: Optional[Dict[str, Any]] = None):
        self._s = script or {}
        self.calls: List[str] = []
        self._counts: Dict[str, int] = {}
        self._visible_left = int(self._s.get("visible_times", 0))
        self._attached: List[str] = []
        self._prompts: List[str] = []

    def _fail(self, name: str) -> Optional[str]:
        fails = self._s.get("fail", {})
        if name not in fails:
            return None
        self._counts[name] = self._counts.get(name, 0) + 1
        times = self._s.get("fail_times", {}).get(name)
        if times is not None and self._counts[name] > times:
            return None
        return fails[name]

    async def is_page_ready(self):
        return True, []

    async def capture_baseline(self) -> Dict[str, Any]:
        self.calls.append("capture_baseline")
        return {"output_count": 2, "output_srcs": ["https://x/old0.png", "https://x/old1.png"],
                "outputs": [], "timestamp": 1000}

    async def is_security_dialog_visible(self) -> bool:
        self.calls.append("is_security_dialog_visible")
        if self._visible_left > 0:
            self._visible_left -= 1
            return True
        return False

    async def attach_image(self, image_path: str):
        self.calls.append("attach_image")
        err = self._fail("attach_image")
        if err:
            return False, err
        self._attached.append(image_path)
        return True, f"Attached {image_path[-12:]}"

    async def insert_prompt(self, prompt_text: str):
        self.calls.append("insert_prompt")
        err = self._fail("insert_prompt")
        if err:
            return False, err
        self._prompts.append(prompt_text)
        return True, f"Inserted len {len(prompt_text)}"

    async def verify_prompt(self, expected: str):
        self.calls.append("verify_prompt")
        if self._s.get("verify_prompt_ok", True):
            return True, "Exact match"
        return False, "Mismatch"

    async def submit(self):
        self.calls.append("submit")
        return True, "Clicked"

    async def wait_for_new_output(self, baseline, timeout_ms=0,
                                  correlation_id=None, cancel_check=None):
        self.calls.append("wait_for_new_output")
        src = self._s.get("new_src", "https://x/new.png")
        return "completed", {
            "new_src": src,
            "associatedJobId": correlation_id,
            "expectedJobId": correlation_id,
            "jobFound": True,
            "orderCheck": "ok",
        }

    async def download_image(self, src: str):
        self.calls.append("download_image")
        err = self._fail("download_image")
        if err:
            return False, b"", err
        return True, b"x" * 200, "image/png"

    async def highlight_selector(self, selector: str, **kw):
        self.calls.append(f"highlight:{selector[:30]}")
        return {"x": 1, "y": 2, "width": 10, "height": 10}

    async def show_watcher_overlay(self, *a, **k):
        self.calls.append("show_overlay")
        return True

    async def hide_watcher_overlay(self, *a, **k):
        self.calls.append("hide_overlay")
        return True

    async def is_generating(self):
        return False, "steady"

    async def get_generation_state(self, correlation_id=None):
        return {}


def make_find_and_click(script: Optional[Dict[str, str]] = None):
    """Scripted visual runner: {selector_substr: 'ok'|'fail'}, default 'ok'."""
    calls: List[str] = []
    script = script or {}

    async def fake(client, req, engine=None):
        sel = getattr(req, "selector", "")
        calls.append(sel)
        if engine is not None:
            try:
                engine._log(f"[fake-click] FIND {sel[:40]}", "info")
            except Exception:
                pass
        for key, res in script.items():
            if key in sel:
                return res
        return "ok"

    fake.calls = calls
    return fake


def make_handle_captcha(status: str = "solved"):
    """Patched `handle_captcha`: instant outcome, records invocations."""
    calls: List[Any] = []

    async def fake(ctx):
        calls.append(getattr(ctx, "source", "?"))
        return SimpleNamespace(status=status, reason="")

    fake.calls = calls
    return fake


def install_patches(monkeypatch, ctrl_script: Optional[dict] = None,
                    click_script: Optional[dict] = None,
                    captcha_status: Optional[str] = None):
    """Patch controller factory + visual runner (+captcha) for the run pipeline.

    The converged runner binds find_and_click as its own module global;
    the legacy-loop bridge patch died with the loop in A4 (R8 removed the
    last bridge-side visual_click import).
    """
    import app.browser.cdp_arena as arena_mod
    import app.services.captcha as captcha_mod
    import app.services.single_job_runner as runner_mod

    ctrl = FakeCtrl(ctrl_script)
    monkeypatch.setattr(arena_mod, "CDPArenaController",
                        lambda *a, **k: ctrl)
    clicks = make_find_and_click(click_script)
    monkeypatch.setattr(runner_mod, "find_and_click", clicks)
    captcha = None
    if captcha_status is not None:
        captcha = make_handle_captcha(captcha_status)
        monkeypatch.setattr(captcha_mod, "handle_captcha", captcha)
    return SimpleNamespace(ctrl=ctrl, clicks=clicks, captcha=captcha)
