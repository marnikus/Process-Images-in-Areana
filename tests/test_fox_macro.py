"""I-64 · The per-run pool macro — every value baked in, XClick only, never `tab=0`.

The URL guard is executed in node against a stubbed `location` (RULE 8: run the
JS, don't read the string).
"""

import json
import shutil
import subprocess
from datetime import date

import pytest

from app.browser.uivision import macro as base_macro
from app.browser.uivision.pool import macro as pool_macro
from app.browser.uivision.pool.macro import (ANCHOR_SETTLE_MS, PoolStep, build_pool_commands,
                                             build_pool_macro, pool_macro_name, url_guard_js)

pytestmark = pytest.mark.unit
node = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")


def step(anchor="LMArena", offset=0, needle="arena.ai", target="xpath=//button[@id='go']"):
    return PoolStep(anchor=anchor, offset=offset, needle=needle, target=target, pause_ms=3000)


def names(cmds):
    return [c["Command"] for c in cmds]


def test_offset_zero_is_the_title_alone_then_the_guard_then_the_tail():
    cmds = build_pool_commands(step())
    assert names(cmds) == ["selectWindow", "executeScript", "bringBrowserToForeground",
                           "executeScript", "XClick", "echo"]
    assert (cmds[0]["Target"], cmds[0]["Value"]) == ("title=LMArena", "")
    assert not any(c["Target"].startswith("tab=") for c in cmds)   # never tab=0 (autostart tab)


def test_an_offset_reanchors_on_the_focused_window_then_steps_right():
    cmds = build_pool_commands(step(anchor="Google", offset=2))
    assert names(cmds)[:4] == ["selectWindow", "bringBrowserToForeground", "pause", "selectWindow"]
    assert cmds[2]["Target"] == str(ANCHOR_SETTLE_MS) and ANCHOR_SETTLE_MS > 500
    assert cmds[3]["Target"] == "tab=2" and cmds[3]["Value"] == ""


def test_a_blank_needle_skips_the_guard_and_the_tail_bakes_the_values():
    cmds = build_pool_commands(step(needle="  "))
    assert names(cmds) == ["selectWindow", "bringBrowserToForeground", "executeScript", "XClick", "echo"]
    assert cmds[3]["Target"] == "xpath=//button[@id='go']"          # a literal — no cmd_var
    assert cmds[2]["Target"] == base_macro.render_find_rect_js("xpath=//button[@id='go']", 3000)
    assert cmds[4]["Target"] == base_macro.DONE_TEXT


def test_the_dom_click_ban_covers_every_pool_macro(monkeypatch):
    seen = []
    monkeypatch.setattr(pool_macro, "refuse_dom_clicks", lambda cmds: seen.append(list(cmds)))
    cmds = build_pool_commands(step())
    assert seen == [cmds]
    assert not {c["Command"].lower() for c in cmds} & base_macro.FORBIDDEN_COMMANDS


def test_the_macro_document_and_its_name():
    doc = build_pool_macro("Python_XClick_Demo_pool", step(), today=date(2026, 9, 25))
    assert (doc["Name"], doc["CreationDate"]) == ("Python_XClick_Demo_pool", "2026-9-25")
    assert pool_macro_name("Python_XClick_Demo") == "Python_XClick_Demo_pool"
    assert len(pool_macro_name("M" * 64)) == 64
    with pytest.raises(ValueError):
        pool_macro_name("bad name")


def run_guard(js, href):
    script = (f"const location = {{ href: {json.dumps(href)} }};\n"
              f"try {{ console.log(JSON.stringify({{ ok: true, r: {js} }})); }}\n"
              f"catch (e) {{ console.log(JSON.stringify({{ ok: false, e: e.message }})); }}")
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    return json.loads(out.stdout.strip().splitlines()[-1])


@node
def test_the_url_guard_passes_a_worker_page_and_throws_on_a_stranger():
    js = url_guard_js("arena.ai")
    assert run_guard(js, "https://arena.ai/c/1") == {"ok": True, "r": "worker page: https://arena.ai/c/1"}
    assert run_guard(js, "HTTPS://ARENA.AI/x")["ok"] is True       # case-insensitive
    stranger = run_guard(js, "https://google.com/")
    assert stranger["ok"] is False and "not a worker page" in stranger["e"]
    assert run_guard(url_guard_js('a"b'), 'https://x/a"b')["ok"] is True   # the needle is JSON-safe
