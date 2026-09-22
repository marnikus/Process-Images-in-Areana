"""I-65 · the "Firefox auto with Extension" panel slots.

RULE 8: real ConfigManager, real service layer; only the browser launch is
faked. The slots must never raise into Qt, so every failure path is asserted to
come back as a JSON payload instead.
"""

import asyncio
import json

import pytest

from app.persistence.config_manager import ConfigManager
from app.ui.panels import uivision as uiv
from app.ui.panels.uivision import UiVisionMixin

from tests.test_panel_slots import make_host

pytestmark = pytest.mark.unit


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def host(tmp_path):
    """A mixin host with a real config and one Arena URL row."""
    cfg = ConfigManager(str(tmp_path / "cfg.json"))
    emitted = []
    h, logs = make_host([UiVisionMixin], config=cfg,
                        url_rows=[{"url": "https://arena.ai/image/direct"}])
    h.uivision_result = type("S", (), {"emit": staticmethod(lambda p: emitted.append(p))})()
    h._emitted = emitted
    h._logs = logs
    return h


def payload(raw):
    return json.loads(raw)


class TestSettingsSlot:
    def test_the_first_paint_gets_the_defaults(self, host):
        got = payload(host.get_uivision_settings())
        assert got["uivision_macro"] == "Python_XClick_Demo"
        assert got["uivision_tab_pattern"] == "arena.ai"

    def test_it_reports_the_tab_the_pattern_resolves_to(self, host):
        assert payload(host.get_uivision_settings())["matched_url"] == \
            "https://arena.ai/image/direct"

    def test_it_is_not_ready_until_the_paths_are_set(self, host):
        got = payload(host.get_uivision_settings())
        assert got["ready"] is False and "ui.vision.html path" in got["missing"]

    def test_it_is_ready_once_configured(self, host):
        host.save_uivision_settings(json.dumps({"uivision_html_path": "/r/ui.vision.html",
                                                "uivision_log_path": "/r/log.txt"}))
        assert payload(host.get_uivision_settings())["ready"] is True

    def test_a_host_without_config_still_answers(self):
        h, _ = make_host([UiVisionMixin])
        assert payload(h.get_uivision_settings())["ready"] is False


class TestSaveSlot:
    def test_values_persist(self, host):
        host.save_uivision_settings(json.dumps({"uivision_tab_pattern": "example.test"}))
        assert payload(host.get_uivision_settings())["uivision_tab_pattern"] == "example.test"

    def test_the_reply_reflects_the_new_pattern(self, host):
        got = payload(host.save_uivision_settings(json.dumps({"uivision_tab_pattern": "nope"})))
        assert got["matched_url"] == ""

    def test_unknown_keys_are_ignored(self, host):
        host.save_uivision_settings(json.dumps({"evil_key": 1}))
        assert host.config.get_state("evil_key", "absent") == "absent"

    def test_bad_json_is_reported_not_raised(self, host):
        assert "error" in payload(host.save_uivision_settings("{not json"))

    def test_saving_is_logged(self, host):
        host.save_uivision_settings(json.dumps({"uivision_macro": "M"}))
        assert any("Ui.Vision settings saved" in msg for _, msg in host._logs)


class TestMacroSlot:
    def test_it_returns_the_macro_json(self, host):
        got = payload(host.get_uivision_macro())
        assert got["ok"] and json.loads(got["macro"])["Name"] == "Python_XClick_Demo"

    def test_the_macro_uses_xclick_not_click(self, host):
        doc = json.loads(payload(host.get_uivision_macro())["macro"])
        commands = [r["Command"].lower() for r in doc["Commands"]]
        assert "xclick" in commands and "click" not in commands


class TestRunSlot:
    def configure(self, host, tmp_path):
        host.save_uivision_settings(json.dumps({
            "uivision_html_path": str(tmp_path / "ui.vision.html"),
            "uivision_log_path": str(tmp_path / "uiv.log"),
            "uivision_timeout_s": 0.2}))

    def test_an_unconfigured_run_is_refused_without_launching(self, host, monkeypatch):
        launched = []
        monkeypatch.setattr(uiv.service, "run_demo", lambda *a: launched.append(a))
        got = payload(host.run_uivision_test())
        assert got["ok"] is False and "ui.vision.html path" in got["message"]
        assert launched == []

    def test_a_configured_run_reports_that_it_started(self, host, tmp_path, monkeypatch):
        self.configure(host, tmp_path)
        monkeypatch.setattr(uiv, "schedule_coro", lambda b, c: c.close())
        got = payload(host.run_uivision_test())
        assert got["ok"] and got["state"] == "running"

    def test_the_verdict_arrives_on_the_signal(self, host, tmp_path, monkeypatch):
        self.configure(host, tmp_path)

        async def fake(config, url):
            return uiv.service.MacroOutcome(state="ok", message="done", lines=["[status] ok"])

        monkeypatch.setattr(uiv.service, "run_demo", fake)
        run(uiv.run_test(host))
        assert host._emitted and payload(host._emitted[0])["ok"] is True

    def test_a_failed_run_is_emitted_and_logged_as_a_warning(self, host, tmp_path, monkeypatch):
        self.configure(host, tmp_path)

        async def fake(config, url):
            return uiv.service.MacroOutcome(state="failed", message="no XModules")

        monkeypatch.setattr(uiv.service, "run_demo", fake)
        run(uiv.run_test(host))
        assert payload(host._emitted[0])["ok"] is False
        assert any(level == "warn" for level, _ in host._logs)

    def test_the_run_names_the_macro_and_the_tab_in_the_log(self, host, tmp_path, monkeypatch):
        self.configure(host, tmp_path)

        async def fake(config, url):
            return uiv.service.MacroOutcome(state="ok", message="done")

        monkeypatch.setattr(uiv.service, "run_demo", fake)
        run(uiv.run_test(host))
        assert any("arena.ai" in msg for _, msg in host._logs)


class TestErrorPaths:
    def test_a_broken_config_is_reported_not_raised(self, host, monkeypatch):
        def boom(_settings):
            raise RuntimeError("config exploded")
        monkeypatch.setattr(uiv.service, "config_from_settings", boom)
        assert "error" in payload(host.get_uivision_settings())
        assert payload(host.get_uivision_macro())["ok"] is False

    def test_url_rows_from_a_callable_are_used(self):
        h, _ = make_host([UiVisionMixin], _url_rows=lambda: [{"url": "https://arena.ai/x"}])
        assert payload(h.get_uivision_settings())["matched_url"] == "https://arena.ai/x"

    def test_a_failing_url_source_does_not_break_the_panel(self):
        def boom():
            raise RuntimeError("no rows")
        h, _ = make_host([UiVisionMixin], _url_rows=boom)
        assert payload(h.get_uivision_settings())["matched_url"] == ""
