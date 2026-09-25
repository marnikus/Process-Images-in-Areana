"""Workspace save — the SAVE algorithm (design §C.5) and snapshot meta.

Split from `coordinator.py` (shared helpers) to keep both files inside the
RULE 18 budget. The folder is built in a sibling temp dir, `manifest.json`
is written last (commit marker), publish is an atomic rename, and the
save-report is written into the published folder so it always reflects
reality. A failed save never touches previous snapshots.
"""

from __future__ import annotations

import time
from pathlib import Path

from app.persistence.json_store import load_json, save_json_atomic
from app.persistence.workspace import fsio
from app.persistence.workspace.integrity import canonical_bytes
from app.persistence.workspace.manifest import build_manifest
from . import reports
from .coordinator import (META_FILE, RECENT_CAP, SaveRequest, _domain_entries,
                          _file_docs, _log, _selected_providers, app_meta,
                          capture_all, compat_block, config_dir, default_base,
                          snapshot_id_for, utc_now_iso)


def _write_state_files(temp: Path, captures: list) -> dict:
    """Native files into `<temp>/state/`, integrity per file (bytes may be shared)."""
    return {rel: fsio.write_bytes(temp, rel, canonical_bytes(doc))
            for rel, doc in _file_docs(captures).items()}


def inclusion_policy() -> dict:
    """Documented per-resource inclusion policy (design §D.3) — one home: policies."""
    from .providers.policies import INCLUSION_POLICY
    return dict(INCLUSION_POLICY)


def _write_env(temp: Path, bridge) -> None:
    """metadata/app-environment.json — redacted (no user paths, no secrets)."""
    from app.persistence.workspace.manifest import FORMAT_NAME, WORKSPACE_FORMAT
    env = {**app_meta(bridge), "grid_version": compat_block()["grid_version"],
           "workspace_format": WORKSPACE_FORMAT, "format": FORMAT_NAME,
           "inclusion_policy": inclusion_policy()}
    fsio.write_bytes(temp, "metadata/app-environment.json", canonical_bytes(env))


def _report_rows(captures: list) -> list:
    return [{"domain_id": c.provider.domain_id,
             "ok": not c.error and bool(c.result and c.result.ok),
             "excluded": bool(c.error or (c.result and c.result.excluded))}
            for c in captures]


def save_workspace(bridge, request: SaveRequest) -> dict:
    """Capture → temp folder → manifest last → atomic publish (design §C.5)."""
    started = utc_now_iso()
    providers = _selected_providers(request.selected)
    if not providers:
        return {"ok": False, "error": "no domains selected"}
    target = (Path(request.base_dir) if request.base_dir
              else default_base(bridge)) / fsio.snapshot_dir_name(
                  request.name, time.gmtime())
    captures = capture_all(bridge, providers)
    failed = [c for c in captures if c.error]
    if failed and not request.allow_partial:
        return _abort_result(request, captures, started)
    return _publish_save({"bridge": bridge, "request": request, "target": target,
                          "started": started}, captures)


def _abort_result(request: SaveRequest, captures: list, started: str) -> dict:
    """A selected domain failed without allow_partial → refuse; no temp was created."""
    names = [c.provider.domain_id for c in captures if c.error]
    return {"ok": False, "result": reports.SAVE_RESULT_FAILED,
            "error": "domain(s) failed to capture: " + ", ".join(names)
                     + " — fix the cause or allow a partial snapshot",
            "errors": [c.error for c in captures if c.error],
            "snapshot_id": snapshot_id_for(started, request.name)}


def _publish_save(plan: dict, captures: list) -> dict:
    """Build the temp folder, write the manifest last, publish, then report.

    `plan` bundles bridge/request/target/started for the publish step.
    """
    bridge, request = plan["bridge"], plan["request"]
    target, started = plan["target"], plan["started"]
    temp = fsio.new_temp_dir(target)
    try:
        plan["file_entries"] = _write_state_files(temp, captures)
        _write_env(temp, bridge)
        timing = {"snapshot_id": snapshot_id_for(started, request.name),
                  "started_utc": started, "finished_utc": utc_now_iso()}
        report = reports.save_report(
            timing=timing, domains=_report_rows(captures),
            errors=[c.error for c in captures if c.error], published=True)
        manifest = _snapshot_manifest(plan, captures, report)
        fsio.write_bytes(temp, "manifest.json", canonical_bytes(manifest))
        fsio.publish(temp, target)
    except (OSError, FileExistsError) as exc:
        return _publish_failed(target, temp, exc)
    fsio.write_bytes(target, "reports/save-report.json", canonical_bytes(report))
    _record_snapshot(bridge, str(target))
    _log(bridge, f"💾 Workspace saved: {target.name} — {report['result']}", "success")
    return {"ok": True, **report, "path": str(target)}


def _snapshot_manifest(plan: dict, captures: list, report: dict) -> dict:
    """The manifest for this publish (built AFTER the report owns the snapshot id)."""
    request = plan["request"]
    header = {"snapshot_id": report["snapshot_id"], "name": request.name,
              "description": request.description, "created_utc": plan["started"],
              "snapshot_kind": "partial" if any(c.error for c in captures)
                               else "full"}
    return build_manifest(header=header, app_meta=app_meta(plan["bridge"]),
                          compat=compat_block(),
                          domains=_domain_entries(captures, plan["file_entries"]))


def _publish_failed(target: Path, temp: Path, exc: Exception) -> dict:
    """Publish failed → retain the temp as <target>.failed-<ts>, never claim success."""
    failed = target.with_name(target.name + ".failed-" + time.strftime("%H%M%S"))
    try:
        temp.rename(failed)
    except OSError:
        pass
    return {"ok": False, "result": reports.SAVE_RESULT_FAILED,
            "error": f"publish failed: {exc}", "failed_folder": str(failed),
            "previous_snapshots_untouched": True}


# ---- snapshot meta (recent list, last save/restore, quick load) ----

def _meta_path(bridge) -> Path:
    return config_dir(bridge) / META_FILE


def _read_meta(bridge) -> dict:
    meta = load_json(_meta_path(bridge), {})
    return meta if isinstance(meta, dict) else {}


def _write_meta(bridge, meta: dict) -> None:
    try:
        save_json_atomic(_meta_path(bridge), meta)
    except OSError:
        pass


def _record_snapshot(bridge, path: str) -> None:
    meta = _read_meta(bridge)
    recent = [p for p in meta.get("recent", []) if p != path]
    recent.insert(0, path)
    meta["recent"] = recent[:RECENT_CAP]
    meta["last_snapshot"] = {"path": path, "utc": utc_now_iso()}
    _write_meta(bridge, meta)


def record_restore(bridge, root: str, result: str) -> None:
    meta = _read_meta(bridge)
    meta["last_restore"] = {"path": str(root), "utc": utc_now_iso(), "result": result}
    _write_meta(bridge, meta)


def recent_snapshots(bridge, limit: int = RECENT_CAP) -> list:
    """Existing recent snapshots (missing ones pruned from the list, never shown)."""
    meta = _read_meta(bridge)
    kept = [p for p in meta.get("recent", []) if Path(p).exists()]
    if len(kept) != len(meta.get("recent", [])):
        meta["recent"] = kept
        _write_meta(bridge, meta)
    return kept[:max(1, int(limit))]


def last_snapshot(bridge) -> str:
    """The quick-load target: the last successful save, when it still exists."""
    meta = _read_meta(bridge)
    path = (meta.get("last_snapshot") or {}).get("path", "")
    return path if path and Path(path).exists() else ""


def last_restore(bridge) -> dict:
    """The last restore attempt ({path, utc, result}) for the window's status line."""
    meta = _read_meta(bridge)
    return meta.get("last_restore") or {}
