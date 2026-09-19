"""Bridge panel mixins — one mixin (slots only) + module functions per file.

Import direction: panels -> services/core/browser (+ qt_compat). Services
never import panels. Bridge composes the mixins (Bridge(QObject, *mixins)).
"""

from app.ui.panels.blocks_library import BlocksLibraryMixin
from app.ui.panels.blocks_stack import BlocksStackMixin
from app.ui.panels.layout_state import LayoutStateMixin
from app.ui.panels.undo_history import UndoHistoryMixin

__all__ = ["BlocksLibraryMixin", "BlocksStackMixin", "LayoutStateMixin", "UndoHistoryMixin"]
