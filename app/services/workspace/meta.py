"""Workspace meta — snapshot identity, app environment, shared paths/log.

The one home for everything that describes a snapshot rather than moving
state: config paths, UTC stamps, snapshot ids, the redacted app-env block,
the compat block, and the bridge log helper. No capture/apply logic lives
here (that is save.py / apply.py). No Qt, no app.ui imports.
"""

from __future__ import annotations

import platform
import subprocess
import time
from pathlib import Path

from app.core.window_catalog import GRID_VERSION
from app.persistence.workspace.manifest import FORMAT_NAME, MIN_WORKSPACE_FORMAT, WORKSPACE_FORMAT

META_FILE = "workspace_meta.json"
DEFAULT_DIR_NAME = "workspaces"
RECENT_CAP = 10          # recent-snapshot list length
TEMP_MAX = 10            # stale unpublished temp folders tolerated (fsio hygiene)


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


def log_message(bridge, message: str, level: str = "info") -> None:
    """Best-effort bridge log (never raises — reporting must not kill a run)."""
    try:
        bridge._log(message, level)
    except Exception:
        pass
