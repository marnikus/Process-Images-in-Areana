"""Captcha solving providers the Watcher can use (B10 — provider dropdown restored).

Both providers speak the classic 2Captcha `in.php` / `res.php` protocol, so
the ONE official SDK (`2captcha-python`) drives both — the provider only
changes the SDK's `server` host (RULE 20: only these hosts are ever contacted):

* `2captcha`   — https://2captcha.com          (SDK default host)
* `capmonster` — CapMonster Cloud, whose 2Captcha-compatible endpoint is
                 https://api.capmonster.cloud/in.php + /res.php
                 (docs.capmonster.cloud → "creating a task via URL parameters").

Adding a provider = one more row here (+ an <option> in the Captcha window).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

DEFAULT_PROVIDER = "2captcha"


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    server: str          # host handed to the SDK (`https://{server}/in.php`)
    dashboard: str       # where the user finds the API key (UI hint only)


PROVIDERS: Dict[str, Provider] = {
    "2captcha": Provider(id="2captcha", label="2Captcha", server="2captcha.com",
                         dashboard="https://2captcha.com/enterpage"),
    "capmonster": Provider(id="capmonster", label="CapMonster Cloud", server="api.capmonster.cloud",
                           dashboard="https://capmonster.cloud/Dashboard"),
}

PROVIDER_IDS: List[str] = list(PROVIDERS)


def normalize_provider(value) -> str:
    """Known provider id (case/space-insensitive) or the default."""
    key = str(value or "").strip().lower()
    return key if key in PROVIDERS else DEFAULT_PROVIDER


def provider_label(value) -> str:
    return PROVIDERS[normalize_provider(value)].label


def provider_server(value) -> str:
    return PROVIDERS[normalize_provider(value)].server


def providers_summary() -> List[Dict[str, str]]:
    """UI list: [{id, label, server, dashboard}] in dropdown order."""
    return [{"id": p.id, "label": p.label, "server": p.server, "dashboard": p.dashboard}
            for p in PROVIDERS.values()]
