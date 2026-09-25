"""The Firefox image job's macro documents (steps 14–19, design D-1…D-12).

Every stage is one Ui.Vision run: `selectWindow` on the pooled tab with an EMPTY
Value (reuse, never open), `bringBrowserToForeground` (native input needs the
foreground), the stage's probes, one native click at most, one `echo` per answer.
The job's own constants are baked into the FILE (exactly three `${!cmd_varN}`
exist, and a multiline Unicode prompt must not ride a command line); per-run
numbers ride `cmd_var1` (budget), `cmd_var2` (the click locator), `cmd_var3` (tab).

RED at base: `app/browser/uivision/job_macro.py` did not exist.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.browser.uivision import job_macro as jm
from app.browser.uivision import macro as uv_macro
from app.browser.uivision.runner import RunSpec

pytestmark = pytest.mark.unit

TOKEN = "20260925-142530-A7F3"
PROMPT = "héllo\nworld [JOB-ID: x] 🎨"


def inputs(stage="prepare", **kw):
    base = dict(stage=stage, token=TOKEN, image_path="/tmp/pics/a.png", file_name="a.png",
                prompt=PROMPT, baseline=["blob:https://arena.ai/old"])
    base.update(kw)
    return jm.StageInputs(**base)


def commands(stage, **kw):
    return jm.build_document(inputs(stage, **kw))["Commands"]


def names(cmds):
    return [c["Command"] for c in cmds]


def targets(cmds, command):
    return [c["Target"] for c in cmds if c["Command"] == command]


def test_every_stage_builds_a_valid_document():
    for stage in jm.STAGES:
        doc = jm.build_document(inputs(stage))
        assert doc["Name"] == jm.macro_name(stage, TOKEN)
        assert doc["Commands"], stage
        uv_macro.validate_macro_name(doc["Name"])          # grammar, not hope
        uv_macro.refuse_dom_clicks(doc["Commands"])        # the builder already refused


def test_macro_name_is_one_file_per_stage_and_token():
    assert jm.macro_name("submit", TOKEN) == "Arena_Job_Submit_20260925-142530-A7F3"
    assert jm.macro_name("newchat", "reset") == "Arena_Job_Newchat_reset"
    assert jm.macro_name("prepare", "a/b c;d") == "Arena_Job_Prepare_abcd"
    assert jm.macro_name("prepare", "") == "Arena_Job_Prepare_run"
    with pytest.raises(ValueError):
        jm.macro_name("nope", TOKEN)


def test_every_stage_reuses_the_tab_and_never_opens_one():
    for stage in jm.STAGES:
        cmd = commands(stage)[0]
        assert cmd["Command"] == "selectWindow"
        assert cmd["Target"] == "${!cmd_var3}"         # the pooled tab, from the lane
        assert cmd["Value"] == ""                      # empty Value: reuse, E210 if gone
        assert names(commands(stage))[1] == "bringBrowserToForeground"


def echoes(cmds):
    return " ".join(c["Target"] for c in cmds if c["Command"] == "echo")


def test_prepare_attaches_natively_and_proves_it_from_the_page():
    cmds = commands("prepare")
    assert "XClick" in names(cmds)                     # Add files (native OS dialog)
    assert targets(cmds, "XType")[0] == "/tmp/pics/a.png"
    assert "${KEY_ENTER}" in targets(cmds, "XType")
    marks = echoes(cmds)
    for mark in ("ARENA_STATE=", "ARENA_ATTACH_SEL=", "ARENA_ATTACH=", "ARENA_PROMPT=",
                 "ARENA_GUARD=", "ARENA_WHY="):
        assert mark in marks, mark


def test_prepare_drops_a_stale_tile_behind_a_guarded_click_before_attaching():
    """A stale tile is dropped first (never submitted); the guard makes it conditional."""
    cmds = commands("prepare")
    click_targets = targets(cmds, "XClick")
    assert "${arenaRemove}" in click_targets           # the located stale-tile button
    assert "${arenaAttach}" in click_targets           # then Add files
    guard = next(i for i, c in enumerate(cmds) if c["Command"] == "if"
                 and "${arenaRemove}" in c["Target"])
    assert cmds[guard + 1]["Command"] == "XClick"
    assert "ARENA_STATE2=" in echoes(cmds)             # the post-cleanup baseline is echoed


def test_submit_clicks_send_exactly_once_and_only_behind_the_guard():
    cmds = commands("submit")
    clicks = [c for c in cmds if c["Command"] == "XClick"]
    assert len(clicks) == 1, "one Send click per job — the macro owns the count"
    index = cmds.index(clicks[0])
    guards = [i for i, c in enumerate(cmds) if c["Command"] == "if"]
    assert guards and guards[0] < index, "the click must sit behind the guard"
    assert "arenaGuard" in cmds[guards[0]]["Target"]
    assert names(cmds).count("store") == 2             # 0 → click → 1: the count is real
    assert "ARENA_SUBMIT=" in echoes(cmds)             # the count lands in the savelog
    assert "ARENA_RESULT=" in echoes(cmds)             # and the wait's own answer


def test_the_prompt_is_baked_into_the_script_and_never_typed_nor_clicked():
    """XType/XClick targets are paths/locators/keys — the prompt only rides the script."""
    for stage in jm.STAGES:
        for cmd in commands(stage):
            if cmd["Command"] in ("XType", "XClick", "if", "store", "pause", "echo", "selectWindow"):
                assert PROMPT not in str(cmd.get("Target", "")), (stage, cmd["Command"])
                assert "\n" not in str(cmd.get("Target", "")), (stage, cmd["Command"])
    payload = json.loads(jm.payload(inputs("submit")))
    assert payload["prompt"] == PROMPT                  # exact Unicode, multiline
    assert payload["expect"] == jm.job_replies.prompt_hash(PROMPT)
    assert payload["token"] == TOKEN and payload["file"] == "a.png"
    assert payload["baseline"] == ["blob:https://arena.ai/old"]


def test_fetch_and_probe_only_observe_and_carry_the_source():
    for stage in ("fetch", "probe"):
        cmds = commands(stage, src="blob:https://arena.ai/9", budget_ms=4000)
        assert "XClick" not in names(cmds), f"{stage} must not click"
        assert "store" not in names(cmds), f"{stage} must not write a click count"
    assert json.loads(jm.payload(inputs("fetch", src="blob:x")))["src"] == "blob:x"


def test_newchat_clicks_the_link_once_and_verifies_the_clean_page():
    """The link is located in the page (stored as a macro variable), then clicked natively."""
    cmds = commands("newchat")
    assert names(cmds).count("XClick") == 1
    assert "ARENA_STATE=" in cmds[-1]["Target"]
    assert json.loads(jm.payload(inputs("newchat")))["until"] == "clean"


def test_only_the_two_variables_the_launch_sets_are_used_in_the_documents():
    """`cmd_var1` (budget) and `cmd_var3` (tab) are rendered by the extension; the
    payload never needs `cmd_var2` — the probes' inline literal carries it instead."""
    for stage in jm.STAGES:
        text = json.dumps(commands(stage))
        assert "${!cmd_var4}" not in text
        assert text.count("${!cmd_var1}") >= 1, stage
        assert "${!cmd_var2}" not in text, stage


def test_budgets_are_the_generation_timeout_and_bounded_fallbacks():
    assert jm.budget_for("prepare") == 20000
    assert jm.budget_for("submit", 300000) == 300000
    assert jm.budget_for("submit", 0) == jm.GENERATION_FALLBACK_MS
    assert jm.budget_for("submit", 10 ** 9) == jm.MAX_GENERATION_MS
    assert jm.budget_for("fetch") == 30000

    class B:
        class state:
            class settings:
                class timeouts:
                    pass

    B.state.settings.timeouts = {"generation": 240}
    assert jm.generation_timeout_ms(B()) == 240000


def test_write_stage_lands_in_the_extension_home_and_page_in_the_config_dir(tmp_path):
    spec = RunSpec(pattern="", target="id=go", macro="Arena_Job_Prepare_T", storage="xfile",
                   home=str(tmp_path / "uivision"), binary="", timeout_sec=60, pause_ms=1000,
                   config_dir=str(tmp_path / "cfg"))
    written = jm.write_stage(spec, inputs("prepare"))
    assert written == tmp_path / "uivision" / "macros" / f"{jm.macro_name('prepare', TOKEN)}.json"
    text = written.read_text(encoding="utf-8")
    assert json.loads(text)["Name"] == jm.macro_name("prepare", TOKEN)
    assert "héllo" in text and "\\nworld" in text            # Unicode + newline survive
    page = jm.page(spec)
    assert Path(page).is_file() and page.endswith("ui.vision.html")
    log = jm.log_path(spec.config_dir, "submit", "20260925-142530")
    assert log.endswith("logs/submit-20260925-142530.txt")


def test_payload_is_compact_json_that_keeps_the_extra_keys():
    extra = {"why": "lost ack"}
    text = jm.payload(inputs("probe", extra=extra))
    data = json.loads(text)
    assert data["why"] == "lost ack"
    assert text == json.dumps(data, ensure_ascii=False, separators=(",", ":"))
