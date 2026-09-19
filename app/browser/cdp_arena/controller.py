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
)


class CDPArenaController(
    BaseMixin,
    AttachMixin,
    SubmitMixin,
    DownloadMixin,
    HighlightMixin,
    StateMixin,
    OutputMixin,
):
    def __init__(self, cdp_client: CDPClient, log_callback=None):
        super().__init__(cdp_client, log_callback)
