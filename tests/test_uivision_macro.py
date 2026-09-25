"""The Ui.Vision macro builder — reuse the tab, draw the rect, XClick (I-63).

The owner's rules live here as code (2026-09-23): the macro **never opens a
page** (selectWindow with an EMPTY Value column — the extension's E210 is the
honest no-tab answer), the find step is one best-effort `executeScript` that
draws the RED confirmation rectangle (`#ff2d2d`, RULE 1's COLOR_FIND), and the
click is **XClick** — `refuse_dom_clicks` bans every JS-level mouse command and
the sequence test pins the whole flow. Per-run values ride `${!cmd_var1..3}`
(the extension seeds exactly `!CMD_VAR1..3`): pause budget, target, tab.
"""

import json
from datetime import date

import pytest

from app.browser.uivision import macro

pytestmark = pytest.mark.unit

NEW_CHAT = "xpath=//a[span[text()='New Chat']]"


def test_framework_macro_is_the_reuse_confirm_click_sequence():
    commands = macro.build_commands()
    assert [c["Command"] for c in commands] == [
        "selectWindow", "bringBrowserToForeground", "executeScript", "XClick", "echo"]
    assert commands[0]["Target"] == macro.TAB_VAR          # ${!cmd_var3} — the pattern's tab
    assert commands[0]["Value"] == ""                      # EMPTY: nothing is ever opened
    assert commands[2]["Command"] == "executeScript"       # the find + RED-rect step
    assert commands[3]["Target"] == macro.TARGET_VAR       # ${!cmd_var2} — the locator
    assert commands[3]["Command"] == "XClick"              # native OS input, never Click
    assert commands[4]["Value"] == "green"                 # the done marker lands in savelog


def test_the_macro_never_opens_a_page():
    commands = macro.build_commands()
    names = {c["Command"].lower() for c in commands}
    assert "open" not in names and "openbrowser" not in names
    for c in commands:
        assert c["Value"] == "" or c["Command"] == "echo", \
            f"{c['Command']} carries a Value that could navigate: {c['Value']!r}"
        assert "tab=open" not in c["Target"]


def test_find_rect_script_carries_the_references_and_the_rule1_red():
    script = macro.build_commands()[2]["Target"]
    assert macro.PAUSE_VAR in script and macro.TARGET_VAR in script
    assert macro.FIND_RECT_COLOR in script
    assert macro.FIND_RECT_COLOR == "#ff2d2d"              # RULE 1 COLOR_FIND
    assert "pointer-events:none" in script                 # never intercepts the native click
    leftover = script.replace(macro.PAUSE_VAR, "").replace(macro.TARGET_VAR, "")
    assert "${" not in leftover                             # exactly two references, no more


def test_no_dom_level_mouse_command_rides_the_macro():
    names = {c["Command"].lower() for c in macro.build_commands()}
    assert not (names & macro.FORBIDDEN_COMMANDS)


def test_refuse_dom_clicks_names_the_offender():
    with pytest.raises(ValueError, match="clickandwait"):
        macro.refuse_dom_clicks([{"Command": "XClick"}, {"Command": "clickAndWait"}])
    macro.refuse_dom_clicks([{"Command": "XClick"}, {"Command": "echo"}])  # no raise


def test_render_find_rect_js_mirrors_the_extension_rendering():
    """The extension renders ${!cmd_varN} with JSON.stringify — a ready string literal."""
    js = macro.render_find_rect_js(NEW_CHAT, 3000)
    assert "${" not in js                                   # every reference rendered
    assert f"var locator = \"{NEW_CHAT}\";" in js           # JSON.stringify of the locator
    assert 'var budget = Math.min(Math.max(parseInt("3000", 10) || 3000, 1000), 25000);' in js


def test_render_find_rect_js_quotes_a_hostile_locator_safely():
    hostile = r'xpath=//*[text()="it\'s \"> \"]'     # quotes + backslashes in the locator
    js = macro.render_find_rect_js(hostile, 500)
    assert f"var locator = {json.dumps(hostile, ensure_ascii=False)};" in js


def test_macro_name_grammar():
    assert macro.validate_macro_name("Python_XClick_Demo") == "Python_XClick_Demo"
    assert macro.validate_macro_name("  ok-name_2  ") == "ok-name_2"
    for bad in ("", "bad name", "../evil", "a/b", "x" * 65, "-lead", None):
        with pytest.raises(ValueError):
            macro.validate_macro_name(bad)


def test_creation_date_is_uivisions_unpadded_format():
    assert macro.creation_date(date(2026, 9, 5)) == "2026-9-5"
    assert macro.creation_date(date(2026, 12, 31)) == "2026-12-31"


def test_build_macro_document_shape_and_json_round_trip():
    doc = macro.build_macro(today=date(2026, 9, 23))
    assert doc["Name"] == macro.DEFAULT_MACRO_NAME == "Python_XClick_Demo"
    assert doc["CreationDate"] == "2026-9-23"
    assert isinstance(doc["Commands"], list) and len(doc["Commands"]) == 5
    assert all(set(c) == {"Command", "Target", "Value", "Description"} for c in doc["Commands"])
    text = macro.to_json(doc)
    assert text.endswith("\n")
    assert json.loads(text) == doc


# ── the TAB URL PATTERN as a guarded primary attempt (bug #2, 2026-09-24) ───

def _url_shape():
    from app.browser.uivision import plan
    return plan.Patterns


def test_url_pattern_bakes_a_guarded_primary_attempt():
    P = _url_shape()
    commands = macro.build_commands(P("", "arena.ai/image"))
    assert [c["Command"] for c in commands] == [
        "store", "selectWindow", "store",                 # the guarded url= attempt
        "selectWindow", "bringBrowserToForeground",       # today's five, unchanged
        "executeScript", "XClick", "echo"]
    assert commands[0]["Target"] == "true" and commands[0]["Value"] == "!errorIgnore"
    assert commands[1]["Target"] == "url=*arena.ai/image*" and commands[1]["Value"] == ""
    assert commands[2]["Target"] == "false" and commands[2]["Value"] == "!errorIgnore"
    assert commands[3]["Target"] == macro.TAB_VAR          # the HARD fallback decides
    for c in commands:
        assert "tab=open" not in c["Target"]              # never opens a page
        assert "open" not in c["Command"].lower()


def test_url_and_title_patterns_keep_both_attempts_and_the_fallback():
    P = _url_shape()
    commands = macro.build_commands(P("Arena", "arena.ai"))
    assert commands[1]["Target"] == "url=*arena.ai*"      # primary = the URL pattern
    assert commands[3]["Target"] == macro.TAB_VAR         # cmd_var3 = title=*Arena*
    assert [c["Command"] for c in commands][4:] == [
        "bringBrowserToForeground", "executeScript", "XClick", "echo"]


def test_title_only_and_blank_configs_run_no_dance():
    P = _url_shape()
    five = ["selectWindow", "bringBrowserToForeground", "executeScript", "XClick", "echo"]
    assert [c["Command"] for c in macro.build_commands(P("Arena"))] == five
    assert [c["Command"] for c in macro.build_commands(P())] == five
    assert [c["Command"] for c in macro.build_commands()] == five   # None = blank


def test_build_macro_bakes_the_patterns_into_this_runs_document():
    from app.browser.uivision import plan
    doc = macro.build_macro("Python_XClick_Demo", plan.Patterns("", "arena.ai"),
                            today=date(2026, 9, 24))
    assert doc["CreationDate"] == "2026-9-24"
    assert len(doc["Commands"]) == 8
    assert doc["Commands"][1]["Target"] == "url=*arena.ai*"
    text = macro.to_json(doc)
    assert json.loads(text) == doc
