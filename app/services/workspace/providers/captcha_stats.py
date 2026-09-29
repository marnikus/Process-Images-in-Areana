"""captcha_stats provider — `config/captcha_stats.json` (counters + per-site + balance).

Counters are worth keeping; the balance is a live external value and is
marked stale on restore (recomputed on the next Balance click — task rule 7).
"""

from __future__ import annotations

from pathlib import Path

from pathlib import Path

from app.services.workspace.provider import config_dir
from app.services.workspace.providers._base import JsonFileProvider

FILE_NAME = "captcha_stats.json"


def stats_file(bridge) -> Path:
    return config_dir(bridge) / FILE_NAME


def stats_error(doc) -> str | None:
    if not isinstance(doc, dict):
        return "document is not an object"
    if "per_site" in doc and not isinstance(doc["per_site"], dict):
        return "'per_site' must be an object"
    return None


class CaptchaStatsProvider(JsonFileProvider):
    """Captcha encounter/solve counters, per-site stats, last balance/error."""

    domain_id = "captcha_stats"
    display_name = "Captcha Statistics"
    native_rel_path = "state/captcha_stats.json"
    schema_version = "1"
    sensitivity = "public"

    def file_path(self, bridge) -> Path:
        return stats_file(bridge)

    def validate(self, doc) -> str | None:
        return stats_error(doc)

    def reconcile(self, bridge) -> list:
        return ["captcha balance marked stale — refresh it in the Captcha window"]
