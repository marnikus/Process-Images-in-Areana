"""The autorun page + launch URL — Ui.Vision's official command-line API.

`ui.vision.html` is the extension's own exported page (the noImport genHtml
variant); the launch URL carries only whitelisted INVOKE_URL_PARAMS plus
`autoclose` (deliberately OFF the whitelist — the extension ignores it, the
page's JS reads it). Every value survives percent-encoding (the extension
decodes with decodeURIComponent). The macro never opens a page (2026-09-23):
cmd_var1 is the pause budget in ms, cmd_var2 the XClick target, cmd_var3 the
tab target — there is no URL param. The page's own close is the protected-tab
rule's backstop (2026-09-24): it fires after the run's verdict window and can
only ever close ITS tab — kantuInvokeSuccess (a dispatch-time event, not a
completion event) must never trigger a close.
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
                   "data-kantu", "Error #203", "Error #204", "kantuInvokeSuccess",
                   "autoclose", "closeSelf", "window.close()"):
        assert marker in page, marker
    assert "<title>Ui.Vision Autostart Page</title>" in page


def test_page_title_guard_scopes_the_backstop_to_its_own_tab():
    """The backstop may only close the autostart page — the title is the guard."""
    page = autorun.PAGE_HTML
    assert f"document.title !== '{autorun.PAGE_TITLE}'" in page
    assert page.count("window.close()") == 1           # the backstop is the ONLY close


def test_page_has_no_dispatch_time_self_close():
    """kantuInvokeSuccess fires at DISPATCH (not completion) — it must not close anything."""
    page = autorun.PAGE_HTML
    assert "kantuInvokeError" not in page               # the event does not exist in V9
    success = page.split("var onInvokeSuccess = function () {", 1)[1].split("}", 1)[0]
    assert "window.close" not in success and "location.href" not in success


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
    # zero backstop → no autoclose param at all (the page stays timer-free)
    assert set(query) == {"macro", "storage", "direct", "savelog",
                          "cmd_var1", "cmd_var2", "cmd_var3", "closeRPA"}


def test_backstop_param_appended_last_and_absent_when_zero(tmp_path):
    url = autorun.launch_url(spec_for(tmp_path, backstop_sec=300))
    assert parse_qs(urlsplit(url).query)["autoclose"] == ["300"]
    assert url.rstrip("/").rsplit("/", 1)[-1].split("&")[-1] == "autoclose=300"  # last param
    assert "autoclose" not in autorun.launch_url(spec_for(tmp_path, backstop_sec=0))
    assert "autoclose" not in autorun.launch_url(spec_for(tmp_path))             # default 0


def test_launch_url_close_rpa_off_and_file_uri_base(tmp_path):
    url = autorun.launch_url(spec_for(tmp_path, close_rpa=False, pause_ms=1500))
    query = parse_qs(urlsplit(url).query)
    assert query["closeRPA"] == ["0"]
    assert query["cmd_var1"] == ["1500"]
    assert url.startswith(Path(spec_for(tmp_path).page_path).resolve().as_uri() + "?")
