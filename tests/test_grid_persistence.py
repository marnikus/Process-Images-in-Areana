"""Grid window-set parity (2026-09-18 grid-restore-push, root cause).

Python's WINDOW_IDS lagged the JS UI (missing "captcha" — 13 vs 14 windows).
Every save of a live 14-window grid then failed Python validation, "migrated"
(no-op, nothing missing), re-validated, failed again — and canonical_grid_payload
silently returned the 13-window DEFAULT, replacing the user's layout on disk.
Restart then restored the default — "grid save is not working / win on restart
is resetted". The user's own session.json grid was byte-identical to the
default, proving the replacement.

Docs: docs/archive/2026-09-18-window-preset-restore/design.md
"""

import json

import pytest

from app.core.layout_service import WINDOW_IDS, canonical_grid_payload, default_payload, leaf_ids
from app.persistence.config_manager import ConfigManager
from app.ui.bridge import Bridge


def _make_bridge(tmp_path) -> Bridge:
    cfg = ConfigManager(config_dir=str(tmp_path / "config"))
    return Bridge(cfg, tmp_path / "app_state.json")


@pytest.mark.unit
def test_python_window_set_matches_ui():
    # the UI (sash-core.js WINDOWS) has 14 windows incl. captcha
    assert len(WINDOW_IDS) == 14
    assert "captcha" in WINDOW_IDS


@pytest.mark.unit
def test_live_fourteen_window_grid_survives_save_and_restart(tmp_path):
    """A custom frame with the captcha window must come back unchanged."""
    bridge = _make_bridge(tmp_path)
    data = json.loads(default_payload())
    data["tree"]["sizes"] = [10, 10, 80]  # the user's custom frame
    user_layout = json.dumps({"v": 4, "tree": data["tree"]})
    expected, err = canonical_grid_payload(user_layout)
    assert err is None and expected  # 14-leaf tree validates cleanly now
    assert bridge.save_grid_layout(user_layout) is True
    assert bridge.get_grid_layout() == expected  # NOT the default
    # restart: fresh bridge on the same config dir
    bridge2 = _make_bridge(tmp_path)
    got = bridge2.get_grid_layout()
    assert got == expected
    got_tree = json.loads(got)["tree"]
    assert "captcha" in leaf_ids(got_tree)
    assert [float(s) for s in got_tree["sizes"]] == [10.0, 10.0, 80.0]  # custom frame kept


@pytest.mark.unit
def test_unmigratable_layout_is_rejected_not_replaced(tmp_path):
    """An unknown window must reject the save with a reason — never silently
    swap in the default (the old silent-replacement behavior)."""
    bridge = _make_bridge(tmp_path)
    data = json.loads(default_payload())
    tree = json.loads(json.dumps(data["tree"]))
    for child in tree["children"]:  # rename the "log" leaf → unknown window
        if child.get("t") == "leaf" and child.get("id") == "log":
            child["id"] = "bogus_window"
    bad = json.dumps({"v": 4, "tree": tree})
    _, err = canonical_grid_payload(bad)
    assert err and "migrated" in err  # window set mismatch, migration cannot fix it
    assert bridge.save_grid_layout(bad) is False
    assert bridge.get_grid_layout() == ""  # nothing stored — no default swap-in
