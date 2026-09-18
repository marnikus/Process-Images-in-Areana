"""UI payloads for the Recordings window (WebChannel-safe dicts).

Pure presentation over the store/service: every envelope carries `ok` and a
bounded body, so the WebChannel never sees a Python object or an unbounded
string. No I/O beyond what the store already guards.
"""

from __future__ import annotations

from typing import Any, Dict

from .diffview import snapshot_diff, timeline_summary

SNAPSHOT_PREVIEW_LIMIT = 1500000  # bound what the WebChannel carries


def list_payload(svc: Any) -> Dict[str, Any]:
    sessions, skipped = svc.store.list_sessions()
    return {"ok": True, "enabled": svc.enabled(), "sessions": sessions,
            "skipped": skipped[:10]}


def detail_payload(store: Any, session_id: str, event_limit: int = 400) -> Dict[str, Any]:
    headers, _ = store.list_sessions()
    header = next((h for h in headers if h.get("id") == session_id), None)
    if header is None:
        return {"ok": False, "error": "unknown session"}
    events = store.load_events(session_id, event_limit)
    return {"ok": True, "session": header, "events": events,
            "timeline": timeline_summary(store.load_events(session_id, 5000))}


def snapshot_payload(store: Any, session_id: str, name: str) -> Dict[str, Any]:
    html = store.load_snapshot(session_id, name)
    if not html:
        return {"ok": False, "error": "snapshot not found"}
    return {"ok": True, "html": html[:SNAPSHOT_PREVIEW_LIMIT]}


def diff_payload(store: Any, spec: Dict[str, str]) -> Dict[str, Any]:
    """spec = {session_a, name_a, session_b, name_b}."""
    html_a = store.load_snapshot(str(spec.get("session_a") or ""), str(spec.get("name_a") or ""))
    html_b = store.load_snapshot(str(spec.get("session_b") or ""), str(spec.get("name_b") or ""))
    if not html_a or not html_b:
        return {"ok": False, "error": "snapshot not found"}
    return {"ok": True, **snapshot_diff(html_a, html_b)}


def label_payload(store: Any, session_id: str, label: str) -> Dict[str, Any]:
    ok, info = store.set_label(session_id, label)
    return {"ok": ok, "label" if ok else "error": info}


def delete_payload(svc: Any, session_id: str) -> Dict[str, Any]:
    if str(session_id) in svc._active:
        return {"ok": False, "error": "recording still active"}
    ok = svc.store.delete(session_id)
    return {"ok": ok, **({} if ok else {"error": "delete failed"})}


def settings_payload(svc: Any) -> Dict[str, Any]:
    return {"ok": True, "enabled": svc.enabled(), "root": str(svc.store.root)}
