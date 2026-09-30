"""captcha_stats provider — `config/captcha_stats.json` (counters + per-site + balance).

Counters are worth keeping; the balance is a live external value and is
marked stale on restore (recomputed on the next Balance click — task rule 7).
"""

from __future__ import annotations

from pathlib import Path

from app.persistence.json_store import save_json_atomic
from app.services.workspace.provider import (ApplyOutcome, CaptureResult, StateProvider,
                                         config_dir, live_capture, members, object_doc)

FILE_NAME = "captcha_stats.json"


def stats_file(bridge) -> Path:
    return config_dir(bridge) / FILE_NAME


def stats_error(doc) -> str | None:
    if (shape := object_doc(doc)):
        return shape
    return members(doc, per_site=dict)


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
        return live_capture(stats_file(bridge))

    def validate(self, doc) -> str | None:
        return stats_error(doc)

    def apply(self, bridge, doc) -> ApplyOutcome:
        save_json_atomic(stats_file(bridge), doc)
        return ApplyOutcome(ok=True)

    def reconcile(self, bridge) -> list:
        return ["captcha balance marked stale — refresh it in the Captcha window"]
