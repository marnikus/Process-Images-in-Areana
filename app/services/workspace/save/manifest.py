from __future__ import annotations
from app.persistence.workspace import fsio
from app.persistence.workspace.integrity import canonical_bytes
from app.persistence.workspace.manifest import FORMAT_NAME, WORKSPACE_FORMAT, build_manifest
from ..meta import app_meta, compat_block, default_base, log_message, snapshot_id_for, utc_now_iso
from ..providers.policies import INCLUSION_POLICY

def inclusion_policy() -> dict:
    return dict(INCLUSION_POLICY)

def _write_env(temp, bridge) -> None:
    env = {**app_meta(bridge), "grid_version": compat_block()["grid_version"], "workspace_format": WORKSPACE_FORMAT, "format": FORMAT_NAME, "inclusion_policy": inclusion_policy()}
    fsio.write_bytes(temp, "metadata/app-environment.json", canonical_bytes(env))

def _report_rows(captures: list) -> list:
    return [{"domain_id": c.provider.domain_id, "required": bool(c.provider.required), "ok": not c.error and bool(c.result and c.result.ok), "excluded": bool(c.error or (c.result and c.result.excluded))} for c in captures]

def _snapshot_manifest(ctx, captures: list, report: dict) -> dict:
    header = {"snapshot_id": report["snapshot_id"], "name": ctx.request.name, "description": ctx.request.description, "created_utc": ctx.started_utc, "snapshot_kind": "partial" if any(c.error for c in captures) else "full"}
    return build_manifest(header=header, app_meta=app_meta(ctx.bridge), compat=compat_block(), domains=domain_entries(captures, ctx.file_entries))

from .capture import domain_entries
