"""Step-by-step report for one captcha diagnose probe (the "Scan now" output).

The numbered lines answer "detecting captcha on screen is not clear" (2026-09-18):
each line states what the page ACTUALLY has (dialogs, iframes, geometry) so a
missed detection is visible as a specific missing marker, not a silent boolean.
Docs: docs/archive/2026-09-18-captcha-wait-visibility/design.md
"""

from __future__ import annotations

from typing import Any, Dict, List


def _describe_frames(frames: List[Dict[str, Any]]) -> str:
    # ideal-size: 8 lines reason=one compact evidence line per iframe
    if not frames:
        return "none on page"
    parts = []
    for f in frames[:4]:
        loc = "in badge" if f.get("in_badge") else ("in dialog" if f.get("in_dialog") else "on page")
        vis = f"visible {f.get('w')}x{f.get('h')} at {f.get('x')},{f.get('y')}" if f.get("on_screen") else "hidden/off-screen"
        parts.append(f"{loc} {vis}")
    return "; ".join(parts)


def _describe_dialogs(count: int, hits: List[Dict[str, Any]]) -> str:
    # ideal-size: 5 lines reason=matched markers per open dialog (max 3 shown)
    if not count:
        return "0 open"
    parts = []
    for h in hits[:3]:
        text = (h.get("text") or "")[:40]
        markers = ",".join(h.get("hits") or []) or "no marker"
        parts.append(f"'{text}' [{markers}]" if text else f"[{markers}]")
    return f"{count} open — " + "; ".join(parts)


def _verdict_line(info: Dict[str, Any], ev: Dict[str, Any]) -> str:
    # ideal-size: 7 lines reason=step 3 of the report
    if info.get("visible"):
        anchor = info.get("anchor") or {}
        extra = f" kind={info.get('kind')}, sitekey={'set' if info.get('sitekey') else 'MISSING'}, anchor cb={'yes' if anchor.get('cb') else 'no'}"
        return f"  3. verdict: CHALLENGE VISIBLE{extra} — {ev.get('reason') or '?'}"
    return f"  3. verdict: no challenge — {ev.get('reason') or '?'}"


def _action_line(info: Dict[str, Any], status: Dict[str, Any]) -> str:
    # ideal-size: 6 lines reason=step 5 of the report
    if info.get("visible"):
        action = "job flow settles it (auto-solve or manual wait with the why-flag)" if status.get("enabled") else "manual solve in Chrome (auto-solve OFF)"
        return f"  5. action: {action}"
    return "  5. action: none — nothing to solve on this page"


def build_scan_report(info: Dict[str, Any], page_url: str, status: Dict[str, Any]) -> List[str]:
    # ideal-size: 13 lines reason=numbered verdict + evidence + auto-solve state
    ev = info.get("evidence") or {}
    mode = "ON" if status.get("enabled") else "OFF"
    key = f"key {status.get('masked_key') or '(not set)'}" if status.get("has_key") else "key (not set)"
    err = f", last error: {status.get('last_error')}" if status.get("last_error") else ""
    return [
        f"🔎 Captcha scan — step by step on {page_url or '(unknown page)'}",
        f"  1. open dialogs: {_describe_dialogs(ev.get('dialogs_open', 0), ev.get('dialog_hits') or [])}",
        f"  2. reCAPTCHA iframes: {_describe_frames(ev.get('iframes') or [])}",
        _verdict_line(info, ev),
        f"  4. auto-solve: {mode} — 2Captcha {key}{err}",
        _action_line(info, status),
    ]
