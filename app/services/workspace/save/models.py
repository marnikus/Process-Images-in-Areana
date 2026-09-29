from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class SaveRequest:
    name: str
    description: str = ""
    selected: list = None
    allow_partial: bool = False
    base_dir: str = ""

@dataclass
class SaveRunContext:
    bridge: object
    request: SaveRequest
    target: Path
    started_utc: str
    file_entries: dict = field(default_factory=dict)

@dataclass
class Capture:
    provider: object
    result: object = None
    error: dict = None
    entry: dict = field(default_factory=dict)
