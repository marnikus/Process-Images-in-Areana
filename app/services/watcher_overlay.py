"""Watcher overlay helpers — pure message builders and decision predicates (C1).

Extracted from WatcherService.check_once to keep orchestrator ≤20 LOC, CC≤7.
Each helper has real responsibility name, not foo_part1 gaming.
"""

from __future__ import annotations
import time
from typing import Dict, Any


def build_captcha_msg(timeout_sec: int) -> str:
    return f"wait for user. Captcha (timeout {timeout_sec}s)"


def build_generation_msg(details: Dict[str, Any], timeout_sec: int) -> str:
    labels = []
    try:
        for d in details.get("details", []):
            if isinstance(d, dict) and d.get("label"):
                labels.append(d["label"])
    except Exception:
        pass
    detail_str = ", ".join(labels) if labels else "generating"
    return f"wait for finish generation {detail_str} (timeout {timeout_sec}s)"


def should_start_captcha_waiting(current_kind: str | None) -> bool:
    return current_kind != "captcha"


def should_start_generation_waiting(current_kind: str | None) -> bool:
    return current_kind != "generation"


def is_captcha_timeout(waiting_since: float | None, timeout_sec: int) -> bool:
    if not waiting_since:
        return False
    return (time.time() - waiting_since) > timeout_sec


def is_generation_timeout(waiting_since: float | None, timeout_sec: int) -> bool:
    if not waiting_since:
        return False
    return (time.time() - waiting_since) > timeout_sec


def should_clear_overlay(waiting_kind: str | None, is_captcha: bool, is_gen: bool) -> bool:
    if waiting_kind not in ("generation", "captcha"):
        return False
    return not is_captcha and not is_gen


def build_clear_msg(kind: str | None, elapsed_sec: int) -> str:
    return f"{kind} finished after {elapsed_sec}s — clearing overlay"
