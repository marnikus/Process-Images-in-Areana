"""Who takes part — the one home for domain selection (audit #3 S1).

Both halves of the feature ask the same question against different sources:
save selects over the registry, restore selects over the manifest (which is the
registry of the snapshot being restored). Keeping the rules here — and only
here — is what stops save and restore from drifting apart (audit #3 N6). Pure
registry/manifest logic: no bridge, no files, no Qt.
"""

from __future__ import annotations

from app.persistence.workspace.manifest import entry_for

from .registry import all_providers, get, restore_order


def select_providers(selected) -> tuple:
    """(providers, unknown ids) for a save-style selection over the registry.

    `selected=None` means every registered provider. Unknown ids come back
    named instead of being filtered away (audit #3 N6) — the caller decides
    what to tell the user; nothing is ever dropped without a word.
    """
    providers = all_providers()
    if selected is None:
        return providers, []
    wanted = set(selected)
    picked = [p for p in providers if p.domain_id in wanted]
    known = {p.domain_id for p in picked}
    unknown = [s for s in dict.fromkeys(selected) if s not in known]
    return picked, unknown


def selected_ids(manifest: dict, selected) -> list:
    """Manifest ids for this restore.

    Default (selected=None) restores every domain that owns a file; the
    policy domains (secret keys, recordings) appear in the preview and the
    manifest with their exclusion reason, and join only when explicitly
    selected — then they answer with their policy row, never a silent skip.
    """
    ids = list(manifest.get("domains", {}).keys())
    if selected is None:
        return [i for i in ids if (entry_for(manifest, i) or {}).get("path")]
    wanted = set(selected)
    return [i for i in ids if i in wanted]


def manifest_selection(manifest: dict, selected) -> tuple:
    """Providers + selected ids the manifest lacks + ids no provider owns.

    `unknown` are explicitly selected ids absent from the manifest (refused);
    `orphans` are manifest domains this build has no provider for — a snapshot
    from a newer build. They must be REPORTED (one skip row each), never
    dropped the way `[p for p in providers if p]` used to (audit #3 N5).
    """
    domains = manifest.get("domains", {})
    unknown = [s for s in (selected or []) if s not in domains]
    ordered = restore_order(set(selected_ids(manifest, selected)))
    providers = [get(i) for i in ordered]
    orphans = [i for i, p in zip(ordered, providers) if p is None]
    return [p for p in providers if p], unknown, orphans


def strict_deps(provider) -> list:
    """Registered, resolvable strict dependencies of one provider."""
    return [dep for dep, kind in (provider.dependencies or {}).items()
            if kind == "strict" and get(dep)]


def expand_strict(providers: list) -> list:
    """Strict dependencies ride along automatically (task RESTORE 3) — transitively."""
    chosen = {p.domain_id for p in providers}
    pending = list(providers)
    while pending:
        for dep in strict_deps(pending.pop()):
            if dep not in chosen:
                chosen.add(dep)
                pending.append(get(dep))
    ordered_ids = restore_order(set(chosen))
    return [p for p in (get(i) for i in ordered_ids) if p]
