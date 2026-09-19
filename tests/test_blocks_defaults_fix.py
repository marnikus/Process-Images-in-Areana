"""BUG 03.2 — action-block defaults are *always* restorable (headless).

Acceptance (docs/03_bugfix_plan.md):
* delete-all blocks (persisted []) -> load falls back to the 16-block default
  stack; "Restore defaults" brings the full stack back.
* repair must preserve the user's own block order (no re-sort).
"""
import json
from types import SimpleNamespace

import pytest

from app.core.action_blocks import (
    DEFAULT_STACK_ORDER,
    create_default_block,
    default_stack,
    load_stack_from_dicts,
    stack_to_dicts,
)
from app.ui.panels import blocks_defaults
from app.ui.panels.blocks_defaults import (
    REQUIRED_BLOCK_IDS,
    merge_missing_defaults,
    persist,
)


class _Emit:
    def __init__(self):
        self.calls = []

    def emit(self, payload):
        self.calls.append(payload)


def _bridge(blocks=None):
    """config + signal + log — the surface load_blocks/persist touches."""
    stored = {"action_blocks": blocks}
    cfg = SimpleNamespace(
        get_state=lambda key, default=None: stored.get(key, default),
        set_state=lambda **kw: stored.update(kw) or stored,
    )
    return SimpleNamespace(config=cfg, action_blocks_updated=_Emit(),
                           _log=lambda *a, **k: None, _stored=stored)


@pytest.mark.unit
class TestLoadBlocks:
    def test_none_restores_default_stack(self):
        stack = blocks_defaults.load_blocks(_bridge(None))
        assert [b.block_id for b in stack] == DEFAULT_STACK_ORDER
        assert len(stack) == 16

    def test_persisted_empty_list_restores_required_chain(self):
        """The delete-all regression: session holds [] -> never an empty UI.

        Core `load_stack_from_dicts` re-adds its required chain; the panel
        layer then inserts the verify blocks at their canonical positions.
        """
        stack = blocks_defaults.load_blocks(_bridge([]))
        ids = [b.block_id for b in stack]
        assert ids  # never empty
        assert set(ids) == set(REQUIRED_BLOCK_IDS)
        assert ids.index("VERIFY_ATTACHMENT") == ids.index("ATTACH_IMAGE") + 1
        assert ids.index("VERIFY_PROMPT") == ids.index("INSERT_PROMPT") + 1

    def test_corrupt_json_restores_default(self):
        stack = blocks_defaults.load_blocks(_bridge("{not json"))
        assert [b.block_id for b in stack] == DEFAULT_STACK_ORDER

    def test_in_order_partial_stack_repairs_verify_at_canonical_neighbours(self):
        core = [create_default_block(b) for b in (
            "ATTACH_IMAGE", "INSERT_PROMPT", "SUBMIT", "ADVANCE")]
        stack = blocks_defaults.load_blocks(_bridge(stack_to_dicts(core)))
        ids = [b.block_id for b in stack]
        # verify blocks land next to their canonical neighbours...
        assert ids.index("VERIFY_ATTACHMENT") == ids.index("ATTACH_IMAGE") + 1
        assert ids.index("VERIFY_PROMPT") == ids.index("INSERT_PROMPT") + 1
        # ...and the user's blocks keep their relative order
        assert [i for i in ids if i in ("ATTACH_IMAGE", "INSERT_PROMPT",
                                        "SUBMIT", "ADVANCE")] == \
            ["ATTACH_IMAGE", "INSERT_PROMPT", "SUBMIT", "ADVANCE"]
        assert set(REQUIRED_BLOCK_IDS) <= set(ids)

    def test_out_of_order_user_blocks_keep_relative_order(self):
        custom = create_default_block("CUSTOM_FIND")  # real user block
        core = [create_default_block("ATTACH_IMAGE"), custom,
                create_default_block("INSERT_PROMPT"),
                create_default_block("SUBMIT"), create_default_block("ADVANCE")]
        stack = blocks_defaults.load_blocks(_bridge(stack_to_dicts(core)))
        ids = [b.block_id for b in stack]
        # every required block is present again...
        assert set(REQUIRED_BLOCK_IDS) <= set(ids)
        # ...and user blocks were neither dropped nor re-ordered
        user = [i for i in ids if i in ("ATTACH_IMAGE", "CUSTOM_FIND",
                                        "INSERT_PROMPT", "SUBMIT", "ADVANCE")]
        assert user == ["ATTACH_IMAGE", "CUSTOM_FIND", "INSERT_PROMPT",
                        "SUBMIT", "ADVANCE"]

    def test_complete_stack_untouched(self):
        full = default_stack()
        stack = blocks_defaults.load_blocks(_bridge(stack_to_dicts(full)))
        assert [b.block_id for b in stack] == DEFAULT_STACK_ORDER

    def test_json_string_state_accepted(self):
        raw = json.dumps(stack_to_dicts(default_stack()))
        stack = blocks_defaults.load_blocks(_bridge(raw))
        assert [b.block_id for b in stack] == DEFAULT_STACK_ORDER


@pytest.mark.unit
class TestMergeMissing:
    def test_no_missing_is_identity(self):
        stack = default_stack()
        merged, added = merge_missing_defaults(stack)
        assert added == [] and merged is stack

    def test_adds_only_what_is_gone(self):
        partial = [create_default_block("OBSERVE_BASELINE"),
                   create_default_block("SUBMIT")]
        merged, added = merge_missing_defaults(partial)
        assert set(added) == set(REQUIRED_BLOCK_IDS) - {"OBSERVE_BASELINE", "SUBMIT"}
        assert {b.block_id for b in merged} >= set(REQUIRED_BLOCK_IDS)

    def test_user_order_preserved(self):
        tail = create_default_block("ADVANCE")
        head = create_default_block("OBSERVE_BASELINE")
        merged, _ = merge_missing_defaults([tail, head])
        ids = [b.block_id for b in merged]
        assert ids.index("ADVANCE") < ids.index("OBSERVE_BASELINE")


@pytest.mark.unit
class TestPersistAndRestore:
    def test_persist_writes_and_emits_json(self):
        b = _bridge(None)
        stack = default_stack()
        dicts = persist(b, stack)
        assert b._stored["action_blocks"] == stack_to_dicts(stack)
        assert len(b.action_blocks_updated.calls) == 1
        # JSON round-trip normalises the internal tuple fields -> normalise both
        assert json.loads(b.action_blocks_updated.calls[0]) == \
            json.loads(json.dumps(dicts))

    def test_restore_default_blocks_full(self):
        b = _bridge([])
        res = json.loads(blocks_defaults.BlocksDefaultsMixin.restore_default_blocks(b, False))
        assert res["ok"] is True
        assert len(res["blocks"]) == 16
        assert res["added"] == list(DEFAULT_STACK_ORDER)
        assert b._stored["action_blocks"]  # persisted
        assert b.action_blocks_updated.calls  # UI signal

    def test_restore_merge_missing_keeps_custom(self):
        b = _bridge(None)
        # user stack: one surviving default block + one custom block
        b._stored["action_blocks"] = stack_to_dicts(
            [create_default_block("OBSERVE_BASELINE"),
             create_default_block("CUSTOM_FIND")])
        res = json.loads(blocks_defaults.BlocksDefaultsMixin.restore_default_blocks(b, True))
        assert res["ok"] is True
        ids = [x["block_id"] for x in res["blocks"]]
        assert set(REQUIRED_BLOCK_IDS) <= set(ids)
        assert "CUSTOM_FIND" in ids  # custom block kept
        # the load already repaired the required chain -> nothing left to add
        assert res["added"] == []

    def test_restore_reports_error_instead_of_raising(self):
        class _BoomSignal:
            def emit(self, payload):
                raise RuntimeError("emit exploded")

        class _Broken:
            config = _bridge(None).config
            action_blocks_updated = _BoomSignal()
            _log = lambda *a, **k: None

        # a corrupted session falls back to defaults (never raises), but a
        # persist failure must come back as ok:false with the reason
        res = json.loads(blocks_defaults.BlocksDefaultsMixin.restore_default_blocks(
            _Broken(), False))
        assert res["ok"] is False and "emit exploded" in res["error"]

        def _get(key, default=None):
            raise RuntimeError("state exploded")

        class _Corrupt:
            config = SimpleNamespace(get_state=_get, set_state=lambda **kw: None)
            action_blocks_updated = _Emit()
            _log = lambda *a, **k: None

        res = json.loads(blocks_defaults.BlocksDefaultsMixin.restore_default_blocks(
            _Corrupt(), False))
        assert res["ok"] is True  # corrupted state degrades to defaults, loudly logged
