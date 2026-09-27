"""Workspace save — the whole SAVE side (design §C.5): selection, coherent
capture under the queue lock, validation, temp build, manifest-last publish,
and the save-report. The recent/last index lives in `snapshot_index.py`.

The folder is built in a sibling temp dir, `manifest.json` is written last
(commit marker), publish is an atomic rename, and the save-report is written
into the published folder so it always reflects reality. A failed save never
touches previous snapshots. Snapshot identity/env live in `meta.py`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from app.persistence.workspace import fsio
from app.persistence.workspace.errors import WorkspaceError
from app.persistence.workspace.integrity import canonical_bytes
from app.persistence.workspace.manifest import build_manifest
from . import reports
from .meta import (app_meta, compat_block, default_base, log_message,
                   snapshot_id_for, utc_now_iso)
from .snapshot_index import record_snapshot


@dataclass
class SaveRequest:
    """Parameters of one workspace save (param object — keeps signatures ≤4)."""
    name: str
    description: str = ""
    selected: list = None
    allow_partial: bool = False
    base_dir: str = ""


@dataclass
class Capture:
    """Per-domain capture bookkeeping for one save run."""
    provider: object
    result: object = None
    error: dict = None
    entry: dict = field(default_factory=dict)


def selected_providers(selected) -> list:
    """All providers, or the explicitly selected subset (save-side selection)."""
    from .registry import all_providers
    providers = all_providers()
    if selected is None:
        return providers
    wanted = set(selected)
    return [p for p in providers if p.domain_id in wanted]


def capture_one(bridge, provider) -> Capture:
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
        return Capture(provider=provider, result=result)
    except WorkspaceError as exc:
        return Capture(provider=provider, error=exc.to_dict())
    except Exception as exc:
        return Capture(provider=provider,
                       error=WorkspaceError(provider.domain_id, "capture", str(exc)).to_dict())


def capture_all(bridge, providers) -> list:
    """One coherent capture pass under the queue funnel's lock (snapshot boundary).

    The lock import is deferred: `live.feed` pulls the whole live stack, and
    import-time coupling state→save would be the wrong direction.
    """
    from app.services.live.feed import state_lock
    with state_lock(bridge):
        return [capture_one(bridge, provider) for provider in providers]


def file_docs(captures: list) -> dict:
    """rel_path → merged native doc (session_settings + grid_window share one file)."""
    docs: dict = {}
    for capture in captures:
        if capture.error or capture.result.excluded or not capture.result.ok:
            continue
        rel = capture.provider.native_rel_path
        doc = capture.result.doc
        docs[rel] = {**docs.get(rel, {}), **doc} if isinstance(doc, dict) else doc
    return docs


def _capture_block(capture) -> dict:
    """The manifest `capture` block: failed, policy-excluded, or included with notes."""
    if capture.error:
        return {"ok": False, "excluded": True, "excluded_reason": capture.error["cause"]}
    if capture.result.excluded:
        return {"ok": True, "excluded": True,
                "excluded_reason": capture.result.excluded_reason,
                "redacted_reference": capture.result.doc}
    return {"ok": True, "excluded": False, "notes": list(capture.result.notes)}


def domain_entries(captures: list, file_entries: dict) -> dict:
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
        entry["capture"] = _capture_block(capture)
        entries[p.domain_id] = entry
    return entries


def _write_state_files(temp: Path, captures: list) -> dict:
    """Native files into `<temp>/state/`, integrity per file (bytes may be shared)."""
    return {rel: fsio.write_bytes(temp, rel, canonical_bytes(doc))
            for rel, doc in file_docs(captures).items()}


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
    providers = selected_providers(request.selected)
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
                          "started": started}, captures)  # `run` context, see _publish_save


def _abort_result(request: SaveRequest, captures: list, started: str) -> dict:
    """A selected domain failed without allow_partial → refuse; no temp was created."""
    names = [c.provider.domain_id for c in captures if c.error]
    return {"ok": False, "result": reports.SAVE_RESULT_FAILED,
            "error": "domain(s) failed to capture: " + ", ".join(names)
                     + " — fix the cause or allow a partial snapshot",
            "errors": [c.error for c in captures if c.error],
            "snapshot_id": snapshot_id_for(started, request.name)}


def _stage(run: dict, captures: list, temp: Path) -> dict:
    """Write state files + env into the temp folder, manifest LAST; return the report."""
    run["file_entries"] = _write_state_files(temp, captures)
    _write_env(temp, run["bridge"])
    started = run["started"]
    timing = {"snapshot_id": snapshot_id_for(started, run["request"].name),
              "started_utc": started, "finished_utc": utc_now_iso()}
    report = reports.save_report(
        timing=timing, domains=_report_rows(captures),
        errors=[c.error for c in captures if c.error], published=True)
    manifest = _snapshot_manifest(run, captures, report)
    fsio.write_bytes(temp, "manifest.json", canonical_bytes(manifest))
    return report


def _publish_save(run: dict, captures: list) -> dict:
    """Build the temp folder, write the manifest last, publish, then report.

    `run` bundles bridge/request/target/started for one save execution.
    """
    bridge, target = run["bridge"], run["target"]
    temp = fsio.new_temp_dir(target)
    try:
        report = _stage(run, captures, temp)
        fsio.publish(temp, target)
    except (OSError, FileExistsError) as exc:
        return _publish_failed(target, temp, exc)
    fsio.write_bytes(target, "reports/save-report.json", canonical_bytes(report))
    record_snapshot(bridge, str(target))
    log_message(bridge, f"💾 Workspace saved: {target.name} — {report['result']}", "success")
    return {"ok": True, **report, "path": str(target)}


def _snapshot_manifest(run: dict, captures: list, report: dict) -> dict:
    """The manifest for this publish (built AFTER the report owns the snapshot id)."""
    request = run["request"]
    header = {"snapshot_id": report["snapshot_id"], "name": request.name,
              "description": request.description, "created_utc": run["started"],
              "snapshot_kind": "partial" if any(c.error for c in captures)
                               else "full"}
    return build_manifest(header=header, app_meta=app_meta(run["bridge"]),
                          compat=compat_block(),
                          domains=domain_entries(captures, run["file_entries"]))


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
