"""Workspace restore — backward compat alias for preview (S12).

The preview logic now lives in `preview.py` (clearer name: preview vs mutating
restore). This module re-exports for backward compatibility — existing imports
`from app.services.workspace.restore import preview_restore` keep working.
"""

from __future__ import annotations

from .preview import (
    _file_status,
    _folder_root,
    _inside,
    _preview_row,
    _remap_notes,
    _row_head,
    preview_restore,
)

__all__ = [
    "preview_restore",
    "_inside",
    "_row_head",
    "_file_status",
    "_preview_row",
    "_folder_root",
    "_remap_notes",
]
