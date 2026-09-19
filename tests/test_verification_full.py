"""D5 mutation triage: VerificationService, branch-complete.

Targets validate_downloaded_file (18), verify_submission_started (1),
verify_output_new_and_correlated (2), delegation methods (1).
"""

import asyncio

from app.services.verification import VerificationService

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 8
BMP = b"BM" + b"\x00" * 16


class TestValidateDownloadedFile:
    def test_empty(self):
        svc = VerificationService(None)
        assert asyncio.run(svc.validate_downloaded_file(b"")) == (False, "Empty file", {})
        assert asyncio.run(svc.validate_downloaded_file(None)) == (False, "Empty file", {})

    def test_html_rejected(self):
        svc = VerificationService(None)
        for head in (b"<html><body>", b"<!DOCTYPE html>", b"  <HTML>"):
            ok, err, meta = asyncio.run(svc.validate_downloaded_file(head + b"x" * 50))
            assert ok is False
            assert "HTML" in err
            assert meta == {}

    def test_magic_bytes(self):
        svc = VerificationService(None)
        for head, fmt in ((PNG, "png"), (JPG, "jpg"), (WEBP, "webp"), (BMP, "bmp")):
            ok, err, meta = asyncio.run(svc.validate_downloaded_file(head))
            assert ok is True, head
            assert err == ""
            assert meta["format"] == fmt
            assert meta["size"] == len(head)

    def test_riff_without_webp_falls_to_pil(self):
        svc = VerificationService(None)
        ok, err, meta = asyncio.run(svc.validate_downloaded_file(
            b"RIFF\x00\x00\x00\x00AVI ", content_type="image/png"))
        assert ok is True
        assert meta["format"] == "png"

    def test_pil_validated(self):
        try:
            from PIL import Image
        except ImportError:
            import pytest
            pytest.skip("PIL not installed")
        import io
        # GIF: no magic-byte shortcut, so the PIL verify path runs
        img = Image.new("RGB", (4, 4), "red")
        buf = io.BytesIO()
        img.save(buf, format="GIF")
        svc = VerificationService(None)
        ok, err, meta = asyncio.run(svc.validate_downloaded_file(buf.getvalue()))
        assert ok is True
        assert meta["format"] == "gif"
        assert meta["width"] == 4
        assert meta["height"] == 4

    def test_garbage_no_content_type(self):
        svc = VerificationService(None)
        raw = b"\x00\x01\x02 not an image at all"
        ok, err, meta = asyncio.run(svc.validate_downloaded_file(raw))
        assert ok is False
        assert "Invalid image format" in err
        assert meta["size"] == len(raw)

    def test_garbage_with_image_content_type(self):
        svc = VerificationService(None)
        ok, err, meta = asyncio.run(svc.validate_downloaded_file(
            b"\x00\x01\x02 not an image", content_type="image/webp"))
        assert ok is True
        assert meta["format"] == "webp"


class FakePage:
    def __init__(self, result=None, raises=False):
        self.result = result
        self.raises = raises
        self.waits = 0

    async def wait_for_timeout(self, ms):
        self.waits += 1

    async def evaluate(self, js):
        if self.raises:
            raise RuntimeError("page gone")
        return self.result


class FakeBrowser:
    def __init__(self, page_result=None, page_raises=False,
                 found=True, data=None):
        self.page = FakePage(page_result, page_raises)
        self.found = found
        self.data = data or {}
        self.attachment_calls = []
        self.prompt_calls = []

    async def detect_new_output(self, baseline):
        return self.found, self.data

    async def verify_attachment(self, name):
        self.attachment_calls.append(name)
        return True, "attached"

    async def verify_prompt(self, text):
        self.prompt_calls.append(text)
        return False, "prompt differs"


class TestDelegation:
    def test_verify_attachment(self):
        browser = FakeBrowser()
        ok, msg = asyncio.run(
            VerificationService(browser).verify_attachment_success("a.png"))
        assert (ok, msg) == (True, "attached")
        assert browser.attachment_calls == ["a.png"]

    def test_verify_prompt(self):
        browser = FakeBrowser()
        ok, msg = asyncio.run(VerificationService(browser).verify_prompt_text("hi"))
        assert (ok, msg) == (False, "prompt differs")
        assert browser.prompt_calls == ["hi"]


class TestVerifySubmissionStarted:
    def test_textarea_cleared(self):
        browser = FakeBrowser(page_result={"empty": True, "hasSpinner": False, "value": ""})
        ok, msg = asyncio.run(VerificationService(browser).verify_submission_started({}))
        assert ok is True
        assert "empty=True" in msg
        assert browser.page.waits == 1

    def test_spinner_visible(self):
        browser = FakeBrowser(page_result={"empty": False, "hasSpinner": True, "value": ""})
        ok, msg = asyncio.run(VerificationService(browser).verify_submission_started({}))
        assert ok is True
        assert "spinner=True" in msg

    def test_not_confirmed(self):
        browser = FakeBrowser(page_result={"empty": False, "hasSpinner": False,
                                           "value": "leftover text"})
        ok, msg = asyncio.run(VerificationService(browser).verify_submission_started({}))
        assert ok is False
        assert "leftover text" in msg

    def test_page_error(self):
        browser = FakeBrowser(page_raises=True)
        ok, msg = asyncio.run(VerificationService(browser).verify_submission_started({}))
        assert ok is False
        assert "Verification error: page gone" == msg


class TestVerifyOutputCorrelation:
    def test_no_new_output(self):
        svc = VerificationService(FakeBrowser(found=False, data={"reason": "timeout"}))
        ok, _, reason = asyncio.run(
            svc.verify_output_new_and_correlated({"timestamp": 1}))
        assert ok is False
        assert reason == "No new output: timeout"

    def test_timestamp_not_after_baseline(self):
        browser = FakeBrowser(found=True, data={
            "new_output": {"src": "s"}, "current": {"timestamp": 100}})
        ok, _, reason = asyncio.run(
            VerificationService(browser).verify_output_new_and_correlated({"timestamp": 100}))
        assert ok is False
        assert "Timestamp not after baseline" in reason

    def test_correlated(self):
        browser = FakeBrowser(found=True, data={
            "new_output": {"src": "s"}, "current": {"timestamp": 200}})
        ok, data, reason = asyncio.run(
            VerificationService(browser).verify_output_new_and_correlated({"timestamp": 100}))
        assert ok is True
        assert reason == "New output detected and correlated"
        assert data["new_output"]["src"] == "s"
