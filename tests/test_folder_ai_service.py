"""folder_ai_service tests (R12/d): queue sync + off-thread worker."""

import time
from pathlib import Path
from types import SimpleNamespace

from app.ui.services import folder_ai_service as fa


class Rec:
    def __init__(self):
        self.calls = []

    def __call__(self, *a):
        self.calls.append(a)


def img(abspath, rel="a.png"):
    return SimpleNamespace(absolute_path=str(abspath), relative_path=rel,
                           filename="a.png", base_name="a",
                           size=10, mtime=123.0, fingerprint="f")


def test_drop_missing_queue_images(tmp_path):
    keep, gone = img(tmp_path / "keep.png"), img(tmp_path / "gone.png")
    images = [keep, gone]
    fa.drop_missing_queue_images(images, tmp_path, ["gone.png"])
    assert images == [keep]


def test_rename_queue_images(tmp_path):
    (tmp_path / "a.png").write_text("x")
    old = str(Path(tmp_path, "a_AI.png").resolve())
    images = [img(old, "a_AI.png")]
    fa.rename_queue_images(images, tmp_path, [("a_AI.png", "a.png")])
    assert images[0].relative_path == "a.png"
    assert images[0].filename == "a.png" and images[0].base_name == "a"
    assert images[0].absolute_path == str(Path(tmp_path, "a.png").resolve())
    assert images[0].fingerprint != "f"


def fake_bridge(images):
    logs = Rec()
    state = SimpleNamespace(images=images, recalculate_progress=Rec())
    return (SimpleNamespace(state=state, _log=lambda m, l="info": logs(m, l),
                            _save_arena=Rec(), _scan_in_progress=True,
                            _thumb_executor=None), logs)


def test_worker_only_mode_deletes_and_syncs(tmp_path):
    (tmp_path / "a_AI.png").write_text("x")
    (tmp_path / "b.png").write_text("y")
    images = [img(tmp_path / "a_AI.png", "a_AI.png"),
              img(tmp_path / "b.png", "b.png")]
    bridge, logs = fake_bridge(images)
    fa.folder_ai_worker(bridge, tmp_path, {".png"}, "only")
    assert not (tmp_path / "b.png").exists()
    assert (tmp_path / "a_AI.png").exists()
    assert [i.relative_path for i in images] == ["a_AI.png"]
    assert any("Only _AI" in m for m, _ in logs.calls)
    assert bridge._scan_in_progress is False
    assert bridge._save_arena.calls


def test_worker_strip_mode_renames_and_syncs(tmp_path):
    (tmp_path / "a_AI.png").write_text("x")
    images = [img(tmp_path / "a_AI.png", "a_AI.png")]
    bridge, logs = fake_bridge(images)
    fa.folder_ai_worker(bridge, tmp_path, {".png"}, "strip")
    assert (tmp_path / "a.png").exists()
    assert images[0].relative_path == "a.png"
    assert any("Drop _AI" in m for m, _ in logs.calls)
    assert bridge._scan_in_progress is False


def test_worker_failure_logs_and_releases_flag():
    bridge, logs = fake_bridge([])
    bridge.state = None  # AttributeError inside try
    fa.folder_ai_worker(bridge, Path("/nonexistent"), {".png"}, "only")
    assert any("Folder _AI op failed" in m for m, _ in logs.calls)
    assert bridge._scan_in_progress is False


def test_submit_uses_executor_or_thread(tmp_path):
    submitted = Rec()
    bridge, _ = fake_bridge([])
    bridge._thumb_executor = SimpleNamespace(submit=lambda *a: submitted(*a))
    fa.submit_folder_ai(bridge, tmp_path, {".png"}, "only")
    assert submitted.calls and submitted.calls[0][0] is fa.folder_ai_worker

    bridge._thumb_executor = None  # thread fallback
    fa.submit_folder_ai(bridge, tmp_path, {".png"}, "only")
    for _ in range(200):
        if bridge._scan_in_progress is False:
            break
        time.sleep(0.01)
    assert bridge._scan_in_progress is False
