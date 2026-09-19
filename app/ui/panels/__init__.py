"""Bridge panel mixins — one mixin (slots only) + module functions per file.

Import direction: panels -> services/core/browser (+ qt_compat); acyclic
sibling-panel reuse is allowed (single-source funcs, never import back).
Services never import panels. Bridge composes the mixins
(Bridge(QObject, *mixins)).
"""

from app.ui.panels.app_settings import AppSettingsMixin
from app.ui.panels.blocks_library import BlocksLibraryMixin
from app.ui.panels.blocks_stack import BlocksStackMixin
from app.ui.panels.browser_tabs import BrowserTabsMixin
from app.ui.panels.cdp_tools import CdpToolsMixin
from app.ui.panels.layout_state import LayoutStateMixin
from app.ui.panels.page_pool import PagePoolMixin
from app.ui.panels.queue_scan import QueueScanMixin
from app.ui.panels.run_control import RunControlMixin
from app.ui.panels.undo_history import UndoHistoryMixin
from app.ui.panels.url_queue import UrlQueueMixin
from app.ui.panels.watcher_captcha import WatcherCaptchaMixin

__all__ = [
    "AppSettingsMixin",
    "BlocksLibraryMixin",
    "BlocksStackMixin",
    "BrowserTabsMixin",
    "CdpToolsMixin",
    "LayoutStateMixin",
    "PagePoolMixin",
    "QueueScanMixin",
    "RunControlMixin",
    "UndoHistoryMixin",
    "UrlQueueMixin",
    "WatcherCaptchaMixin",
]
