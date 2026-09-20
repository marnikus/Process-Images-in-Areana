"""Queue thumbnails (`queue_scan.request_thumbnail` and friends) — the contract
is "never blocks the UI thread": cached data URL, pending ticket while a job
runs, error JSON for unknown / missing files, slot always released.

RULE 8: real PNGs in tmp_path through the real thumbnail service; the only
fake is the bridge surface (cache, in-progress set, executor, signal).
"""

import json
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from app.ui.panels import queue_scan


class Signal:
    def __init__(self):
        self.emitted = []

    def emit(self, *args):
        self.emitted.append(args)


def make_bridge(images, executor=None):
    return SimpleNamespace(state=SimpleNamespace(images=images), _thumb_cache={},
                           _thumb_in_progress=set(), _thumb_executor=executor,
                           thumbnail_ready=Signal())


def png(tmp_path: Path, name: str = "a.png") -> Path:
    path = tmp_path / name
    Image.new("RGB", (300, 200), (200, 30, 30)).save(path)
    return path


def item(path: Path, img_id: str = "id-a"):
    return SimpleNamespace(id=img_id, absolute_path=str(path))


def test_sync_path_returns_data_url_and_caches(tmp_path):
    bridge = make_bridge([item(png(tmp_path))])
    res = json.loads(queue_scan.request_thumbnail(bridge, "id-a"))
    assert res["ok"] and res["id"] == "id-a" and res["data_url"].startswith("data:image/")
    assert bridge._thumb_cache["id-a"] == res["data_url"]
    again = json.loads(queue_scan.request_thumbnail(bridge, "id-a"))
    assert again["cached"] is True and again["data_url"] == res["data_url"]


def test_unknown_id_and_missing_file_are_error_json(tmp_path):
    bridge = make_bridge([item(tmp_path / "gone.png")])
    assert json.loads(queue_scan.request_thumbnail(bridge, "nope")) == {"ok": False, "error": "not found"}
    assert json.loads(queue_scan.request_thumbnail(bridge, "id-a")) == {"ok": False, "error": "file not exists"}
    assert bridge._thumb_cache == {}


def test_executor_path_hands_out_a_pending_ticket_then_emits(tmp_path):
    path = png(tmp_path)
    with ThreadPoolExecutor(max_workers=1) as pool:
        bridge = make_bridge([item(path)], executor=pool)
        first = json.loads(queue_scan.request_thumbnail(bridge, "id-a"))
        assert first["pending"] is True and first["fallback_url"] == f"file://{path}"
    # pool exited → the job finished and its done-callback ran
    assert "id-a" in bridge._thumb_cache and bridge._thumb_in_progress == set()
    (img_id, payload), = bridge.thumbnail_ready.emitted
    assert img_id == "id-a" and json.loads(payload)["data_url"] == bridge._thumb_cache["id-a"]
    assert json.loads(queue_scan.request_thumbnail(bridge, "id-a"))["cached"] is True


def test_in_progress_request_gets_a_ticket_not_a_second_job(tmp_path):
    path = png(tmp_path)
    submitted = []
    fake_pool = SimpleNamespace(submit=lambda *a: submitted.append(a) or Future())
    bridge = make_bridge([item(path)], executor=fake_pool)
    queue_scan.request_thumbnail(bridge, "id-a")
    res = json.loads(queue_scan.request_thumbnail(bridge, "id-a"))
    assert res == {"ok": False, "pending": True, "id": "id-a", "fallback_url": f"file://{path}"}
    assert len(submitted) == 1 and bridge._thumb_in_progress == {"id-a"}


def test_executor_refusal_falls_back_to_sync(tmp_path):
    def refuse(*_a):
        raise RuntimeError("shutdown")
    bridge = make_bridge([item(png(tmp_path))], executor=SimpleNamespace(submit=refuse))
    res = json.loads(queue_scan.request_thumbnail(bridge, "id-a"))
    assert res["ok"] and "id-a" in bridge._thumb_cache and bridge._thumb_in_progress == set()


def test_done_callback_releases_the_slot_on_failure():
    bridge = make_bridge([])
    bridge._thumb_in_progress.add("id-a")
    fut = Future()
    fut.set_exception(OSError("decoder"))
    queue_scan.thumb_job_done(bridge, "id-a", fut)
    assert bridge._thumb_in_progress == set() and bridge._thumb_cache == {}
    ok = Future()
    ok.set_result({"ok": False, "error": "not an image"})
    bridge._thumb_in_progress.add("id-a")
    queue_scan.thumb_job_done(bridge, "id-a", ok)
    assert bridge._thumb_in_progress == set() and bridge.thumbnail_ready.emitted == []


def test_bulk_selection_and_find_image():
    imgs = [SimpleNamespace(id="1", status="pending", selected=False),
            SimpleNamespace(id="2", status="failed", selected=False),
            SimpleNamespace(id="3", status="completed", selected=True)]
    assert queue_scan.apply_bulk_selection(imgs, True, "failed") == 1
    assert [i.selected for i in imgs] == [False, True, True]
    assert queue_scan.apply_bulk_selection(imgs, False, "all") == 3
    assert not any(i.selected for i in imgs)
    assert queue_scan.find_image(imgs, "2") is imgs[1] and queue_scan.find_image(imgs, "x") is None


def test_resolve_scan_root_distinguishes_unset_from_missing(tmp_path):
    assert queue_scan.resolve_scan_root({}) == (None, "No folder set")
    assert queue_scan.resolve_scan_root({"root_path": str(tmp_path / "nope")}) == (None, "Folder does not exist")
    assert queue_scan.resolve_scan_root({"root_path": str(tmp_path)}) == (tmp_path, "")
