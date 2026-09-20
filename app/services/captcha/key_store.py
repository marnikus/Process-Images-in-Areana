"""Captcha solver key store — local, git-ignored, excluded from presets.

B10 (2026-10-06): multi-provider again. The Captcha window offers a provider
dropdown (2Captcha / CapMonster Cloud); each provider keeps its own API key
and the active one is what the Watcher's SdkSolver uses.

File: `config/captcha_solvers.json` — the shape the pre-import app used:

    {"provider": "2captcha", "solve_timeout_sec": 180,
     "providers": {"2captcha":   {"enabled": true, "api_key": "..."},
                   "capmonster": {"enabled": true, "api_key": "..."}}}

Legacy: `config/2captcha.json` (single-provider file written by the
2026-10-02 UI). While it exists its key is authoritative for the 2Captcha
slot (it is the newest thing the user saved with the old UI); the first
`save()` folds it into captcha_solvers.json and removes it.

Design ("not exposed publicly"):
* NOT in session.json (general state) and NOT in arena.json (preset
  export/import shares that file);
* file mode 0600 best-effort;
* only masked getters cross the WebChannel; the raw key never reaches the
  UI payload or the log console (RULE 20 credential hygiene).
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

from app.services.captcha_watcher.providers import (
    DEFAULT_PROVIDER,
    PROVIDER_IDS,
    normalize_provider,
)

DEFAULT_TIMEOUT_SEC = 180
MIN_TIMEOUT_SEC = 30
MAX_TIMEOUT_SEC = 600


def _clean_keys(keys) -> Dict[str, str]:
    """{provider id → stripped key}; blank keys and non-dicts drop out."""
    out: Dict[str, str] = {}
    for pid, raw in (keys or {}).items():
        key = str(raw or "").strip()
        if key:
            out[normalize_provider(pid)] = key
    return out


@dataclass
class CaptchaSettings:
    enabled: bool = False
    api_key: str = ""                 # key of the ACTIVE provider (compat view)
    solve_timeout_sec: int = DEFAULT_TIMEOUT_SEC
    provider: str = DEFAULT_PROVIDER
    keys: Dict[str, str] = field(default_factory=dict)   # provider id → api key

    def __post_init__(self) -> None:
        self.provider = normalize_provider(self.provider)
        self.keys = _clean_keys(self.keys)
        self.api_key = str(self.api_key or "").strip()
        if self.api_key:
            self.keys[self.provider] = self.api_key      # explicit key wins for the active provider
        else:
            self.api_key = self.keys.get(self.provider, "")

    def key_for(self, provider: str) -> str:
        return self.keys.get(normalize_provider(provider), "")

    def with_provider(self, provider: str) -> "CaptchaSettings":
        """Same keys/timeout, another active provider."""
        return CaptchaSettings(enabled=self.enabled, api_key="", solve_timeout_sec=self.solve_timeout_sec,
                               provider=provider, keys=dict(self.keys))

    def with_key(self, provider: str, key: str) -> "CaptchaSettings":
        """Same settings with one provider's key replaced (empty removes it)."""
        keys = dict(self.keys)
        pid = normalize_provider(provider)
        key = str(key or "").strip()
        if key:
            keys[pid] = key
        else:
            keys.pop(pid, None)
        return CaptchaSettings(enabled=self.enabled, api_key="", solve_timeout_sec=self.solve_timeout_sec,
                               provider=self.provider, keys=keys)


def clamp_timeout(value: Any) -> int:
    """User timeout clamped to a sane range, bad values → default."""
    try:
        return max(MIN_TIMEOUT_SEC, min(MAX_TIMEOUT_SEC, int(value)))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SEC


def _read_json(path: Path) -> Dict[str, Any]:
    """Dict content of a JSON file; missing/corrupt/non-object → {} (RULE 13)."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_legacy_mirror(path: Path, settings: CaptchaSettings) -> None:
    """Best-effort: legacy file mirrors the saved 2Captcha key (never raises)."""
    try:
        path.write_text(json.dumps({
            "enabled": False, "api_key": settings.key_for("2captcha"),
            "solve_timeout_sec": clamp_timeout(settings.solve_timeout_sec)}, indent=2), encoding="utf-8")
    except Exception:
        pass


def _keys_from_providers(data: Dict[str, Any]) -> Dict[str, str]:
    """`providers: {id: {api_key} | key}` → clean {id → key} ({} when malformed)."""
    providers = data.get("providers")
    if not isinstance(providers, dict):
        return {}
    return _clean_keys({pid: (entry.get("api_key", "") if isinstance(entry, dict) else entry)
                        for pid, entry in providers.items()})


def _merge_keys(data: Dict[str, Any], legacy: Dict[str, Any], provider: str) -> Dict[str, str]:
    """providers{} keys + flat `api_key` (→ active provider) + legacy 2captcha.json (wins for 2Captcha)."""
    keys = _keys_from_providers(data)
    flat_key = str(data.get("api_key", "") or "").strip()
    if flat_key and not keys.get(provider):
        keys[provider] = flat_key
    legacy_key = str(legacy.get("api_key", "") or "").strip()
    if legacy_key:
        keys["2captcha"] = legacy_key          # authoritative until migrated by save()
    return keys


class CaptchaKeyStore:
    """Load/save the solver settings file; corrupt → defaults (RULE 13)."""

    FILENAME = "captcha_solvers.json"
    LEGACY_FILENAME = "2captcha.json"

    def __init__(self, config_dir: str | Path):
        self._path = Path(config_dir) / self.FILENAME
        self._legacy_path = Path(config_dir) / self.LEGACY_FILENAME

    # ------------------------------------------------------------------ load

    def load(self) -> CaptchaSettings:
        data = _read_json(self._path)
        legacy = _read_json(self._legacy_path)
        provider = normalize_provider(data.get("provider", DEFAULT_PROVIDER))
        timeout = data.get("solve_timeout_sec", legacy.get("solve_timeout_sec", DEFAULT_TIMEOUT_SEC))
        settings = CaptchaSettings(
            enabled=bool(data.get("enabled", legacy.get("enabled", False))),
            api_key="",
            solve_timeout_sec=clamp_timeout(timeout),
            provider=provider,
            keys=_merge_keys(data, legacy, provider),
        )
        settings.enabled = settings.enabled and bool(settings.api_key)
        return settings

    @property
    def has_legacy_file(self) -> bool:
        return self._legacy_path.exists()

    # ------------------------------------------------------------------ save

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
        self._retire_legacy(settings)

    def _retire_legacy(self, settings: CaptchaSettings) -> None:
        """Fold config/2captcha.json away; if it cannot be removed keep it in
        step with the saved 2Captcha key so it never re-imports a stale one."""
        if not self._legacy_path.exists():
            return
        try:
            self._legacy_path.unlink()
            return
        except Exception:
            pass
        _write_legacy_mirror(self._legacy_path, settings)

    @staticmethod
    def _to_dict(s: CaptchaSettings) -> Dict[str, Any]:
        providers = {pid: {"enabled": bool(s.keys.get(pid)), "api_key": s.keys.get(pid, "")}
                     for pid in PROVIDER_IDS}
        for pid, key in s.keys.items():                 # keep keys of ids not in the registry
            providers.setdefault(pid, {"enabled": bool(key), "api_key": key})
        return {
            "provider": s.provider,
            "enabled": bool(s.enabled and bool(s.api_key)),
            "solve_timeout_sec": clamp_timeout(s.solve_timeout_sec),
            "providers": providers,
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
