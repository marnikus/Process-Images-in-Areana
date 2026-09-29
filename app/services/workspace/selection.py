"""Workspace restore selection — which domains, strict deps, unknown ids.

Split from apply.py (S5) — one responsibility: decide the provider list for
a restore run. No file IO, no mutation, only registry + manifest.
"""

from __future__ import annotations

from app.persistence.workspace.manifest import entry_for
from .registry import get, restore_order


def _selected_ids(manifest: dict, selected) -> list:
    """Manifest ids for this restore — default = every domain with a file."""
    ids = list(manifest.get("domains", {}).keys())
    if selected is None:
        return [i for i in ids if (entry_for(manifest, i) or {}).get("path")]
    wanted = set(selected)
    return [i for i in ids if i in wanted]


def selection_providers(manifest: dict, selected) -> tuple:
    """Providers for this restore + unknown-id rows (manifest is registry)."""
    unknown = [s for s in (selected or []) if s not in manifest.get("domains", {})]
    ordered = restore_order(set(_selected_ids(manifest, selected)))
    providers = [get(i) for i in ordered]
    return [p for p in providers if p], unknown


def _strict_deps(provider) -> list:
    """Registered, resolvable strict dependencies of one provider."""
    return [dep for dep, kind in (provider.dependencies or {}).items()
            if kind == "strict" and get(dep)]


def expand_strict(providers: list) -> list:
    """Strict dependencies ride along automatically — transitively."""
    chosen = {p.domain_id for p in providers}
    pending = list(providers)
    while pending:
        for dep in _strict_deps(pending.pop()):
            if dep not in chosen:
                chosen.add(dep)
                pending.append(get(dep))
    ordered_ids = restore_order(set(chosen))
    return [p for p in (get(i) for i in ordered_ids) if p]
