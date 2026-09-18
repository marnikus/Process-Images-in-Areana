#!/usr/bin/env python3
"""tools/analyze_captcha_recording.py — evidence-gated session diagnostic.

Classifies each recorded captcha encounter from its OWN persisted evidence
(manifest + events), per the verification signatures in
docs/archive/2026-09-18-captcha-bot-failure-analysis/verification-and-problem-diagnostic.md §2.4:

  STALE-TOKEN     token arrived for a rotated/dead generation
  WRONG-CALLBACK  injection OK but no site verification request afterwards
  NO-ORACLE       dialog cleared after callback, but no acceptance request found
  DEAD-GEN        page error during the solve
  NOT-ACCEPTED    site rejected the token (dialog stayed up through the grace)
  DIALOG-GONE-*   the user (or the page) handled the challenge, not the bot

Usage:
    python tools/analyze_captcha_recording.py <session-folder | recordings-root>

Prints compact, paste-safe lines per session — no tokens, keys, or bodies.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

GRACE_MS = 1000  # post-token acceptance window before counting site requests


def _load(folder: Path) -> tuple[dict, list[dict]]:
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    events = []
    path = folder / "events.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    events.append(value)
            except json.JSONDecodeError:
                continue
    return manifest, events


def _page_host(manifest: dict) -> str:
    try:
        return urlsplit(str(manifest.get("url", ""))).hostname or ""
    except Exception:
        return ""


def _net_rows(events: list[dict]) -> list[tuple[int, str, str, str]]:
    """(offset_ms, kind, host, method-or-status) for network lifecycle events."""
    rows = []
    for event in events:
        if event.get("kind") in ("network_request", "network_response", "network_failure"):
            payload = event
            host = urlsplit(str(payload.get("url", ""))).hostname or ""
            detail = str(payload.get("method") or payload.get("status") or "")
            rows.append((int(payload.get("offset_ms", 0)), event["kind"], host, detail))
    return rows


def _as_ms(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0  # "[REDACTED]" by the legacy sanitizer, or missing


def _token_state(events: list[dict]) -> tuple[int, str, str]:
    """Last auto-attempt state: (token_at_ms, dialog_at_token, inject)."""
    token_ms, dialog, inject = 0, "", ""
    for event in events:
        if event.get("kind") == "state" and event.get("state") == "auto_attempt_finished":
            token_ms = _as_ms(event.get("token_at_ms"))
            dialog = str(event.get("dialog_at_token", ""))
            inject = str(event.get("inject", ""))
    return token_ms, dialog, inject


def _post_token_site_requests(rows: list[tuple[int, str, str, str]],
                              token_ms: int, host: str) -> int:
    if token_ms <= 0 or not host:
        return 0
    return sum(1 for off, kind, h, _ in rows
               if kind == "network_request" and off >= token_ms + GRACE_MS and h == host)


def _classify(manifest: dict, events: list[dict]) -> str:
    status = str(manifest.get("outcome") or manifest.get("status") or "")
    reason = str(manifest.get("reason", ""))
    token_ms, dialog, _ = _token_state(events)
    rows = _net_rows(events)
    post = _post_token_site_requests(rows, token_ms, _page_host(manifest))
    if status == "solved":
        return "SOLVED — bot token accepted"
    if status == "manual":
        return f"MANUAL fallback (auto reason: {reason[:60] or 'n/a'})"
    if status == "page_error":
        return "DEAD-GEN — page error during the solve"
    if status == "token_stale":
        label = "STALE-TOKEN"
        if "identity_changed" in reason or "sitekey_changed" in reason:
            label += " (challenge/sitekey rotated)"
        if dialog in ("gone", "error"):
            label += "; dialog already gone at token"
        return label
    if status == "auto_failed":
        if reason.startswith("not_accepted"):
            hint = "WRONG-CALLBACK suspicion — no post-token site request" if post == 0 else ""
            return f"NOT-ACCEPTED {hint}".strip()
        if "dialog_gone" in reason:
            return f"DIALOG-GONE — {reason[:70]}"
        return f"AUTO-FAILED — {reason[:70]}"
    return f"UNCLASSIFIED — {status}"


def analyze(folder: Path) -> str:
    manifest, events = _load(folder)
    token_ms, dialog, inject = _token_state(events)
    if "REDACTED" in dialog:  # legacy sanitizer wiped the evidence
        dialog = "? (redacted by old sanitizer)"
    rows = _net_rows(events)
    grecaptcha = sum(1 for _, _, h, _ in rows if "grecaptcha" in h or "recaptcha" in h)
    parts = [
        f"{folder.name}  outcome={manifest.get('outcome', '?')} "
        f"reason={str(manifest.get('reason', ''))[:70]}",
        f"  code={'hardened' if 'attempts' in manifest else 'PRE-HARDENING (no attempts field — app ran old code)'} "
        f"task={manifest.get('task_id', '?')} polls={manifest.get('polls', '?')} "
        f"attempts={manifest.get('attempts', '?')} method={manifest.get('method', '?')}",
        f"  token@{token_ms}ms dialog_at={dialog or '?'} inject={inject[:60] or '?'} "
        f"net={len(rows)} reqs (grecaptcha={grecaptcha})",
        f"  => {_classify(manifest, events)}",
    ]
    return "\n".join(parts)


def _find_session_folders(root: Path) -> list[Path]:
    """Session folders in single, flat (legacy) and per-day layouts."""
    if not root.exists():
        return []
    found = {p.parent for p in root.glob("*/manifest.json")}
    found.update(p.parent for p in root.glob("*/*/manifest.json"))
    if (root / "manifest.json").exists():
        found.add(root)
    return sorted(found, key=lambda p: p.name)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    root = Path(argv[1])
    folders = _find_session_folders(root)
    if not folders:
        print(f"no recordings found under {root}")
        return 1
    for folder in folders:
        print(analyze(folder))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
