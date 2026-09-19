"""Arena mixins — split controller methods to keep each class ≤15 methods (C3).

RULE18: file 150-300, class methods ≤15, func ≤20, CC≤10.
"""
from __future__ import annotations

import logging
from typing import Dict, Any, Optional, List, Tuple, Callable

from ..cdp_client import CDPClient

log = logging.getLogger("arena")


class BaseMixin:
    cdp: CDPClient
    _log_callback: Optional[Callable]

    def __init__(self, cdp_client: CDPClient, log_callback=None):
        self.cdp = cdp_client
        self._log_callback = log_callback

    def set_log_callback(self, cb: Callable[[str], None]):
        self._log_callback = cb

    def _log(self, msg: str, level: str = "info"):
        log.info(msg)
        if self._log_callback:
            try:
                self._log_callback(msg)
            except Exception:
                pass

    async def ensure_connected(self) -> bool:
        if self.cdp.is_connected:
            return True
        self._log("CDP not connected", "warn")
        return False

    def report(self, message: str, level: str = "info"):
        self._log(message, level)


class AttachMixin:
    async def attach_image(self, image_path: str) -> Tuple[bool, str]:
        from .attach import attach_image as mod
        return await mod(self.cdp, image_path, self.ensure_connected, self._log)

    async def verify_attachment(self, expected_filename: str) -> Tuple[bool, str]:
        from .attach import verify_attachment as mod
        return await mod(self.cdp, expected_filename)


class SubmitMixin:
    async def insert_prompt(self, prompt_text: str) -> Tuple[bool, str]:
        from .submit import insert_prompt as mod
        return await mod(self.cdp, prompt_text, self.ensure_connected)

    async def verify_prompt(self, expected: str) -> Tuple[bool, str]:
        from .submit import verify_prompt as mod
        return await mod(self.cdp, expected)

    async def submit(self) -> Tuple[bool, str]:
        from .submit import submit as mod
        return await mod(self.cdp, self.ensure_connected)

    async def submit_when_ready(self, timeout_sec: float = 8.0) -> Tuple[bool, str]:
        from .submit import submit_when_ready as mod
        return await mod(self.cdp, self.ensure_connected, timeout_sec)


class DownloadMixin:
    async def download_image(self, src: str) -> Tuple[bool, bytes, str]:
        from .download import download_image as mod
        return await mod(self.cdp, src, self._log)


class HighlightMixin:
    async def highlight_selector(self, selector: str, color: str = "#FF0000",
                                 duration_ms: int = 2000, caption: str = "") -> dict | None:
        from .highlight import HighlightSpec, highlight_selector as mod
        spec = HighlightSpec(color=color, duration_ms=duration_ms, caption=caption)
        return await mod(self.cdp, selector, spec)

    async def clear_highlights(self):
        from .highlight import clear_highlights as mod
        return await mod(self.cdp)

    async def show_watcher_overlay(self, message: str = "wait for finish generation",
                                   kind: str = "generation", timeout_sec: int = 600,
                                   sub: str = "") -> bool:
        from .highlight import WatcherOverlaySpec, show_watcher_overlay as mod
        spec = WatcherOverlaySpec(message=message, kind=kind, timeout_sec=timeout_sec, sub=sub)
        return await mod(self.cdp, spec)

    async def hide_watcher_overlay(self) -> bool:
        from .highlight import hide_watcher_overlay as mod
        return await mod(self.cdp)


class StateMixin:
    async def capture_baseline(self) -> Dict[str, Any]:
        from .state import capture_baseline as mod
        return await mod(self.cdp)

    async def scan_page_errors(self) -> str:
        from .state import scan_page_errors as mod
        return await mod(self.cdp)

    async def is_page_ready(self) -> Tuple[bool, List[str]]:
        from .state import is_page_ready as mod
        return await mod(self.cdp)

    async def is_security_dialog_visible(self) -> bool:
        from .state import is_security_dialog_visible as mod
        return await mod(self.cdp)

    async def is_generating(self) -> Tuple[bool, Dict[str, Any]]:
        from .state import is_generating as mod
        return await mod(self.cdp)

    async def get_generation_state(self, correlation_id: Optional[str] = None) -> Dict[str, Any]:
        from .state import get_generation_state as mod
        return await mod(self.cdp, correlation_id)

    async def reload_page(self) -> Tuple[bool, str]:
        from .state import reload_page as mod
        return await mod(self.cdp, self._log)


class OutputMixin:
    async def wait_for_new_output(self, baseline: Dict[str, Any], timeout_ms: int = 180000,
                                  correlation_id: Optional[str] = None,
                                  cancel_check=None) -> Tuple[str, Dict[str, Any]]:
        from .output import WaitSpec, wait_for_new_output as mod
        spec = WaitSpec(baseline=baseline, timeout_ms=timeout_ms,
                        correlation_id=correlation_id, cancel_check=cancel_check,
                        log_cb=self._log, ctrl=self)
        return await mod(self.cdp, spec)
