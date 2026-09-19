"""Probe spec vocabulary — adapted from Old App backend/probe_requests.py for Arena."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

MATCH_CONTAINS = "contains"
MATCH_EXACT = "exact"

COLOR_FIND = "#ff2d2d"      # RED
COLOR_CLICK = "#ff9500"     # ORANGE
COLOR_COLLECT = "#00c853"   # GREEN
COLOR_PROMPT = "#00AAFF"    # BLUE
COLOR_SUBMIT = "#FFAA00"    # YELLOW

@dataclass(frozen=True, slots=True)
class FindProbeSpec:
    label_selector: Optional[str] = None
    match_text: Optional[str] = None
    match_mode: str = MATCH_CONTAINS
    highlight: bool = True
    highlight_ms: int = 2000
    color: str = COLOR_FIND
    caption: str = "FOUND"
    max_candidates: int = 6

@dataclass(frozen=True, slots=True)
class ClickProbeSpec:
    highlight: bool = True
    highlight_ms: int = 2000
    color: str = COLOR_CLICK
    caption: str = "CLICK"
    do_click: bool = True

@dataclass(frozen=True, slots=True)
class HighlightSpec:
    label_selector: Optional[str] = None
    match_text: Optional[str] = None
    match_mode: str = MATCH_CONTAINS
    color: str = COLOR_COLLECT
    caption: str = "MATCH"
    highlight_ms: int = 2000
    clear_first: bool = True
