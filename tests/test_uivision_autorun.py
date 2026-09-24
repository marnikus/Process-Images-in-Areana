"""The autorun page + launch URL — Ui.Vision's official command-line API.

`ui.vision.html` is the extension's own exported page (the noImport genHtml
variant); the launch URL carries only whitelisted INVOKE_URL_PARAMS and every
value survives percent-encoding (the extension decodes with decodeURIComponent).
The macro never opens a page (2026-09-23): cmd_var1 is the pause budget in ms,
cmd_var2 the XClick target, cmd_var3 the tab target — there is no URL param.
"""

import os
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from app.browser.uivision import autorun
from app.browser.uivision.autorun import LaunchSpec

pytestmark = pytest.mark.unit

TARGET = "xpath=//a[span[text()='New Chat']]"


def spec_for(tmp_path, **over):
    kw = dict(page_path=str(tmp_path / "ui.vision.html"), macro="Python_XClick_Demo",
              storage="xfile", log_path=str(tmp_path / "logs" / "run-1.txt"),
              pause_ms=3000, target=TARGET, tab="title=*Arena*")
    kw.update(over)
    return LaunchSpec(**kw)


def test_page_html_is_the_vendored_autorun_page():
    page = autorun.PAGE_HTML
    for marker in ("kantuSaveAndRunMacro", "noImport: true", "storageMode: 'browser'",
                   "data-kantu", "Error #203", "Error #204", "kantuInvokeSuccess"):
        assert marker in page, marker
    assert "<title>Ui.Vision Autostart Page</title>" in page


def test_write_page_creates_once_and_heals(tmp_path):
    page = tmp_path / "sub" / "ui.vision.html"
    got = autorun.write_page(page)
    assert got == page and page.read_text(encoding="utf-8") == autorun.PAGE_HTML
    old = time.time() - 5000
    os.utime(page, (old, old))
    autorun.write_page(page)                      # identical content: untouched
    assert page.stat().st_mtime == pytest.approx(old)
    page.write_text("broken", encoding="utf-8")
    autorun.write_page(page)                      # differs: rewritten
    assert page.read_text(encoding="utf-8") == autorun.PAGE_HTML


def test_launch_url_carries_the_whitelisted_params_and_no_url(tmp_path):
    url = autorun.launch_url(spec_for(tmp_path))
    parts = urlsplit(url)
    assert parts.scheme == "file"
    assert parts.path.endswith("/ui.vision.html")
    query = parse_qs(parts.query)
    assert query["macro"] == ["Python_XClick_Demo"]   # case-sensitive name
    assert query["storage"] == ["xfile"]
    assert query["direct"] == ["1"]                   # skip the confirm dialog
    assert query["closeRPA"] == ["1"]
    assert query["savelog"] == [str(Path(tmp_path / "logs" / "run-1.txt").resolve())]
    # percent-encoding round trip: the extension's parseQuery decodes these
    assert query["cmd_var1"] == ["3000"]              # the pause budget (ms), not a URL
    assert query["cmd_var2"] == [TARGET]
    assert query["cmd_var3"] == ["title=*Arena*"]     # the pattern's tab is reused
    # the macro never opens a page: no URL rides the launch URL
    assert "arena.ai" not in url and "https" not in parts.query
    assert set(query) == {"macro", "storage", "direct", "savelog",
                          "cmd_var1", "cmd_var2", "cmd_var3", "closeRPA"}


def test_launch_url_close_rpa_off_and_file_uri_base(tmp_path):
    url = autorun.launch_url(spec_for(tmp_path, close_rpa=False, pause_ms=1500))
    query = parse_qs(urlsplit(url).query)
    assert query["closeRPA"] == ["0"]
    assert query["cmd_var1"] == ["1500"]
    assert url.startswith(Path(spec_for(tmp_path).page_path).resolve().as_uri() + "?")


def _spec_and_run(tmp_path):
    from types import SimpleNamespace
    from app.browser.uivision import plan as plan_mod
    target = plan_mod.Target(profile_name="Work", profile_dir="/ff/w",
                             url="https://arena.ai/a", title="A1")
    run = plan_mod.PlannedRun(target=target, index=1, total=1, label="L",
                              selector="tab=-1", profile_args=("-P", "Work"),
                              log_path=str(tmp_path / "logs" / "run-1.txt"))
    spec = SimpleNamespace(macro="M", storage="xfile", pause_ms=3000, target="css=#go")
    return spec, run


def test_launch_url_for_renders_one_runs_values(tmp_path):
    from urllib.parse import parse_qs, urlsplit
    spec, run = _spec_and_run(tmp_path)
    url = autorun.launch_url_for(spec, str(tmp_path / "ui.vision.html"), run, "tab=-1")
    query = parse_qs(urlsplit(url).query)
    assert query["cmd_var3"] == ["tab=-1"]                # the resolved selector rides
    assert query["cmd_var1"] == ["3000"] and query["cmd_var2"] == ["css=#go"]
    assert query["savelog"] == [str(Path(run.log_path).resolve())]


def test_manual_lines_name_the_profile_url_and_wait(tmp_path):
    _spec, run = _spec_and_run(tmp_path)
    url = "file:///autorun?macro=M"
    lines = autorun.manual_lines(run, url, "profile “Work” has no open Firefox window", 90)
    assert [level for _line, level in lines] == ["warn", "warn", "info"]
    assert "has no open Firefox window" in lines[0][0]
    assert "MANUAL STEP" in lines[1][0] and url in lines[1][0] and "Work" in lines[1][0]
    assert "90s" in lines[2][0] and "run continues" in lines[2][0]
