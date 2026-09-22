"""I-65 · the tab pattern and the demo run.

The pattern is the control the operator drives this feature with, so its
matching rules are pinned — especially that a blank pattern matches *nothing*
rather than an arbitrary tab.
"""

import asyncio
import json

import pytest

from app.services import uivision_service as service


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


ROWS = [{"url": "https://arena.ai/image/direct"}, {"url": "https://example.test/x"},
        {"url": "https://Arena.ai/other"}]


class TestConfig:
    def test_defaults_are_usable_out_of_the_box(self):
        cfg = service.config_from_settings({})
        assert cfg.macro == "Python_XClick_Demo"
        assert cfg.tab_pattern == "arena.ai"
        assert cfg.target.startswith("xpath=")

    def test_saved_values_win(self):
        cfg = service.config_from_settings({"uivision_macro": "Other",
                                            "uivision_tab_pattern": "foo.test"})
        assert cfg.macro == "Other" and cfg.tab_pattern == "foo.test"

    def test_it_reads_attribute_style_settings_too(self):
        cfg = service.config_from_settings(type("S", (), {"uivision_macro": "Attr"})())
        assert cfg.macro == "Attr"

    def test_the_paths_are_what_is_missing_initially(self):
        assert service.config_from_settings({}).missing() == ["ui.vision.html path",
                                                              "log file path"]

    def test_a_filled_config_is_ready(self):
        cfg = service.config_from_settings({"uivision_html_path": "/r/ui.vision.html",
                                            "uivision_log_path": "/r/log.txt"})
        assert cfg.is_ready and cfg.missing() == []

    def test_a_bad_timeout_falls_back_to_the_default(self):
        for bad in ("abc", None, -5, 0):
            assert service.config_from_settings({"uivision_timeout_s": bad}).timeout_s == 60.0

    def test_as_dict_round_trips_through_config_from_settings(self):
        cfg = service.config_from_settings({"uivision_macro": "M", "uivision_target": "xpath=//b"})
        assert service.config_from_settings(cfg.as_dict()).as_dict() == cfg.as_dict()


class TestPattern:
    def test_it_matches_case_insensitively(self):
        assert len(service.matching_urls(ROWS, "arena.ai")) == 2

    def test_it_matches_a_substring(self):
        assert service.matching_urls(ROWS, "/image/direct") == ["https://arena.ai/image/direct"]

    def test_a_blank_pattern_matches_nothing(self):
        # a blank control field must never silently pick some arbitrary tab
        assert service.matching_urls(ROWS, "") == []
        assert service.matching_urls(ROWS, "   ") == []

    def test_a_pattern_with_no_match_is_empty(self):
        assert service.matching_urls(ROWS, "nowhere.test") == []

    def test_plain_string_rows_work_too(self):
        assert service.matching_urls(["https://arena.ai/"], "arena") == ["https://arena.ai/"]

    def test_pick_takes_the_first_match(self):
        assert service.pick_url(ROWS, "arena.ai") == "https://arena.ai/image/direct"

    def test_a_full_url_pattern_works_without_any_rows(self):
        # the window must be usable before the URL list has anything in it
        assert service.pick_url([], "https://arena.ai/") == "https://arena.ai/"

    def test_a_bare_pattern_with_no_rows_picks_nothing(self):
        assert service.pick_url([], "arena.ai") == ""


class TestRunDemo:
    def ready(self, **kw):
        base = {"uivision_html_path": "/r/ui.vision.html", "uivision_log_path": "/r/log.txt"}
        base.update(kw)
        return service.config_from_settings(base)

    def test_an_unconfigured_run_fails_with_the_gaps(self):
        out = run(service.run_demo(service.config_from_settings({}), "https://arena.ai/"))
        assert not out.ok and "ui.vision.html path" in out.message

    def test_a_run_without_a_matching_tab_fails_clearly(self):
        out = run(service.run_demo(self.ready(), ""))
        assert not out.ok and "pattern" in out.message

    def test_a_ready_run_reaches_the_runner(self, monkeypatch):
        seen = {}

        async def fake(run_obj, binary, timeout):
            seen.update(macro=run_obj.macro, vars=run_obj.cmd_vars, binary=binary)
            return service.MacroOutcome(state="ok", message="done")

        monkeypatch.setattr(service, "run_macro", fake)
        out = run(service.run_demo(self.ready(), "https://arena.ai/"))
        assert out.ok
        assert seen["vars"][0] == "https://arena.ai/"      # cmd_var1 = the tab
        assert seen["vars"][1].startswith("xpath=")        # cmd_var2 = the target


class TestMacroSource:
    def test_it_is_importable_json_named_after_the_config(self):
        doc = json.loads(service.demo_macro_json(service.config_from_settings({"uivision_macro": "M"})))
        assert doc["Name"] == "M"

    def test_it_uses_xclick(self):
        doc = json.loads(service.demo_macro_json(service.config_from_settings({})))
        assert any(r["Command"] == "XClick" for r in doc["Commands"])

    def test_the_preview_url_shows_what_would_be_opened(self):
        cfg = service.config_from_settings({"uivision_html_path": "/r/ui.vision.html",
                                            "uivision_log_path": "/r/log.txt"})
        assert service.preview_url(cfg, "https://arena.ai/").startswith("file:///r/ui.vision.html?")


class TestMacroNameGap:
    def test_a_blank_macro_name_is_reported_as_missing(self):
        cfg = service.UiVisionConfig({"uivision_html_path": "/r/ui.vision.html",
                                      "uivision_log_path": "/r/log.txt", "uivision_macro": ""})
        cfg.macro = ""  # the window's field cleared by hand
        assert cfg.missing() == ["macro name"] and not cfg.is_ready
