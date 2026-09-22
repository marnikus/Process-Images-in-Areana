"""I-65 · the Ui.Vision autorun URL — the whole API surface of the extension.

A wrong URL fails silently (the extension just sits there), so the encoding
rules are pinned here: `file:///`, percent-encoded values, `direct=1`, and a
`savelog` absolute path.
"""

from urllib.parse import parse_qs, urlparse

import pytest

from app.browser.uivision.command_url import (STORAGE_XFILE, MacroRun, build_autorun_url,
                                              to_file_url)


def q(url: str) -> dict:
    """The query parameters of `url`, decoded."""
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


class TestFileUrl:
    def test_windows_path_becomes_a_file_url(self):
        # a bare C:\… path makes the browser report "file not found"
        assert to_file_url(r"C:\rpa\ui.vision.html") == "file:///C:/rpa/ui.vision.html"

    def test_posix_path_becomes_a_file_url(self):
        assert to_file_url("/opt/rpa/ui.vision.html") == "file:///opt/rpa/ui.vision.html"

    def test_an_existing_url_is_left_alone(self):
        for url in ("file:///x/ui.vision.html", "https://example.test/ui.vision.html"):
            assert to_file_url(url) == url

    def test_empty_path_is_empty(self):
        assert to_file_url("") == "" and to_file_url(None) == ""

    def test_spaces_are_encoded(self):
        assert " " not in to_file_url(r"C:\Program Files\ui.vision.html")


class TestAutorunUrl:
    def run(self, **kw):
        kw.setdefault("macro", "Python_XClick_Demo")
        kw.setdefault("html_path", r"C:\rpa\ui.vision.html")
        return MacroRun(**kw)

    def test_the_prompt_is_skipped(self):
        # without direct=1 Ui.Vision asks "run this macro?" and the run stalls
        assert q(build_autorun_url(self.run()))["direct"] == "1"

    def test_the_rpa_window_is_kept_open(self):
        # the default is closeRPA=1, which would tear the log down mid-poll
        assert q(build_autorun_url(self.run()))["closeRPA"] == "0"

    def test_the_users_browser_is_never_closed(self):
        assert q(build_autorun_url(self.run()))["closeBrowser"] == "0"

    def test_the_macro_name_is_passed(self):
        assert q(build_autorun_url(self.run()))["macro"] == "Python_XClick_Demo"

    def test_cmd_vars_are_numbered_from_one(self):
        url = build_autorun_url(self.run(cmd_vars=["https://arena.ai/", "xpath=//a"]))
        assert q(url)["cmd_var1"] == "https://arena.ai/"
        assert q(url)["cmd_var2"] == "xpath=//a"

    def test_only_three_cmd_vars_exist(self):
        # the extension exposes ${!cmd_var1..3}; a 4th would be dropped silently
        url = build_autorun_url(self.run(cmd_vars=list("abcd")))
        assert "cmd_var4" not in q(url) and q(url)["cmd_var3"] == "c"

    def test_an_xpath_target_survives_the_round_trip(self):
        # the real target is full of / [ ] ' = — all of which would split the query
        target = "xpath=//a[span[text()='New Chat']]"
        url = build_autorun_url(self.run(cmd_vars=["https://arena.ai/", target]))
        assert q(url)["cmd_var2"] == target
        assert "[" not in urlparse(url).query  # actually encoded, not just parsed back

    def test_the_log_path_is_passed_for_direct_writing(self):
        url = build_autorun_url(self.run(log_path="/tmp/uiv.log"))
        assert q(url)["savelog"] == "/tmp/uiv.log"

    def test_no_savelog_when_no_log_path(self):
        assert "savelog" not in q(build_autorun_url(self.run()))

    def test_the_storage_mode_is_passed(self):
        assert q(build_autorun_url(self.run(), storage=STORAGE_XFILE))["storage"] == "xfile"

    def test_the_url_starts_at_the_extension_page(self):
        assert build_autorun_url(self.run()).startswith("file:///C:/rpa/ui.vision.html?")


class TestRunnable:
    def test_a_run_without_a_macro_builds_no_url(self):
        # half a URL would open a blank page and look like a hung macro
        assert build_autorun_url(MacroRun("", "C:/x/ui.vision.html")) == ""

    def test_a_run_without_the_html_page_builds_no_url(self):
        assert build_autorun_url(MacroRun("M", "")) == ""

    def test_missing_names_what_is_absent(self):
        assert MacroRun("", "").missing() == ["no macro name", "no ui.vision.html path"]

    def test_a_complete_run_is_runnable(self):
        assert MacroRun("M", "C:/x/ui.vision.html").is_runnable
