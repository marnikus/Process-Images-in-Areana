"""The Firefox result tail: bytes → validation → staging → the atomic `_AI` save.

Chrome's tail is three blocks that write straight into the queue's image; the
Firefox lane needs the same rules **plus** a recoverable intermediate state,
because the bytes travel through a macro: the validated bytes land in
`<dir>/.<name>.part` first (a dot-file with a non-image suffix, invisible to the
scanner), then the final name is resolved again through `naming.get_output_path`
(never overwriting an existing `_AI` file — RULE 23) and written atomically.

RED at base: `app/services/firefox_result.py` did not exist.
"""

from __future__ import annotations

import io
import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from PIL import Image

from app.services import firefox_result as fr

pytestmark = pytest.mark.unit


def settings(**out):
    base = {"suffix": "_AI", "preserve_format": True, "overwrite": False,
            "unique_suffix_template": "{base}_AI_{n}{ext}"}
    base.update(out)
    return NS(output=base)


def image_bytes(fmt="PNG", size=(64, 64)):
    """Noise, not a flat colour: a legit 60x40 solid PNG is only ~88 bytes and the
    download floor (Chrome's own, >100 bytes) would refuse it — the tests must
    exercise real payloads, and the too-small case has its own test."""
    buf = io.BytesIO()
    Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3)).save(buf, format=fmt)
    return buf.getvalue()


def source(tmp_path, name="a.png"):
    path = tmp_path / name
    path.write_bytes(image_bytes())
    return path


def test_upright_formats_validate_and_report_their_own_extension():
    for fmt, ext in (("PNG", ".png"), ("JPEG", ".jpg"), ("WEBP", ".webp")):
        ok, got, note = fr.validate_bytes(image_bytes(fmt))
        assert ok, note
        assert got == ext and fmt.lower() in note


def test_html_and_corrupt_and_tiny_downloads_are_rejected_not_saved():
    ok, _ext, note = fr.validate_bytes(b"<html><body>rate limited</body></html>")
    assert not ok and "HTML page" in note
    ok, _ext, note = fr.validate_bytes(b"\x89PNG" + b"\x00" * 300)
    assert not ok and "unreadable image" in note
    ok, _ext, note = fr.validate_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 40)
    assert not ok and ("too small" in note or "unreadable" in note)
    assert fr.validate_bytes(b"")[0] is False


def test_plan_output_keeps_the_source_folder_and_never_reuses_an_ai_name(tmp_path):
    src = source(tmp_path, "pic.png")
    img = NS(absolute_path=str(src))
    planned = fr.plan_output(img, settings())
    assert planned == tmp_path / "pic_AI.png"
    # a previous run's file exists: the plan must move on, not overwrite (RULE 23)
    (tmp_path / "pic_AI.png").write_bytes(image_bytes())
    (tmp_path / "pic_AI_2.png").write_bytes(image_bytes())
    assert fr.plan_output(img, settings()) == tmp_path / "pic_AI_3.png"
    # the downloaded format wins when it is known and the user preserves formats —
    # and it is a namespace of its own, so `pic_AI.webp` is free even while `pic_AI.png` is taken
    assert fr.plan_output(img, settings(), ext=".webp") == tmp_path / "pic_AI.webp"
    (tmp_path / "pic_AI.webp").write_bytes(image_bytes("WEBP"))
    assert fr.plan_output(img, settings(), ext=".webp") == tmp_path / "pic_AI_2.webp"
    assert fr.plan_output(img, settings(preserve_format=False), ext=".webp") == tmp_path / "pic_AI_3.png"


def test_staging_path_is_a_dot_file_with_a_non_image_suffix(tmp_path):
    final = tmp_path / "pic_AI.png"
    staged = fr.staging_path(final)
    assert staged == tmp_path / ".pic_AI.png.part"
    assert staged.name.startswith(".") and staged.suffix == ".part"


def test_store_staging_finalize_and_discard_leave_no_trace(tmp_path):
    src = source(tmp_path, "pic.png")
    img = NS(absolute_path=str(src))
    final = fr.plan_output(img, settings())
    data = image_bytes("JPEG")
    ok, note = fr.store_staging(final, data)
    assert ok and "staged" in note
    assert fr.staged_bytes(final) == data
    assert not final.exists()                      # nothing at the final name yet
    ok, note = fr.finalize(final, data)
    assert ok and final.read_bytes() == data and "saved" in note
    assert not fr.staging_path(final).exists()     # the staging file is gone
    fr.discard_staging(final)                      # idempotent


def test_a_partial_download_stays_in_staging_and_never_becomes_the_final_file(tmp_path):
    src = source(tmp_path, "pic.png")
    final = fr.plan_output(NS(absolute_path=str(src)), settings())
    fr.store_staging(final, b"\x89PNG\r\n\x1a\n" + b"0" * 20)
    assert fr.staged_bytes(final) and not final.exists()
    ok, _ext, note = fr.validate_bytes(fr.staged_bytes(final))
    assert not ok and note                       # a torn download is refused, not promoted


def test_disk_full_and_access_denied_are_named_not_swallowed(tmp_path, monkeypatch):
    src = source(tmp_path, "pic.png")
    final = fr.plan_output(NS(absolute_path=str(src)), settings())

    def no_space(directory, path, data):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(fr, "atomic_write_bytes", no_space)
    ok, note = fr.store_staging(final, image_bytes())
    assert not ok and "No space left on device" in note
    ok, note = fr.finalize(final, image_bytes())
    assert not ok and "No space left on device" in note

    def denied(directory, path, data):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(fr, "atomic_write_bytes", denied)
    ok, note = fr.finalize(final, image_bytes())
    assert not ok and "Permission denied" in note


def test_an_atomic_rename_failure_keeps_the_staged_bytes_for_the_next_attempt(tmp_path, monkeypatch):
    src = source(tmp_path, "pic.png")
    final = fr.plan_output(NS(absolute_path=str(src)), settings())
    data = image_bytes()
    assert fr.store_staging(final, data)[0] is True

    import app.core.naming as naming

    def broken_replace(srcp, dstp):
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(naming.os, "replace", broken_replace)
    ok, note = fr.finalize(final, data)
    assert not ok and "cross-device" in note
    assert fr.staged_bytes(final) == data        # recovery can still finalize it


def test_download_delegates_to_the_shared_fetch_and_keeps_its_failure_words(monkeypatch):
    calls = {}

    def fake_fetch(url, timeout=45):
        calls["args"] = (url, timeout)
        return True, b"xx", "image/png", ""

    monkeypatch.setattr(fr, "fetch_bytes", fake_fetch)
    ok, data, note = fr.download("https://x/a.png", timeout=7)
    assert ok and data == b"xx" and calls["args"] == ("https://x/a.png", 7)

    def html_fetch(url, timeout=45):
        return False, b"", "text/html", "the bytes are an HTML page"

    monkeypatch.setattr(fr, "fetch_bytes", html_fetch)
    ok, data, note = fr.download("https://x/a.png")
    assert not ok and data == b"" and "HTML page" in note


def test_find_recent_output_sees_only_what_this_job_wrote(tmp_path):
    """The planned name cannot cover a format the download chose, so the family match
    plus the journal's own start time is the window — an older `_AI` file is not ours."""
    src = source(tmp_path, "pic.png")
    old = tmp_path / "pic_AI.png"
    old.write_bytes(image_bytes())                                 # a previous run's file
    started = datetime.now(timezone.utc).isoformat()               # this job starts here
    # explicit stamps: a test tmpdir's mtime resolution is coarser than the window
    os.utime(old, (fr.timestamp_of(started) - 60, fr.timestamp_of(started) - 60))
    assert fr.find_recent_output(src, settings(), started) is None
    fresh = tmp_path / "pic_AI_2.jpg"                              # this job's own output
    fresh.write_bytes(image_bytes("JPEG"))
    os.utime(fresh, (fr.timestamp_of(started) + 5, fr.timestamp_of(started) + 5))
    assert fr.find_recent_output(src, settings(), started) == fresh
    assert fr.find_recent_output(src, settings(), "") == fresh


def test_staged_bytes_of_a_missing_file_is_empty_not_an_exception(tmp_path):
    assert fr.staged_bytes(Path(tmp_path) / "nothing_AI.png") == b""
    fr.discard_staging(Path(tmp_path) / "nothing_AI.png")
