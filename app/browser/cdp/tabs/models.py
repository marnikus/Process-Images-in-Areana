from __future__ import annotations
from dataclasses import dataclass

@dataclass
class TabInfo:
    id: str
    title: str
    url: str
    ws_url: str
    type: str = "page"

CANDIDATE_HOSTS = ["127.0.0.1", "localhost"]
