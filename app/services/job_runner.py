"""
Job Runner — orchestrates primary processing workflow.
Refactored C16: split into handlers to meet RULE16/18 (LOC≤30, CC≤10, class≤150).
"""
import asyncio
from pathlib import Path
from typing import Optional, Callable, Dict, Any
from datetime import datetime

from ..core.models import ImageItem, UrlRow, JobRecord, JobRequest, AppState
from ..core.enums import ImageStatus, JobStatus
from ..utils.correlation import generate_correlation_id, build_final_prompt
from ..core.naming import OutputSpec, get_output_path, atomic_write_bytes
from ..browser.controller import BrowserController
from .verification import VerificationService


class _Logger:
    def __init__(self, state: AppState, cb: Optional[Callable] = None):
        self._state = state
        self._cb = cb

    def log(self, job_id: str, msg: str, level: str = "info", extra: Dict[str, Any] = None):
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "job_id": job_id,
            "message": msg,
            "level": level,
            "extra": extra or {},
        }
        print(f"[{entry['timestamp']}] [{job_id}] {msg}")
        if self._cb:
            self._cb(entry)
        for job in self._state.jobs:
            if job.job_id == job_id:
                job.logs.append(entry)
                break


class _BaselineHandler:
    def __init__(self, browser: BrowserController, logger: _Logger):
        self._browser = browser
        self._logger = logger

    async def ensure_ready(self):
        ready, reasons = await self._browser.is_page_ready()
        if not ready:
            raise RuntimeError(f"Page not ready: {', '.join(reasons)}")

    async def capture(self, job: JobRecord):
        baseline = await self._browser.capture_baseline()
        job.baseline = baseline
        self._logger.log(job.job_id, f"Baseline captured: {baseline.get('output_count')} outputs")
        return baseline

    async def check_security(self, job: JobRecord, waiter):
        if not await self._browser.is_security_dialog_visible():
            return
        job.status = JobStatus.PAUSED_USER_ACTION.value
        self._logger.log(job.job_id, "Security verification detected, pausing", level="warning")
        await waiter(job)


class _AttachmentHandler:
    def __init__(self, browser: BrowserController, verification: VerificationService, logger: _Logger):
        self._browser = browser
        self._verif = verification
        self._logger = logger

    async def attach(self, job: JobRecord, image: ImageItem):
        job.status = JobStatus.ATTACHING.value
        self._logger.log(job.job_id, f"Attaching image {image.absolute_path}")
        ok = await self._browser.attach_image(image.absolute_path)
        if not ok:
            raise RuntimeError("Attachment failed: file input not found")

    async def _try_remove_and_reattach(self, image: ImageItem):
        try:
            sel_remove = self._browser.page.locator('button[aria-label="Remove file"]').first
            if await sel_remove.is_visible():
                await sel_remove.click()
                await self._browser.page.wait_for_timeout(500)
                return await self._browser.attach_image(image.absolute_path)
        except Exception:
            pass
        return False

    async def verify(self, job: JobRecord, image: ImageItem):
        verified, reason = await self._verif.verify_attachment_success(image.filename)
        if verified:
            job.status = JobStatus.ATTACHMENT_VERIFIED.value
            self._logger.log(job.job_id, f"Attachment verified: {reason}")
            return
        self._logger.log(job.job_id, f"Attachment verification failed: {reason}, retrying", level="warning")
        await self._browser.page.wait_for_timeout(1000)
        await self._try_remove_and_reattach(image)
        verified, reason = await self._verif.verify_attachment_success(image.filename)
        if not verified:
            raise RuntimeError(f"Attachment verification failed after retry: {reason}")
        job.status = JobStatus.ATTACHMENT_VERIFIED.value
        self._logger.log(job.job_id, f"Attachment verified: {reason}")


class _PromptHandler:
    def __init__(self, browser: BrowserController, verification: VerificationService, logger: _Logger):
        self._browser = browser
        self._verif = verification
        self._logger = logger

    async def insert(self, job: JobRecord, final_prompt: str, correlation_id: str):
        job.status = JobStatus.PROMPT_INSERTED.value
        self._logger.log(job.job_id, f"Inserting prompt with correlation {correlation_id}")
        ok = await self._browser.insert_prompt(final_prompt)
        if not ok:
            raise RuntimeError("Prompt insertion failed")

    async def verify(self, job: JobRecord, final_prompt: str):
        verified, reason = await self._verif.verify_prompt_text(final_prompt)
        if verified:
            job.status = JobStatus.PROMPT_VERIFIED.value
            self._logger.log(job.job_id, f"Prompt verified: {reason}")
            return
        self._logger.log(job.job_id, f"Prompt mismatch: {reason}, correcting", level="warning")
        await self._browser.insert_prompt(final_prompt)
        verified, reason = await self._verif.verify_prompt_text(final_prompt)
        if not verified:
            raise RuntimeError(f"Prompt verification failed: {reason}")
        job.status = JobStatus.PROMPT_VERIFIED.value
        self._logger.log(job.job_id, f"Prompt verified: {reason}")


class _SubmitHandler:
    def __init__(self, browser: BrowserController, verification: VerificationService, logger: _Logger):
        self._browser = browser
        self._verif = verification
        self._logger = logger

    async def submit(self, job: JobRecord):
        self._logger.log(job.job_id, "Submitting once")
        submitted, reason = await self._browser.submit()
        if not submitted:
            raise RuntimeError(f"Submit failed: {reason}")
        job.submitted_at = datetime.utcnow().isoformat() + "Z"
        job.status = JobStatus.SUBMITTED.value

    async def verify_started(self, job: JobRecord, baseline):
        verified, reason = await self._verif.verify_submission_started(baseline)
        if not verified:
            self._logger.log(job.job_id, f"Submission not confirmed: {reason}, continuing", level="warning")


class _GenerationHandler:
    def __init__(self, browser: BrowserController, logger: _Logger, timeouts: dict):
        self._browser = browser
        self._logger = logger
        self._timeouts = timeouts

    async def wait(self, job: JobRecord, baseline, waiter):
        job.status = JobStatus.WAITING_GENERATION.value
        self._logger.log(job.job_id, "Waiting for generation")
        gen_timeout = self._timeouts.get("generation", 180) * 1000
        status, data = await self._browser.wait_for_generation(baseline, timeout=gen_timeout)
        if status == "paused_user_action":
            job.status = JobStatus.PAUSED_USER_ACTION.value
            self._logger.log(job.job_id, f"Paused for user action: {data.get('reason')}", level="warning")
            await waiter(job)
            status, data = await self._browser.wait_for_generation(baseline, timeout=gen_timeout)
        if status == "failed":
            raise RuntimeError(f"Generation failed or timeout: {data.get('error')}")
        return status, data


class _OutputHandler:
    def __init__(self, verification: VerificationService, logger: _Logger):
        self._verif = verification
        self._logger = logger

    async def detect(self, job: JobRecord, image: ImageItem, baseline, wait_data):
        job.status = JobStatus.OUTPUT_DETECTED.value
        is_valid, data, reason = await self._verif.verify_output_new_and_correlated(baseline)
        if not is_valid:
            return self._needs_review(job, image, f"Output correlation uncertain: {reason}")
        new_src = wait_data.get("new_src") or data.get("new_output", {}).get("src")
        if not new_src:
            new_src = data.get("new_output", {}).get("src")
        if not new_src:
            return self._needs_review(job, image, "New output src not found")
        job.output_src = new_src
        self._logger.log(job.job_id, f"New output detected: {new_src}")
        return new_src, data

    def _needs_review(self, job: JobRecord, image: ImageItem, err: str):
        job.status = JobStatus.NEEDS_REVIEW.value
        job.needs_review = True
        job.error = err
        image.status = ImageStatus.NEEDS_REVIEW.value
        image.error = err
        self._logger.log(job.job_id, f"Needs review: {err}", level="warning")
        return None

    async def download(self, job: JobRecord, browser: BrowserController, new_src: str):
        job.status = JobStatus.DOWNLOADING.value
        self._logger.log(job.job_id, f"Downloading {new_src}")
        success, file_bytes, ctype = await browser.download_image(new_src)
        if not success:
            raise RuntimeError(f"Download failed: {ctype}")
        return file_bytes, ctype

    async def validate(self, job: JobRecord, file_bytes: bytes, ctype: str):
        job.status = JobStatus.VALIDATING.value
        valid, error, metadata = await self._verif.validate_downloaded_file(file_bytes, ctype)
        if not valid:
            raise RuntimeError(f"Downloaded file invalid: {error}")
        job.output_metadata = metadata
        self._logger.log(job.job_id, f"Download validated: {metadata}")
        return metadata

    def save(self, job: JobRecord, image: ImageItem, file_bytes: bytes, save_ctx: dict):
        job.status = JobStatus.SAVING.value
        source_path = Path(image.absolute_path)
        metadata = save_ctx.get("metadata", {})
        output_cfg = save_ctx.get("output_cfg", {})
        fmt = metadata.get("format")
        downloaded_ext = f".{fmt}" if fmt and not fmt.startswith(".") else fmt
        spec = OutputSpec(
            suffix=output_cfg.get("suffix", "_AI"),
            preserve_format=output_cfg.get("preserve_format", True),
            overwrite=output_cfg.get("overwrite", False),
            downloaded_ext=downloaded_ext,
            unique_template=output_cfg.get("unique_suffix_template", "{base}_AI_{n}{ext}"),
        )
        output_path = get_output_path(source_path, spec)
        atomic_write_bytes(source_path.parent, output_path, file_bytes)
        job.saved_path = str(output_path)
        image.output_path = str(output_path)
        self._logger.log(job.job_id, f"Saved to {output_path}")


class _SingleJobExecutor:
    def __init__(self, browser: BrowserController, state: AppState, logger: _Logger, verification: VerificationService):
        self._browser = browser
        self._state = state
        self._logger = logger
        self._verification = verification
        self._baseline_h = _BaselineHandler(browser, logger)
        self._attach_h = _AttachmentHandler(browser, verification, logger)
        self._prompt_h = _PromptHandler(browser, verification, logger)
        self._submit_h = _SubmitHandler(browser, verification, logger)
        self._gen_h = _GenerationHandler(browser, logger, state.settings.timeouts)
        self._output_h = _OutputHandler(verification, logger)

    async def _wait_for_user_action(self, job: JobRecord, cancel_flag):
        self._logger.log(job.job_id, "Waiting for user to complete security verification...", level="warning")
        while True:
            if cancel_flag():
                raise RuntimeError("Cancelled during user action wait")
            if not await self._browser.is_security_dialog_visible():
                ready, _ = await self._browser.is_page_ready()
                if ready:
                    self._logger.log(job.job_id, "Security dialog gone, page ready again")
                    break
            await asyncio.sleep(2)

    def _create_job(self, image: ImageItem, url_row: UrlRow, user_prompt: str, attempt: int):
        correlation_id = generate_correlation_id()
        final_prompt = build_final_prompt(correlation_id, user_prompt)
        job = JobRecord.create(JobRequest(image, url_row, correlation_id, final_prompt, attempt))
        self._state.jobs.append(job)
        image.status = ImageStatus.PROCESSING.value
        image.assigned_url_id = url_row.id
        image.attempt_count = attempt
        self._logger.log(job.job_id, f"Starting job for {image.relative_path} with URL {url_row.url}, attempt {attempt}")
        return job, final_prompt, correlation_id

    async def _run_steps(self, ctx: dict):
        job = ctx["job"]
        image = ctx["image"]
        final_prompt = ctx["final_prompt"]
        correlation_id = ctx["correlation_id"]
        cancel_flag = ctx["cancel_flag"]
        waiter = lambda j: self._wait_for_user_action(j, cancel_flag)
        await self._baseline_h.ensure_ready()
        baseline = await self._baseline_h.capture(job)
        await self._baseline_h.check_security(job, waiter)
        await self._attach_h.attach(job, image)
        await self._attach_h.verify(job, image)
        await self._prompt_h.insert(job, final_prompt, correlation_id)
        await self._prompt_h.verify(job, final_prompt)
        await self._submit_h.submit(job)
        await self._submit_h.verify_started(job, baseline)
        _, wait_data = await self._gen_h.wait(job, baseline, waiter)
        result = await self._output_h.detect(job, image, baseline, wait_data)
        if result is None:
            return job
        new_src, data = result
        file_bytes, ctype = await self._output_h.download(job, self._browser, new_src)
        metadata = await self._output_h.validate(job, file_bytes, ctype)
        self._output_h.save(job, image, file_bytes, {"metadata": metadata, "output_cfg": self._state.settings.output})
        job.status = JobStatus.COMPLETED.value
        image.status = ImageStatus.COMPLETED.value
        image.error = None
        self._logger.log(job.job_id, "Job completed successfully")
        return job

    async def execute(self, ctx: dict) -> JobRecord:
        image = ctx["image"]
        url_row = ctx["url_row"]
        user_prompt = ctx["user_prompt"]
        attempt = ctx.get("attempt", 1)
        cancel_flag = ctx.get("cancel_flag", lambda: False)
        job, final_prompt, correlation_id = self._create_job(image, url_row, user_prompt, attempt)
        try:
            return await self._run_steps({"job": job, "image": image, "final_prompt": final_prompt, "correlation_id": correlation_id, "cancel_flag": cancel_flag})
        except Exception as e:
            job.status = JobStatus.FAILED.value
            job.error = str(e)
            image.status = ImageStatus.FAILED.value
            image.error = str(e)
            self._logger.log(job.job_id, f"Job failed: {e}", level="error")
            return job
        finally:
            self._state.recalculate_progress()


class _BatchExecutor:
    def __init__(self, browser: BrowserController, state: AppState, logger: _Logger, single_executor: _SingleJobExecutor):
        self._browser = browser
        self._state = state
        self._logger = logger
        self._single = single_executor

    def _ready_urls(self, urls):
        return [u for u in urls if u.enabled and u.last_status == "ready"]

    def _selected_images(self, images):
        return [img for img in images if img.selected and img.status in [ImageStatus.PENDING.value, ImageStatus.SELECTED.value, ImageStatus.FAILED.value]]

    async def _wait_if_paused(self, pause_flag, cancel_flag):
        while pause_flag():
            self._logger.log("batch", "Paused, waiting for resume...")
            await asyncio.sleep(1)
            if cancel_flag():
                break

    async def _ensure_url(self, url_row: UrlRow):
        if self._browser.page and self._browser.page.url != url_row.url:
            await self._browser.navigate(url_row.url)

    def _check_attempts(self, img: ImageItem, max_attempts: int) -> bool:
        attempt = img.attempt_count + 1
        if attempt > max_attempts:
            self._logger.log("batch", f"Skipping {img.relative_path} — max attempts reached", level="warning")
            img.status = ImageStatus.SKIPPED.value
            img.error = "Max attempts reached"
            return False
        return True

    async def _process_one(self, ctx: dict):
        img = ctx["img"]
        url_row = ctx["url_row"]
        user_prompt = ctx["user_prompt"]
        cancel_flag = ctx.get("cancel_flag", lambda: False)
        progress_cb = ctx.get("progress_cb")
        img.assigned_url_id = url_row.id
        await self._ensure_url(url_row)
        max_attempts = self._state.settings.retries.get("max_attempts", 3)
        if not self._check_attempts(img, max_attempts):
            return
        attempt = img.attempt_count + 1
        job = await self._single.execute({"image": img, "url_row": url_row, "user_prompt": user_prompt, "attempt": attempt, "cancel_flag": cancel_flag})
        if progress_cb:
            progress_cb(job, img)
        await asyncio.sleep(1)

    async def run(self, batch_ctx: dict):
        images = batch_ctx["images"]
        urls = batch_ctx["urls"]
        user_prompt = batch_ctx["user_prompt"]
        progress_cb = batch_ctx.get("progress_cb")
        cancel_flag = batch_ctx.get("cancel_flag", lambda: False)
        pause_flag = batch_ctx.get("pause_flag", lambda: False)
        stop_flag = batch_ctx.get("stop_flag", lambda: False)
        ready_urls = self._ready_urls(urls)
        if not ready_urls:
            raise RuntimeError("No ready URLs available")
        selected_images = self._selected_images(images)
        if not selected_images:
            self._logger.log("batch", "No selected pending images")
            return
        self._logger.log("batch", f"Starting batch with {len(selected_images)} images, {len(ready_urls)} ready URLs")
        url_index = 0
        for img in selected_images:
            if cancel_flag():
                self._logger.log("batch", "Batch cancelled")
                break
            if stop_flag():
                self._logger.log("batch", "Stopping after current as requested")
                break
            await self._wait_if_paused(pause_flag, cancel_flag)
            url_row = ready_urls[url_index % len(ready_urls)]
            url_index += 1
            await self._process_one({"img": img, "url_row": url_row, "user_prompt": user_prompt, "cancel_flag": cancel_flag, "progress_cb": progress_cb})
        self._logger.log("batch", "Batch complete")


class JobRunner:
    def __init__(self, browser: BrowserController, state: AppState, log_callback: Optional[Callable[[str], None]] = None):
        self.browser = browser
        self.state = state
        self.verification = VerificationService(browser)
        self._logger = _Logger(state, log_callback)
        self._single = _SingleJobExecutor(browser, state, self._logger, self.verification)
        self._batch = _BatchExecutor(browser, state, self._logger, self._single)
        self._cancel_requested = False
        self._pause_requested = False
        self._stop_after_current = False

    def request_cancel(self):
        self._cancel_requested = True

    def request_pause(self):
        self._pause_requested = True

    def request_resume(self):
        self._pause_requested = False

    def request_stop_after_current(self):
        self._stop_after_current = True

    async def run_single_job(self, image: ImageItem, url_row: UrlRow, user_prompt: str, attempt: int = 1) -> JobRecord:
        return await self._single.execute({"image": image, "url_row": url_row, "user_prompt": user_prompt, "attempt": attempt, "cancel_flag": lambda: self._cancel_requested})

    async def _wait_for_user_action(self, job: JobRecord):
        await self._single._wait_for_user_action(job, lambda: self._cancel_requested)

    async def run_batch(self, images: list[ImageItem], urls: list[UrlRow], user_prompt: str, progress_callback: Optional[Callable] = None):
        await self._batch.run({
            "images": images,
            "urls": urls,
            "user_prompt": user_prompt,
            "progress_cb": progress_callback,
            "cancel_flag": lambda: self._cancel_requested,
            "pause_flag": lambda: self._pause_requested,
            "stop_flag": lambda: self._stop_after_current,
        })
