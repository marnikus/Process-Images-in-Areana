"""Workspace coordinator — save side, snapshot meta, recent-snapshot list.

Thin orchestrator over the provider table (design §C.5): providers are
captured coherently under the queue lock, validated immediately, written
into a sibling temp folder, manifest last, then published atomically. A
failed save never touches previous snapshots; a required-domain failure
aborts unless the user explicitly allows a partial snapshot. No Qt.
"""

from __future__ import annotations

import platform
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.core.window_catalog import GRID_VERSION
from app.persistence.workspace.errors import WorkspaceError
from app.persistence.workspace.manifest import (FORMAT_NAME, MIN_WORKSPACE_FORMAT,
                                                WORKSPACE_FORMAT)
from .registry import all_providers

META_FILE = "workspace_meta.json"
DEFAULT_DIR_NAME = "workspaces"
RECENT_CAP = 10
TEMP_MAX = 10


@dataclass
class SaveRequest:
    """Parameters of one workspace save (param object — keeps signatures ≤4)."""
    name: str
    description: str = ""
    selected: list = None
    allow_partial: bool = False
    base_dir: str = ""


@dataclass
class _Capture:
    """Per-domain capture bookkeeping for one save run."""
    provider: object
    result: object = None
    error: dict = None
    entry: dict = field(default_factory=dict)


def config_dir(bridge) -> Path:
    return Path(getattr(bridge.config, "dir", "config"))


def default_base(bridge) -> Path:
    return config_dir(bridge) / DEFAULT_DIR_NAME


def utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def snapshot_id_for(created_utc: str, name: str) -> str:
    from app.persistence.workspace.integrity import sha256_bytes
    digest = sha256_bytes(f"{name}|{created_utc}".encode("utf-8"))[:8]
    return f"ws_{created_utc.replace('-', '').replace(':', '')}_{digest}"


def app_meta(bridge) -> dict:
    """Redacted app/environment block (no user paths, no secrets)."""
    return {
        "version": getattr(bridge.state, "version", "1.0.0"),
        "build": _build_sha(),
        "platform": platform.system(),
        "python": platform.python_version(),
    }


def _build_sha() -> str:
    try:
        here = Path(__file__).resolve().parents[2]
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=here,
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def compat_block() -> dict:
    return {"min_workspace_format": MIN_WORKSPACE_FORMAT, "grid_version": GRID_VERSION,
            "format": FORMAT_NAME, "workspace_format": WORKSPACE_FORMAT}


def _log(bridge, message: str, level: str = "info") -> None:
    try:
        bridge._log(message, level)
    except Exception:
        pass


def _selected_providers(selected) -> list:
    providers = all_providers()
    if selected is None:
        return providers
    wanted = set(selected)
    return [p for p in providers if p.domain_id in wanted]


def _capture_one(bridge, provider) -> _Capture:
    """Capture + immediate validation (SAVE algorithm step 1/3); failure → excluded entry."""
    try:
        result = provider.capture(bridge)
        if not result.ok:
            raise WorkspaceError(provider.domain_id, "capture",
                                 "capture failed: " + ("; ".join(result.notes) or "unknown"))
        if not result.excluded:
            err = provider.validate(result.doc)
            if err:
                raise WorkspaceError(provider.domain_id, "semantic", err)
        return _Capture(provider=provider, result=result)
    except WorkspaceError as exc:
        return _Capture(provider=provider, error=exc.to_dict())
    except Exception as exc:
        return _Capture(provider=provider,
                        error=WorkspaceError(provider.domain_id, "apply", str(exc)).to_dict())


def capture_all(bridge, providers) -> list:
    """One coherent capture pass under the queue funnel's lock (snapshot boundary)."""
    from app.services.live.feed import state_lock
    with state_lock(bridge):
        return [_capture_one(bridge, provider) for provider in providers]


def _file_docs(captures: list) -> dict:
    """rel_path → merged native doc (session_settings + grid_window share one file)."""
    docs: dict = {}
    for capture in captures:
        if capture.error or capture.result.excluded or not capture.result.ok:
            continue
        rel = capture.provider.native_rel_path
        doc = capture.result.doc
        docs[rel] = {**docs.get(rel, {}), **doc} if isinstance(doc, dict) else doc
    return docs


def _domain_entries(captures: list, file_entries: dict) -> dict:
    """One manifest entry per registered domain — included fully, excluded with reason."""
    entries = {}
    for capture in captures:
        p = capture.provider
        entry = {
            "display_name": p.display_name, "path": p.native_rel_path,
            "schema_version": p.schema_version,
            "supported_migrations": list(p.supported_migrations),
            "required": p.required, "dependencies": dict(p.dependencies),
            "sensitivity": p.sensitivity,
        }
        entry.update(file_entries.get(p.native_rel_path, {}))
        if capture.error:
            entry["capture"] = {"ok": False, "excluded": True,
                                "excluded_reason": capture.error["cause"]}
        elif capture.result.excluded:
            entry["capture"] = {"ok": True, "excluded": True,
                                "excluded_reason": capture.result.excluded_reason,
                                "redacted_reference": capture.result.doc}
        else:
            entry["capture"] = {"ok": True, "excluded": False,
                                "notes": list(capture.result.notes)}
        entries[p.domain_id] = entry
    return entries
