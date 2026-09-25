"""The Ui.Vision macro builder — reuse the tab, draw the rect, XClick, close its own tab.

The owner's rules live here as code (2026-09-23 + 2026-09-24 rebuild): the macro
**never opens a page** (selectWindow with an EMPTY Value column — the
extension's E210/E212 is the honest no-tab answer), the find step is one
best-effort `executeScript` that draws the RED confirmation rectangle
(`#ff2d2d`, RULE 1's COLOR_FIND), and the click is **XClick** —
`refuse_dom_clicks` bans every JS-level mouse command. The protected-tab rule
(2026-09-24) is gated twice: `refuse_unsafe_tab_commands` refuses any opening
command and any tab-closing command OUTSIDE the pinned final cleanup pair
(selectWindow to the autostart tab → TAB=CLOSE), and `refuse_unpinned_shape`
refuses any drift from the pinned command sequence. Per-run values ride
`${!cmd_var1..3}` (the extension seeds exactly `!CMD_VAR1..3`): pause budget,
target, tab.
"""

import json
from datetime import date

import pytest

from app.browser.uivision import autorun, macro

pytestmark = pytest.mark.unit

NEW_CHAT = "xpath=//a[span[text()='New Chat']]"


def test_framework_macro_is_the_reuse_confirm_click_cleanup_sequence():
    commands = macro.build_commands()
    assert [c["Command"] for c in commands] == [
        "selectWindow", "bringBrowserToForeground", "executeScript", "XClick",
        "echo", "selectWindow", "selectWindow"]
    assert commands[0]["Target"] == macro.TAB_VAR          # ${!cmd_var3} — the pattern's tab
    assert commands[0]["Value"] == ""                      # EMPTY: nothing is ever opened
    assert commands[2]["Command"] == "executeScript"       # the find + RED-rect step
    assert commands[3]["Target"] == macro.TARGET_VAR       # ${!cmd_var2} — the locator
    assert commands[3]["Command"] == "XClick"              # native OS input, never Click
    assert commands[4]["Value"] == "green"                 # the done marker lands in savelog
    assert commands[5]["Target"] == autorun.PAGE_TITLE_SELECTOR  # back to the autostart tab
    assert commands[6]["Target"] == "TAB=CLOSE"            # close it — the run's own tab


def test_the_macro_never_opens_a_page():
    commands = macro.build_commands()
    names = {c["Command"].lower() for c in commands}
    assert "open" not in names and "openbrowser" not in names
    for c in commands:
        assert c["Value"] == "" or c["Command"] == "echo", \
            f"{c['Command']} carries a Value that could navigate: {c['Value']!r}"
        assert "tab=open" not in c["Target"]


def test_only_the_cleanup_pair_closes_a_tab():
    """The protected-tab rule: the final TAB=CLOSE may exist, and only there."""
    commands = macro.build_commands()
    closers = [c for c in commands if "tab=close" in c["Target"].lower()]
    assert [c["Target"] for c in closers] == ["TAB=CLOSE"]
    assert closers[0] is commands[-1]
    assert commands[-2]["Target"] == autorun.PAGE_TITLE_SELECTOR


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


def test_refuse_unsafe_tab_commands_bans_opening_and_stray_closing():
    good_tail = [{"Command": "selectWindow", "Target": autorun.PAGE_TITLE_SELECTOR},
                 {"Command": "selectWindow", "Target": "TAB=CLOSE"}]
    macro.refuse_unsafe_tab_commands([{"Command": "echo", "Target": ""}] + good_tail)
    with pytest.raises(ValueError, match="never opens"):
        macro.refuse_unsafe_tab_commands([{"Command": "open", "Target": "https://x"}])
    with pytest.raises(ValueError, match="cleanup pair"):
        macro.refuse_unsafe_tab_commands([{"Command": "selectWindow", "Target": "TAB=CLOSE"}])
    with pytest.raises(ValueError, match="cleanup pair"):
        macro.refuse_unsafe_tab_commands(
            [{"Command": "selectWindow", "Target": "title=*other tab*"}] + good_tail[1:])
    with pytest.raises(ValueError, match="cleanup pair"):
        macro.refuse_unsafe_tab_commands([{"Command": "selectWindow", "Target": "TAB=CLOSEALLOTHER"}])


def test_refuse_unpinned_shape_catches_drift():
    names = lambda cs: cs  # the gate reads the Command fields
    good = [{"Command": n, "Target": ""} for n in macro.MACRO_SHAPE]
    macro.refuse_unpinned_shape(good)
    drifted = [dict(c, Command="echo") for c in good]      # XClick swapped for an echo
    with pytest.raises(ValueError, match="drifted"):
        macro.refuse_unpinned_shape(drifted)
    with pytest.raises(ValueError, match="drifted"):
        macro.refuse_unpinned_shape(good[:-1])              # a dropped command
    assert macro.MACRO_SHAPE[-2:] == ("selectwindow", "selectwindow")


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
    assert isinstance(doc["Commands"], list) and len(doc["Commands"]) == 7
    assert all(set(c) == {"Command", "Target", "Value", "Description"} for c in doc["Commands"])
    text = macro.to_json(doc)
    assert text.endswith("\n")
    assert json.loads(text) == doc


def test_page_title_constant_backs_the_page_and_the_cleanup():
    """The cleanup's title is the page's own <title> — one owner, pinned on both sides."""
    assert f"<title>{autorun.PAGE_TITLE}</title>" in autorun.PAGE_HTML
    assert autorun.PAGE_TITLE_SELECTOR == f"title=*{autorun.PAGE_TITLE}*"
