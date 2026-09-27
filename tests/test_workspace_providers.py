"""Workspace providers — capture/validate/apply per domain on a real Bridge (W3/W7).

Characterization + contract on the actual stores: capture round-trips the
native doc, validation rejects real damage, apply commits through the
store's own writer, and every provider keeps the architecture contract.
"""

import json

import pytest

from app.persistence.config_manager import ConfigManager
from app.services.captcha.key_store import CaptchaKeyStore
from app.services.workspace import registry
from app.services.workspace.meta import app_meta, snapshot_id_for, utc_now_iso
from app.services.workspace.save import capture_all
from app.services.workspace.providers import arena_state as asp
from app.services.workspace.providers import session as sp
from app.ui.bridge import Bridge

pytestmark = pytest.mark.unit

RAW_KEY = "aaaaaaaaaaaaaaaaaaaaaaaa1234"


@pytest.fixture()
def bridge(tmp_path):
    return Bridge(config_manager=ConfigManager(config_dir=str(tmp_path)),
                  state_path=tmp_path / "app_state.json")


# ---- capture round-trips the native stores ----

def test_every_domain_captures_ok_on_a_real_bridge(bridge):
    for capture in capture_all(bridge, registry.all_providers()):
        assert capture.error is None, (capture.provider.domain_id, capture.error)
        assert capture.result.ok
    excluded = {c.provider.domain_id for c in capture_all(bridge, registry.all_providers())
                if c.result.excluded}
    assert excluded == {"captcha_keys", "captcha_recordings"}


def test_arena_state_capture_is_the_native_doc(bridge):
    bridge.state.urls = []
    doc = registry.get("arena_state").capture(bridge).doc
    assert set(doc) >= {"version", "urls", "folder", "prompt", "settings", "images",
                        "jobs", "progress", "run_state"}


def test_session_domains_split_one_file_by_ownership(bridge):
    bridge.config.set_state(cdp_port=9333)
    settings_doc = registry.get("session_settings").capture(bridge).doc
    grid_doc = registry.get("grid_window").capture(bridge).doc
    assert "cdp_port" in settings_doc and "cdp_port" not in grid_doc
    assert set(grid_doc) == {"grid_layout", "window_states", "window_geometry"}
    assert set(settings_doc) & set(grid_doc) == set()  # disjoint ownership


def test_undo_capture_reflects_the_live_timeline(bridge):
    bridge.undo_service.push("prompt", {"user_prompt": "hello"})
    doc = registry.get("undo").capture(bridge).doc
    assert doc["history"][-1]["kind"] == "prompt" and isinstance(doc["index"], int)


# ---- semantic validation ----

def test_arena_state_rejects_broken_shapes():
    assert asp.semantic_error({"urls": "x"}) is not None
    assert "relative_path" in asp.semantic_error(
        {"urls": [], "images": [{"id": "a"}], "jobs": [], "prompt": {},
         "settings": {}, "folder": {}})
    good = {"urls": [{}], "images": [{"id": "a", "relative_path": "x"}], "jobs": [],
            "prompt": {}, "settings": {}, "folder": {}}
    assert asp.semantic_error(good) is None
    good["images"].append({"id": "a", "relative_path": "y"})
    assert "duplicate image ids" in asp.semantic_error(good)


def test_grid_validation_rejects_unknown_ids_and_bad_geometry():
    good = {"grid_layout": json.dumps({"v": 9, "tree": {"t": "leaf", "id": "queue"}})}
    assert sp.grid_error(good) is None
    # the canonical pipeline IS the unknown-panel policy: hard error, not a heal
    assert "invalid grid" in sp.grid_error(
        {"grid_layout": json.dumps({"v": 9, "tree": {"t": "leaf", "id": "ghost"}})})
    assert "invalid grid" in sp.grid_error({"grid_layout": "{broken"})
    assert "must be an int" in sp._geometry_error(
        {"window_geometry": {"x": "0", "y": 0, "width": 100, "height": 100}})
    assert "positive" in sp._geometry_error(
        {"window_geometry": {"x": 0, "y": 0, "width": 0, "height": 100}})
    assert sp._geometry_error({"window_geometry": None}) is None


def test_grid_validation_accepts_legacy_window_id():
    tree = {"t": "leaf", "id": "captcha_records"}
    assert sp.grid_error({"grid_layout": json.dumps({"v": 5, "tree": tree})}) is None


# ---- apply commits through the store's own writer ----

def test_undo_apply_restores_the_timeline(bridge):
    provider = registry.get("undo")
    doc = {"history": [{"kind": "prompt", "value": {"x": 1}}], "index": 0}
    provider.apply(bridge, doc)
    history, index = bridge.config.undo.get()
    assert history == doc["history"] and index == 0


def test_undo_apply_failure_is_a_workspace_error(bridge, monkeypatch):
    from app.persistence.workspace.errors import WorkspaceError
    provider = registry.get("undo")
    monkeypatch.setattr(bridge.config.undo, "set", lambda h, i: False)
    with pytest.raises(WorkspaceError) as exc:
        provider.apply(bridge, {"history": [], "index": -1})
    assert exc.value.stage == "apply"


def test_grid_apply_keeps_unowned_keys_and_canonicalizes(bridge):
    from app.core.layout_service import canonical_grid_payload
    from app.core.window_catalog import WINDOW_IDS
    bridge.config.set_state(cdp_port=9444, grid_layout=None)
    provider = registry.get("grid_window")
    payload = json.dumps({"v": 8, "tree": {"t": "leaf", "id": "queue"}})
    provider.apply(bridge, {"grid_layout": payload})
    assert bridge.config.get_state("cdp_port") == 9444  # unowned key untouched
    stored = bridge.config.get_state("grid_layout")
    assert canonical_grid_payload(stored) == (stored, None)  # canonical fixed point
    assert json.loads(stored)["v"] == 9
    from app.core.layout_service import leaf_ids
    assert sorted(leaf_ids(json.loads(stored)["tree"])) == sorted(WINDOW_IDS)


def test_window_states_apply_filters_unknown_ids(bridge):
    provider = registry.get("grid_window")
    provider.apply(bridge, {"window_states": {"closed": ["log", "ghost"], "minimized": ["log"]}})
    assert bridge.config.get_state("window_states") == {"closed": ["log"], "minimized": []}


def test_preset_store_replace_all_validates(bridge):
    bridge.config.window_presets.save_preset("A", {"grid": {"payload": "{}"}})
    doc = bridge.config.window_presets.all_data()
    registry.get("window_presets").apply(bridge, doc)
    assert bridge.config.window_presets.load_preset("A") == {"grid": {"payload": "{}"}}
    with pytest.raises(ValueError):
        bridge.config.window_presets.replace_all({"window_presets": []})


def test_job_history_apply_rebuilds_the_live_store(bridge):
    from app.services import job_history as jh
    provider = registry.get("job_history")
    doc = {"next_job_no": 7, "entries": [{"job_no": 6, "image_path": "x.png"}]}
    provider.apply(bridge, doc)
    store = jh.store_of(bridge)
    assert store._next_no == 7 and store.recent(1)[0]["image_path"] == "x.png"


def test_cooldowns_apply_preserves_native_sections(bridge):
    provider = registry.get("cooldowns")
    doc = {"version": 1, "entries": {"t1": {"cooldown_until": 9}}, "stats": {}, "aliases": {}}
    provider.apply(bridge, doc)
    from app.services.workspace.providers.cooldowns import cooldown_file
    on_disk = json.loads(cooldown_file(bridge).read_text(encoding="utf-8"))
    assert on_disk["entries"]["t1"]["cooldown_until"] == 9


def test_policy_providers_refuse_apply(bridge):
    from app.persistence.workspace.errors import WorkspaceError
    for domain_id in ("captcha_keys", "captcha_recordings"):
        with pytest.raises(WorkspaceError) as exc:
            registry.get(domain_id).apply(bridge, {})
        assert exc.value.stage == "apply" and exc.value.recommended()


# ---- secret policy ----

def test_captcha_keys_capture_carries_masked_presence_only(bridge, tmp_path):
    CaptchaKeyStore(str(tmp_path)).save(
        CaptchaKeyStore.load.__func__ if False else _settings_with_key())
    capture = registry.get("captcha_keys").capture(bridge)
    assert capture.excluded and "RULE 20" in capture.excluded_reason
    raw = json.dumps(capture.doc)
    assert "aaaa****1234" in raw and RAW_KEY not in raw


def _settings_with_key():
    from app.services.captcha.key_store import CaptchaSettings
    return CaptchaSettings(provider="2captcha", solve_timeout_sec=120,
                           keys={"2captcha": RAW_KEY})


# ---- coordinator helpers ----

def test_snapshot_id_is_stable_and_derived():
    one = snapshot_id_for("2026-09-25T00:00:00Z", "name")
    assert one == snapshot_id_for("2026-09-25T00:00:00Z", "name")
    assert one != snapshot_id_for("2026-09-25T00:00:00Z", "other")
    assert one.startswith("ws_20260925")


def test_app_meta_is_redacted(bridge):
    meta = app_meta(bridge)
    assert set(meta) == {"version", "build", "platform", "python"}
    assert str(bridge.config.dir) not in json.dumps(meta)


def test_utc_now_iso_shape():
    assert utc_now_iso().endswith("Z") and "T" in utc_now_iso()
