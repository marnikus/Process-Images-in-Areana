"""2Captcha key store — local, git-ignored, excluded from presets.

Design ("not exposed publicly"):
* separate file `config/2captcha.json` — NOT in session.json (general state)
  and NOT in arena.json (preset export/import shares that file);
* file mode 0600 best-effort;
* only masked getters cross the WebChannel; the raw key never reaches the
  UI payload or the log console (RULE 20 credential hygiene).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from ...persistence.json_store import atomic_write_json, load_json

DEFAULT_TIMEOUT_SEC = 180
MIN_TIMEOUT_SEC = 30
MAX_TIMEOUT_SEC = 600


@dataclass
class CaptchaSettings:
    enabled: bool = False
    api_key: str = ""
    solve_timeout_sec: int = DEFAULT_TIMEOUT_SEC


def clamp_timeout(value: Any) -> int:
    """User timeout clamped to a sane range, bad values → default."""
    try:
        return max(MIN_TIMEOUT_SEC, min(MAX_TIMEOUT_SEC, int(value)))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SEC


class CaptchaKeyStore:
    """Load/save the 2Captcha settings file; corrupt → defaults (RULE 13)."""

    FILENAME = "2captcha.json"

    def __init__(self, config_dir: str | Path):
        self._path = Path(config_dir) / self.FILENAME

    def load(self) -> CaptchaSettings:
        # corrupt/missing/wrong-type -> default settings (RULE 13, json_store)
        return self._from_dict(load_json(self._path, {}))

    def _from_dict(self, data: Dict[str, Any]) -> CaptchaSettings:
        key = data.get("api_key", "")
        return CaptchaSettings(
            enabled=bool(data.get("enabled", False)) and bool(key),
            api_key=str(key or "").strip(),
            solve_timeout_sec=clamp_timeout(data.get("solve_timeout_sec", DEFAULT_TIMEOUT_SEC)),
        )

    def save(self, settings: CaptchaSettings) -> None:
        # atomic write + 0600 (RULE 20 credential hygiene), via json_store
        atomic_write_json(self._path, self._to_dict(settings), mode=0o600)

    @staticmethod
    def _to_dict(s: CaptchaSettings) -> Dict[str, Any]:
        return {
            "enabled": bool(s.enabled and bool(s.api_key)),
            "api_key": s.api_key,
            "solve_timeout_sec": clamp_timeout(s.solve_timeout_sec),
        }

    @staticmethod
    def mask(key: str) -> str:
        """UI-safe form: first4 + **** + last4; short/empty → short/empty."""
        key = (key or "").strip()
        if len(key) < 8:
            return key
        return f"{key[:4]}****{key[-4:]}"
