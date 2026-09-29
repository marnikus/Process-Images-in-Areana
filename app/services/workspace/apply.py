"""Workspace restore — facade (S5 split).

The mutating restore side was split into focused modules:
- selection.py: which providers, strict deps
- transaction.py: per-domain gates + rollback
- restore_runner.py: preflight, backup, loop, report

This file re-exports public symbols for backward compatibility
(`app.services.workspace.apply.restore_workspace` etc.) and keeps the
typed `RestoreRunContext` that replaces the old untyped dict.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pathlib import Path

from .meta import log_message as _meta_log_message
from .registry import get as _registry_get, restore_order
from .restore_runner import _finish, _preflight, _reconcile_all, restore_workspace as _restore_workspace_impl
from .selection import _selected_ids as _sel_ids, selection_providers as _sel_providers
from .transaction import (
    _apply_domain,
    _checked_doc,
    _dependency_row,
    _guarded,
    _migrated_doc,
    _policy_row,
    _restore_one,
    _restore_row,
    _rollback,
    _skip_row,
    _version_row,
)


@dataclass
class RestoreRunContext:
    """Typed context for one restore execution — replaces untyped dict (S1)."""
    bridge: object
    manifest: dict
    files: dict
    failed: set = field(default_factory=set)


# Registry access — exposed for backward compat and monkeypatching in tests
get = _registry_get
log_message = _meta_log_message

# Selection helpers — wrappers using `get` from this module so monkeypatch works
def _strict_deps(provider) -> list:
    return [dep for dep, kind in (provider.dependencies or {}).items()
            if kind == "strict" and get(dep)]


def expand_strict(providers: list) -> list:
    chosen = {p.domain_id for p in providers}
    pending = list(providers)
    while pending:
        for dep in _strict_deps(pending.pop()):
            if dep not in chosen:
                chosen.add(dep)
                pending.append(get(dep))
    ordered_ids = restore_order(set(chosen))
    return [p for p in (get(i) for i in ordered_ids) if p]


def _selected_ids(manifest: dict, selected) -> list:
    return _sel_ids(manifest, selected)


def selection_providers(manifest: dict, selected) -> tuple:
    return _sel_providers(manifest, selected)


# Logging helper — uses `log_message` from this module so tests can monkeypatch
_RESULT_LEVEL = {"success": "success", "success_with_warnings": "warn"}


def _log_result(bridge, root: Path, report: dict) -> None:
    log_message(bridge,
                f"♻️ Workspace restore from {root.name}: {report['result']} — "
                f"{len(report['restored'])} restored, {len(report['skipped'])} skipped",
                _RESULT_LEVEL.get(report["result"], "error"))


def restore_workspace(bridge, root, selected=None) -> dict:
    # Delegate to runner impl; runner's own _log_result uses meta.log_message,
    # but we want the public restore_workspace to also work when called via apply.
    # The runner impl will log via its own path; we call it directly.
    return _restore_workspace_impl(bridge, root, selected)


# Re-export for backward compat — tests import private helpers from apply
__all__ = [
    "RestoreRunContext",
    "restore_workspace",
    "selection_providers",
    "expand_strict",
    "_selected_ids",
    "_strict_deps",
    "_skip_row",
    "_guarded",
    "_version_row",
    "_policy_row",
    "_rollback",
    "_apply_domain",
    "_dependency_row",
    "_migrated_doc",
    "_checked_doc",
    "_restore_one",
    "_restore_row",
    "_preflight",
    "_log_result",
    "_finish",
    "_reconcile_all",
]
