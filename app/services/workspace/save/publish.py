from __future__ import annotations
import time
from pathlib import Path
from app.persistence.workspace import fsio
from app.persistence.workspace.integrity import canonical_bytes
from .. import reports
from .capture import capture_all, selected_providers
from .manifest import _report_rows, _snapshot_manifest, _write_env
from .capture import _write_state_files
from ..meta import default_base, log_message, snapshot_id_for, utc_now_iso
from .models import SaveRequest, SaveRunContext
from ..snapshot_index import record_snapshot

def save_workspace(bridge, request: SaveRequest) -> dict:
    started = utc_now_iso()
    providers = selected_providers(request.selected)
    if not providers:
        return {"ok": False, "error": "no domains selected"}
    target = (Path(request.base_dir) if request.base_dir else default_base(bridge)) / fsio.snapshot_dir_name(request.name, time.gmtime())
    captures = capture_all(bridge, providers)
    failed = [c for c in captures if c.error]
    if failed and not request.allow_partial:
        return _abort_result(request, captures, started)
    ctx = SaveRunContext(bridge=bridge, request=request, target=target, started_utc=started)
    return _publish_save(ctx, captures)

def _abort_result(request: SaveRequest, captures: list, started: str) -> dict:
    names = [c.provider.domain_id for c in captures if c.error]
    return {"ok": False, "result": reports.SAVE_RESULT_FAILED, "error": "domain(s) failed to capture: " + ", ".join(names) + " — fix the cause or allow a partial snapshot", "errors": [c.error for c in captures if c.error], "snapshot_id": snapshot_id_for(started, request.name)}

def _stage(ctx: SaveRunContext, captures: list, temp: Path) -> dict:
    ctx.file_entries = _write_state_files(temp, captures)
    _write_env(temp, ctx.bridge)
    timing = {"snapshot_id": snapshot_id_for(ctx.started_utc, ctx.request.name), "started_utc": ctx.started_utc, "finished_utc": utc_now_iso()}
    report = reports.save_report(timing=timing, domains=_report_rows(captures), errors=[c.error for c in captures if c.error], published=True)
    manifest = _snapshot_manifest(ctx, captures, report)
    fsio.write_bytes(temp, "manifest.json", canonical_bytes(manifest))
    return report

def _publish_save(ctx: SaveRunContext, captures: list) -> dict:
    temp = fsio.new_temp_dir(ctx.target)
    try:
        report = _stage(ctx, captures, temp)
        fsio.publish(temp, ctx.target)
    except OSError as exc:
        return _publish_failed(ctx.target, temp, exc)
    record_snapshot(ctx.bridge, str(ctx.target))
    note = fsio.write_report(ctx.target, "reports/save-report.json", canonical_bytes(report))
    log_message(ctx.bridge, f"💾 Workspace saved: {ctx.target.name} — {report['result']}", "success")
    return {"ok": True, **report, "path": str(ctx.target), **({"report_note": note} if note else {})}

def _publish_failed(target: Path, temp: Path, exc: Exception) -> dict:
    failed = target.with_name(target.name + ".failed-" + time.strftime("%H%M%S"))
    try:
        temp.rename(failed)
    except OSError:
        failed = temp
    return {"ok": False, "result": reports.SAVE_RESULT_FAILED, "error": f"publish failed: {exc}", "failed_folder": str(failed), "previous_snapshots_untouched": True}
