"""BUG 03.5 — one guaranteed live path for every JS button (headless).

Acceptance (docs/03_bugfix_plan.md):
* `invoke(name, args_json)` routes to the real slot and always answers JSON;
* the boot audit reports missing / fallback-only slots so a dead button
  fails loudly instead of silently;
* `tools/check_dom_ids.py` stays at zero dead ids.
"""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ui import bridge_slots
from app.ui.bridge_slots import (
    REQUIRED_SLOTS,
    all_required,
    audit_slots,
    dispatch,
    log_slot_audit,
)

REPO = Path(__file__).parent.parent


class _Bridge:
    """Plain python stand-in: enough of the slot surface to audit/dispatch."""

    def __init__(self, **overrides):
        self.calls = []
        self._logs = []

        def add_url(text, tab_id=""):
            self.calls.append(("add_url", text, tab_id))
            return json.dumps({"ok": True, "id": "u1"})

        def get_action_blocks():
            return {"ok": True, "blocks": []}

        def restore_default_blocks(merge_missing=False):
            return json.dumps({"ok": True, "added": []})

        def scan_folder(start_dir=""):
            self.calls.append(("scan_folder", start_dir))
            return json.dumps({"ok": True, "count": 3})

        def pick_folder(start_dir=""):
            return {"ok": True, "path": "/tmp"}  # dict on purpose (normalise)

        def set_folder_path(path):
            return None  # None on purpose

        def clear_queue():
            return "cleared"  # bare string on purpose

        def broken():
            raise ValueError("boom")

        slots = {
            "add_url": add_url, "get_action_blocks": get_action_blocks,
            "restore_default_blocks": restore_default_blocks,
            "scan_folder": scan_folder, "pick_folder": pick_folder,
            "set_folder_path": set_folder_path, "clear_queue": clear_queue,
            "broken": broken,
        }
        for name, fn in slots.items():
            setattr(self, name, fn)
        for name, value in overrides.items():
            setattr(self, name, value)

    def _log(self, msg, level="info"):
        self._logs.append((msg, level))


@pytest.mark.unit
class TestDispatch:
    def test_routes_to_slot_and_normalises_json_string(self):
        b = _Bridge()
        out = json.loads(dispatch(b, "add_url", json.dumps(["https://x.test", "t1"])))
        assert out == {"ok": True, "id": "u1"}
        assert b.calls == [("add_url", "https://x.test", "t1")]

    def test_dict_result_becomes_json(self):
        out = json.loads(dispatch(b := _Bridge(), "pick_folder", "[]"))
        assert out == {"ok": True, "path": "/tmp"}

    def test_none_result_becomes_ok(self):
        out = json.loads(dispatch(_Bridge(), "set_folder_path", '["/tmp"]'))
        assert out == {"ok": True}

    def test_bare_string_wrapped(self):
        out = json.loads(dispatch(_Bridge(), "clear_queue", "[]"))
        assert out == {"ok": True, "value": "cleared"}

    def test_unknown_slot_rejected(self):
        out = json.loads(dispatch(_Bridge(), "drop_all_tables", "[]"))
        assert out["ok"] is False and "not in contract" in out["error"]

    def test_unimplemented_slot_rejected(self):
        out = json.loads(dispatch(_Bridge(), "get_url_presets", "[]"))
        assert out["ok"] is False and "not implemented" in out["error"]

    def test_bad_args_json_rejected(self):
        out = json.loads(dispatch(_Bridge(), "add_url", "{not json"))
        assert out["ok"] is False and "bad args" in out["error"]

    def test_scalar_args_wrapped_into_list(self):
        b = _Bridge()
        dispatch(b, "scan_folder", json.dumps("/tmp"))
        assert b.calls == [("scan_folder", "/tmp")]

    def test_exception_never_propagates(self):
        b = _Bridge(clear_queue=lambda: 1 / 0)  # contract slot that raises
        out = json.loads(dispatch(b, "clear_queue", "[]"))
        assert out["ok"] is False and "ZeroDivisionError" in out["error"]

    def test_invoke_via_mixin_matches_dispatch(self):
        b = _Bridge()
        mixin = bridge_slots.BridgeDispatchMixin
        b.invoke = mixin.invoke.__get__(b, type(b))
        b.slot_audit = mixin.slot_audit.__get__(b, type(b))
        assert json.loads(b.invoke("clear_queue")) == {"ok": True, "value": "cleared"}
        report = json.loads(b.slot_audit())
        assert report["missing"]  # most contract slots are not on this fake


class _FakeMethod:
    def __init__(self, name):
        self._n = name.encode()

    def name(self):
        return self._n


class _FakeMetaObject:
    def __init__(self, names):
        self._names = names

    def methodCount(self):
        return len(self._names)

    def method(self, i):
        return _FakeMethod(self._names[i])


def _full_bridge():
    """Every contract slot callable + meta-object exposing all of them."""
    logs = []
    attrs = {name: (lambda *a, _n=name, _l=logs: _l.append(_n) or json.dumps({"ok": True}))
             for name in all_required()}
    attrs["_log"] = lambda msg, level="info": logs.append((msg, level))
    attrs["metaObject"] = lambda: _FakeMetaObject(list(all_required()))
    return SimpleNamespace(**attrs), logs


@pytest.mark.unit
class TestAudit:
    def test_required_contract_contains_new_slots(self):
        flat = all_required()
        assert "get_arena_state" in flat          # url_list group
        assert "restore_default_blocks" in flat   # BUG 03.2
        assert "pick_folder" in flat and "set_folder_path" in flat
        assert len(REQUIRED_SLOTS) == 5  # grouped by window

    def test_headless_reports_fallback_only_not_missing(self):
        report = audit_slots(_full_bridge()[0])
        assert report["missing"] == []  # every slot is callable on the fake
        assert report["exposed"] == sorted(all_required())

    def test_headless_without_metaobject_is_fallback_only(self):
        b = _full_bridge()[0]
        b.metaObject = None
        report = audit_slots(b)
        assert report["exposed"] == []
        assert "add_url" in report["fallback_only"]
        assert report["missing"] == []

    def test_missing_slot_is_detected(self):
        b, _ = _full_bridge()
        del b.add_url
        report = audit_slots(b)
        assert report["missing"] == ["add_url"]

    def test_log_slot_audit_banner(self):
        b, logs = _full_bridge()
        report = log_slot_audit(b)
        assert report["missing"] == []
        assert any("✅ Bridge contract OK" in m for m, _ in logs)

    def test_log_slot_audit_missing_is_loud(self):
        class _Bare:
            _log_calls = []

            def _log(self, msg, level="info"):
                self._log_calls.append((msg, level))

        bare = _Bare()
        log_slot_audit(bare)
        errs = [m for m, l in bare._log_calls if l == "error"]
        assert errs and "MISSING" in errs[0]


@pytest.mark.integration
def test_dom_id_checker_green():
    """tools/check_dom_ids.py — zero dead ids across index.html + all JS."""
    proc = subprocess.run(
        [sys.executable, str(REPO / "tools" / "check_dom_ids.py")],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "0 dead" in proc.stdout
