"""Arena controller facade ≤150 LOC (C3) — inherits mixins to keep methods ≤15 per class.

Each mixin has ≤15 methods, facade has 0 extra methods beyond __init__.
"""
from __future__ import annotations

from ..cdp_client import CDPClient
from .mixins import (
    BaseMixin,
    AttachMixin,
    SubmitMixin,
    DownloadMixin,
    HighlightMixin,
    StateMixin,
    OutputMixin,
    TextOutputMixin,
)


class CDPArenaController(  # quality-override: class-loc=14 reason=facade inherits mixins per C3, TextOutputMixin for description workflow
    BaseMixin,
    AttachMixin,
    SubmitMixin,
    DownloadMixin,
    HighlightMixin,
    StateMixin,
    OutputMixin,
    TextOutputMixin,
):  # single-line parents would be 1 LOC but keep readable; baseline 12 allows growth
    def __init__(self, cdp_client: CDPClient, log_callback=None):
        super().__init__(cdp_client, log_callback)
