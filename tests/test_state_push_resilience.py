"""B10 — the Image Queue must follow the run even when persistence misbehaves.

Three contracts (SYSTEM_OF_RECORD I-39):
* `save_arena_state` ALWAYS emits `arena_state_updated` + `progress_updated`,
  also when `save_state` raises (Windows sharing violation, locked/read-only
  file, full disk). Before B10 a failed write silently skipped the UI push,
  freezing every queue row at `pending / 0 / —` for the whole run.
* the save failure is reported to the log console, de-duplicated (same error
  within 10 s → one line), so a locked file cannot flood the console.
* `_atomic_json_write` retries a transient replace failure instead of failing
  the whole save.
"""

from __future__ import annotations

import errno
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import persistence
from app.core.models import AppState, ImageItem
from app.services.job_events import job_finished_payload
from app.ui.panels import layout_state


class Rec:
    def __init__(self):
        self.calls = []

    def emit(self, *a):
        self.calls.append(a)


def _image(status="pending", attempts=0, **kw):
    base = dict(id="i1", relative_path="a.png", absolute_path="F:/x/a.png", filename="a.png",
                base_name="a", extension=".png", size=1, mtime=0.0, fingerprint="f1",
                status=status, attempt_count=attempts)
    base.update(kw)
    return ImageItem(**base)


def _bridge(tmp_path: Path):
    state = AppState()
    state.images = [_image()]
    state.recalculate_progress()
    return SimpleNamespace(state=state, state_path=tmp_path / "app_state.json",
                           arena_state_updated=Rec(), progress_updated=Rec(), arena_log=Rec(),
                           _run_state="running")


def _pushed_images(bridge):
    assert bridge.arena_state_updated.calls, "no arena_state_updated push"
    return json.loads(bridge.arena_state_updated.calls[-1][0])["images"]


# ---------------------------------------------------------------- always emit

@pytest.mark.unit
def test_save_ok_persists_and_emits(tmp_path):
    bridge = _bridge(tmp_path)
    bridge.state.images[0].status = "processing"
    bridge.state.images[0].attempt_count = 1
    layout_state.save_arena_state(bridge)
    on_disk = json.loads(bridge.state_path.read_text(encoding="utf-8"))
    assert on_disk["images"][0]["status"] == "processing"
    assert _pushed_images(bridge)[0] == {**_pushed_images(bridge)[0], "status": "processing", "attempts": 1}
    assert len(bridge.progress_updated.calls) == 1
    assert json.loads(bridge.progress_updated.calls[0][0])["run_state"] == "running"
    assert bridge.arena_log.calls == []


@pytest.mark.unit
def test_save_failure_still_pushes_the_live_state(tmp_path, monkeypatch):
    bridge = _bridge(tmp_path)
    bridge.state.images[0].status = "completed"
    bridge.state.images[0].attempt_count = 1
    bridge.state.images[0].output_path = "F:/x/a_AI.png"

    def boom(state, path):
        raise PermissionError(errno.EACCES, "The process cannot access the file", str(path))
    monkeypatch.setattr(layout_state, "save_state", boom)

    layout_state.save_arena_state(bridge)

    row = _pushed_images(bridge)[0]
    assert (row["status"], row["attempts"], row["output_path"]) == ("completed", 1, "F:/x/a_AI.png")
    assert len(bridge.progress_updated.calls) == 1
    assert not bridge.state_path.exists()
    # reported once, loudly, without hiding that the UI keeps updating
    assert len(bridge.arena_log.calls) == 1
    msg, level = bridge.arena_log.calls[0]
    assert level == "error" and "Failed to save state" in msg and "UI keeps updating" in msg
    assert "PermissionError" in msg


@pytest.mark.unit
def test_repeated_identical_save_failure_is_logged_once_per_window(tmp_path, monkeypatch):
    bridge = _bridge(tmp_path)
    monkeypatch.setattr(layout_state, "save_state", lambda s, p: (_ for _ in ()).throw(OSError("locked")))
    clock = {"t": 100.0}
    monkeypatch.setattr(layout_state.time, "monotonic", lambda: clock["t"])

    for _ in range(5):
        layout_state.save_arena_state(bridge)
    assert len(bridge.arena_state_updated.calls) == 5, "every call still pushes state"
    assert len(bridge.arena_log.calls) == 1

    clock["t"] += layout_state.SAVE_ERROR_RELOG_SEC + 0.1
    layout_state.save_arena_state(bridge)
    assert len(bridge.arena_log.calls) == 2, "re-logged after the window"

    monkeypatch.setattr(layout_state, "save_state", lambda s, p: (_ for _ in ()).throw(OSError("disk full")))
    layout_state.save_arena_state(bridge)
    assert len(bridge.arena_log.calls) == 3, "a different error is logged immediately"
    assert "disk full" in bridge.arena_log.calls[-1][0]


@pytest.mark.unit
def test_emit_failure_never_raises_into_the_runner(tmp_path):
    bridge = _bridge(tmp_path)
    bridge.arena_state_updated = None  # broken signal object
    layout_state.save_arena_state(bridge)  # must not raise
    assert bridge.state_path.exists()


# ------------------------------------------------------------- replace retry

def _flaky_replace(monkeypatch, failures, exc_factory):
    """Patch Path.replace: fail `failures` times, then perform the real move.
    (A plain function — instances with __call__ do not bind `self` as methods.)"""
    real = Path.replace
    counter = SimpleNamespace(calls=0)

    def replace(src, dst):
        counter.calls += 1
        if counter.calls <= failures:
            raise exc_factory()
        return real(src, dst)
    monkeypatch.setattr(Path, "replace", replace)
    return counter


@pytest.mark.unit
def test_transient_permission_error_on_replace_is_retried(tmp_path, monkeypatch):
    flaky = _flaky_replace(monkeypatch, 2, lambda: PermissionError(errno.EACCES, "sharing violation"))
    monkeypatch.setattr(persistence.time, "sleep", lambda s: None)
    target = tmp_path / "state.json"
    persistence._atomic_json_write(target, {"ok": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": 1}
    assert flaky.calls == 3
    assert [p for p in tmp_path.iterdir() if p.suffix == ".tmp"] == []


@pytest.mark.unit
def test_persistent_permission_error_gives_up_after_the_budget(tmp_path, monkeypatch):
    flaky = _flaky_replace(monkeypatch, 99, lambda: PermissionError(errno.EACCES, "sharing violation"))
    slept = []
    monkeypatch.setattr(persistence.time, "sleep", slept.append)
    with pytest.raises(PermissionError):
        persistence._atomic_json_write(tmp_path / "state.json", {"ok": 1})
    assert flaky.calls == persistence.REPLACE_ATTEMPTS
    assert len(slept) == persistence.REPLACE_ATTEMPTS - 1
    assert slept == sorted(slept) and slept[0] == persistence.REPLACE_BACKOFF_SEC
    assert [p for p in tmp_path.iterdir() if p.suffix == ".tmp"] == [], "tmp file cleaned up"


@pytest.mark.unit
def test_non_transient_oserror_is_not_retried(tmp_path, monkeypatch):
    flaky = _flaky_replace(monkeypatch, 99, lambda: OSError(errno.ENOSPC, "No space left on device"))
    monkeypatch.setattr(persistence.time, "sleep", lambda s: None)
    with pytest.raises(OSError):
        persistence._atomic_json_write(tmp_path / "state.json", {"ok": 1})
    assert flaky.calls == 1


@pytest.mark.unit
def test_save_state_roundtrip_still_works(tmp_path):
    state = AppState()
    state.images = [_image(status="failed", attempts=2, error="x")]
    persistence.save_state(state, tmp_path / "s.json")
    loaded = persistence.load_state(tmp_path / "s.json")
    assert loaded.images[0].status == "failed" and loaded.images[0].attempt_count == 2


# --------------------------------------------------------- job_finished shape

@pytest.mark.unit
def test_job_finished_payload_carries_row_identity_and_fields():
    img = _image(status="completed", attempts=1, output_path="F:/x/a_AI.png", error="stale")
    done = job_finished_payload(img, "completed", "Saved to F:/x/a_AI.png")
    assert done == {"status": "completed", "message": "Saved to F:/x/a_AI.png",
                    "output_path": "F:/x/a_AI.png", "image_id": "i1", "image_path": "F:/x/a.png",
                    "attempts": 1, "error": ""}
    img = _image(status="failed", attempts=3, error="Find & Click failed for button")
    failed = job_finished_payload(img, "failed", "Find & Click failed for button")
    assert failed["error"] == "Find & Click failed for button" and failed["attempts"] == 3
    assert failed["output_path"] == "" and failed["image_id"] == "i1"


@pytest.mark.unit
def test_job_finished_payload_tolerates_bare_objects():
    payload = job_finished_payload(SimpleNamespace(), "completed", "m")
    assert payload["image_id"] == "" and payload["attempts"] == 0 and payload["output_path"] == ""
