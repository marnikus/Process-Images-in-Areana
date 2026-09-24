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
                   "data-kantu", "Error #203", "Error #204", "kantuInvokeSuccess",
                   "kantuInvokeError"):
        assert marker in page, marker
    assert "<title>Ui.Vision Autostart Page</title>" in page


def test_page_html_error_path_does_not_close_or_navigate():
    """On macro error the autorun page stays put — no window.close, no about:blank.

    The 2026-09-24 owner fix: closing or navigating the autorun tab on error
    can race the extension's cleanup and overwrite the user-prepared tab
    the macro was supposed to find. The Ui.Vision docs already document
    this UX ("the Ui.Vision RPA window stays open if … the macro stops
    with an error"). The Error #203 timer is kept so a missing file-URL
    permission still surfaces.
    """
    page = autorun.PAGE_HTML
    # Locate the error handler block (between kantuInvokeError listener add and
    # the next '});' — we read it as one string and check the absence of the
    # two calls).
    start = page.index("onInvokeError = function () {")
    end = page.index("window.addEventListener('kantuInvokeError', onInvokeError)",
                     start)
    block = page[start:end]
    assert "window.close" not in block, "error handler must NOT call window.close"
    assert "about:blank" not in block, "error handler must NOT navigate to about:blank"
    # the success path keeps its cleanup — close is still legal there
    start_ok = page.index("onInvokeSuccess = function () {")
    end_ok = page.index("window.addEventListener('kantuInvokeSuccess', onInvokeSuccess)",
                        start_ok)
    ok_block = page[start_ok:end_ok]
    assert "window.close" in ok_block
    assert "about:blank" in ok_block
    # the 8s permission-error alert is on both paths
    assert page.count("Error #203") == 1      # one declaration, both paths share


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


def test_write_page_overwrites_older_autorun_with_old_close_on_error(tmp_path):
    """An older autorun page (pre-fix `window.close()` on error) is rewritten.

    The 2026-09-24 owner fix removed `window.close() + about:blank` from
    the error path. If the user already had an older `ui.vision.html`
    on disk (from an earlier chat session / older code), the next
    `write_page` call MUST replace it — the on-disk page is the file
    the extension loads, and a stale copy defeats the protected-tab rule.
    `write_page` is idempotent on identical content but always rewrites
    when content differs (the file's mtime would also be stale), so this
    is guaranteed by construction.
    """
    page = tmp_path / "uivision" / "ui.vision.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    # Simulate an OLDER autorun page that closes on error
    old_page = """
    <html><body><script>
    var onInvokeError = function () {
      clearTimeout(timer);
      window.close();
      window.location.href = 'about:blank';
    }
    </script></body></html>
    """
    page.write_text(old_page, encoding="utf-8")
    # First sanity: the stale file DOES close on error
    assert "window.close" in page.read_text(encoding="utf-8")
    # Now simulate a run: write_page is called
    autorun.write_page(page)
    # The new page MUST be the current one
    assert page.read_text(encoding="utf-8") == autorun.PAGE_HTML
    # Extract only the error handler block and assert no close/navigate
    content = page.read_text(encoding="utf-8")
    start = content.index("onInvokeError = function () {")
    end = content.index("window.addEventListener('kantuInvokeError', onInvokeError)",
                        start)
    error_block = content[start:end]
    assert "window.close" not in error_block, \
        "stale autorun page must NOT survive — the protected-tab rule depends on it"
    assert "about:blank" not in error_block


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
