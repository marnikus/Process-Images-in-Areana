"""Helpers extracted from the Global Saving System during the merge (RULE 18 splits).

Each one was a block inside a longer function; the end-to-end behaviour is
pinned by test_workspace_{core,save,restore,panel}. These pin each helper's
own contract.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.persistence.workspace import fsio
from app.services.workspace import apply as ws_apply
from app.services.workspace import recover, restore, save
from app.services.workspace.provider import CaptureResult, one_file
from app.services.workspace.runs import RestoreRun, SaveRequest, SaveRun
from app.ui.panels.workspace import clamp_to_screen

pytestmark = pytest.mark.unit


class _Screen:
    def __init__(self, left=0, top=0, width=1920, height=1080):
        self._l, self._t, self._w, self._h = left, top, width, height

    def left(self): return self._l
    def top(self): return self._t
    def width(self): return self._w
    def height(self): return self._h
    def right(self): return self._l + self._w - 1
    def bottom(self): return self._t + self._h - 1


def test_run_contexts_declare_their_shared_fields():
    """N1: run contexts are value objects — the fields helpers share are declared once."""
    request = SaveRequest(name="n", selected=["undo"])
    assert request.allow_partial is False and request.base_dir == ""
    run = SaveRun(bridge="b", request=request, target=Path("/t"), started="s", snapshot_id="ws_1")
    assert (run.snapshot_id, run.started) == ("ws_1", "s")
    restore_run = RestoreRun(bridge="b", manifest={}, files={}, failed=set())
    assert restore_run.failed == set()
    assert save.SaveRequest is SaveRequest  # the public import surface stays put


def test_one_file_lists_only_existing_files(tmp_path):
    here = tmp_path / "a.json"
    here.write_text("{}")
    assert one_file(here) == [here]
    assert one_file(tmp_path / "gone.json") == [] and one_file(None) == []


def test_clamp_to_screen_pulls_an_off_screen_window_back():
    got = clamp_to_screen({"x": 3000, "y": -50, "width": 2560, "height": 900}, _Screen())
    assert got == {"x": 1819, "y": 0, "width": 1920, "height": 900}


def test_clamp_to_screen_keeps_a_fitting_window():
    geo = {"x": 10, "y": 20, "width": 800, "height": 600}
    assert clamp_to_screen(geo, _Screen()) == geo


def _capture(error=None, **result):
    provider = SimpleNamespace(domain_id="d")
    return save.Capture(provider=provider, result=CaptureResult(ok=True, **result),
                        error=error)


def test_capture_block_three_shapes():
    assert save._capture_block(_capture(error={"cause": "boom"})) == {
        "ok": False, "excluded": True, "excluded_reason": "boom"}
    excluded = save._capture_block(_capture(excluded=True, excluded_reason="secret",
                                            doc={"present": True}))
    assert excluded == {"ok": True, "excluded": True, "excluded_reason": "secret",
                        "redacted_reference": {"present": True}}
    assert save._capture_block(_capture(notes=["n"])) == {
        "ok": True, "excluded": False, "notes": ["n"]}


def test_row_head_defaults_for_an_unknown_entry():
    assert restore._row_head({}, "x") == {
        "domain_id": "x", "display_name": "x", "required": False,
        "sensitivity": "public", "dependencies": {}}


def test_file_status_ok_and_size_mismatch(tmp_path):
    path = tmp_path / "s.json"
    path.write_bytes(b"12345")
    entry = {"path": "state/s.json", "bytes": 5, "schema_version": 1}
    assert restore._file_status({}, entry, path)["status"] == "ok"
    row = restore._file_status({}, {**entry, "bytes": 9}, path)
    assert row["status"] == "size_mismatch" and "5 bytes" in row["note"]


def test_affected_files_and_copy_affected(tmp_path):
    live = tmp_path / "live.json"
    live.write_text("{}")
    gone = tmp_path / "gone.json"
    provider = SimpleNamespace(domain_id="d", live_paths=lambda b: [live, gone])
    files = recover._affected_files(None, [provider])
    assert files == {"d": [live, gone]}
    backup = tmp_path / "backup"
    backup.mkdir()
    copied, absent = recover._copy_affected(files, backup)
    assert copied == {"d": ["d__live.json"]} and absent == {"d": ["gone.json"]}
    assert (backup / "d__live.json").read_text() == "{}"


def test_publish_by_copy_leaves_only_the_target(tmp_path):
    temp = tmp_path / "temp"
    (temp / "state").mkdir(parents=True)
    (temp / "state" / "a.json").write_text("{}")
    target = tmp_path / "snap"
    fsio._publish_by_copy(temp, target)
    assert (target / "state" / "a.json").read_text() == "{}"
    assert [p.name for p in tmp_path.iterdir() if ".copy-" in p.name] == []


@pytest.mark.parametrize("result,level", [("success", "success"),
                                          ("success_with_warnings", "warn"),
                                          ("failed", "error")])
def test_log_result_level_per_outcome(monkeypatch, result, level):
    lines = []
    monkeypatch.setattr(ws_apply, "log_message", lambda b, m, lv: lines.append((m, lv)))
    ws_apply._log_result(None, Path("/x/snap_1"),
                         {"result": result, "restored": ["a"], "skipped": []})
    assert lines == [("♻️ Workspace restore from snap_1: " + result
                      + " — 1 restored, 0 skipped", level)]
