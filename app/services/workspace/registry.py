"""The ONE workspace provider table (RULE 10 — no second list).

`RESTORE_ORDER` is the topological restore order (design §B.2: persisted
domains are mutually independent in v1; strict edges, when a future domain
adds one, skip dependents through the shared machinery). Instantiation is
module-level: providers are stateless.
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

RESTORE_ORDER = (
    "captcha_keys", "captcha_recordings", "captcha_stats", "cooldowns",
    "arena_state", "session_settings", "grid_window", "undo",
    "window_presets", "arena_presets", "job_history",
)

_TABLE: dict = {}
for _cls in (CaptchaKeysProvider, RecordingsProvider, CaptchaStatsProvider,
             CooldownsProvider, ArenaStateProvider, SessionSettingsProvider,
             GridWindowProvider, UndoProvider, WindowPresetsProvider,
             ArenaPresetsProvider, JobHistoryProvider):
    _provider = _cls()
    _TABLE[_provider.domain_id] = _provider


def get(domain_id: str) -> StateProvider | None:
    """Provider by stable domain id (manifest vocabulary), or None."""
    return _TABLE.get(domain_id)


def all_providers() -> list:
    """Every registered provider in RESTORE_ORDER — save iterates this."""
    return [get(domain_id) for domain_id in RESTORE_ORDER if get(domain_id)]


def file_providers() -> list:
    """Providers that own a workspace file (policy-excluded domains stay out)."""
    return [p for p in all_providers() if p.native_rel_path]
