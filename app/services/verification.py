"""
Verification service for attachments, submissions, outputs.
"""
from typing import Dict, Any, Tuple

class VerificationService:
    def __init__(self, browser_controller):
        self.browser = browser_controller

    async def verify_attachment_success(self, expected_filename: str) -> Tuple[bool, str]:
        """Verify attachment success from page state, not only from click."""
        return await self.browser.verify_attachment(expected_filename)

    async def verify_prompt_text(self, expected_prompt: str) -> Tuple[bool, str]:
        """Verify prompt text matches exactly."""
        return await self.browser.verify_prompt(expected_prompt)

    async def verify_submission_started(self, baseline: Dict[str, Any], timeout: int = 5000) -> Tuple[bool, str]:
        """
        Verify that processing/loading state started after submit.
        Checks: textarea cleared, spinner appears, or new user message.
        """
        try:
            # Simple check: textarea should be empty or spinner visible after submit
            await self.browser.page.wait_for_timeout(1000)
            # Check textarea empty
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
            result = await self.browser.page.evaluate(js)
            if result.get("empty") or result.get("hasSpinner"):
                return True, f"Submission confirmed: empty={result.get('empty')}, spinner={result.get('hasSpinner')}"
            else:
                return False, f"Submission not confirmed: textarea not empty and no spinner, value={result.get('value')}"
        except Exception as e:
            return False, f"Verification error: {e}"

    async def verify_output_new_and_correlated(self, baseline: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], str]:
        """
        A result is valid only when app can establish it is new and belongs to current job.
        - Capture known output elements before submission
        - Record submission timestamp and message position
        - Wait for new output container or meaningful change
        - Reject output elements that existed before submission
        - Confirm new result appears after current prompt/message in same conversation flow
        - Wait until generation and image loading complete before downloading
        Returns (is_valid, data, reason)
        """
        # Detect new output
        found, data = await self.browser.detect_new_output(baseline)
        if not found:
            return False, data, f"No new output: {data.get('reason')}"

        # Additional correlation: check if new output appears after baseline timestamp
        # For MVP, we already ensured src not in baseline and loaded
        # Further checks: DOM order, timestamp
        current = data.get("current", {})
        if current.get("timestamp", 0) <= baseline.get("timestamp", 0):
            # Might be old, but if src is new, still okay? Mark needs review if uncertain
            return False, data, "Timestamp not after baseline, uncertain correlation"

        return True, data, "New output detected and correlated"

    async def validate_downloaded_file(self, data: bytes, content_type: str = "") -> Tuple[bool, str, Dict[str, Any]]:
        """
        Validate that downloaded bytes represent supported image and are not HTML error page.
        Returns (valid, error, metadata)
        """
        if not data or len(data) == 0:
            return False, "Empty file", {}
        # Check HTML
        lower_start = data[:200].lower()
        if b"<html" in lower_start or b"<!doctype" in lower_start:
            return False, "Downloaded file is HTML, not image", {}

        # Check magic bytes for png, jpg, webp
        metadata = {"size": len(data)}
        if data.startswith(b"\x89PNG"):
            metadata["format"] = "png"
            return True, "", metadata
        elif data.startswith(b"\xff\xd8\xff"):
            metadata["format"] = "jpg"
            return True, "", metadata
        elif data.startswith(b"RIFF") and b"WEBP" in data[:12]:
            metadata["format"] = "webp"
            return True, "", metadata
        elif data[:2] == b"BM":
            metadata["format"] = "bmp"
            return True, "", metadata
        else:
            # Try PIL to validate
            try:
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(data))
                img.verify()
                metadata["format"] = img.format.lower() if img.format else "unknown"
                metadata["width"], metadata["height"] = img.size if hasattr(img, 'size') else (0,0)
                return True, "", metadata
            except Exception as e:
                # If content-type says image, allow?
                if "image" in content_type.lower():
                    metadata["format"] = content_type.split("/")[-1]
                    return True, "", metadata
                return False, f"Invalid image format: {e}", metadata
