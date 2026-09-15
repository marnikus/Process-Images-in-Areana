"""
Job Runner — orchestrates primary processing workflow for each selected pending image.
Implements state machine per spec steps 09-20.
"""
import asyncio
import time
from pathlib import Path
from typing import Optional, Callable, Dict, Any
from ..core.models import ImageItem, UrlRow, JobRecord, AppState
from ..core.enums import ImageStatus, JobStatus
from ..utils.correlation import generate_correlation_id, build_final_prompt
from ..core.naming import get_output_path, atomic_write_bytes
from ..browser.controller import BrowserController
from .verification import VerificationService
from datetime import datetime

class JobRunner:
    def __init__(self, browser: BrowserController, state: AppState, log_callback: Optional[Callable[[str], None]] = None):
        self.browser = browser
        self.state = state
        self.verification = VerificationService(browser)
        self.log_callback = log_callback
        self._cancel_requested = False
        self._pause_requested = False
        self._stop_after_current = False

    def _log(self, job_id: str, message: str, level: str = "info", extra: Dict[str, Any] = None):
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "job_id": job_id,
            "message": message,
            "level": level,
            "extra": extra or {},
        }
        # print
        print(f"[{entry['timestamp']}] [{job_id}] {message}")
        if self.log_callback:
            self.log_callback(entry)
        # Also append to job record if exists
        for job in self.state.jobs:
            if job.job_id == job_id:
                job.logs.append(entry)
                break

    def request_cancel(self):
        self._cancel_requested = True

    def request_pause(self):
        self._pause_requested = True

    def request_resume(self):
        self._pause_requested = False

    def request_stop_after_current(self):
        self._stop_after_current = True

    async def run_single_job(self, image: ImageItem, url_row: UrlRow, user_prompt: str, attempt: int = 1) -> JobRecord:
        """
        Run workflow for one image. Steps 09-20.
        """
        correlation_id = generate_correlation_id()
        final_prompt = build_final_prompt(correlation_id, user_prompt)

        job = JobRecord.create(image, url_row, correlation_id, final_prompt, attempt=attempt)
        self.state.jobs.append(job)
        image.status = ImageStatus.PROCESSING.value
        image.assigned_url_id = url_row.id
        image.attempt_count = attempt

        job_id = job.job_id
        self._log(job_id, f"Starting job for {image.relative_path} with URL {url_row.url}, attempt {attempt}")

        try:
            # Step 11: Assign ready URL + capture baseline
            job.status = JobStatus.BASELINE_CAPTURED.value
            # Ensure page is ready
            ready, reasons = await self.browser.is_page_ready()
            if not ready:
                raise RuntimeError(f"Page not ready: {', '.join(reasons)}")

            baseline = await self.browser.capture_baseline()
            job.baseline = baseline
            job.status = JobStatus.BASELINE_CAPTURED.value
            self._log(job_id, f"Baseline captured: {baseline.get('output_count')} outputs before")

            # Check for security dialog
            if await self.browser.is_security_dialog_visible():
                job.status = JobStatus.PAUSED_USER_ACTION.value
                self._log(job_id, "Security verification detected before attachment, pausing", level="warning")
                # Wait for manual completion
                await self._wait_for_user_action(job)

            # Step 12: Attach image
            job.status = JobStatus.ATTACHING.value
            self._log(job_id, f"Attaching image {image.absolute_path}")
            ok = await self.browser.attach_image(image.absolute_path)
            if not ok:
                raise RuntimeError("Attachment failed: file input not found or set_input_files failed")

            # Step 13: Verify attachment
            verified, reason = await self.verification.verify_attachment_success(image.filename)
            if not verified:
                # Retry once safely
                self._log(job_id, f"Attachment verification failed: {reason}, retrying", level="warning")
                await self.browser.page.wait_for_timeout(1000)
                # Try remove if possible
                try:
                    sel_remove = self.browser.page.locator('button[aria-label="Remove file"]').first
                    if await sel_remove.is_visible():
                        await sel_remove.click()
                        await self.browser.page.wait_for_timeout(500)
                        ok = await self.browser.attach_image(image.absolute_path)
                        verified, reason = await self.verification.verify_attachment_success(image.filename)
                except Exception:
                    pass
                if not verified:
                    raise RuntimeError(f"Attachment verification failed after retry: {reason}")

            job.status = JobStatus.ATTACHMENT_VERIFIED.value
            self._log(job_id, f"Attachment verified: {reason}")

            # Step 14-15: Insert and verify prompt
            job.status = JobStatus.PROMPT_INSERTED.value
            self._log(job_id, f"Inserting prompt with correlation {correlation_id}")
            ok = await self.browser.insert_prompt(final_prompt)
            if not ok:
                raise RuntimeError("Prompt insertion failed")

            verified, reason = await self.verification.verify_prompt_text(final_prompt)
            if not verified:
                self._log(job_id, f"Prompt mismatch: {reason}, correcting", level="warning")
                # Correct
                ok = await self.browser.insert_prompt(final_prompt)
                verified, reason = await self.verification.verify_prompt_text(final_prompt)
                if not verified:
                    raise RuntimeError(f"Prompt verification failed: {reason}")

            job.status = JobStatus.PROMPT_VERIFIED.value
            self._log(job_id, f"Prompt verified: {reason}")

            # Step 16: Submit once
            self._log(job_id, "Submitting once")
            # Highlight settings
            highlight_enabled = self.state.settings.highlight.get("enabled", True)
            highlight_duration = self.state.settings.highlight.get("duration_seconds", 2)
            highlight_color = self.state.settings.highlight.get("color", "#FF0000")
            highlight_width = self.state.settings.highlight.get("border_width", 3)

            # We already highlight inside submit, but we can also use settings
            submitted, reason = await self.browser.submit()
            if not submitted:
                raise RuntimeError(f"Submit failed: {reason}")

            job.submitted_at = datetime.utcnow().isoformat() + "Z"
            job.status = JobStatus.SUBMITTED.value

            # Verify submission started
            verified, reason = await self.verification.verify_submission_started(baseline)
            if not verified:
                self._log(job_id, f"Submission not confirmed: {reason}, but continuing", level="warning")
                # Not fatal, continue to wait

            # Step 17: Wait safely
            job.status = JobStatus.WAITING_GENERATION.value
            self._log(job_id, "Waiting for generation")
            generation_timeout = self.state.settings.timeouts.get("generation", 180) * 1000

            wait_status, wait_data = await self.browser.wait_for_generation(baseline, timeout=generation_timeout)

            if wait_status == "paused_user_action":
                job.status = JobStatus.PAUSED_USER_ACTION.value
                self._log(job_id, f"Paused for user action: {wait_data.get('reason')}", level="warning")
                await self._wait_for_user_action(job)
                # After user action, retry waiting
                wait_status, wait_data = await self.browser.wait_for_generation(baseline, timeout=generation_timeout)

            if wait_status == "failed":
                raise RuntimeError(f"Generation failed or timeout: {wait_data.get('error')}")

            # Step 18: Detect new output
            job.status = JobStatus.OUTPUT_DETECTED.value
            is_valid, data, reason = await self.verification.verify_output_new_and_correlated(baseline)
            if not is_valid:
                # Mark needs review instead of false success
                job.status = JobStatus.NEEDS_REVIEW.value
                job.needs_review = True
                job.error = f"Output correlation uncertain: {reason}"
                image.status = ImageStatus.NEEDS_REVIEW.value
                image.error = job.error
                self._log(job_id, f"Needs review: {reason}", level="warning")
                return job

            new_src = wait_data.get("new_src") or data.get("new_output", {}).get("src")
            if not new_src:
                # Try to get from data
                new_src = data.get("new_output", {}).get("src")
            if not new_src:
                job.status = JobStatus.NEEDS_REVIEW.value
                job.needs_review = True
                job.error = "New output src not found"
                image.status = ImageStatus.NEEDS_REVIEW.value
                self._log(job_id, "Needs review: src not found", level="warning")
                return job

            job.output_src = new_src
            self._log(job_id, f"New output detected: {new_src}")

            # Step 19: Download + validate
            job.status = JobStatus.DOWNLOADING.value
            self._log(job_id, f"Downloading {new_src}")
            success, file_bytes, content_type_or_error = await self.browser.download_image(new_src)
            if not success:
                raise RuntimeError(f"Download failed: {content_type_or_error}")

            job.status = JobStatus.VALIDATING.value
            valid, error, metadata = await self.verification.validate_downloaded_file(file_bytes, content_type_or_error)
            if not valid:
                raise RuntimeError(f"Downloaded file invalid: {error}")

            job.output_metadata = metadata
            self._log(job_id, f"Download validated: {metadata}")

            # Step 20: Save beside source as *_AI.ext
            job.status = JobStatus.SAVING.value
            source_path = Path(image.absolute_path)
            # Determine downloaded ext from metadata or content-type
            downloaded_ext = None
            fmt = metadata.get("format")
            if fmt:
                downloaded_ext = f".{fmt}" if not fmt.startswith(".") else fmt

            output_path = get_output_path(
                source_path,
                suffix=self.state.settings.output.get("suffix", "_AI"),
                preserve_format=self.state.settings.output.get("preserve_format", True),
                overwrite=self.state.settings.output.get("overwrite", False),
                downloaded_ext=downloaded_ext,
                unique_template=self.state.settings.output.get("unique_suffix_template", "{base}_AI_{n}{ext}")
            )

            # Atomic write
            atomic_write_bytes(source_path.parent, output_path, file_bytes)
            job.saved_path = str(output_path)
            image.output_path = str(output_path)
            self._log(job_id, f"Saved to {output_path}")

            # Mark completed
            job.status = JobStatus.COMPLETED.value
            image.status = ImageStatus.COMPLETED.value
            image.error = None
            self._log(job_id, f"Job completed successfully")

        except Exception as e:
            job.status = JobStatus.FAILED.value
            job.error = str(e)
            image.status = ImageStatus.FAILED.value
            image.error = str(e)
            self._log(job_id, f"Job failed: {e}", level="error")

        finally:
            self.state.recalculate_progress()

        return job

    async def _wait_for_user_action(self, job: JobRecord):
        """Wait for user to complete security verification manually."""
        self._log(job.job_id, "Waiting for user to complete security verification...", level="warning")
        # Poll until security dialog disappears and page ready
        while True:
            if self._cancel_requested:
                raise RuntimeError("Cancelled during user action wait")
            if not await self.browser.is_security_dialog_visible():
                ready, _ = await self.browser.is_page_ready()
                if ready:
                    self._log(job.job_id, "Security dialog gone, page ready again")
                    break
            await asyncio.sleep(2)

    async def run_batch(self, images: list[ImageItem], urls: list[UrlRow], user_prompt: str, progress_callback: Optional[Callable] = None):
        """Process queue one image at a time, round-robin URLs."""
        ready_urls = [u for u in urls if u.enabled and u.last_status == "ready"]
        if not ready_urls:
            raise RuntimeError("No ready URLs available")

        selected_images = [img for img in images if img.selected and img.status in [ImageStatus.PENDING.value, ImageStatus.SELECTED.value, ImageStatus.FAILED.value]]
        if not selected_images:
            self._log("batch", "No selected pending images")
            return

        self._log("batch", f"Starting batch with {len(selected_images)} images, {len(ready_urls)} ready URLs")

        url_index = 0
        for img in selected_images:
            if self._cancel_requested:
                self._log("batch", "Batch cancelled")
                break
            if self._stop_after_current:
                self._log("batch", "Stopping after current as requested")
                break
            # Handle pause
            while self._pause_requested:
                self._log("batch", "Paused, waiting for resume...")
                await asyncio.sleep(1)
                if self._cancel_requested:
                    break

            # Assign URL round-robin
            url_row = ready_urls[url_index % len(ready_urls)]
            url_index += 1
            img.assigned_url_id = url_row.id

            # Ensure browser on correct URL
            if self.browser.page and self.browser.page.url != url_row.url:
                await self.browser.navigate(url_row.url)

            attempt = img.attempt_count + 1
            max_attempts = self.state.settings.retries.get("max_attempts", 3)
            if attempt > max_attempts:
                self._log("batch", f"Skipping {img.relative_path} — max attempts reached", level="warning")
                img.status = ImageStatus.SKIPPED.value
                img.error = "Max attempts reached"
                continue

            job = await self.run_single_job(img, url_row, user_prompt, attempt=attempt)

            if progress_callback:
                progress_callback(job, img)

            # Small delay between jobs
            await asyncio.sleep(1)

        self._log("batch", "Batch complete")
