# ideal-size: 20 lines reason=facade for text_output_probes package
from __future__ import annotations
from .baseline import JS_BASELINE_TEXT, build_baseline_text_js
from .check import JS_CHECK_NEW_TEXT, build_check_text_js

__all__ = ["build_baseline_text_js", "build_check_text_js", "JS_BASELINE_TEXT", "JS_CHECK_NEW_TEXT"]
