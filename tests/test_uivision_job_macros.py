"""Firefox image job — the phase macros + page scripts, Python half (design §4, 2026-09-25).

The JS bodies run for real in `tests/js/test_firefox_job_scripts.mjs` (RULE 8);
this file pins the macro contract: every phase selects the pooled tab with an
EMPTY Value (never opens a page), page JS travels base64-encoded so Ui.Vision's
`${…}` interpolation never touches it, clicks are native XClick rows only, the
submit macro clicks send at most once and only behind the guard flag, and a
reply is accepted only for its own job token.
"""

import base64
import json
import re

import pytest

from app.browser.uivision import job_macros as jm
from app.browser.uivision import job_scripts as js
from app.browser.uivision import macro

pytestmark = pytest.mark.unit

UV_VARS = {"${!cmd_var1}", "${!cmd_var2}", "${!cmd_var3}", "${KEY_ENTER}", "${KEY_ESC}",
           "${arenaJob}", "${arenaGuard}", "${attachEsc}", "${goFlag}", "${dialogOpen}", "${uploadItem}",
           "${KEY_ALT+KEY_N}", "${KEY_CTRL+KEY_A}", "${KEY_CTRL+KEY_V}", "${KEY_ALT+KEY_O}"}


def commands(phase):
    return [(c["Command"], c["Target"], c["Value"]) for c in phase.commands]


def all_macros():
    return [jm.probe_macro("c1", "baseline", js.baseline_js(True)),
            jm.attach_macro("c1", "C:/up/arena_c1.png", js.attach_wait_js("arena_c1.png", 8000)),
            jm.submit_macro("c1", js.guard_js("c1", "ab", "arena_c1.png"), js.ack_js("c1", 6000)),
            jm.reset_macro("c1", js.clean_js(15000))]


def test_every_phase_first_selects_the_pooled_tab_without_opening_a_page():
    for phase in all_macros():
        first = commands(phase)[0]
        assert first == ("selectWindow", macro.TAB_VAR, ""), phase.name


def test_only_extension_variables_use_dollar_braces():
    """Page JS (with its own `${…}` template literals) is never interpolated."""
    for phase in all_macros():
        text = json.dumps(list(phase.commands))
        assert set(re.findall(r"\$\{[^}]+\}", text)) <= UV_VARS, phase.name


def test_the_loader_carries_the_body_base64_and_names_token_and_phase():
    body = js.prompt_js("hello ${x} ž")
    target = jm.loader("c1", "prompt", body)
    encoded = re.search(r'atob\("([^"]+)"\)', target).group(1)
    assert base64.b64decode(encoded).decode("utf-8") == body
    assert '"c1"' in target and '"prompt"' in target and target.startswith("return ")


def test_attach_pastes_the_staged_path_into_the_dialog_and_escapes_on_a_miss():
    """Live fix 2026-09-26: the path is pasted (never typed); the dialog rows are file_dialog's."""
    phase = jm.attach_macro("c1", "C:/up/arena_c1.png", "1")
    rows = commands(phase)
    xtypes = [t for c, t, _ in rows if c == "XType"]
    assert xtypes == ["${KEY_ALT+KEY_N}", "${KEY_CTRL+KEY_A}", "${KEY_CTRL+KEY_V}", "${KEY_ALT+KEY_O}",
                      "${KEY_ENTER}", "${KEY_ESC}"]
    assert ("store", '"C:/up/arena_c1.png"', "!clipboard") in rows
    assert [c for c, _, _ in rows].count("XClick") == 2  # the + and (gated) its popup item
    assert phase.xclick.startswith("css=") and "Add files" in phase.xclick
    assert ("if_v2", "${attachEsc} == 1", "") in rows


def test_submit_clicks_send_at_most_once_and_only_behind_the_guard():
    phase = jm.submit_macro("c1", "1", "2")
    names = [c for c, _, _ in commands(phase)]
    assert names.count("XClick") == 1
    assert names.index("if_v2") < names.index("XClick") < names.index("end")
    assert "Send message" in phase.xclick and phase.name == "Arena_Job_Submit"


def test_flag_scripts_read_the_reply_as_a_json_string_or_an_object():
    """Live 2026-09-26: Ui.Vision renders ${var} as a JSON STRING (".data is undefined").
    Executed for real in tests/js/test_firefox_job_scripts.mjs (string, object, garbage)."""
    for src, var in ((jm._FLAG_JS, "${arenaGuard}"), (jm._ESC_JS, "${arenaJob}")):
        assert var in src and "JSON.parse" in src and "typeof r === 'string'" in src


def test_no_phase_ever_uses_a_dom_click():
    for phase in all_macros():
        assert not {c for c, _, _ in commands(phase)} & set(macro.FORBIDDEN_COMMANDS)
    with pytest.raises(ValueError):
        jm._finish("x", [macro.command("click", "css=button", "")])


def test_reset_clicks_new_chat_then_checks_the_clean_page():
    phase = jm.reset_macro("c1", "1")
    assert phase.name == "Arena_Job_Reset" and "/image/direct" in phase.xclick
    assert [c for c, _, _ in commands(phase)][-2:] == ["executeScript", "echo"]


def test_parse_replies_keeps_only_this_job_and_the_last_answer():
    def row(token, phase, data):
        return "[echo] " + jm.REPLY_MARK + json.dumps({"token": token, "phase": phase, "data": data})

    lines = ["[info] Executing: | echo | ARENA_JOB=${arenaJob} | blue |",
             row("other", "baseline", {"x": 0}), row("c1", "baseline", {"x": 1}),
             row("c1", "baseline", {"x": 2}), row("c1", "guard", "not-a-dict"),
             "[echo] ARENA_JOB={broken json"]
    assert jm.parse_replies(lines, "c1") == {"baseline": {"x": 2}}
    assert jm.parse_replies(None, "c1") == {}


def test_build_document_and_log_path(tmp_path):
    phase = jm.probe_macro("c1", "observe", "1", timeout_sec=90)
    doc = jm.build_document(phase)
    assert doc["Name"] == "Arena_Job_Observe" and doc["Commands"] == list(phase.commands)
    assert phase.timeout_sec == 90
    path = jm.log_path(tmp_path, "c1", "observe", "20260925-120000")
    assert path.endswith("job-c1-observe-20260925-120000.txt")


def test_provision_writes_the_phase_macro_and_the_autorun_page(tmp_path):
    from types import SimpleNamespace as NS
    spec = NS(home=str(tmp_path / "uv"), config_dir=str(tmp_path / "cfg"))
    page = jm.provision(spec, jm.probe_macro("c1", "baseline", "1"))
    written = json.loads((tmp_path / "uv" / "macros" / "Arena_Job_Baseline.json").read_text("utf-8"))
    assert written["Name"] == "Arena_Job_Baseline" and page.endswith(".html")


def test_css_prefixes_a_selector_for_the_find_rect_row():
    assert jm.css('a[href="/x"]') == 'css=a[href="/x"]'


def test_script_helpers():
    assert js.expr(";(() => 1)();") == "(() => 1)()"
    assert js.marker("c1") == "[JOB-ID: c1]"
    assert js.security_js(False).count("security: false") == 1
    assert "JS_SECURITY" not in js.security_js(True)


def test_observe_embeds_chromes_strict_check_with_the_baseline():
    body = js.observe_js("c1", {"srcs": ["https://r2/old.png"], "outputs": []}, 12000, False)
    assert "https://r2/old.png" in body and '"c1"' in body and "12000" in body


def test_flag_scripts_read_the_variable_their_probe_stores():
    """The if_v2 flags parse the reply the probe saved — same variable name, both ends (audit F9)."""
    submit = jm.submit_macro("c1", "1", "1")
    attach = jm.attach_macro("c1", "/u/arena_c1.png", "1")
    guard_store = next(c["Value"] for c in submit.commands
                       if c["Command"] == "executeScript" and c["Description"] == "guard probe")
    attach_store = next(c["Value"] for c in attach.commands
                        if c["Command"] == "executeScript" and c["Description"] == "attach probe")
    assert "${" + guard_store + "}" in jm._FLAG_JS
    assert "${" + attach_store + "}" in jm._ESC_JS


def test_every_phase_macro_has_the_default_savelog_deadline():
    macros = [jm.probe_macro("c1", "baseline", "1"), jm.attach_macro("c1", "/u/a.png", "1"),
              jm.submit_macro("c1", "1", "1"), jm.reset_macro("c1", "1")]
    assert {m.timeout_sec for m in macros} == {60}


# ── 2026-09-26 live fix: “+” opens a popup; its “Add files” item opens the OS dialog ──

def test_the_add_files_menu_item_selectors_come_from_the_site_adapter():
    from app.browser.probe_selectors import add_files_menu_item_selectors, add_files_menu_item_text
    sels = add_files_menu_item_selectors()
    assert sels and all("lucide-paperclip" in s for s in sels)
    assert add_files_menu_item_text() == "Add files"


def test_attach_clicks_plus_then_the_add_files_item_then_fills_the_dialog():
    phase = jm.attach_macro("c1", "C:/up/arena_c1.png", "1")
    rows = commands(phase)
    clicks = [i for i, (c, _, _) in enumerate(rows) if c == "XClick"]
    assert len(clicks) == 2, "the + button, then the popup's Add files item"
    assert rows[clicks[0]][1] == macro.TARGET_VAR and "Add files" in phase.xclick
    tag = rows.index(("executeScript", "return " + js.upload_item_js(), "uploadItem"))
    gate = rows.index(("if_v2", "${uploadItem} == 1", ""))
    item = rows[clicks[1]]
    assert item[1] == jm.UPLOAD_ITEM == "css=[data-arena-upload-item]"
    assert clicks[0] < tag < gate < clicks[1] < rows.index(("end", "", ""), gate)
    rect = rows[clicks[1] - 1]
    assert rect[0] == "executeScript" and jm.UPLOAD_ITEM in rect[1], "RED find rect before the item click"
    clip = next(i for i, r in enumerate(rows) if r[2] == "!clipboard")
    assert clicks[1] < clip, "the dialog rows run after the item opened it"
