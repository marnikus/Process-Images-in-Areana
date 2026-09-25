"""The Firefox identify macro — shape, reuse, rendering and the savelog reply.

The in-page behaviour (probe + overlay) is EXECUTED in
`tests/js/test_firefox_identify.mjs` (RULE 8); this file pins the Python half:
the macro never opens a page or clicks, reuses the Chrome probe and badge
bodies, renders `${!cmd_var1..2}` like the extension, and reads back only a
validated `{email, via, overlay, text}` answer.
"""

import json
import re

import pytest

from app.browser.owner_probe import build_owner_probe
from app.browser.uivision import identify as idf
from app.browser.uivision import macro
from app.browser.worker_badge import WORKER_ATTR

pytestmark = pytest.mark.unit


def test_macro_reuses_the_tab_probes_and_echoes_the_answer():
    doc = idf.build_identify_macro()
    names = [c["Command"] for c in doc["Commands"]]
    assert doc["Name"] == idf.MACRO_NAME == "Arena_Identify"
    assert names == ["selectWindow", "executeScript", "echo"]
    select, script, echo = doc["Commands"]
    assert select["Target"] == macro.TAB_VAR and select["Value"] == ""   # never opens a page
    assert script["Value"] == idf.REPLY_VAR
    assert echo["Target"] == "ARENA_IDENTITY=${arenaIdentity}"


def test_identify_js_embeds_the_one_probe_and_the_one_badge():
    js = idf.build_identify_js()
    assert build_owner_probe() in js                 # RULE 21: one selector home
    assert WORKER_ATTR in js and "pointer-events:none" in js
    assert "querySelectorAll('[data-arena-worker]').forEach(e => e.remove())" in js


def test_only_the_extension_variables_use_dollar_braces():
    """Ui.Vision renders every `${…}` in executeScript — a stray one would corrupt the JS."""
    found = set(re.findall(r"\$\{[^}]*\}", idf.build_identify_js()))
    assert found == {macro.PAUSE_VAR, macro.TARGET_VAR}


def test_render_matches_the_extension_stringify_contract():
    js = idf.render_identify_js(2, "Profile1")
    assert "${" not in js
    assert json.dumps(idf.payload(2, "Profile1")) in js
    assert 'parseInt("8000", 10)' in js


def test_payload_carries_number_name_and_clear_flag():
    assert json.loads(idf.payload(2, "mail@x.io")) == {"no": 2, "name": "mail@x.io", "clear": False}
    assert json.loads(idf.payload(None, None, clear=True)) == {"no": 0, "name": "", "clear": True}


def _reply(**kw):
    body = {"email": "", "via": "", "overlay": "ok", "text": ""}
    body.update(kw)
    return "ARENA_IDENTITY=" + json.dumps(body)


def test_parse_reply_reads_the_rendered_echo_and_ignores_the_template_row():
    lines = ["[info] Executing: | echo | ARENA_IDENTITY=${arenaIdentity} | blue |",
             "[echo] " + _reply(email=" MailReceiverPro@Gmail.com ", via="scope",
                                text="2# mailreceiverpro@gmail.com")]
    got = idf.parse_reply(lines)
    assert got == {"email": "mailreceiverpro@gmail.com", "via": "scope", "overlay": "ok",
                   "text": "2# mailreceiverpro@gmail.com"}


def test_parse_reply_drops_a_non_address_and_never_carries_candidates():
    line = _reply(email="Settings", candidates=["secret page text"])
    got = idf.parse_reply([line])
    assert got["email"] == "" and "candidates" not in got


def test_parse_reply_without_an_answer_is_empty():
    assert idf.parse_reply(["echo: done", "ARENA_IDENTITY={torn"]) == {}
    assert idf.parse_reply(None) == {}


def test_last_answer_wins():
    lines = [_reply(email="a@x.io"), _reply(email="b@x.io")]
    assert idf.parse_reply(lines)["email"] == "b@x.io"


def test_provision_writes_the_macro_and_page(tmp_path):
    from types import SimpleNamespace
    spec = SimpleNamespace(home=str(tmp_path / "uv"), config_dir=str(tmp_path / "cfg"))
    page = idf.provision(spec)
    doc = json.loads((tmp_path / "uv" / "macros" / "Arena_Identify.json").read_text())
    assert doc["Name"] == "Arena_Identify" and page.endswith("ui.vision.html")
    assert (tmp_path / "cfg" / "uivision" / "logs").is_dir()


def test_identify_log_never_shares_a_job_savelog(tmp_path):
    path = idf.log_path(tmp_path, "20260925-101010")
    assert path.endswith("identify-20260925-101010.txt") and "run-" not in path
