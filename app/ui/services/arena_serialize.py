"""Arena state -> JS serialization (pure, no Qt/signals).

Owns the AppState.to_dict() -> JS-friendly shape mapping (one section per
function). Panels call `arena_to_js(state)`; Bridge keeps no copy.
"""

from __future__ import annotations

from typing import Any, Dict, List


def urls_to_js(d: Dict[str, Any]) -> List[Dict[str, Any]]:
    """URL rows -> {id, url, enabled, status, last_error, ...}."""
    out = []
    for u in d.get("urls", []):
        out.append({
            "id": u.get("id"),
            "url": u.get("url"),
            "enabled": u.get("enabled", True),
            "status": u.get("last_status", "unchecked"),
            "last_error": u.get("error", ""),
            "last_checked": u.get("last_checked"),
            "tab_id": u.get("tab_id", ""),
            "receiver": bool(u.get("receiver", False)),
        })
    return out


def images_to_js(d: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Image rows -> JS queue fields."""
    out = []
    for img in d.get("images", []):
        out.append({
            "id": img.get("id"),
            "relative_path": img.get("relative_path"),
            "absolute_path": img.get("absolute_path"),
            "filename": img.get("filename"),
            "status": img.get("status", "pending"),
            "selected": img.get("selected", False),
            "assigned_url": img.get("assigned_url_id") or "",
            "attempts": img.get("attempt_count", 0),
            "output_path": img.get("output_path") or "",
            "error": img.get("error") or "",
            "size": img.get("size", 0),
        })
    return out


def prompt_to_js(d: Dict[str, Any]) -> Dict[str, Any]:
    """Prompt -> {template}."""
    return {"template": d.get("prompt", {}).get("user_prompt", "")}


def settings_to_js(d: Dict[str, Any]) -> Dict[str, Any]:
    """Settings -> flattened timeouts/output/highlight/browser view."""
    # ideals-TABLED (R10.9): flat 12-key view mapping at CC 1; one key
    # per line is the readable shape, any split would scatter the wire view.
    settings_dict = d.get("settings", {})
    timeouts = settings_dict.get("timeouts", {})
    output = settings_dict.get("output", {})
    highlight = settings_dict.get("highlight", {})
    browser = settings_dict.get("browser", {})
    return {
        "timeout_seconds": timeouts.get("page_load", 30),
        "generation_timeout": timeouts.get("generation", 180),
        "max_retries": settings_dict.get("retries", {}).get("max_attempts", 3),
        "naming_suffix": output.get("suffix", "_AI"),
        "supported_types": d.get("folder", {}).get("supported_types", [".png", ".jpg"]),
        "overwrite": output.get("overwrite", False),
        "highlight_duration": highlight.get("duration_seconds", 3),
        "max_concurrent": settings_dict.get("concurrency", 1),
        "browser": browser,
        "output": output,
        "highlight": highlight,
        "timeouts": timeouts,
    }


def arena_to_js(state) -> Dict[str, Any]:
    """Full AppState -> JS-friendly shape (matches old bridge contract)."""
    d = state.to_dict()
    return {
        "version": d.get("version"),
        "urls": urls_to_js(d),
        "images": images_to_js(d),
        "folder": d.get("folder", {}),
        "prompt": prompt_to_js(d),
        "settings": settings_to_js(d),
        "progress": d.get("progress", {}),
        "run_state": d.get("run_state"),
        "jobs": d.get("jobs", []),
    }
