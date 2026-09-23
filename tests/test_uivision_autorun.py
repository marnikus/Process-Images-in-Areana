"""The autorun page + launch URL — Ui.Vision's official command-line API.

`ui.vision.html` is the extension's own exported page (the noImport genHtml
variant); the launch URL carries only whitelisted INVOKE_URL_PARAMS and every
value survives percent-encoding (the extension decodes with decodeURIComponent).
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
URL = "https://arena.ai/?a=1&b=two three"


def spec_for(tmp_path, **over):
    kw = dict(page_path=str(tmp_path / "ui.vision.html"), macro="Python_XClick_Demo",
              storage="xfile", log_path=str(tmp_path / "logs" / "run-1.txt"),
              url=URL, target=TARGET)
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


def test_launch_url_carries_the_whitelisted_params(tmp_path):
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
    assert query["cmd_var1"] == [URL]
    assert query["cmd_var2"] == [TARGET]
    assert query["cmd_var3"] == ["tab=open"]      # default: no tab to reuse


def test_launch_url_carries_an_explicit_tab_target(tmp_path):
    url = autorun.launch_url(spec_for(tmp_path, tab="title=*Arena*"))
    query = parse_qs(urlsplit(url).query)
    assert query["cmd_var3"] == ["title=*Arena*"]


def test_launch_url_close_rpa_off_and_file_uri_base(tmp_path):
    url = autorun.launch_url(spec_for(tmp_path, close_rpa=False))
    assert parse_qs(urlsplit(url).query)["closeRPA"] == ["0"]
    assert url.startswith(Path(spec_for(tmp_path).page_path).resolve().as_uri() + "?")
