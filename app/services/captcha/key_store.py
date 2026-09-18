"""2Captcha key store — local, git-ignored, excluded from presets.

Design ("not exposed publicly"):
* separate file `config/2captcha.json` — NOT in session.json (general state)
  and NOT in arena.json (preset export/import shares that file);
* file mode 0600 best-effort;
* only masked getters cross the WebChannel; the raw key never reaches the
  UI payload or the log console (RULE 20 credential hygiene).
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

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
        if not self._path.exists():
            return CaptchaSettings()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return CaptchaSettings()
        return self._from_dict(data if isinstance(data, dict) else {})

    def _from_dict(self, data: Dict[str, Any]) -> CaptchaSettings:
        key = data.get("api_key", "")
        return CaptchaSettings(
            enabled=bool(data.get("enabled", False)) and bool(key),
            api_key=str(key or "").strip(),
            solve_timeout_sec=clamp_timeout(data.get("solve_timeout_sec", DEFAULT_TIMEOUT_SEC)),
        )

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

    @staticmethod
    def _to_dict(s: CaptchaSettings) -> Dict[str, Any]:
        return {
            "enabled": bool(s.enabled and bool(s.api_key)),
            "api_key": s.api_key,
            "solve_timeout_sec": clamp_timeout(s.solve_timeout_sec),
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
