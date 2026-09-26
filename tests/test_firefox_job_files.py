"""Firefox job — journal, upload staging, output gate + atomic save (design D-3/D-8/D-9).

Every branch of the three file-level modules the job relies on: the journal
refuses illegal moves and survives a restart, the source check names each
reason, the staged copy is ASCII-only, the download gate rejects HTTP / HTML /
tiny / partial bodies, PIL decides the extension, and the `_AI` save is atomic,
never overwrites and retries a transient sharing violation.
"""

import io
import os
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from app.core.enums import JobStatus
from app.core.naming import OutputSpec
from app.services import firefox_job_output as out
from app.services import firefox_job_upload as up
from app.services.firefox_job_journal import JobJournal, is_post_submit, journal_of
from tests.firefox_job_harness import image_bytes, source_image

pytestmark = pytest.mark.unit


# ── journal ──────────────────────────────────────────────────────────────────

def test_journal_moves_only_along_the_job_state_machine(tmp_path):
    journal = JobJournal(tmp_path / "j.json")
    journal.create("c1", tab_id="t")
    assert journal.advance("c1", JobStatus.BASELINE_CAPTURED.value, baseline={"srcs": []})
    assert not journal.advance("c1", JobStatus.SUBMITTED.value)          # skipping verify: refused
    assert journal.get("c1")["status"] == JobStatus.BASELINE_CAPTURED.value
    assert not journal.advance("nope", JobStatus.FAILED.value)
    assert journal.update("c1", submit_ack=True) and not journal.update("nope", x=1)


def test_journal_survives_a_restart_and_lists_open_records(tmp_path):
    path = tmp_path / "j.json"
    first = JobJournal(path)
    first.create("a")
    first.create("b")
    first.advance("b", JobStatus.FAILED.value)
    again = JobJournal(path)
    assert [r["job_id"] for r in again.open_records()] == ["a"]
    again.drop("a")
    again.drop("a")                                   # idempotent
    assert JobJournal(path).get("a") is None


def test_journal_drops_a_corrupt_or_wrong_shape_file(tmp_path):
    path = tmp_path / "j.json"
    path.write_text('{"jobs": {"x": {"status": 1}, "y": "bad", "z": {"status": "created"}}}', "utf-8")
    assert [r["job_id"] for r in JobJournal(path).open_records()] == ["z"]
    path.write_text("not json", "utf-8")
    assert JobJournal(path).open_records() == []
    path.write_text('{"jobs": []}', "utf-8")
    assert JobJournal(path).open_records() == []


def test_post_submit_statuses_are_the_no_resubmit_set():
    assert is_post_submit({"status": "submitted"}) and is_post_submit({"status": "saving"})
    assert not is_post_submit({"status": "prompt_verified"}) and not is_post_submit(None)


def test_journal_of_is_memory_only_without_a_real_config_dir():
    bridge = NS(config=NS(dir=object()))
    journal = journal_of(bridge)
    journal.create("c1")
    assert journal_of(bridge) is journal and journal.get("c1")


def test_journal_of_tolerates_a_bridge_that_refuses_attributes():
    class Frozen:
        __slots__ = ("config",)

    bridge = Frozen()
    bridge.config = NS(dir=None)
    assert journal_of(bridge).get("x") is None


# ── upload staging ───────────────────────────────────────────────────────────

def test_check_source_accepts_png_jpeg_webp(tmp_path):
    for name, fmt in (("a.png", "PNG"), ("b.JPG", "JPEG"), ("c.jpeg", "JPEG"), ("d.webp", "WEBP")):
        assert up.check_source(source_image(tmp_path, name, fmt)) == ""


def test_check_source_names_every_refusal(tmp_path):
    assert "missing" in up.check_source(tmp_path / "none.png")
    assert "unsupported" in up.check_source(source_image(tmp_path, "a.gif", "GIF"))
    (tmp_path / "noext").write_bytes(b"x")
    assert "(none)" in up.check_source(tmp_path / "noext")
    (tmp_path / "junk.png").write_bytes(b"not an image at all")
    assert "not a readable image" in up.check_source(tmp_path / "junk.png")
    assert "extension says WEBP" in up.check_source(source_image(tmp_path, "x.webp", "PNG"))


def test_the_upload_path_is_the_queue_file_made_absolute(tmp_path, monkeypatch):
    """Live fix 2026-09-26: no staging copy — the dialog gets the queue file itself."""
    src = source_image(tmp_path, "Fotka ž 2026.PNG")
    assert up.upload_path(src) == str(src.resolve())
    monkeypatch.chdir(tmp_path)
    assert up.upload_path("Fotka ž 2026.PNG") == str(src.resolve())


def test_drop_staged_removes_only_a_legacy_staging_copy_never_the_queue_image(tmp_path):
    image = source_image(tmp_path, "icon-box-package.png")
    up.drop_staged(image)                                   # a new record's staged_upload = the image
    up.drop_staged(tmp_path / "arena_c1.png")                  # arena_* outside an uploads folder
    assert image.is_file()
    for folder in ("uploads", "arena_uploads"):
        legacy = tmp_path / folder / "arena_c1.png"
        legacy.parent.mkdir()
        legacy.write_bytes(b"x")
        up.drop_staged(legacy)
        assert not legacy.exists()
    up.drop_staged("")


def test_drop_staged_swallows_os_errors(monkeypatch):
    def locked(self, missing_ok=False):
        raise PermissionError("locked")

    monkeypatch.setattr(Path, "unlink", locked)
    up.drop_staged("/x/uploads/arena_c1.png")


# ── download gate ────────────────────────────────────────────────────────────

GOOD = image_bytes()


@pytest.mark.parametrize("status,ctype,length,data,needle", [
    (403, "image/png", None, GOOD, "HTTP 403"),
    (200, "text/html; charset=utf-8", None, GOOD, "HTML page"),
    (200, "application/octet-stream", None, b"  <!DOCTYPE html><p>" + b"x" * 200, "HTML page"),
    (200, "image/png", None, b"\x89PNG" * 5, "only 20 bytes"),
    (200, "image/png", str(len(GOOD) + 10), GOOD, "partial download"),
])
def test_check_response_rejects(status, ctype, length, data, needle):
    with pytest.raises(out.OutputError, match=needle):
        out.check_response(status, ctype, length, data)


def test_check_response_accepts_a_good_body():
    out.check_response(200, "image/png", str(len(GOOD)), GOOD)
    out.check_response(200, "", "", GOOD)


class Resp:
    def __init__(self, data, status=200, headers=None):
        self.data, self.status, self.headers = data, status, headers or {"Content-Type": "image/png"}

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_returns_checked_bytes_and_names_failures():
    assert out.fetch("https://x/a.png", 5, opener=lambda req, timeout: Resp(GOOD)) == GOOD
    with pytest.raises(out.OutputError, match="HTTP 500"):
        out.fetch("https://x", 5, opener=lambda req, timeout: Resp(GOOD, status=500))

    def refused(req, timeout):
        raise OSError("connection reset")

    with pytest.raises(out.OutputError, match="download failed: connection reset"):
        out.fetch("https://x", 5, opener=refused)


@pytest.mark.parametrize("fmt,ext", [("PNG", ".png"), ("JPEG", ".jpeg"), ("WEBP", ".webp")])
def test_validate_image_decides_the_extension(fmt, ext):
    assert out.validate_image(image_bytes(fmt)) == ext


def test_validate_image_refuses_corrupt_and_foreign_formats():
    with pytest.raises(out.OutputError, match="corrupt"):
        out.validate_image(GOOD[:60])
    buffer = io.BytesIO()
    from PIL import Image
    Image.new("RGB", (4, 4)).save(buffer, "GIF")
    with pytest.raises(out.OutputError, match="unexpected image format gif"):
        out.validate_image(buffer.getvalue())


def test_stage_bytes_and_read_back_by_hash(tmp_path):
    path = out.stage_bytes(tmp_path / "job", GOOD)
    assert path.name == "download.bin" and not (tmp_path / "job" / "download.part").exists()
    assert out.read_staged(path, out.sha256(GOOD)) == GOOD
    assert out.read_staged(path, "other") is None
    assert out.read_staged(tmp_path / "none", "x") is None and out.read_staged(None, "x") is None


def test_output_spec_mirrors_the_chrome_settings():
    spec = out.output_spec(NS(output={"suffix": "_X", "unique_suffix_template": "{base}_X_{n}{ext}"}), ".png")
    assert (spec.suffix, spec.downloaded_ext, spec.preserve_format, spec.overwrite) == ("_X", ".png", True, False)
    assert out.output_spec(None, ".webp").suffix == "_AI"


def spec(ext=".png"):
    return OutputSpec(suffix="_AI", preserve_format=True, overwrite=False, downloaded_ext=ext,
                      unique_template="{base}_AI_{n}{ext}")


def test_save_beside_names_by_the_ai_rule_and_never_overwrites(tmp_path):
    src = source_image(tmp_path, "cat.jpg", "JPEG")
    first = out.save_beside(src, GOOD, spec())
    second = out.save_beside(src, GOOD, spec())
    assert (first.name, second.name) == ("cat_AI.png", "cat_AI_2.png")
    assert not [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]


def test_save_beside_retries_a_sharing_violation(tmp_path, monkeypatch):
    src = source_image(tmp_path)
    calls, real = [], out.atomic_write_bytes

    def flaky(folder, target, data):
        calls.append(target)
        if len(calls) == 1:
            raise PermissionError("in use")
        return real(folder, target, data)

    monkeypatch.setattr(out, "atomic_write_bytes", flaky)
    slept = []
    assert out.save_beside(src, GOOD, spec(), sleep=slept.append).name == "photo_AI.png"
    assert slept == [0.5]


def test_save_beside_names_a_permanent_failure(tmp_path, monkeypatch):
    def full(folder, target, data):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(out, "atomic_write_bytes", full)
    with pytest.raises(out.OutputError, match="No space left"):
        out.save_beside(source_image(tmp_path), GOOD, spec(), sleep=lambda s: None)


def test_save_beside_gives_up_after_the_last_transient_try(tmp_path, monkeypatch):
    def denied(folder, target, data):
        raise PermissionError("access denied")

    monkeypatch.setattr(out, "atomic_write_bytes", denied)
    with pytest.raises(out.OutputError, match="access denied"):
        out.save_beside(source_image(tmp_path), GOOD, spec(), sleep=lambda s: None)


def test_find_saved_matches_the_family_by_hash_only(tmp_path):
    src = source_image(tmp_path, "a[1].png")
    (tmp_path / "a[1]_AI.png").write_bytes(b"other")
    (tmp_path / "a[1]_AI_2.png").write_bytes(GOOD)
    (tmp_path / "a[1]_AIX.png").write_bytes(GOOD)
    assert out.find_saved(src, out.sha256(GOOD)) == tmp_path / "a[1]_AI_2.png"
    assert out.find_saved(src, "nope") is None
    assert out.find_saved(tmp_path / "missing" / "x.png", "h") is None


def test_transient_classification():
    assert out._transient(PermissionError("x"))
    err = OSError("x")
    err.winerror = 32
    assert out._transient(err) and not out._transient(OSError(28, "full"))
    assert os.sep  # platform-neutral module


def test_job_folder_lives_under_the_config_dir():
    from types import SimpleNamespace as NS
    from app.services.firefox_job_journal import JOBS_DIR, job_folder
    assert job_folder(NS(config=NS(dir="/cfg")), "c1") == Path("/cfg") / JOBS_DIR / "c1"
    assert job_folder(NS(), "c1") == Path(".") / JOBS_DIR / "c1"
