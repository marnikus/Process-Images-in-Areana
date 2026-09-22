"""I-65 · the macro document — XClick only, never a DOM Click.

The isTrusted rule is the reason this feature exists, so it is tested as a
hard refusal rather than a convention: `build_macro` must reject any
DOM-level command outright.
"""

import json

import pytest

from app.browser.uivision.macro import (FORBIDDEN_COMMANDS, NEW_CHAT_XPATH, MacroStep,
                                        build_macro, macro_json, new_chat_macro)


def commands(macro) -> list:
    return [row["Command"] for row in macro["Commands"]]


class TestTrustedInputOnly:
    @pytest.mark.parametrize("bad", ["click", "Click", "CLICK", "clickAt", "type", "sendKeys"])
    def test_dom_commands_are_refused(self, bad):
        # a DOM click reaches the page as isTrusted:false — the exact tell we avoid
        with pytest.raises(ValueError, match="DOM-level"):
            build_macro("M", [MacroStep(bad, "xpath=//a")])

    def test_the_error_names_the_replacement(self):
        with pytest.raises(ValueError, match="XClick"):
            build_macro("M", [MacroStep("click", "x")])

    def test_xclick_is_allowed(self):
        assert commands(build_macro("M", [MacroStep("XClick", "x")])) == ["XClick"]

    def test_the_forbidden_set_is_lowercase(self):
        # _reject_dom_clicks lowercases before comparing; an uppercase entry
        # in the set would therefore never match anything
        assert all(c == c.lower() for c in FORBIDDEN_COMMANDS)


class TestDemoMacro:
    def test_it_clicks_natively_and_never_via_the_dom(self):
        assert "XClick" in commands(new_chat_macro())
        assert not ({c.lower() for c in commands(new_chat_macro())} & FORBIDDEN_COMMANDS)

    def test_it_opens_pauses_clicks_and_echoes(self):
        # the shape the task asked for: open URL → pause → XClick → echo done
        got = commands(new_chat_macro())
        assert got[0] == "open" and got[1] == "pause"
        assert got.index("XClick") > got.index("pause")
        assert got[-1] == "echo"

    def test_done_is_echoed_so_the_log_has_a_verdict(self):
        assert any(r["Command"] == "echo" and r["Target"] == "done"
                   for r in new_chat_macro()["Commands"])

    def test_url_and_target_default_to_command_line_vars(self):
        # one stored macro serves every run; Python passes both per call
        rows = new_chat_macro()["Commands"]
        assert rows[0]["Target"] == "${!cmd_var1}"
        assert any(r["Target"] == "${!cmd_var2}" for r in rows if r["Command"] == "XClick")

    def test_explicit_values_override_the_vars(self):
        rows = new_chat_macro(url="https://arena.ai/", target="xpath=//b")["Commands"]
        assert rows[0]["Target"] == "https://arena.ai/"
        assert [r for r in rows if r["Command"] == "XClick"][0]["Target"] == "xpath=//b"

    def test_the_settle_pause_is_in_milliseconds(self):
        rows = new_chat_macro(settle_seconds=2.0)["Commands"]
        assert rows[1]["Target"] == "2000"

    def test_the_macro_is_named_for_the_caller(self):
        assert new_chat_macro(name="Python_XClick_Demo")["Name"] == "Python_XClick_Demo"

    def test_the_new_chat_xpath_matches_the_arena_sidebar(self):
        # <a href="/image/direct"><span>New Chat</span></a>
        assert NEW_CHAT_XPATH == "xpath=//a[span[text()='New Chat']]"


class TestSerialisation:
    def test_macro_json_is_importable_json(self):
        doc = json.loads(macro_json("M", [MacroStep("XClick", "x")]))
        assert doc["Name"] == "M" and doc["Commands"][0]["Command"] == "XClick"

    def test_every_row_has_the_three_keys_uivision_expects(self):
        for row in new_chat_macro()["Commands"]:
            assert set(row) == {"Command", "Target", "Value"}
