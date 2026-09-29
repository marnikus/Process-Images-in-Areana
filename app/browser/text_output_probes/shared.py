from __future__ import annotations
import json
from ..probe_selectors import assistant_message_selectors, assistant_text_selectors, generating_spinners_js, model_label_probe, user_message_selector

SELECTORS_TEXT = assistant_text_selectors()
SELECTORS_ASSISTANT = assistant_message_selectors()
_GEN_SPINNERS = generating_spinners_js()
_MODEL_LABEL = model_label_probe()
USER_MESSAGE_SELECTOR = user_message_selector
