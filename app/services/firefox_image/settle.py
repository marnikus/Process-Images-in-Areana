"""Settle a Firefox image job without letting review become a plain failure (I-65).

`needs_review` emits status `needs_review` (the reason is the message; the
error field stays empty unless status is `failed`). History only knows
failed/completed, so a review is recorded `failed=True` — never completed.
A clean cancel still emits nothing (I-61), because that path uses `_handle_result`.

Imports: job events/history + the dispatcher result helper (lazy, no cycle at import).
"""

from __future__ import annotations

from app.core.enums import ImageStatus
from app.services.job_history import HistoryInput, record_history


def _ids(job) -> tuple:
    corr = str(getattr(job, "corr_id", "") or "")
    return corr, str(getattr(job, "lane_job_id", "") or corr)


def emit_review(job, err: str) -> None:
    """Tell the window this image needs a person. History does not say completed."""
    from app.services.multi_page_dispatcher import FinishInfo, _emit_finished, _recalc_save
    job.img.status = ImageStatus.NEEDS_REVIEW.value
    job.img.error = err
    corr, job_id = _ids(job)
    _emit_finished(job.bridge, FinishInfo(job_id=job_id, img=job.img,
                                          status="needs_review", message=err or "needs_review"))
    record_history(HistoryInput(bridge=job.bridge, pool=job.pool, img=job.img,
                                tab_id=job.tab_id, job_id=job_id, failed=True, err=err))
    _recalc_save(job.bridge)


def _saved(job) -> bool:
    return job.img.status == ImageStatus.COMPLETED.value and bool(job.img.output_path)


def settle(job, failed: bool, err: str) -> None:
    """Review stays needs_review. A saved file is not wiped by a late cancel."""
    if job.img.status == ImageStatus.NEEDS_REVIEW.value:
        emit_review(job, err or job.img.error or "needs_review")
        return
    _keep_saved(job, failed, err)


def _keep_saved(job, failed: bool, err: str) -> None:
    from app.services.multi_page_dispatcher import _handle_result
    saved = _saved(job)
    flag = bool(getattr(job.bridge, "_cancel_requested", False))
    if saved:
        job.bridge._cancel_requested = False
    try:
        _handle_result(_result_ctx(job, failed, err))
    finally:
        if saved:
            job.bridge._cancel_requested = flag


def _result_ctx(job, failed: bool, err: str):
    from app.services.multi_page_dispatcher import ResultCtx
    corr, job_id = _ids(job)
    return ResultCtx(bridge=job.bridge, pool=job.pool, img=job.img, tab_id=job.tab_id,
                     corr_id=corr, job_id=job_id, failed=failed, err=err)
