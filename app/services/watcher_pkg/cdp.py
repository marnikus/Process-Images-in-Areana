"""Watcher CDP boundary — structured detection and passive page overlays."""

from __future__ import annotations

from typing import Any, Callable

from app.browser.captcha_probes import build_detect_js
from app.services.captcha.signals import CaptchaSignal


def _empty_pages(_value):
    return []


def _dict_pages(value):
    return [(str(key), controller) for key, controller in value.items() if controller]


def _pair_present(value):
    return len(value) == 2 and isinstance(value[0], str)


def _pair_result(value):
    return [(value[0], value[1])] if value[1] else []


def _pair_page(value):
    return _pair_result(value) if _pair_present(value) else None


def _many_pages(value):
    return [(str(key), controller) for key, controller in value if controller]


def _sequence_pages(value):
    return _pair_page(value) or _many_pages(value)


def _one_page(value):
    return [(str(getattr(value, "tab_id", "primary")), value)]


_PAGE_NORMALIZERS = {type(None): _empty_pages, dict: _dict_pages,
                    list: _sequence_pages, tuple: _sequence_pages}


def normalize_pages(value: Any) -> list[tuple[str, Any]]:
    normalizer = _PAGE_NORMALIZERS.get(type(value), _one_page)
    return normalizer(value)


def _empty_value():
    return None


def _getter_or_empty(getter):
    return getter or _empty_value


def _call_getter(getter, logger):
    try:
        return _getter_or_empty(getter)()
    except Exception as exc:
        logger(f"Watcher CDP getter failed: {type(exc).__name__}", "warn")
        return None


def collect_pages(getter: Callable | None, logger: Callable) -> list[tuple[str, Any]]:
    return normalize_pages(_call_getter(getter, logger))


async def _cdp_probe(cdp):
    return CaptchaSignal.from_result(await cdp.cdp.evaluate(build_detect_js()))


async def _gate_probe(cdp):
    return CaptchaSignal(visible=bool(await cdp.is_security_dialog_visible()))


async def _probe_page(cdp):
    probe = _cdp_probe if hasattr(cdp, "cdp") else _gate_probe
    return await probe(cdp)


async def detect_signal(cdp, logger) -> CaptchaSignal:
    try:
        return await _probe_page(cdp)
    except Exception as exc:
        logger(f"Watcher captcha check error: {type(exc).__name__}", "warn")
        return CaptchaSignal()


class WatcherCDP:
    """Fail-open probes used by the enabled Watcher."""

    def __init__(self, cdp_getter: Callable | None, logger: Callable):
        self._cdp_getter = cdp_getter
        self._logger = logger

    def get_pages(self):
        return collect_pages(self._cdp_getter, self._logger)

    async def detect_captcha(self, cdp) -> CaptchaSignal:
        return await detect_signal(cdp, self._logger)

    async def check_generation(self, cdp):
        try:
            return await cdp.is_generating()
        except Exception as exc:
            return False, {"error": str(exc)}

    async def show_overlay(self, cdp, msg, kind, timeout):
        try:
            await cdp.show_watcher_overlay(msg, kind=kind, timeout_sec=timeout)
        except Exception as exc:
            self._logger(f"Watcher overlay show failed: {type(exc).__name__}", "warn")

    async def hide_overlay(self, cdp):
        try:
            await cdp.hide_watcher_overlay()
        except Exception:
            pass


# Compatibility methods keep older integrations on the structured boundary.
def _get_compat(probe):
    pages = probe.get_pages()
    return pages[0][1] if pages else None


async def _check_captcha_compat(probe, cdp):
    return (await probe.detect_captcha(cdp)).visible


WatcherCDP.get = _get_compat
WatcherCDP.check_captcha = _check_captcha_compat
