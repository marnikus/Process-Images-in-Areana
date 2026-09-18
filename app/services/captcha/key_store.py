"""Solver-provider key store — local, git-ignored, excluded from presets.

One document `config/captcha_solvers.json` holds every provider's credentials
plus the active provider (file mode 0600 best-effort). Design (RULE 20
hygiene, "not exposed publicly"):
* NOT in session.json (general state) and NOT in arena.json (preset
  export/import shares that file) — presets never carry keys;
* only masked getters cross the WebChannel; the raw key never reaches the
  UI payload or the log console;
* the legacy single-provider `config/2captcha.json` is migrated on load
  (read-only import — the old file is never deleted or rewritten).
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from .providers import DEFAULT_PROVIDER, provider_for

DEFAULT_TIMEOUT_SEC = 180
MIN_TIMEOUT_SEC = 30
MAX_TIMEOUT_SEC = 600


@dataclass
class ProviderCreds:
    """One provider's opt-in credentials (enabled requires a key)."""

    enabled: bool = False
    api_key: str = ""


@dataclass
class CaptchaSettings:
    """Store document; `.api_key`/`.enabled` are the ACTIVE provider's values."""

    provider: str = DEFAULT_PROVIDER
    solve_timeout_sec: int = DEFAULT_TIMEOUT_SEC
    creds: Dict[str, ProviderCreds] = field(default_factory=dict)

    @property
    def active(self) -> ProviderCreds:
        return self.creds.get(self.provider) or ProviderCreds()

    @property
    def api_key(self) -> str:
        return self.active.api_key

    @property
    def enabled(self) -> bool:
        return self.active.enabled

    @classmethod
    def for_provider(cls, provider: str, *, enabled: bool = False, api_key: str = "",
                     solve_timeout_sec: int = DEFAULT_TIMEOUT_SEC) -> "CaptchaSettings":
        """Single-provider settings (tests + apply_settings seed)."""
        pid = provider_for(provider).id
        key = (api_key or "").strip()
        creds = {pid: ProviderCreds(enabled=bool(enabled and key), api_key=key)}
        return cls(provider=pid, solve_timeout_sec=clamp_timeout(solve_timeout_sec),
                   creds=creds)


def clamp_timeout(value: Any) -> int:
    """User timeout clamped to a sane range, bad values → default."""
    try:
        return max(MIN_TIMEOUT_SEC, min(MAX_TIMEOUT_SEC, int(value)))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SEC


class CaptchaKeyStore:
    """Load/save the multi-provider settings file; corrupt → defaults (RULE 13)."""

    FILENAME = "captcha_solvers.json"
    LEGACY_FILENAME = "2captcha.json"

    def __init__(self, config_dir: str | Path):
        self._path = Path(config_dir) / self.FILENAME
        self._legacy_path = Path(config_dir) / self.LEGACY_FILENAME

    def load(self) -> CaptchaSettings:
        """New store first; fall back to the legacy single-provider document."""
        data = self._read_json(self._path)
        if data is None:
            data = self._legacy_document()
        return self._from_dict(data if isinstance(data, dict) else {})

    def save(self, settings: CaptchaSettings) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=self._path.stem + "_", suffix=".tmp",
                                   dir=str(self._path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._to_dict(settings), f, indent=2, ensure_ascii=False)
            Path(tmp).replace(self._path)
        finally:
            self._cleanup_tmp(tmp)
        self._lock_mode(self._path)

    def _legacy_document(self) -> Optional[Dict[str, Any]]:
        """Legacy 2captcha.json shape → new document shape (read-only import)."""
        old = self._read_json(self._legacy_path)
        if old is None:
            return None
        key = str(old.get("api_key") or "").strip()
        creds = {DEFAULT_PROVIDER: {"enabled": bool(old.get("enabled")) and bool(key),
                                    "api_key": key}}
        return {"provider": DEFAULT_PROVIDER, "providers": creds,
                "solve_timeout_sec": old.get("solve_timeout_sec", DEFAULT_TIMEOUT_SEC)}

    @staticmethod
    def _read_json(path: Path) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _from_dict(self, data: Dict[str, Any]) -> CaptchaSettings:
        s = CaptchaSettings(
            provider=provider_for(data.get("provider")).id,
            solve_timeout_sec=clamp_timeout(data.get("solve_timeout_sec", DEFAULT_TIMEOUT_SEC)),
            creds=self._creds_from(data.get("providers")))
        if s.provider not in s.creds:  # active provider always has an entry
            s.creds[s.provider] = ProviderCreds()
        return s

    @staticmethod
    def _creds_from(raw: Any) -> Dict[str, ProviderCreds]:
        if not isinstance(raw, dict):
            return {}
        creds = {}
        for pid, entry in raw.items():
            if isinstance(entry, dict):
                key = str(entry.get("api_key") or "").strip()
                creds[str(pid)] = ProviderCreds(
                    enabled=bool(entry.get("enabled")) and bool(key), api_key=key)
        return creds

    @staticmethod
    def _to_dict(s: CaptchaSettings) -> Dict[str, Any]:
        return {
            "provider": provider_for(s.provider).id,
            "solve_timeout_sec": clamp_timeout(s.solve_timeout_sec),
            "providers": {pid: {"enabled": bool(c.enabled and bool(c.api_key)),
                                "api_key": c.api_key}
                          for pid, c in s.creds.items()},
        }

    @staticmethod
    def _cleanup_tmp(tmp: str) -> None:
        try:
            Path(tmp).unlink(missing_ok=True)
        except Exception:
            pass

    @staticmethod
    def _lock_mode(path: Path) -> None:
        try:
            os.chmod(path, 0o600)  # best effort (no-op failure on some FS)
        except Exception:
            pass

    @staticmethod
    def mask(key: str) -> str:
        """UI-safe form: first4 + **** + last4; short/empty → short/empty."""
        key = (key or "").strip()
        if len(key) < 8:
            return key
        return f"{key[:4]}****{key[-4:]}"
