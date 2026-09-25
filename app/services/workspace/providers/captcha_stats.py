"""captcha_stats provider — `config/captcha_stats.json` (counters + per-site + balance).

Counters are worth keeping; the balance is a live external value and is
marked stale on restore (recomputed on the next Balance click — task rule 7).
"""

from __future__ import annotations

from pathlib import Path

from app.persistence.json_store import load_json, save_json_atomic
from app.services.workspace.provider import ApplyOutcome, CaptureResult, StateProvider

FILE_NAME = "captcha_stats.json"


def stats_file(bridge) -> Path:
    return Path(getattr(bridge.config, "dir", "config")) / FILE_NAME


def stats_error(doc) -> str | None:
    if not isinstance(doc, dict):
        return "document is not an object"
    if "per_site" in doc and not isinstance(doc["per_site"], dict):
        return "'per_site' must be an object"
    return None


class CaptchaStatsProvider(StateProvider):
    """Captcha encounter/solve counters, per-site stats, last balance/error."""

    domain_id = "captcha_stats"
    display_name = "Captcha Statistics"
    native_rel_path = "state/captcha_stats.json"
    schema_version = "1"
    sensitivity = "public"

    def live_paths(self, bridge) -> list:
        return self._one_file(stats_file(bridge))

    def capture(self, bridge) -> CaptureResult:
        return CaptureResult(ok=True, doc=load_json(stats_file(bridge), {}))

    def validate(self, doc) -> str | None:
        return stats_error(doc)

    def plan(self, bridge, doc) -> str:
        return "captcha counters and per-site stats (balance marked stale)"

    def apply(self, bridge, doc) -> ApplyOutcome:
        save_json_atomic(stats_file(bridge), doc)
        return ApplyOutcome(ok=True)

    def reconcile(self, bridge) -> list:
        return ["captcha balance marked stale — refresh it in the Captcha window"]
