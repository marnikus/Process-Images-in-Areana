"""Firefox-auto panel — config get/save, run/stop slots, the status stream.

Stub-bridge tests (the test_job_history.py pattern): real ConfigManager on
tmp_path, FakeSignal records every `firefox_auto_updated` payload, and the run
slot is exercised through its schedule_coro + runner seams — no Qt, no Firefox.
"""

import json
from types import SimpleNamespace

import pytest

from app.browser.uivision import runner as uiv_runner
from app.persistence.config_manager import DEFAULT_SESSION, ConfigManager
from app.ui.panels import firefox_auto as fa
from app.ui.panels.firefox_auto import FirefoxAutoMixin

pytestmark = pytest.mark.unit

DEFAULTS = DEFAULT_SESSION["firefox_auto"]


class FakeSignal:
    def __init__(self):
        self.sent = []

    def emit(self, payload):
        self.sent.append(payload)

    def connect(self, _fn):
        pass


def make_bridge(tmp_path, **kw):
    logs = []
    ns = {"_log": lambda m, l="info": logs.append((l, m)), "_logs": logs,
          "firefox_auto_updated": FakeSignal(),
          "config": ConfigManager(str(tmp_path / "cfg"))}
    ns.update(kw)
    return SimpleNamespace(**ns)


def payloads(bridge):
    return [json.loads(p) for p in bridge.firefox_auto_updated.sent]


# ── get/save config ──────────────────────────────────────────────────────────

def test_get_config_returns_defaults_paths_and_idle_flag(tmp_path):
    fake = make_bridge(tmp_path)
    res = json.loads(FirefoxAutoMixin.get_firefox_auto_config(fake))
    assert res["ok"] is True and res["running"] is False
    assert res["config"] == DEFAULTS
    paths = res["paths"]
    assert set(paths) == {"home", "macro_file", "autorun_file", "log_dir"}
    assert paths["macro_file"].endswith("macros/Python_XClick_Demo.json")
    assert paths["autorun_file"].endswith("ui.vision.html")


def test_save_validates_clamps_and_persists(tmp_path):
    fake = make_bridge(tmp_path)
    res = json.loads(FirefoxAutoMixin.save_firefox_auto_config(fake, json.dumps({
        "pattern": "  My Pattern ", "url": "https://example.com", "target": "xpath=//a",
        "macro": "Ok-Macro_2", "storage": "WEIRD", "home": "", "binary": "",
        "timeout_sec": 9999, "pause_ms": "junk"})))
    assert res["ok"] is True
    cfg = res["config"]
    assert cfg["pattern"] == "My Pattern"                 # trimmed
    assert cfg["macro"] == "Ok-Macro_2"
    assert cfg["storage"] == "xfile"                      # unknown → default
    assert cfg["timeout_sec"] == 600                      # clamped to TIMEOUT_RANGE
    assert cfg["pause_ms"] == DEFAULTS["pause_ms"]        # garbage → default
    assert "url" not in cfg                               # retired key never comes back
    assert fake.config.get_state("firefox_auto") == cfg   # persisted
    saved = payloads(fake)[-1]
    assert saved["kind"] == "saved" and saved["config"] == cfg and "paths" in saved
    assert any(lvl == "success" and "config saved" in msg for lvl, msg in fake._logs)


def test_retired_url_key_drops_from_an_old_stored_config(tmp_path):
    """Old session.json files still carry the pre-2026-09-23 "url" field."""
    fake = make_bridge(tmp_path)
    fake.config.set_state(**{"firefox_auto": dict(DEFAULTS, url="https://arena.ai")})
    cfg = fa.load_config(fake)
    assert "url" not in cfg                               # load heals (RULE 13)
    assert "url" not in fa.validate_config({"url": "https://arena.ai"})   # RULE 10
    res = json.loads(FirefoxAutoMixin.save_firefox_auto_config(fake, "{}"))
    assert res["ok"] is True and "url" not in res["config"]
    assert "url" not in fake.config.get_state("firefox_auto")


def test_save_refuses_a_bad_macro_name_by_name(tmp_path):
    fake = make_bridge(tmp_path)
    res = json.loads(FirefoxAutoMixin.save_firefox_auto_config(fake, json.dumps(
        {"macro": "bad name"})))
    assert res["ok"] is False and "not allowed" in res["error"]
    assert fake.config.get_state("firefox_auto") == DEFAULTS     # nothing persisted
    assert any(lvl == "warn" and "refused" in msg for lvl, msg in fake._logs)


def test_save_refuses_unreadable_json(tmp_path):
    fake = make_bridge(tmp_path)
    res = json.loads(FirefoxAutoMixin.save_firefox_auto_config(fake, "{oops"))
    assert res["ok"] is False and "unreadable JSON" in res["error"]


def test_load_heals_a_stored_bad_macro_and_unknown_keys(tmp_path):
    fake = make_bridge(tmp_path)
    fake.config.set_state(**{"firefox_auto": {"macro": "bad name", "pattern": "  X  ",
                                              "unknown_key": 1, "timeout_sec": 3}})
    cfg = fa.load_config(fake)
    assert cfg["macro"] == "Python_XClick_Demo"           # healed to the default
    assert cfg["pattern"] == "X"
    assert "unknown_key" not in cfg
    assert cfg["timeout_sec"] == 15                       # 3 clamps into (15, 600)


def test_paths_info_follows_the_storage_mode(tmp_path):
    fake = make_bridge(tmp_path)
    from pathlib import Path
    cfg = dict(DEFAULTS)
    assert fa.paths_info(fake, cfg)["home"] == str(Path.home() / "Desktop" / "uivision")
    assert fa.paths_info(fake, cfg)["macro_file"].endswith("macros/Python_XClick_Demo.json")
    cfg["storage"] = "browser"
    assert fa.paths_info(fake, cfg)["macro_file"].endswith(
        str(fake.config.dir / "uivision" / "macros" / "Python_XClick_Demo.json"))


# ── run / stop slots ─────────────────────────────────────────────────────────

def test_run_slot_starts_once_and_refuses_the_second_run(tmp_path, monkeypatch):
    fake = make_bridge(tmp_path)
    scheduled = []
    monkeypatch.setattr(fa, "schedule_coro", lambda bridge, coro: scheduled.append(coro))
    res = json.loads(FirefoxAutoMixin.run_firefox_auto_test(fake))
    assert res == {"ok": True, "state": "running"}
    assert fake._firefox_auto_running is True and fake._firefox_auto_stop is False
    assert payloads(fake)[-1] == {"kind": "running"}
    second = json.loads(FirefoxAutoMixin.run_firefox_auto_test(fake))
    assert second["ok"] is False and "already in progress" in second["error"]
    assert len(scheduled) == 1
    scheduled[0].close()                                  # never awaited: close it


def test_stop_slot_needs_a_live_run(tmp_path):
    fake = make_bridge(tmp_path)
    res = json.loads(FirefoxAutoMixin.stop_firefox_auto_test(fake))
    assert res["ok"] is False and "no run in progress" in res["error"]
    fake._firefox_auto_running = True
    res = json.loads(FirefoxAutoMixin.stop_firefox_auto_test(fake))
    assert res == {"ok": True, "state": "stopping"}
    assert fake._firefox_auto_stop is True
    assert any(lvl == "warn" and "stop requested" in msg for lvl, msg in fake._logs)


async def test_do_run_test_streams_steps_and_the_verdict(tmp_path, monkeypatch):
    fake = make_bridge(tmp_path)
    fake._firefox_auto_running = True
    seen = {}

    async def fake_run(spec, report, seams=None):
        seen["spec"] = spec
        seen["seams"] = seams
        report("launch", "starting Firefox")
        return uiv_runner.RunResult(kind="ok", message="macro completed",
                                    steps=(("launch", "starting Firefox"),),
                                    lines=("echo: done",))

    monkeypatch.setattr(uiv_runner, "run_test", fake_run)
    await fa.do_run_test(fake)

    assert fake._firefox_auto_running is False            # finally clears the guard
    spec = seen["spec"]
    assert (spec.pattern, spec.macro, spec.storage) == ("Arena", "Python_XClick_Demo", "xfile")
    assert spec.config_dir == str(fake.config.dir)
    assert seen["seams"].stop() is False                  # stop flag wired, not pressed
    fake._firefox_auto_stop = True
    assert seen["seams"].stop() is True

    kinds = [p["kind"] for p in payloads(fake)]
    assert kinds == ["step", "step", "result"]            # run header + launch + verdict
    result = payloads(fake)[-1]
    assert result["result"] == "ok" and result["lines"] == ["echo: done"]
    assert result["steps"] == [["launch", "starting Firefox"]]
    assert any("🦊" in msg for _lvl, msg in fake._logs)   # RULE 2: every step logged


async def test_do_run_test_reports_an_explosion_as_blocked(tmp_path, monkeypatch):
    fake = make_bridge(tmp_path)
    fake._firefox_auto_running = True

    async def boom(spec, report, seams=None):
        raise RuntimeError("qt gone")

    monkeypatch.setattr(uiv_runner, "run_test", boom)
    await fa.do_run_test(fake)
    assert fake._firefox_auto_running is False
    result = payloads(fake)[-1]
    assert result["kind"] == "result" and result["result"] == "blocked"
    assert "qt gone" in result["message"]


def test_emit_status_survives_a_dead_signal(tmp_path):
    fake = make_bridge(tmp_path)

    def _boom(_payload):
        raise RuntimeError("qt gone")

    fake.firefox_auto_updated.emit = _boom
    fa.emit_status(fake, {"kind": "running"})             # best effort: no raise


def test_build_spec_maps_every_config_field(tmp_path):
    fake = make_bridge(tmp_path)
    cfg = dict(DEFAULTS, home="/h", binary="/b", timeout_sec=120, pause_ms=2000)
    spec = fa.build_spec(fake, cfg)
    assert spec == uiv_runner.RunSpec(
        pattern=cfg["pattern"], target=cfg["target"], macro=cfg["macro"],
        storage="xfile", home="/h", binary="/b", timeout_sec=120, pause_ms=2000,
        config_dir=str(fake.config.dir))
    assert not hasattr(spec, "url")                       # the spec no longer carries a URL
