from __future__ import annotations
from typing import Any, Dict
from .attach import _handle_attach, _handle_verify_attachment, _handle_marker_highlight
from .baseline import _handle_baseline, _handle_text_baseline
from .custom import _handle_custom, _handle_highlight, _handle_pause
from .download import _handle_download
from .prompt import _handle_prompt, _handle_verify_prompt, _handle_type_prompt
from .save import _handle_save
from .advance import _handle_advance
from .security import _handle_security
from .submit import _handle_submit
from .text import _handle_wait_text, _handle_save_json, _handle_generate_description
from .validate import _handle_validate
from .wait import _handle_wait
from app.services.await_processing import handle_await_processing

def _handler_map():
    """Map block_id to handler (24 block types)."""
    # ideals-TABLED (R10.9): flat registry literal; splitting the dict
    # would scatter the A2 converge map across helpers with no seam.
    return {
        "OBSERVE_BASELINE": _handle_baseline,
        "OBSERVE_TEXT_BASELINE": _handle_text_baseline,
        "CHECK_SECURITY": _handle_security,
        "HIGHLIGHT_ATTACH": _handle_marker_highlight,
        "ATTACH_IMAGE": _handle_attach,
        "VERIFY_ATTACHMENT": _handle_verify_attachment,
        "HIGHLIGHT_PROMPT": _handle_marker_highlight,
        "INSERT_PROMPT": _handle_prompt,
        "VERIFY_PROMPT": _handle_verify_prompt,
        "HIGHLIGHT_SUBMIT": _handle_marker_highlight,
        "SUBMIT": _handle_submit,
        "WAIT_OUTPUT": _handle_wait,
        "WAIT_TEXT_OUTPUT": _handle_wait_text,
        "AWAIT_PROCESSING_IMAGE": handle_await_processing,
        "DOWNLOAD": _handle_download,
        "VALIDATE": _handle_validate,
        "SAVE": _handle_save,
        "SAVE_DESCRIPTION_JSON": _handle_save_json,
        "GENERATE_IMAGE_DESCRIPTION": _handle_generate_description,
        "ADVANCE": _handle_advance,
        "CUSTOM_FIND": _handle_custom,
        "HIGHLIGHT": _handle_highlight,
        "PAUSE": _handle_pause,
        "TYPE_PROMPT": _handle_type_prompt,
    }
