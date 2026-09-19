"""Undo-cluster characterization (roadmap W1.3, RULE 8).

Locks the observable behaviour of Bridge._remember_global_edit and
Bridge._apply_undo_entry for every undo kind BEFORE the dispatch-table
refactor. Runs the REAL methods against a stub self (no Qt event loop).

Characterized quirks pinned on purpose (bug-for-bug):
- _apply_undo_entry("action_blocks") logs "Remember action_blocks" — the
  first of two identical elif branches wins; the second is dead code.
- remember("folder") UPDATES state.folder; apply("folder") REPLACES it.
- apply("unknown") logs "(no specific handler)" and returns True.
- remember("unknown") is a silent no-op (no log, no crash).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.models import AppState, ImageItem, UrlRow
from app.persistence.config_manager import ConfigManager
from app.ui.bridge import Bridge


class Signal:
    def __init__(self):
        self.emitted = []

    def emit(self, *args):
        self.emitted.append(args)


def make_stub(tmp_path):
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    state = AppState()
    state.images = [
        ImageItem(id="img-1", relative_path="a.png", absolute_path="/x/a.png",
                  filename="a.png", base_name="a", extension="png",
                  size=1, mtime=1.0, fingerprint="f1", selected=True),
        ImageItem(id="img-2", relative_path="b.png", absolute_path="/x/b.png",
                  filename="b.png", base_name="b", extension="png",
                  size=1, mtime=1.0, fingerprint="f2", selected=False),
    ]
    stub = SimpleNamespace(
        config=ConfigManager(str(config_dir)),
        state=state,
        grid_layout_changed=Signal(),
        grid_layout_persisted=Signal(),
        action_blocks_updated=Signal(),
        logs=[],
        saves=0,
    )
    stub._log = lambda msg, level="info": stub.logs.append((level, str(msg)))
    stub._save_arena = lambda *a, **kw: stub.__dict__.update(
        saves=stub.saves + 1)
    return stub


URLS_JS = [{"id": "u1", "url": "https://a.ai", "enabled": True,
            "status": "ok", "last_error": None},
           {"id": "u2", "url": "https://b.ai", "enabled": False}]


@pytest.fixture
def stub(tmp_path):
    return make_stub(tmp_path)


def remember(stub, kind, value):
    Bridge._remember_global_edit(stub, kind, value)


def apply(stub, kind, value):
    return Bridge._apply_undo_entry(stub, {"kind": kind, "value": value})


# ---- remember -----------------------------------------------------------

def test_remember_grid(stub):
    remember(stub, "grid", '{"cols":3}')
    assert stub.config.get_state("grid_layout", None) == '{"cols":3}'
    assert stub.grid_layout_changed.emitted == [('{"cols":3}',)]
    assert stub.grid_layout_persisted.emitted == [(True,)]


def test_remember_urls(stub):
    remember(stub, "urls", URLS_JS)
    urls = stub.state.urls
    assert [u.url for u in urls] == ["https://a.ai", "https://b.ai"]
    assert [u.enabled for u in urls] == [True, False]
    assert urls[0].last_status == "ok"
    assert stub.saves == 1


def test_remember_folder_updates(stub):
    stub.state.folder["root_path"] = "/orig"
    remember(stub, "folder", {"root_path": "/new", "extra": 1})
    assert stub.state.folder["root_path"] == "/new"   # UPDATE, not replace
    assert stub.state.folder["extra"] == 1
    assert stub.saves == 1


def test_remember_queue_selection(stub):
    remember(stub, "queue", [{"id": "img-1", "selected": False},
                             {"id": "img-2", "selected": True}])
    assert stub.state.images[0].selected is False
    assert stub.state.images[1].selected is True
    assert stub.saves == 1


def test_remember_prompt_str_and_dict(stub):
    remember(stub, "prompt", "hello [JOB-ID]")
    assert stub.state.prompt["user_prompt"] == "hello [JOB-ID]"
    remember(stub, "prompt", {"template": "tpl"})
    assert stub.state.prompt["user_prompt"] == "tpl"


def test_remember_settings(stub):
    remember(stub, "settings", {"timeouts": {"generation": 99},
                                "output": {"suffix": "_X"},
                                "supported_types": [".png"]})
    assert stub.state.settings.timeouts["generation"] == 99
    assert stub.state.settings.output["suffix"] == "_X"
    assert stub.state.folder["supported_types"] == [".png"]
    assert stub.saves == 1


def test_remember_action_blocks(stub):
    remember(stub, "action_blocks", [{"block_id": "SUBMIT"}])
    assert stub.config.get_state("action_blocks", None) == [{"block_id": "SUBMIT"}]
    assert len(stub.action_blocks_updated.emitted) == 1


def test_remember_arena_snapshot(stub):
    remember(stub, "arena", {"urls": URLS_JS, "folder": {"root_path": "/ar"},
                             "prompt": {"template": "ar-prompt"}})
    assert [u.url for u in stub.state.urls] == ["https://a.ai", "https://b.ai"]
    assert stub.state.folder["root_path"] == "/ar"
    assert stub.state.prompt["user_prompt"] == "ar-prompt"
    assert stub.saves == 1


def test_remember_unknown_is_silent_noop(stub):
    before_logs, before_saves = list(stub.logs), stub.saves
    remember(stub, "mystery", {"any": "thing"})
    assert stub.logs == before_logs
    assert stub.saves == before_saves


def test_remember_malformed_values_do_not_crash(stub):
    remember(stub, "urls", "not-a-list")       # wrong shape: ignored
    remember(stub, "folder", "not-a-dict")
    remember(stub, "settings", None)
    assert stub.saves == 0


# ---- apply ---------------------------------------------------------------

def test_apply_grid(stub):
    assert apply(stub, "grid", '{"cols":2}') is True
    assert stub.grid_layout_changed.emitted == [('{"cols":2}',)]
    assert stub.grid_layout_persisted.emitted == [(True,)]


def test_apply_window_states(stub):
    assert apply(stub, "window_states", {"main": [1, 2]}) is True
    assert stub.config.get_state("window_states", None) == {"main": [1, 2]}


def test_apply_urls(stub):
    assert apply(stub, "urls", URLS_JS) is True
    assert len(stub.state.urls) == 2
    assert stub.state.urls[0].id == "u1"
    assert stub.saves == 1


def test_apply_folder_replaces(stub):
    stub.state.folder["root_path"] = "/orig"
    stub.state.folder["keep_me"] = "yes"
    assert apply(stub, "folder", {"root_path": "/new"}) is True
    assert stub.state.folder == {"root_path": "/new"}   # REPLACE, not update
    assert stub.saves == 1


def test_apply_queue_updates_selection_and_status(stub):
    assert apply(stub, "queue", [{"id": "img-1", "selected": False,
                                  "status": "completed"}]) is True
    assert stub.state.images[0].selected is False
    assert stub.state.images[0].status == "completed"
    assert stub.state.images[1].selected is False  # untouched
    assert stub.saves == 1


def test_apply_prompt(stub):
    assert apply(stub, "prompt", "p1") is True
    assert stub.state.prompt["user_prompt"] == "p1"
    assert apply(stub, "prompt", {"template": "p2"}) is True
    assert stub.state.prompt["user_prompt"] == "p2"


def test_apply_settings(stub):
    assert apply(stub, "settings", {"timeouts": {"generation": 5},
                                    "supported_types": [".webp"]}) is True
    assert stub.state.settings.timeouts["generation"] == 5
    assert stub.state.folder["supported_types"] == [".webp"]
    assert stub.state.settings.supported_types == [".webp"]


def test_apply_action_blocks_logs_remember_quirk(stub):
    # QUIRK pinned: the first (dead-duplicated) branch logs "Remember",
    # not "Undo" — bug-for-bug characterization
    assert apply(stub, "action_blocks", [{"block_id": "SAVE"}]) is True
    assert stub.config.get_state("action_blocks", None) == [{"block_id": "SAVE"}]
    assert any("Remember action_blocks" in msg for _, msg in stub.logs)


def test_apply_arena_snapshot(stub):
    assert apply(stub, "arena", {"urls": URLS_JS,
                                 "folder": {"root_path": "/z"},
                                 "prompt": "z-prompt"}) is True
    assert stub.state.folder["root_path"] == "/z"
    assert stub.state.prompt["user_prompt"] == "z-prompt"
    assert stub.saves == 1


def test_apply_unknown_kind_returns_true_and_logs(stub):
    assert apply(stub, "mystery", None) is True
    assert any("no specific handler" in msg for _, msg in stub.logs)


def test_apply_malformed_entry_returns_false(stub):
    assert Bridge._apply_undo_entry(stub, None) is False
    assert Bridge._apply_undo_entry(stub, "not-a-dict") is False


def test_apply_wrong_shape_value_is_noop_true(stub):
    assert apply(stub, "urls", "nope") is True
    assert stub.saves == 0
