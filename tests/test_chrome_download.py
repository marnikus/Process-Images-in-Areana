"""Chrome download without one giant DevTools reply (2026-09-26, design D-1).

docs/archive/2026-09-26-chrome-job-save-and-confirmations/design.md — the old
path returned the image as a JSON number array in ONE evaluate reply; a 20 MB
PNG closed the socket (1009 "message too big"). RULE 8: the real download
module; only the page (`evaluate`) and the HTTP opener are fakes. The real-CDP
lane is `tests/test_cdp_arena.py` (stub websocket).
"""

from __future__ import annotations

import base64
import json
import re

import pytest

from app.browser.cdp_arena import download as dl
from app.utils import http_image

pytestmark = pytest.mark.unit

PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4


class SlotPage:
    """The page side of the sliced download; `drop_at` loses one slice, `size` lies about the size."""

    def __init__(self, data=PNG, meta=None, drop_at=None, size=None, connected=True):
        self.b64 = base64.b64encode(data).decode()
        self.meta = meta or {"ok": True, "size": size or len(data), "b64len": len(self.b64),
                             "contentType": "image/png", "method": "fetch"}
        self.drop_at, self.freed, self.reads = drop_at, 0, []
        self.is_connected, self.last_error, self.last_error_kind = connected, "", ""

    async def evaluate(self, expr, await_promise=True):
        if "viaCanvas" in expr:
            return json.dumps(self.meta)
        if "delete window.__arenaDl" in expr:
            self.freed += 1
            return True
        start, count = (int(x) for x in re.findall(r", (\d+), (\d+)\)$", expr)[0])
        self.reads.append(start)
        if start == self.drop_at:
            self.last_error = "Execution context was destroyed."
            return None
        return self.b64[start:start + count]


def logs():
    out = []
    return out, (lambda m, l="info": out.append((m, l)))


async def test_slices_never_exceed_the_chunk_and_the_slot_is_freed(monkeypatch):
    monkeypatch.setattr(dl, "CHUNK_CHARS", 100)
    page, (said, say) = SlotPage(), logs()
    ok, data, ctype = await dl.download_image(page, "blob:https://arena.ai/x", say)
    assert (ok, data, ctype) == (True, PNG, "image/png")
    assert page.reads == list(range(0, len(page.b64), 100)) and page.freed == 1
    assert said[-1][0].startswith(f"Page download {len(PNG)} bytes via fetch ({len(page.reads)} slice(s))")


async def test_a_lost_slice_fails_with_the_reason_and_still_frees_the_slot(monkeypatch):
    monkeypatch.setattr(dl, "CHUNK_CHARS", 100)
    page, (said, say) = SlotPage(drop_at=200), logs()
    ok, _, err = await dl.download_image(page, "blob:x", say)
    assert ok is False and page.freed == 1
    assert "slice at 200/" in err and "No result (Execution context was destroyed.)" in err


async def test_a_short_page_copy_is_rejected():
    ok, _, err = await dl.download_image(SlotPage(size=len(PNG) + 5), "blob:x", logs()[1])
    assert ok is False and f"page copy incomplete {len(PNG)}/{len(PNG) + 5} bytes" in err


async def test_a_page_that_serves_html_is_rejected():
    html = b"<!doctype html><html>" + b"x" * 200
    ok, _, err = await dl.download_image(SlotPage(data=html), "blob:x", logs()[1])
    assert ok is False and "got an HTML page" in err


async def test_page_fetch_refusal_is_named():
    page = SlotPage(meta={"ok": False, "error": "fetch: TypeError; canvas: img not on page"})
    ok, _, err = await dl.download_image(page, "blob:x", logs()[1])
    assert ok is False and err.endswith("page download failed: fetch: TypeError; canvas: img not on page")


async def test_a_dead_link_that_does_not_come_back_is_named(monkeypatch):
    async def instant(_s):
        return None
    monkeypatch.setattr("app.browser.page_recovery.asyncio.sleep", instant)
    page = SlotPage(connected=False)
    ok, _, err = await dl.download_image(page, "blob:x", logs()[1])
    assert ok is False and "CDP connection lost — reconnect to the same tab failed" in err


def _png_data_url(data=PNG, b64=True):
    body = base64.b64encode(data).decode() if b64 else data.decode("latin-1")
    return f"data:image/png{';base64' if b64 else ''},{body}"


async def test_data_urls_are_decoded_locally():
    assert await dl.download_image(None, _png_data_url(), logs()[1]) == (True, PNG, "image/png")
    ok, data, _ = await dl.download_image(None, _png_data_url(b"x" * 150, b64=False), logs()[1])
    assert ok and data == b"x" * 150


@pytest.mark.parametrize("src,needle", [
    ("data:image/png;base64,@@@", "data URL rejected"),
    (_png_data_url(b"tiny"), "only 4 bytes"),
])
async def test_bad_data_urls_are_rejected(src, needle):
    ok, _, err = await dl.download_image(None, src, logs()[1])
    assert ok is False and needle in err


async def test_python_first_for_https_and_the_page_is_not_touched(monkeypatch):
    monkeypatch.setattr(dl, "fetch_image", lambda src, timeout: (PNG, "image/png"))
    page = SlotPage()
    assert await dl.download_image(page, "https://r2.example/x.png", logs()[1]) == (True, PNG, "image/png")
    assert page.reads == [] and page.freed == 0


async def test_python_refusal_then_page_success(monkeypatch):
    def refuse(src, timeout):
        raise http_image.OutputError("HTTP 403")
    monkeypatch.setattr(dl, "fetch_image", refuse)
    said, say = logs()
    ok, data, _ = await dl.download_image(SlotPage(), "https://r2.example/x.png", say)
    assert ok and data == PNG
    assert ("Python download failed: HTTP 403 — trying the page", "warn") in said


def test_answer_parsing_accepts_dicts_and_json_text():
    assert dl._as_dict({"ok": 1}) == {"ok": 1}
    assert dl._as_dict('{"ok": 1}') == {"ok": 1}
    assert dl._as_dict("nope") == {} and dl._as_dict(None) == {} and dl._as_dict("[1]") == {}


# ── utils.http_image — the gate both lanes share ──

class Resp:
    def __init__(self, body, status=200, headers=None):
        self.body, self.status = body, status
        self.headers = headers if headers is not None else {"Content-Type": "image/webp"}

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_image_returns_bytes_and_content_type_and_asks_for_an_image():
    seen = []

    def opener(req, timeout):
        seen.append((req.get_header("Accept"), timeout))
        return Resp(PNG)
    assert http_image.fetch_image("https://x/a", 7, opener=opener) == (PNG, "image/webp")
    assert seen == [("image/*,*/*;q=0.8", 7)]


@pytest.mark.parametrize("resp,needle", [
    (Resp(PNG, status=403), "HTTP 403"),
    (Resp(PNG, headers={"Content-Type": "text/html"}), "HTML page"),
    (Resp(PNG, headers={"Content-Length": str(len(PNG) + 1)}), "partial download"),
    (Resp(b"x" * 10, headers={}), "only 10 bytes"),
])
def test_fetch_image_gate(resp, needle):
    with pytest.raises(http_image.OutputError, match=needle):
        http_image.fetch_image("https://x/a", 1, opener=lambda req, timeout: resp)
