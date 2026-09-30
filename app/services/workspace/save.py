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
from .meta import (app_meta, compat_block, default_base, inclusion_policy,
                   log_message, snapshot_id_for, utc_now_iso)
from .registry import all_providers
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


@dataclass(frozen=True)
class SnapshotIdentity:
    """The redacted app identity + compat block, read ONCE per save.

    `meta.app_meta` shells out to `git rev-parse`; building it twice (once for
    the environment file, once for the manifest) spawned the process twice per
    checkpoint for a value that is constant for the process. Both consumers
    now read the same snapshot of it, and the two consumers of the compat keys
    (`environment` and `build_manifest`) share one dict.
    """
    app: dict
    compat: dict

    @classmethod
    def read(cls, bridge) -> "SnapshotIdentity":
        return cls(app=app_meta(bridge), compat=compat_block())

    def environment(self) -> dict:
        """metadata/app-environment.json — exactly the documented key set."""
        return {**self.app, "grid_version": self.compat["grid_version"],
                "workspace_format": self.compat["workspace_format"],
                "format": self.compat["format"],
                "inclusion_policy": inclusion_policy()}


def selected_providers(selected) -> list:
    """All providers, or the explicitly selected subset (save-side selection)."""
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


def _write_env(temp: Path, identity: "SnapshotIdentity") -> None:
    """metadata/app-environment.json — redacted (no user paths, no secrets)."""
    fsio.write_bytes(temp, "metadata/app-environment.json",
                     canonical_bytes(identity.environment()))


def _report_rows(captures: list) -> list:
    return [{"domain_id": c.provider.domain_id, "required": bool(c.provider.required),
             "ok": not c.error and bool(c.result and c.result.ok),
             "excluded": bool(c.error or (c.result and c.result.excluded))}
            for c in captures]


def save_workspace(bridge, request: SaveRequest) -> dict:
    """Capture → temp folder → manifest last → atomic publish (design §C.5)."""
    started = utc_now_iso()
    providers = selected_providers(request.selected)
    if not providers:
        return _refused(bridge, "no domains selected")
    target = _target_folder(bridge, request)
    captures = capture_all(bridge, providers)
    if _blocking(captures) and not request.allow_partial:
        return _abort_result(bridge, request, captures, started)
    return _publish_save({"bridge": bridge, "request": request, "target": target,
                          "started": started}, captures)  # `run` context, see _publish_save


def _blocking(captures: list) -> list:
    """The failed captures that make a save unusable: the REQUIRED ones.

    A non-required domain that fails (a corrupt captcha_stats file, a missing
    cooldown file) degrades the snapshot to `partial` and is listed in the
    report and the log — it does not block a checkpoint the user asked for.
    A required one (arena_state, session_settings — the queue, URLs, prompt
    and settings) means the snapshot would be missing the state the restore
    exists to recover, so the save refuses unless `allow_partial`.
    """
    return [c for c in captures if c.error and c.provider.required]


def _refused(bridge, error: str) -> dict:
    """One refusal helper: the error line is written ONCE, at error level (RULE 2).

    Every way a save can fail says so in the Activity Log and in
    `logs/arena.log`, not only in the reply the Workspace window shows — the
    save may have been fired by a preset, an undo, or nothing on screen.
    """
    log_message(bridge, f"❌ Workspace save refused: {error}", "error")
    return {"ok": False, "error": error}


def _target_folder(bridge, request: SaveRequest) -> Path:
    """Where this save publishes: a free folder under the base, never a collision.

    Two saves in the same second used to produce the same folder name, and the
    second one was refused with "target already exists" — a legitimate action
    reported as a failure. `fsio.unique_dir` gives the second save its own
    `-02` folder, which still sorts chronologically.
    """
    base = Path(request.base_dir) if request.base_dir else default_base(bridge)
    return fsio.unique_dir(base, fsio.snapshot_dir_name(request.name, time.gmtime()))


def _abort_result(bridge, request: SaveRequest, captures: list, started: str) -> dict:
    """A REQUIRED domain failed without allow_partial → refuse; no temp was created."""
    result = _refused(bridge, "required domain(s) failed to capture: "
                      + _causes(_blocking(captures))
                      + " — fix the cause or allow a partial snapshot")
    return {**result, "result": reports.SAVE_RESULT_FAILED,
            "errors": [c.error for c in captures if c.error],
            "snapshot_id": snapshot_id_for(started, request.name)}


def _causes(captures: list) -> str:
    """`domain (cause)` for each — a refusal must say WHY (RULE 2)."""
    return ", ".join(f"{c.provider.domain_id} ({c.error['cause']})" for c in captures)


def _stage(run: dict, captures: list, temp: Path, identity: SnapshotIdentity) -> dict:
    """Write state files + env into the temp folder, manifest LAST; return the report."""
    run["file_entries"] = _write_state_files(temp, captures)
    _write_env(temp, identity)
    started = run["started"]
    timing = {"snapshot_id": snapshot_id_for(started, run["request"].name),
              "started_utc": started, "finished_utc": utc_now_iso()}
    report = reports.save_report(
        timing=timing, domains=_report_rows(captures),
        errors=[c.error for c in captures if c.error])
    manifest = _snapshot_manifest(run, captures, report, identity)
    fsio.write_bytes(temp, "manifest.json", canonical_bytes(manifest))
    return report


def _publish_save(run: dict, captures: list) -> dict:
    """Build the temp folder, write the manifest last, publish, then report.

    `run` bundles bridge/request/target/started for one save execution.
    """
    bridge, target = run["bridge"], run["target"]
    identity = SnapshotIdentity.read(bridge)
    temp = fsio.new_temp_dir(target)
    try:
        report = _stage(run, captures, temp, identity)
        fsio.publish(temp, target)
    except OSError as exc:  # FileExistsError is an OSError
        return _publish_failed(bridge, target, temp, exc)
    record_snapshot(bridge, str(target))
    note = fsio.write_report(target, "reports/save-report.json", canonical_bytes(report))
    log_message(bridge, f"💾 Workspace saved: {target.name} — {report['result']}", _LEVELS[report["result"]])
    return {"ok": True, **report, "path": str(target), **({"report_note": note} if note else {})}


_LEVELS = {"success": "success", "partial": "warn"}


def _snapshot_manifest(run: dict, captures: list, report: dict,
                       identity: SnapshotIdentity) -> dict:
    """The manifest for this publish (built AFTER the report owns the snapshot id)."""
    request = run["request"]
    header = {"snapshot_id": report["snapshot_id"], "name": request.name,
              "description": request.description, "created_utc": run["started"],
              "snapshot_kind": "partial" if any(c.error for c in captures)
                               else "full"}
    return build_manifest(header=header, app_meta=identity.app, compat=identity.compat,
                          domains=domain_entries(captures, run["file_entries"]))


def _publish_failed(bridge, target: Path, temp: Path, exc: Exception) -> dict:
    """Publish failed → retain the temp as <target>.failed-<ts>, never claim success."""
    failed = target.with_name(target.name + ".failed-" + time.strftime("%H%M%S"))
    try:
        temp.rename(failed)
    except OSError:
        failed = temp            # the partial folder stays where it is — say so
    result = _refused(bridge, f"publish failed: {exc}")
    return {**result, "result": reports.SAVE_RESULT_FAILED,
            "failed_folder": str(failed), "previous_snapshots_untouched": True}
