"""The Windows OS file dialog of the Firefox attach macro (live fix 2026-09-26).

Owner's live run: the Add-files XClick opened the dialog, but the File name box
stayed EMPTY and the dialog stayed open (even the ESC row never closed it). Root
causes, each pinned here:

* Ui.Vision XType in browser mode never reaches the OS dialog — every key row
  must run inside `XDesktopAutomation true … false`;
* `!StringEscape` (default on) eats `\\u` `\\t` `\\n` of a Windows path, and typing
  a path char by char is rewritten by the dialog's autocomplete — the path is
  PASTED from `!clipboard`, quoted, with forward slashes, never XType'd;
* Firefox's dialog ignores a bare Enter (Ui.Vision forum) — Open is Alt+O, and an
  Enter / ESC follows only while the dialog is provably still open (the page has
  no focus and our preview is absent), so a stray key never lands in the page.
"""

import pytest

from app.browser.uivision import file_dialog as fd
from app.browser.uivision import job_macros as jm

pytestmark = pytest.mark.unit

PATH = r"C:\Users\nora\Process\config\uivision\uploads\arena_c1.png"


def rows(cmds):
    return [(c["Command"], c["Target"], c["Value"]) for c in cmds]


def desktop_spans(seq):
    """(command, target) of every row, tagged with whether desktop mode is on."""
    on, out = False, []
    for cmd, target, _ in seq:
        if cmd == "XDesktopAutomation":
            on = target == "true"
            continue
        out.append((cmd, target, on))
    return out, on


def test_dialog_path_is_quoted_with_forward_slashes():
    assert fd.dialog_path(PATH) == '"C:/Users/nora/Process/config/uivision/uploads/arena_c1.png"'


@pytest.mark.parametrize("bad", ["", "  ", "C:/a\nb.png", 'C:/a"b.png', "C:/${x}/a.png"])
def test_dialog_path_refuses_what_the_dialog_or_ui_vision_would_mangle(bad):
    with pytest.raises(ValueError):
        fd.dialog_path(bad)


def test_the_path_is_pasted_from_the_clipboard_with_string_escape_off():
    seq = rows(fd.fill_and_open(PATH, "arena_c1.png"))
    off = seq.index(("store", "false", "!StringEscape"))
    clip = seq.index(("store", fd.dialog_path(PATH), "!clipboard"))
    back = seq.index(("store", "true", "!StringEscape"))
    assert off < clip < back
    assert not any(c == "XType" and "arena_c1" in t for c, t, _ in seq), "never type the path"


def test_every_key_goes_to_the_os_dialog_in_desktop_mode():
    tagged, left_on = desktop_spans(rows(fd.fill_and_open(PATH, "arena_c1.png")))
    assert [t for c, t, on in tagged if c == "XType" and not on] == []
    assert [c for c, _, on in tagged if c == "executeScript" and on] == [], "page probes run in browser mode"
    assert left_on is False


def test_file_name_is_focused_filled_then_opened():
    keys = [t for c, t, _ in rows(fd.fill_and_open(PATH, "arena_c1.png")) if c == "XType"]
    assert keys[:4] == ["${KEY_ALT+KEY_N}", "${KEY_CTRL+KEY_A}", "${KEY_CTRL+KEY_V}", "${KEY_ALT+KEY_O}"]


def test_enter_is_a_fallback_only_while_the_dialog_is_still_open():
    seq = rows(fd.fill_and_open(PATH, "arena_c1.png"))
    probe = seq.index(("executeScript", fd.still_open_js("arena_c1.png"), fd.OPEN_VAR))
    gate = seq.index(("if_v2", "${" + fd.OPEN_VAR + "} == 1", ""))
    enter = seq.index(("XType", "${KEY_ENTER}", ""))
    assert probe < gate < enter < seq.index(("end", "", ""), gate)


def test_still_open_means_no_page_focus_and_no_preview_of_ours():
    body = fd.still_open_js("arena_c1.png")
    assert body.startswith("return ") and "document.hasFocus()" in body
    assert 'img[alt=\\"arena_c1.png\\"]' in body or "img[alt=\"arena_c1.png\"]" in body


def test_escape_closes_a_leftover_dialog_in_desktop_mode_only_behind_its_flag():
    seq = rows(fd.escape_when("${attachEsc} == 1"))
    assert seq[0] == ("if_v2", "${attachEsc} == 1", "")
    tagged, left_on = desktop_spans(seq)
    assert ("XType", "${KEY_ESC}", True) in tagged and left_on is False
    assert seq[-1][0] == "end"


def test_attach_macro_uses_the_dialog_rows_and_escapes_only_a_dialog_still_open():
    phase = jm.attach_macro("c1", PATH, "1")
    seq = rows(phase.commands)
    tagged, left_on = desktop_spans(seq)
    assert [t for c, t, on in tagged if c == "XType" and not on] == [], "no key in browser mode"
    assert left_on is False
    assert [t for c, t, _ in seq if c == "XClick"] == [jm.macro.TARGET_VAR, jm.UPLOAD_ITEM]
    assert "document.hasFocus()" in jm._ESC_JS
