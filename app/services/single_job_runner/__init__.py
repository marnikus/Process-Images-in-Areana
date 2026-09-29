# ideal-size: 90 lines reason=facade re-exports block runner package for backward compat per RULE 10
"""Single job runner package — facade (split from 1173 LOC file)."""

from __future__ import annotations

from .advance import _handle_advance
from .attach import (
    _attach_emit,
    _attach_open_dialog,
    _handle_attach,
    _handle_marker_highlight,
    _handle_verify_attachment,
    _marker_selector,
    attachment_preview_selector,
    attach_image,
)
from .baseline import capture_baseline, capture_text_baseline, _handle_baseline, _handle_text_baseline
from .context import JobCtx, _OUTPUT_BLOCKS, log
from .custom import (
    _custom_fallbacks,
    _custom_ok_emit,
    _handle_custom,
    _handle_highlight,
    _handle_pause,
    _highlight_spec,
    _str,
)
from .download import _handle_download, _hide_and_result, _hide_overlay, _verify_download, download_image
from .emit import (
    _display,
    _emit_action,
    _emit_saved_rect,
    _get_blocks,
    _mark_busy,
    _mark_waiting,
    _report_recovery,
)
from .handlers import _handler_map
from .loop import (
    _absorb_block_result,
    _block_skip_reason,
    _handle_one_block,
    _loop_blocks,
    _post_download_warning,
    _record_failure,
    _run_one_checked,
    _soft_failures_forgiven,
)
from .preset import (
    _block_preset_name,
    _block_uses_preset,
    _build_final_from_template,
    _load_preset_template,
    _resolve_prompt_from_preset,
)
from .prompt import _handle_prompt, _handle_verify_prompt, _type_highlight, _handle_type_prompt, insert_prompt
from .runner import _captcha_job_line, _emit_captcha_job_lines, _reset_captcha_reports, run_blocks_for_image
from .save import _handle_save, save_image
from .security import _CAPTCHA_FAILURES, _handle_captcha_outcome, _handle_security, _run_security_captcha, check_security
from .state import _init_old_srcs, _is_cancelled, _maybe_delay, _output_secured, _tab_aborted
from .submit import _click_req, _fallback_list, _submit_fallbacks, _submit_visual, _try_click, _handle_submit, submit_job
from .text import (
    _build_description_doc,
    _get_overwrite_flag,
    _handle_generate_description,
    _handle_save_json,
    _handle_wait_text,
    _poll_text_generation,
    _save_description_json_file,
    _show_text_overlay,
    wait_for_text_output,
)
from .validate import _handle_validate, _infer_ext, _pil_format, _src_suffix
from .wait import (
    _arm_revival,
    _clear_revival,
    _drop_wait_hooks,
    _handle_wait,
    _poll_generation,
    _settle_and_note,
    _show_gen_overlay,
    wait_for_output,
)

__all__ = [
    "JobCtx",
    "capture_baseline",
    "capture_text_baseline",
    "check_security",
    "attach_image",
    "insert_prompt",
    "submit_job",
    "wait_for_output",
    "wait_for_text_output",
    "download_image",
    "save_image",
    "run_blocks_for_image",
    "attachment_preview_selector",
]
