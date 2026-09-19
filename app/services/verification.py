"""Verification service for attachments, submissions, outputs (C4).

RULE18: file 150-300, func ≤20, CC≤10, params≤4, guard clauses, ValidationResult.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any, Tuple


@dataclass
class ValidationResult:
    valid: bool
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OutputCorrelationResult:
    is_valid: bool
    data: Dict[str, Any]
    reason: str


def _check_empty(data: bytes) -> ValidationResult | None:
    if not data or len(data) == 0:
        return ValidationResult(valid=False, error="Empty file", metadata={})
    return None


def _check_html(data: bytes) -> ValidationResult | None:
    lower_start = data[:200].lower()
    if b"<html" in lower_start or b"<!doctype" in lower_start:
        return ValidationResult(valid=False, error="Downloaded file is HTML, not image", metadata={})
    return None


def _check_magic_bytes(data: bytes) -> ValidationResult | None:
    metadata = {"size": len(data)}
    if data.startswith(b"\x89PNG"):
        metadata["format"] = "png"
        return ValidationResult(valid=True, error="", metadata=metadata)
    if data.startswith(b"\xff\xd8\xff"):
        metadata["format"] = "jpg"
        return ValidationResult(valid=True, error="", metadata=metadata)
    if data.startswith(b"RIFF") and b"WEBP" in data[:12]:
        metadata["format"] = "webp"
        return ValidationResult(valid=True, error="", metadata=metadata)
    if data[:2] == b"BM":
        metadata["format"] = "bmp"
        return ValidationResult(valid=True, error="", metadata=metadata)
    return None


def _try_pil_validation(data: bytes, content_type: str) -> ValidationResult:
    metadata = {"size": len(data)}
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(data))
        img.verify()
        metadata["format"] = img.format.lower() if img.format else "unknown"
        if hasattr(img, "size"):
            metadata["width"], metadata["height"] = img.size
        return ValidationResult(valid=True, error="", metadata=metadata)
    except Exception as e:
        if "image" in content_type.lower():
            metadata["format"] = content_type.split("/")[-1]
            return ValidationResult(valid=True, error="", metadata=metadata)
        return ValidationResult(valid=False, error=f"Invalid image format: {e}", metadata=metadata)


class VerificationService:
    def __init__(self, browser_controller):
        self.browser = browser_controller

    async def verify_attachment_success(self, expected_filename: str) -> Tuple[bool, str]:
        return await self.browser.verify_attachment(expected_filename)

    async def verify_prompt_text(self, expected_prompt: str) -> Tuple[bool, str]:
        return await self.browser.verify_prompt(expected_prompt)

    async def _evaluate_submission_state(self):
        js = """
            () => {
                const ta = document.querySelector('textarea[name="message"]');
                if (!ta) return {empty: false, hasSpinner: false};
                const empty = ta.value.trim() === '';
                const spinner = document.querySelector('div.animate-spin');
                const visible = spinner && spinner.offsetParent !== null;
                return {empty: empty, hasSpinner: !!visible, value: ta.value.substring(0, 100)};
            }
            """
        return await self.browser.page.evaluate(js)

    async def verify_submission_started(self, baseline: Dict[str, Any],
                                        timeout: int = 5000) -> Tuple[bool, str]:
        try:
            await self.browser.page.wait_for_timeout(1000)
            result = await self._evaluate_submission_state()
            if result.get("empty") or result.get("hasSpinner"):
                return True, f"Submission confirmed: empty={result.get('empty')}, spinner={result.get('hasSpinner')}"
            return False, f"Submission not confirmed: value={result.get('value')}"
        except Exception as e:
            return False, f"Verification error: {e}"

    async def verify_output_new_and_correlated(self, baseline: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], str]:
        found, data = await self.browser.detect_new_output(baseline)
        if not found:
            return False, data, f"No new output: {data.get('reason')}"
        current = data.get("current", {})
        if current.get("timestamp", 0) <= baseline.get("timestamp", 0):
            return False, data, "Timestamp not after baseline, uncertain correlation"
        return True, data, "New output detected and correlated"

    async def validate_downloaded_file(self, data: bytes,
                                       content_type: str = "") -> Tuple[bool, str, Dict[str, Any]]:
        # Guard clauses via helpers — CC≤10, LOC≤20 (C4)
        res = _check_empty(data)
        if res:
            return res.valid, res.error, res.metadata
        res = _check_html(data)
        if res:
            return res.valid, res.error, res.metadata
        res = _check_magic_bytes(data)
        if res:
            return res.valid, res.error, res.metadata
        res = _try_pil_validation(data, content_type)
        return res.valid, res.error, res.metadata

    def validate_downloaded_file_result(self, data: bytes, content_type: str = "") -> ValidationResult:
        valid, err, meta = self._validate_sync(data, content_type)
        return ValidationResult(valid=valid, error=err, metadata=meta)

    def _validate_sync(self, data: bytes, content_type: str) -> Tuple[bool, str, Dict[str, Any]]:
        res = _check_empty(data)
        if res:
            return res.valid, res.error, res.metadata
        res = _check_html(data)
        if res:
            return res.valid, res.error, res.metadata
        res = _check_magic_bytes(data)
        if res:
            return res.valid, res.error, res.metadata
        res = _try_pil_validation(data, content_type)
        return res.valid, res.error, res.metadata
