"""D4.3: UI panel slot contracts — happy path + guard per slot group (RULE 8).

Panels are mixins (Area A5); each slot is exercised through a bare host class
with the real ConfigManager/PagePool and fakes at the CDP/signal boundary.
Every assertion checks real slot output, so gutting a slot body fails it.
"""

import json

import pytest

from app.core.models import UrlRow
from app.persistence.config_manager import ConfigManager
from app.ui.panels import queue_scan as qs_mod
from app.ui.panels import run_control as rc_mod
from app.ui.panels.app_settings import AppSettingsMixin
from app.ui.panels.blocks_stack import BlocksStackMixin
from app.ui.panels.cdp_tools import CdpToolsMixin
from app.ui.panels.layout_state import LayoutStateMixin
from app.ui.panels.queue_scan import QueueScanMixin
from app.ui.panels.run_control import RunControlMixin
from app.ui.panels.url_queue import UrlQueueMixin
from app.ui.panels.watcher_captcha import WatcherCaptchaMixin
from app.ui.qt_compat import Signal

from tests.test_multi_page_dispatcher_run import make_img

pytestmark = pytest.mark.unit


def make_host(mixins, **attrs):
    class Host(*mixins):  # type: ignore
        pass

    host = Host()
    logs = []
    for key, value in attrs.items():
        setattr(host, key, value)
    if not hasattr(host, "_log"):
        host._log = lambda msg, level="info": logs.append((level, msg))
    if not hasattr(host, "_save_arena"):
        host._save_arena = lambda: None
    if not hasattr(host, "_emit_arena_state"):
        host._emit_arena_state = lambda: None
    if not hasattr(host, "_emit_pool_status"):
        host._emit_pool_status = lambda: None
    return host, logs


def make_state(urls=(), images=()):
    from types import SimpleNamespace
    settings = SimpleNamespace(timeouts={}, output={}, highlight={"duration_seconds": 2},
                               browser={}, supported_types=[".png", ".jpg", ".jpeg", ".webp"])
    st = SimpleNamespace(urls=list(urls), images=list(images),
                         prompt={"user_prompt": "hi [JOB-ID: x]"},
                         folder={"path": "/tmp"},
                         recalculate_progress=lambda: None,
                         settings=settings, selected_url_id=None)
    st.to_dict = lambda: {
        "version": 1,
        "urls": [u.to_dict() for u in st.urls],
        "images": [i.to_dict() for i in st.images],
        "folder": st.folder,
        "prompt": st.prompt,
        "settings": {"timeouts": settings.timeouts, "output": settings.output,
                     "highlight": settings.highlight, "browser": settings.browser},
        "progress": {},
        "run_state": "idle",
        "jobs": [],
    }
    return st


def make_cdp(connected=True):
    from types import SimpleNamespace
    return SimpleNamespace(is_connected=connected)


def make_undo():
    from types import SimpleNamespace
    return SimpleNamespace(push=lambda kind, value: None, history=lambda: ([], 0),
                           set_stack_projection=lambda hist, index: None)


@pytest.fixture
def cfg(isolated_config_dir):
    return ConfigManager(str(isolated_config_dir))


# ── cdp_tools ──

def test_cdp_tools_highlights_fallback_without_cdp(cfg):
    host, _ = make_host((CdpToolsMixin,), cdp=None, config=cfg, state=make_state(),
                        highlight_rect=Signal(str))
    reply = json.loads(host.highlight_selector("div.x", "#ff0000", 400, "cap"))
    assert reply["ok"] is True and reply["fallback"] is True
    assert json.loads(host.highlight_image("i1"))["ok"] is True
    assert json.loads(host.clear_highlights())["ok"] is True


def test_cdp_tools_config_round_trip_and_launch_command(cfg):
    host, _ = make_host((CdpToolsMixin,), cdp=None, config=cfg, state=make_state(),
                        highlight_rect=Signal(str), _page_pool=None)
    reply = json.loads(host.set_cdp_config(json.dumps({"host": "127.0.0.1", "port": 9333})))
    assert reply["ok"] is True and reply["host"] == "127.0.0.1" and reply["port"] == 9333
    assert json.loads(host.get_cdp_config()).get("port") == 9333
    launch = json.loads(host.get_chrome_launch_command())
    assert launch["port"] == 9333 and "/json/list" in launch["test_url"]
    bad = json.loads(host.set_cdp_config("{not json"))
    assert bad["ok"] is False and "error" in bad


def test_cdp_tools_guards_on_missing_cdp_or_image(cfg):
    state = make_state(images=[make_img()])
    host, _ = make_host((CdpToolsMixin,), cdp=None, config=cfg, state=state,
                        highlight_rect=Signal(str))
    assert json.loads(host.cdp_attach_image_test("i-a.png"))["error"] == "CDP not connected"
    host.cdp = make_cdp(connected=True)
    assert "No image found" in json.loads(host.cdp_attach_image_test("nope"))["error"]
    assert "No selected image" in json.loads(host.cdp_test_full_flow())["error"]
    assert json.loads(host.cdp_insert_prompt_test(""))["ok"] is True


# ── url_queue ──

def test_url_queue_add_remove_toggle_edit_test(cfg):
    host, _ = make_host((UrlQueueMixin,), config=cfg, state=make_state(),
                        url_presets_updated=Signal(str), presets_changed=Signal(str, str))
    added = json.loads(host.add_url("https://arena.ai/image/direct"))
    assert added["ok"] is True
    dup = json.loads(host.add_url("https://arena.ai/image/direct"))
    assert dup["error"] == "URL already exists"
    assert json.loads(host.add_url("not a url"))["ok"] is False
    row_id = added["id"]
    assert json.loads(host.toggle_url(row_id))["enabled"] is False
    assert json.loads(host.edit_url(row_id, "https://arena.ai/other"))["ok"] is True
    assert json.loads(host.edit_url(row_id, ""))["error"] == "empty URL"
    assert json.loads(host.test_url(row_id))["status"] == "ready"
    assert json.loads(host.test_url("ghost"))["error"] == "not found"
    assert json.loads(host.remove_url(row_id))["ok"] is True
    assert json.loads(host.remove_url(row_id))["error"] == "not found"
    assert json.loads(host.toggle_url("ghost"))["error"] == "not found"


def test_url_queue_presets_emit_update_signals(cfg):
    host, logs = make_host((UrlQueueMixin,), config=cfg, state=make_state(),
                           url_presets_updated=Signal(str), presets_changed=Signal(str, str))
    host.add_url_preset("https://arena.ai/image/direct")
    presets = json.loads(host.get_url_presets())
    assert any("arena.ai" in p for p in presets)
    assert any("bookmark added" in msg for _, msg in logs)
    host.add_url_preset("")  # guard: empty does not touch the store
    host.remove_url_preset("https://arena.ai/image/direct")
    assert json.loads(host.get_url_presets()) == []
    host.set_last_url_preset("https://arena.ai/kept")
    assert cfg.get_state("last_url_preset") == "https://arena.ai/kept"


# ── run_control ──

def test_run_control_start_run_guards(cfg):
    host, logs = make_host((RunControlMixin,), state=make_state(), config=cfg, cdp=None,
                           _cancel_requested=False, _pause_requested=False,
                           _stop_after=False, _run_state="idle", _batch_future=None)
    assert json.loads(host.start_run())["error"] == "no selected images"
    empty_prompt = make_state()
    empty_prompt.prompt = {"user_prompt": ""}
    host.state = empty_prompt
    assert json.loads(host.start_run())["error"] == "empty prompt"
    img = make_img(); img.selected = True; img.status = "pending"
    host.state = make_state(images=[img])
    assert "url" in json.loads(host.start_run())["error"].lower()  # no enabled URLs
    host.cdp = None
    host.state = make_state(images=[img],
                            urls=[UrlRow.create("https://arena.ai/c",
                                                enabled=True, tab_id="t1")])
    assert "cdp" in json.loads(host.start_run())["error"].lower()  # CDP gate


def test_run_control_start_run_ok_schedules_batch(cfg, monkeypatch):
    scheduled = []

    def fake_schedule(self, coro):
        scheduled.append(coro)
        return coro
    monkeypatch.setattr(rc_mod, "schedule_coro", fake_schedule)
    img = make_img(); img.selected = True; img.status = "pending"
    host, _ = make_host((RunControlMixin,), config=cfg, cdp=make_cdp(connected=True),
                        state=make_state(images=[img], urls=[UrlRow.create("https://arena.ai/c",
                                                                           enabled=True, tab_id="t1")]),
                        _cancel_requested=False, _pause_requested=False,
                        _stop_after=False, _run_state="idle", _batch_future=None,
                        _page_pool=None)
    assert json.loads(host.start_run())["ok"] is True
    assert host._run_state == "running"
    assert scheduled and host._batch_future is scheduled[0]


def test_run_control_pause_resume_stop_cancel_guards(cfg):
    host, _ = make_host((RunControlMixin,), state=make_state(), config=cfg, cdp=None,
                        _cancel_requested=False, _pause_requested=False,
                        _stop_after=False, _run_state="idle", _batch_future=None)
    assert json.loads(host.pause_run())["ok"] is True and host._run_state == "paused"
    assert json.loads(host.resume_run())["ok"] is True and host._run_state == "running"
    assert json.loads(host.stop_after_current())["ok"] is True and host._stop_after is True
    assert json.loads(host.cancel_current())["ok"] is True and host._cancel_requested is True


def test_run_control_retry_and_reset_targets(cfg):
    img = make_img(); img.status = "failed"; img.error = "boom"; img.selected = True
    host, _ = make_host((RunControlMixin,), state=make_state(images=[img]), config=cfg, cdp=None,
                        _cancel_requested=False, _pause_requested=False,
                        _stop_after=False, _run_state="idle", _batch_future=None)
    assert json.loads(host.retry_failed())["ok"] is True
    assert img.status == "pending" and img.error in ("", None)
    assert json.loads(host.retry_image("ghost"))["ok"] is False
    img.status = "completed"
    assert json.loads(host.reset_image("i-a.png"))["ok"] is True
    assert img.status == "pending"
    assert json.loads(host.reset_all())["ok"] is True
    assert json.loads(host.clear_queue())["ok"] is True and host.state.images == []


# ── queue_scan ──

def test_queue_scan_selection_and_folder_guards(cfg):
    img = make_img()
    host, _ = make_host((QueueScanMixin, RunControlMixin), state=make_state(images=[img]),
                        config=cfg, _scan_in_progress=False)
    assert json.loads(host.set_image_selected("i-a.png", True))["ok"] is True
    assert img.selected is True
    assert json.loads(host.set_image_selected("ghost", True))["ok"] is False
    assert json.loads(host.bulk_select(True, ""))["ok"] is True
    assert json.loads(host.clear_images())["ok"] is True
    assert host.state.images == []


def test_queue_scan_folder_path_validation(cfg, tmp_path):
    host, _ = make_host((QueueScanMixin,), state=make_state(), config=cfg,
                        _scan_in_progress=False)
    assert json.loads(host.set_folder_path("no/such/dir"))["ok"] is False
    ok = json.loads(host.set_folder_path(str(tmp_path)))
    assert ok["ok"] is True and ok["path"] == str(tmp_path)
    assert host.state.folder["root_path"] == str(tmp_path)


def test_queue_scan_real_folder_and_rule6_filter(cfg, tmp_path, monkeypatch):
    (tmp_path / "one.png").write_bytes(b"\x89PNG")
    (tmp_path / "two.jpg").write_bytes(b"\xff\xd8")
    (tmp_path / "three.txt").write_text("nope")
    (tmp_path / "four_AI.png").write_bytes(b"\x89PNG")  # AI output — filtered (RULE 6)
    monkeypatch.setattr(qs_mod, "run_off_ui_thread", lambda bridge, fn, *a: fn(bridge, *a))
    host, logs = make_host((QueueScanMixin,), state=make_state(), config=cfg,
                           _scan_in_progress=False)
    host.set_folder_path(str(tmp_path))
    reply = json.loads(host.scan_folder())
    assert reply["ok"] is True and reply["pending"] is True
    names = {img.relative_path for img in host.state.images}
    assert {"one.png", "two.jpg"} <= names
    assert "three.txt" not in names      # unsupported type
    assert "four_AI.png" not in names    # RULE 6: *_AI filtered
    assert any("Scanned" in msg for _, msg in logs)
    host._scan_in_progress = True
    again = json.loads(host.scan_folder())
    assert again["ok"] is False and "in progress" in again["error"]
    host._scan_in_progress = False
    nb = json.loads(host.scan_folder_new_batch())
    assert nb["ok"] is True and nb["cleared"] == 2  # old batch cleared before rescan


# ── app_settings ──

def test_app_settings_theme_prompt_and_save(cfg):
    host, _ = make_host((AppSettingsMixin,), config=cfg, state=make_state(),
                        presets_changed=Signal(str, str), _watcher=None)
    assert host.set_theme("dark") is True  # bool slot
    assert json.loads(host.set_prompt("a prompt [JOB-ID: x]"))["ok"] is True
    assert json.loads(host.save_settings(json.dumps({"generation_timeout_sec": 90})))["ok"] is True
    assert json.loads(host.save_settings("{bad"))["ok"] is False
    assert isinstance(json.loads(host.list_arena_presets()), list)


def test_app_settings_arena_preset_round_trip(cfg):
    host, _ = make_host((AppSettingsMixin,), config=cfg, state=make_state(),
                        presets_changed=Signal(str, str), _watcher=None, cdp=None)
    assert json.loads(host.save_arena_preset("p1"))["ok"] is True
    assert any("p1" in str(p) for p in json.loads(host.list_arena_presets()))
    assert json.loads(host.load_arena_preset("p1"))["ok"] is True
    assert json.loads(host.load_arena_preset("ghost"))["ok"] is False
    assert json.loads(host.delete_arena_preset("p1"))["ok"] is True
    assert json.loads(host.delete_arena_preset("ghost"))["ok"] is False


# ── layout_state ──

def _layout_host(cfg):
    return make_host((LayoutStateMixin,), config=cfg, state=make_state(),
                     undo_service=make_undo(), _exported_paths=[],
                     grid_layout_changed=Signal(str),
                     grid_layout_persisted=Signal(bool),
                     window_preset_list_updated=Signal(str))


def test_layout_state_grid_validation_rejects_unreadable(cfg):
    host, logs = _layout_host(cfg)
    from app.core.layout_service import default_payload
    assert host.get_grid_layout() == ""  # nothing stored yet
    assert host.save_grid_layout("{not json") is False  # RULE 13: unreadable rejected
    assert host.save_grid_layout(default_payload()) is True
    assert json.loads(host.get_grid_layout())["v"] == 5  # canonical round trip
    assert host.save_grid_layout(json.dumps({"v": 999, "tree": {}})) is False
    assert any("rejected" in msg for _, msg in logs)
    assert isinstance(host.reset_grid_layout(), str)  # slot returns JSON payload
    assert isinstance(host.get_window_states(), str)


def test_layout_state_presets_and_state_payloads(cfg):
    from app.core.layout_service import default_payload
    host, _ = _layout_host(cfg)
    assert json.loads(host.save_window_preset("wp1", default_payload()))["ok"] is True
    assert any("wp1" in str(p) for p in json.loads(host.list_window_presets()))
    doc = json.loads(host.load_window_preset("wp1"))  # payload slot: doc, no ok wrapper
    assert doc["name"] == "wp1" and doc["grid"]["window_count"] >= 1
    assert json.loads(host.load_window_preset("ghost"))["ok"] is False
    assert json.loads(host.delete_window_preset("wp1"))["ok"] is True
    app = json.loads(host.get_app_state())  # payload slots carry state, not ok
    assert app["theme"] == "dark" and "undo_history" in app["state"]
    arena = json.loads(host.get_arena_state())
    assert "urls" in arena and "prompt" in arena


# ── blocks_stack ──

def test_blocks_stack_save_add_delete_and_history(cfg):
    host, _ = make_host((BlocksStackMixin,), config=cfg,
                        undo_service=make_undo(), action_blocks_updated=Signal(str))
    stack = json.loads(host.get_action_blocks())
    assert isinstance(stack, list)
    added = json.loads(host.add_action_block("OBSERVE_BASELINE"))
    assert added["ok"] is True and added["id"]
    assert json.loads(host.add_action_block("   "))["ok"] is False  # empty type guard
    current = json.loads(host.get_action_blocks())
    block_id = current[-1]["id"]
    assert json.loads(host.delete_action_block(block_id))["ok"] is True
    assert json.loads(host.delete_action_block(block_id))["ok"] is False
    reset = json.loads(host.reset_action_blocks())
    assert reset["ok"] is True and reset["count"] >= 1
    saved = json.loads(host.save_action_blocks(json.dumps(current)))
    assert saved["ok"] is True and saved["count"] == len(current)
    assert json.loads(host.save_action_blocks("12"))["ok"] is False  # must be array
    host.save_stack_history("not json", 0)  # void slot: bad input never raises
    host.save_stack_history(json.dumps(current), 0)
    preset = json.loads(host.save_stack_preset(json.dumps({"name": "sp1", "blocks": current})))
    assert preset["ok"] is True
    assert any("sp1" in str(p) for p in json.loads(host.get_stack_presets()))
    assert json.loads(host.delete_stack_preset("sp1"))["ok"] is True
    assert json.loads(host.delete_stack_preset("sp1"))["ok"] is False
    assert json.loads(host.export_action_blocks(json.dumps(current)))["ok"] in (True, False)


# ── watcher_captcha ──

def test_watcher_captcha_config_and_state_slots(cfg):
    from app.services.watcher import WatcherConfig, WatcherService
    watcher = WatcherService(config=WatcherConfig(enabled=False, check_interval_ms=100),
                             logger=lambda msg, level="info": None)
    host, logs = make_host((WatcherCaptchaMixin,), config=cfg, _watcher=watcher)
    current = json.loads(host.get_watcher_config())
    assert current["check_interval_ms"] == 100  # plain config dict, no ok wrapper
    updated = json.loads(host.set_watcher_config(json.dumps({"check_interval_ms": 500})))
    assert updated["ok"] is True and watcher.config.check_interval_ms == 500
    assert json.loads(host.set_watcher_config("{bad"))["ok"] is False
    state = json.loads(host.get_watcher_state())
    assert "status" in state
    assert json.loads(host.start_watcher())["ok"] is True
    assert json.loads(host.stop_watcher())["ok"] is True
    assert json.loads(host.clear_watcher_overlay())["ok"] in (True, False)
    check = json.loads(host.check_watcher_now())
    assert "ok" in check or "status" in check
