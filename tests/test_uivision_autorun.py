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


# ── the 2026-09-24 batch-automation cleanup deltas (design: docs/archive) ────

def test_page_dispatches_once_and_never_re_dispatches_on_a_timer():
    """The vendored 1s interval re-ran the macro while it was executing."""
    page = autorun.PAGE_HTML
    assert "setInterval" not in page                       # the re-dispatcher is gone
    assert page.count("dispatchEvent(evt)") == 1           # exactly one dispatch


def test_page_closes_itself_on_invoke_success_and_failsafe():
    page = autorun.PAGE_HTML
    assert "window.addEventListener('kantuInvokeSuccess', onInvokeSuccess)" in page
    assert "closeTab" in page
    assert "setTimeout(closeTab, 120000)" in page          # never lingers past 2 min


def test_page_warns_by_banner_not_by_blocking_alert():
    """A modal must never wait for a human mid-batch — banner + title + auto-close."""
    page = autorun.PAGE_HTML
    assert "alert(" not in page
    for marker in ("Error #203", "Error #204"):            # the diagnostics survive
        assert marker in page, marker
    assert "document.title = text" in page
    assert "setTimeout(closeTab, 8000)" in page            # the #204 path self-closes
