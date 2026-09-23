"""The Ui.Vision macro builder — XClick only, never a DOM click (I-63).

The owner's critical rule lives here as code: `refuse_dom_clicks` bans every
JS-level mouse command, and the framework test macro reuses the run's tab
(selectWindow + tab=open fallback) before bringBrowserToForeground → pause →
XClick → echo done — with the per-run values riding `${!cmd_var1}` /
`${!cmd_var2}` / `${!cmd_var3}`.
"""

import json
from datetime import date

import pytest

from app.browser.uivision import macro

pytestmark = pytest.mark.unit


def test_framework_macro_is_the_demo_sequence():
    commands = macro.build_commands(pause_ms=2500)
    assert [c["Command"] for c in commands] == [
        "store", "store", "selectWindow", "if", "selectWindow", "end", "store",
        "bringBrowserToForeground", "pause", "XClick", "echo"]
    assert commands[0]["Target"] == "true" and commands[0]["Value"] == "!statusOK"
    assert commands[1]["Value"] == "!errorignore"     # the probe may miss: fall through
    assert commands[2]["Target"] == macro.TAB_VAR     # ${!cmd_var3} — reuse the tab
    assert commands[2]["Value"] == macro.URL_VAR      # ${!cmd_var1} — or open it fresh
    assert commands[3]["Target"] == macro.STATUS_FALSE
    assert commands[4]["Target"] == macro.OPEN_TAB == "tab=open"
    assert commands[4]["Value"] == macro.URL_VAR
    assert commands[6]["Target"] == "false"           # strict again before the click
    assert commands[8]["Target"] == "2500"
    assert commands[9]["Target"] == macro.TARGET_VAR  # ${!cmd_var2} — the locator
    assert commands[9]["Command"] == "XClick"         # native OS input, never Click
    assert commands[10]["Value"] == "green"


def test_no_dom_level_mouse_command_rides_the_macro():
    names = {c["Command"].lower() for c in macro.build_commands()}
    assert not (names & macro.FORBIDDEN_COMMANDS)


def test_refuse_dom_clicks_names_the_offender():
    with pytest.raises(ValueError, match="clickandwait"):
        macro.refuse_dom_clicks([{"Command": "XClick"}, {"Command": "clickAndWait"}])
    macro.refuse_dom_clicks([{"Command": "XClick"}, {"Command": "echo"}])  # no raise


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
    doc = macro.build_macro(today=date(2026, 9, 22))
    assert doc["Name"] == macro.DEFAULT_MACRO_NAME == "Python_XClick_Demo"
    assert doc["CreationDate"] == "2026-9-22"
    assert isinstance(doc["Commands"], list) and len(doc["Commands"]) == 11
    assert all(set(c) == {"Command", "Target", "Value", "Description"} for c in doc["Commands"])
    text = macro.to_json(doc)
    assert text.endswith("\n")
    assert json.loads(text) == doc
