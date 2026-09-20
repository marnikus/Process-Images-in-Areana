"""Resume on scan (B13, I-46): a discovered source whose `_AI` output already
exists enters the queue as `completed` — never re-sent unless Reset/Retry.

RULE 8: real files in tmp_path through the real scanner, ImageItem factory,
merge and the scan workers; nothing is stubbed but the bridge surface.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.models import ImageItem
from app.core.run_scope import run_scope
from app.core.scanner import ScanSpec, scan_folder
from app.ui.panels import queue_scan
from app.ui.services.scan_service import merge_scanned, scan_summary


def touch(root: Path, *names: str) -> None:
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")


def by_rel(items):
    return {i["relative_path"]: i for i in items}


def test_scan_reports_the_existing_output_per_source(tmp_path):
    touch(tmp_path, "a.png", "a_AI.png", "b.png", "sub/c.jpg", "sub/c_AI.webp", "d_AI.png")
    items = by_rel(scan_folder(tmp_path))
    assert set(items) == {"a.png", "b.png", "sub/c.jpg"}  # outputs still filtered (RULE 6)
    assert items["a.png"]["existing_output"] == str(tmp_path / "a_AI.png")
    assert items["b.png"]["existing_output"] is None
    assert items["sub/c.jpg"]["existing_output"] == str(tmp_path / "sub" / "c_AI.webp")


def test_exact_ai_wins_then_highest_counter(tmp_path):
    touch(tmp_path, "a.png", "a_AI_2.png", "a_AI.png", "a_AI_7.png",
          "b.png", "b_AI_2.png", "b_AI_10.png", "b_AI_3.png")
    items = by_rel(scan_folder(tmp_path))
    assert items["a.png"]["existing_output"].endswith("a_AI.png")
    assert items["b.png"]["existing_output"].endswith("b_AI_10.png")  # numeric, not lexical


def test_output_must_be_a_sibling_in_the_same_folder(tmp_path):
    touch(tmp_path, "a.png", "other/a_AI.png", "x_AI.png")
    items = by_rel(scan_folder(tmp_path))
    assert items["a.png"]["existing_output"] is None
    assert list(items) == ["a.png"]


def test_ai_files_as_sources_still_get_outputs_reported(tmp_path):
    touch(tmp_path, "a.png", "a_AI.png")
    items = by_rel(scan_folder(tmp_path, ScanSpec(ignore_ai_suffix=False)))
    assert set(items) == {"a.png", "a_AI.png"}
    assert items["a.png"]["existing_output"].endswith("a_AI.png")
    assert items["a_AI.png"]["existing_output"] is None


def scan_dict(rel, output=None):
    return {"relative_path": rel, "absolute_path": f"/x/{rel}", "filename": rel,
            "base_name": rel.rsplit(".", 1)[0], "extension": ".png", "size": 1,
            "mtime": 1.0, "fingerprint": f"fp-{rel}", "id": f"id-{rel}",
            "existing_output": output}


@pytest.mark.parametrize("selected", [False, True])
def test_from_scan_dict_adopts_the_output(selected):
    done = ImageItem.from_scan_dict(scan_dict("a.png", "/x/a_AI.png"), selected=selected)
    assert (done.status, done.selected, done.output_path) == ("completed", False, "/x/a_AI.png")
    fresh = ImageItem.from_scan_dict(scan_dict("b.png"), selected=selected)
    assert fresh.status == ("selected" if selected else "pending")
    assert (fresh.selected, fresh.output_path) == (selected, None)


def test_merged_newcomer_with_output_is_completed_and_out_of_run_scope():
    images = []
    added = merge_scanned(images, [scan_dict("a.png", "/x/a_AI.png"), scan_dict("b.png")])
    assert added == 2
    a, b = images
    assert (a.status, a.output_path) == ("completed", "/x/a_AI.png")
    b.selected = a.selected = True  # user hits "Select all"
    assert [i.relative_path for i in run_scope(images)] == ["b.png"]


def test_rescan_keeps_in_app_status_of_known_items():
    """Boundary: adoption is for newcomers only — Reset → Scan does not flip back."""
    reset = ImageItem.from_scan_dict(scan_dict("a.png"), selected=False)  # as after Reset
    images = [reset]
    assert merge_scanned(images, [scan_dict("a.png", "/x/a_AI.png")]) == 0
    assert (reset.status, reset.output_path, reset.selected) == ("pending", None, False)


def test_scan_summary_names_the_already_done():
    assert scan_summary([scan_dict("a.png"), scan_dict("b.png")], 2) == "Scanned 2 images, 2 new"
    line = scan_summary([scan_dict("a.png", "/x/a_AI.png"), scan_dict("b.png")], 1)
    assert line == "Scanned 2 images, 1 new, 1 already have _AI output (Reset to redo)"


def make_bridge(root: Path):
    logs, saves = [], []
    state = SimpleNamespace(images=[], folder={"root_path": str(root)},
                            recalculate_progress=lambda: None)
    return SimpleNamespace(state=state, _log=lambda m, l="info": logs.append((m, l)),
                           _save_arena=lambda: saves.append(1), _scan_in_progress=True,
                           _logs=logs, _saves=saves)


def test_scan_worker_end_to_end_marks_done_and_logs(tmp_path):
    touch(tmp_path, "a.png", "a_AI.png", "b.png")
    bridge = make_bridge(tmp_path)
    queue_scan.run_scan_merge(bridge, tmp_path)
    statuses = {i.relative_path: i.status for i in bridge.state.images}
    assert statuses == {"a.png": "completed", "b.png": "pending"}
    assert ("Scanned 2 images, 2 new, 1 already have _AI output (Reset to redo)", "success") in bridge._logs
    assert bridge._saves and bridge._scan_in_progress is False


def test_new_batch_worker_reports_the_same_summary(tmp_path):
    touch(tmp_path, "a.png", "a_AI_3.png")
    bridge = make_bridge(tmp_path)
    queue_scan.run_scan_new_batch(bridge, tmp_path, cleared=5)
    img = bridge.state.images[0]
    assert (img.status, Path(img.output_path).name) == ("completed", "a_AI_3.png")
    assert any(m.startswith("🗑 New batch: cleared 5 old — Scanned 1 images, 1 new, 1 already")
               for m, _ in bridge._logs)
