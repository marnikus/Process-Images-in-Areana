from __future__ import annotations
from typing import Dict
from ..selector import SelectorObject
from .chat import SELECTORS_CHAT
from .composer import SELECTORS_COMPOSER
from .security import SELECTORS_SECURITY
from .account import SELECTORS_ACCOUNT

SELECTORS: Dict[str, SelectorObject] = {}
SELECTORS.update(SELECTORS_CHAT)
SELECTORS.update(SELECTORS_COMPOSER)
SELECTORS.update(SELECTORS_SECURITY)
SELECTORS.update(SELECTORS_ACCOUNT)
