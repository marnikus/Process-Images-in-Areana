"""Global cross-surface undo and redo — actual transitions, not replaying remote actions."""

from copy import deepcopy

import pytest

from image_queue.domain.validation import ContractError
from image_queue.workspace.history import edit_state, initial_state, travel, validate_state
from image_queue.workspace.service import WorkspaceService


class MemoryWriter:
    def __init__(self):
        self.calls = []
        self.fail = False

    def save(self, state):
        if self.fail:
            raise ContractError("disk full")
        self.calls.append(deepcopy(state))


def command(service, workspace, label="Edit"):
    return {
        "kind": "edit",
        "revision": service.snapshot()["revision"],
        "workspace": workspace,
        "label": label,
    }


def test_global_timeline_crosses_prompt_layout_settings_and_preserves_jobs(state):
    state["jobs"] = {"completed": {"id": "immutable-job", "output": "source_AI.png"}}
    writer = MemoryWriter()
    service = WorkspaceService(state, writer)
    before = service.snapshot()
    workspace = deepcopy(before["workspace"])
    workspace["prompt"] = "exact \n multilingual текст"
    prompt = service.execute(command(service, workspace, "Prompt"))
    workspace["layout"]["minimized"] = ["composer"]
    layout = service.execute(command(service, workspace, "Minimize"))
    undone = service.execute({"kind": "undo", "revision": layout["revision"]})
    assert undone["workspace"] == prompt["workspace"]
    undone = service.execute({"kind": "undo", "revision": undone["revision"]})
    assert undone["workspace"] == before["workspace"]
    redone = service.execute({"kind": "redo", "revision": undone["revision"]})
    assert redone["workspace"] == prompt["workspace"]
    assert redone["jobs"] == state["jobs"]
    assert len(writer.calls) == 5


def test_undo_save_is_atomic_and_failed_writer_cannot_advance_cursor(state):
    writer = MemoryWriter()
    service = WorkspaceService(state, writer)
    workspace = deepcopy(state["workspace"])
    workspace["folder"] = "/chosen"
    current = service.execute(command(service, workspace))
    writer.fail = True
    with pytest.raises(ContractError, match="disk full"):
        service.execute({"kind": "undo", "revision": current["revision"]})
    assert service.snapshot() == current


def test_new_edit_truncates_redo(state):
    workspace = deepcopy(state["workspace"])
    workspace["prompt"] = "first"
    first = edit_state(state, workspace, "Prompt")
    workspace["prompt"] = "second"
    second = edit_state(first, workspace, "Prompt")
    undo = travel(second, "undo")
    workspace["prompt"] = "replacement"
    changed = edit_state(undo, workspace, "Replacement")
    assert len(changed["history"]) == 2
    assert travel(changed, "redo") == changed
    assert second["workspace"]["prompt"] == "second"


def test_history_cap_preserves_continuity(state):
    for index in range(105):
        workspace = deepcopy(state["workspace"])
        workspace["prompt"] = str(index)
        state = edit_state(state, workspace, "Prompt")
    assert len(state["history"]) == 100
    assert state["cursor"] == 99
    for _ in range(100):
        state = travel(state, "undo")
    assert state["workspace"]["prompt"] == "4"
    assert travel(state, "undo") == state


def test_no_op_does_not_persist_or_inflate_timeline(state):
    writer = MemoryWriter()
    service = WorkspaceService(state, writer)
    assert service.execute(command(service, state["workspace"])) == state
    assert service.execute({"kind": "undo", "revision": 0}) == state
    assert service.execute({"kind": "redo", "revision": 0}) == state
    assert writer.calls == []


def test_busy_stale_unknown_and_job_edit_commands_rejected(state):
    service = WorkspaceService(state, MemoryWriter())
    service.busy = True
    with pytest.raises(ContractError, match="Active job"):
        service.execute({"kind": "undo", "revision": 0})
    service.busy = False
    for payload in [
        {"kind": "undo", "revision": 8},
        {"kind": "undo", "revision": False},
        {"kind": "reset_jobs", "revision": 0},
        {"kind": "undo", "revision": 0, "jobs": {}},
    ]:
        with pytest.raises(ContractError):
            service.execute(payload)
    assert service.snapshot() == state


def test_invalid_history_cannot_be_loaded(state):
    for patch in [
        {"version": 2},
        {"jobs": []},
        {"history": {}},
        {"cursor": 4},
        {"history": [{}] * 101},
    ]:
        with pytest.raises(ContractError):
            validate_state({**state, **patch})
    with pytest.raises(ContractError):
        travel(state, "sideways")
    with pytest.raises(ContractError):
        edit_state(state, {**state["workspace"], "prompt": "new"}, "")


def test_corrupt_history_cursor_and_chain_rejected(state):
    first = edit_state(state, {**state["workspace"], "prompt": "one"}, "One")
    second = edit_state(first, {**first["workspace"], "prompt": "two"}, "Two")
    bad = deepcopy(second)
    bad["workspace"]["prompt"] = "different"
    with pytest.raises(ContractError, match="disagree"):
        validate_state(bad)
    bad = deepcopy(second)
    bad["history"][1]["before"]["prompt"] = "broken chain"
    with pytest.raises(ContractError, match="discontinuous"):
        validate_state(bad)


def test_snapshot_and_defaults_are_defensive_copies(workspace):
    state = initial_state(workspace)
    service = WorkspaceService(state, MemoryWriter())
    workspace["prompt"] = "external mutation"
    snapshot = service.snapshot()
    snapshot["jobs"]["x"] = 1
    assert service.snapshot()["workspace"]["prompt"] == ""
    assert service.snapshot()["jobs"] == {}
