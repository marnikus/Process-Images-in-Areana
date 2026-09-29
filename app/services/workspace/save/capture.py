from __future__ import annotations
from typing import List
from app.persistence.workspace import fsio
from app.persistence.workspace.errors import WorkspaceError
from app.persistence.workspace.integrity import canonical_bytes
from .models import Capture
from ..registry import all_providers

def selected_providers(selected) -> list:
    providers = all_providers()
    if selected is None:
        return providers
    wanted = set(selected)
    return [p for p in providers if p.domain_id in wanted]

def capture_one(bridge, provider) -> Capture:
    try:
        result = provider.capture(bridge)
        if not result.ok:
            raise WorkspaceError(provider.domain_id, "capture", "capture failed: " + ("; ".join(result.notes) or "unknown"))
        if not result.excluded:
            err = provider.validate(result.doc)
            if err:
                raise WorkspaceError(provider.domain_id, "semantic", err)
        return Capture(provider=provider, result=result)
    except WorkspaceError as exc:
        return Capture(provider=provider, error=exc.to_dict())
    except Exception as exc:
        return Capture(provider=provider, error=WorkspaceError(provider.domain_id, "capture", str(exc)).to_dict())

def capture_all(bridge, providers) -> list:
    from app.services.live.feed import state_lock
    with state_lock(bridge):
        return [capture_one(bridge, provider) for provider in providers]

def file_docs(captures: list) -> dict:
    docs: dict = {}
    for capture in captures:
        if capture.error or capture.result.excluded or not capture.result.ok:
            continue
        rel = capture.provider.native_rel_path
        doc = capture.result.doc
        docs[rel] = {**docs.get(rel, {}), **doc} if isinstance(doc, dict) else doc
    return docs

def _capture_block(capture) -> dict:
    if capture.error:
        return {"ok": False, "excluded": True, "excluded_reason": capture.error["cause"]}
    if capture.result.excluded:
        return {"ok": True, "excluded": True, "excluded_reason": capture.result.excluded_reason, "redacted_reference": capture.result.doc}
    return {"ok": True, "excluded": False, "notes": list(capture.result.notes)}

def domain_entries(captures: list, file_entries: dict) -> dict:
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

def _write_state_files(temp, captures: list) -> dict:
    return {rel: fsio.write_bytes(temp, rel, canonical_bytes(doc)) for rel, doc in file_docs(captures).items()}
