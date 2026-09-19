"""Action-block defaults healing (2026-10-02 bugfix).

An empty persisted stack must never reach the runner: `get_action_blocks`
heals + persists the defaults, `save_action_blocks` refuses `[]`, and
`restore_default_blocks` replies with the blocks it saved.
"""

import json

import pytest

from app.core.action_blocks import DEFAULT_STACK_ORDER, validate_stack
from app.core.action_blocks_defaults import (
    REQUIRED_BLOCK_IDS,
    build_default_dicts,
    build_default_stack,
    heal_stack,
    is_empty_stack,
    missing_required,
    regenerate_ids,
)
from app.persistence.config_manager import ConfigManager
from app.ui.panels import blocks_stack
from app.ui.panels.blocks_stack import BlocksStackMixin

pytestmark = pytest.mark.unit


class _Sig:
    """Env-independent stand-in for a bound Qt signal (a class-level `Signal()` on a
    plain non-QObject host has no `.emit` when real PySide6 is installed)."""

    def __init__(self):
        self.slots = []

    def connect(self, fn):
        self.slots.append(fn)

    def emit(self, *args):
        for fn in self.slots:
            fn(*args)


class Host(BlocksStackMixin):
    def __init__(self, cfg):
        self.config = cfg
        self.logs = []
        self._log = lambda m, l="info": self.logs.append((m, l))
        self.emitted = []
        self.action_blocks_updated = _Sig()
        self.undo_service = type("U", (), {"push": lambda s, k, v: None, "history": lambda s: ([], 0),
                                           "set_stack_projection": lambda s, h, i: None})()
        self.action_blocks_updated.connect(self.emitted.append)


@pytest.fixture
def cfg(isolated_config_dir):
    return ConfigManager(str(isolated_config_dir))


def test_build_default_stack_matches_canonical_order_and_validates():
    stack = build_default_stack()
    assert [b.block_id for b in stack] == DEFAULT_STACK_ORDER
    assert "CHECK_SECURITY" in DEFAULT_STACK_ORDER  # observe block stays (detect + pause, never solve)
    assert validate_stack(stack) == (True, "")
    assert missing_required(stack) == [] and set(REQUIRED_BLOCK_IDS) <= set(DEFAULT_STACK_ORDER)
    dicts = build_default_dicts()
    assert len(dicts) == len(stack) and all(d["id"] for d in dicts)
    assert len({b.id for b in build_default_stack()} & {b.id for b in stack}) == 0  # fresh ids per call


def test_helpers_empty_detection_heal_and_regenerate():
    assert is_empty_stack(None) and is_empty_stack([]) and is_empty_stack("") and is_empty_stack(" [] ")
    assert not is_empty_stack([{"block_id": "SUBMIT"}]) and not is_empty_stack('[{"a":1}]') and not is_empty_stack(5)
    assert len(heal_stack([])) == len(DEFAULT_STACK_ORDER)
    keep = build_default_stack()[:2]
    assert heal_stack(keep) is keep
    src = [{"block_id": "SUBMIT", "id": "submit_0"}, "junk", {"block_id": "PAUSE"}]
    out = regenerate_ids(src)
    assert [b["block_id"] for b in out] == ["SUBMIT", "PAUSE"]
    assert out[0]["id"] != "submit_0" and out[0]["id"].startswith("submit_") and out[1]["id"].startswith("pause_")
    assert src[0]["id"] == "submit_0"  # input untouched
    assert missing_required(keep) and "SUBMIT" in missing_required([])


def test_get_action_blocks_heals_empty_and_persists(cfg):
    host = Host(cfg)
    cfg.set_state(action_blocks=[])
    stack = blocks_stack.get_action_blocks(host)
    assert [b.block_id for b in stack] == DEFAULT_STACK_ORDER
    assert len(cfg.get_state("action_blocks")) == len(DEFAULT_STACK_ORDER)  # healed on disk too
    assert any("restored the default stack" in m for m, _ in host.logs)
    cfg.set_state(action_blocks="[]")
    assert len(blocks_stack.get_action_blocks(host)) == len(DEFAULT_STACK_ORDER)
    assert cfg.get_state("action_blocks")[0]["block_id"] == DEFAULT_STACK_ORDER[0]
    cfg.set_state(action_blocks={"not": "a list"})  # unusable type → defaults (not persisted)
    assert len(blocks_stack.get_action_blocks(host)) == len(DEFAULT_STACK_ORDER)
    cfg.set_state(action_blocks=[{"garbage": True}, 3])  # forgiving loader: required blocks appended
    assert validate_stack(blocks_stack.get_action_blocks(host))[0] is True


def test_empty_stack_used_to_lose_the_observe_blocks():
    """Regression pin: the forgiving loader alone turns [] into required-only (no CHECK_SECURITY)."""
    from app.core.action_blocks import load_stack_from_dicts
    bare = load_stack_from_dicts([])
    assert bare and "CHECK_SECURITY" not in {b.block_id for b in bare}
    healed = heal_stack([])
    assert "CHECK_SECURITY" in {b.block_id for b in healed}


def test_get_action_blocks_keeps_a_valid_saved_stack(cfg):
    host = Host(cfg)
    saved = build_default_dicts()
    saved[3]["timeout_ms"] = 4242  # user customisation must survive the read
    cfg.set_state(action_blocks=saved)
    stack = blocks_stack.get_action_blocks(host)
    assert [b.id for b in stack] == [d["id"] for d in saved]
    assert stack[3].timeout_ms == 4242
    assert json.loads(json.dumps(cfg.get_state("action_blocks"))) == json.loads(json.dumps(saved))  # untouched, no heal log
    assert host.logs == []
    partial = saved[:3]
    cfg.set_state(action_blocks=partial)
    kept = blocks_stack.get_action_blocks(host)
    assert [b.id for b in kept[:3]] == [d["id"] for d in partial]  # user rows first, required appended after
    assert validate_stack(kept)[0] is True


def test_save_rejects_empty_and_restore_replies_with_blocks(cfg):
    host = Host(cfg)
    res = json.loads(host.save_action_blocks("[]"))
    assert res["ok"] is False and "restore_default_blocks" in res["error"]
    assert json.loads(host.save_action_blocks("not json"))["ok"] is False
    assert json.loads(host.save_action_blocks('{"a": 1}')) == {"ok": False, "error": "must be array"}
    restored = json.loads(host.restore_default_blocks())
    assert restored["ok"] is True and restored["count"] == len(DEFAULT_STACK_ORDER)
    assert [b["block_id"] for b in restored["blocks"]] == DEFAULT_STACK_ORDER
    assert json.loads(json.dumps(cfg.get_state("action_blocks"))) == restored["blocks"]
    payload = json.loads(host.get_action_blocks())
    assert [b["id"] for b in payload] == [b["id"] for b in restored["blocks"]]


def test_restore_defaults_degrades_to_error_json(cfg, monkeypatch):
    host = Host(cfg)
    monkeypatch.setattr(blocks_stack, "save_action_blocks", lambda bridge, stack: False)
    assert json.loads(blocks_stack.restore_defaults(host)) == {"ok": False, "error": "save failed"}

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(blocks_stack, "build_default_stack", boom)
    assert json.loads(host.restore_default_blocks()) == {"ok": False, "error": "boom"}
