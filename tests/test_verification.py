import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.verification import VerificationService

@pytest.mark.asyncio
async def test_validate_downloaded_file_png():
    service = VerificationService(browser_controller=MagicMock())
    data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    valid, error, meta = await service.validate_downloaded_file(data, "image/png")
    assert valid is True
    assert meta["format"] == "png"

@pytest.mark.asyncio
async def test_validate_downloaded_file_jpg():
    service = VerificationService(browser_controller=MagicMock())
    data = b"\xff\xd8\xff" + b"\x00" * 100
    valid, error, meta = await service.validate_downloaded_file(data, "image/jpeg")
    assert valid is True
    assert meta["format"] == "jpg"

@pytest.mark.asyncio
async def test_validate_downloaded_file_html():
    service = VerificationService(browser_controller=MagicMock())
    data = b"<html><body>Error</body></html>"
    valid, error, meta = await service.validate_downloaded_file(data, "text/html")
    assert valid is False
    assert "HTML" in error

@pytest.mark.asyncio
async def test_validate_downloaded_file_empty():
    service = VerificationService(browser_controller=MagicMock())
    data = b""
    valid, error, meta = await service.validate_downloaded_file(data)
    assert valid is False

@pytest.mark.asyncio
async def test_verify_attachment_success():
    mock_browser = MagicMock()
    mock_browser.verify_attachment = AsyncMock(return_value=(True, "Found preview"))
    service = VerificationService(mock_browser)
    ok, reason = await service.verify_attachment_success("test.png")
    assert ok is True

@pytest.mark.asyncio
async def test_verify_prompt():
    mock_browser = MagicMock()
    mock_browser.verify_prompt = AsyncMock(return_value=(True, "Exact match"))
    service = VerificationService(mock_browser)
    ok, reason = await service.verify_prompt_text("[JOB-ID: xxx]\nPrompt")
    assert ok is True
