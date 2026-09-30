"""The ONE workspace provider table (RULE 10 — no second list).

`PROVIDER_CLASSES` is the single registration list and the single source of
the restore order: a provider that is not in it does not exist, and
`tests/test_workspace_architecture.py` fails if a `StateProvider` subclass is
written anywhere under `providers/` without being added here. Instances are
module-level and stateless — the classes are instantiated once, below.
"""

from __future__ import annotations

from .providers.arena_state import ArenaStateProvider
from .providers.captcha_stats import CaptchaStatsProvider
from .providers.cooldowns import CooldownsProvider
from .providers.job_history import JobHistoryProvider
from .providers.policies import CaptchaKeysProvider, RecordingsProvider
from .providers.preset_stores import ArenaPresetsProvider, WindowPresetsProvider
from .providers.session import GridWindowProvider, SessionSettingsProvider
from .providers.undo import UndoProvider
from .provider import StateProvider

# The one list. Order matters: it is the topological restore order (design
# §B.2 — persisted domains are mutually independent in v1; strict edges, when a
# future domain adds one, skip dependents through the shared machinery).
PROVIDER_CLASSES: tuple = (
    CaptchaKeysProvider, RecordingsProvider, CaptchaStatsProvider,
    CooldownsProvider, ArenaStateProvider, SessionSettingsProvider,
    GridWindowProvider, UndoProvider, WindowPresetsProvider,
    ArenaPresetsProvider, JobHistoryProvider,
)

RESTORE_ORDER = tuple(cls.domain_id for cls in PROVIDER_CLASSES)

_TABLE: dict = {}
for _cls in PROVIDER_CLASSES:
    _provider: StateProvider = _cls()
    _TABLE[_provider.domain_id] = _provider


def restore_order(ids: set) -> list:
    """Registry order first, unknown ids after, sorted (never lose a domain)."""
    known = [i for i in RESTORE_ORDER if i in ids]
    return known + sorted(ids - set(RESTORE_ORDER))


def get(domain_id: str) -> StateProvider | None:
    """Provider by stable domain id (manifest vocabulary), or None."""
    return _TABLE.get(domain_id)


def all_providers() -> list:
    """Every registered provider in RESTORE_ORDER — save iterates this."""
    return [get(domain_id) for domain_id in RESTORE_ORDER if get(domain_id)]


