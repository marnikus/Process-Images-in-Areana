"""Ui.Vision file paths — the XModule home, the runtime dir, the traversal guard."""

from pathlib import Path

import pytest

from app.browser.uivision import paths

pytestmark = pytest.mark.unit


def test_default_home_is_the_xmodule_default():
    # measured from the extension source (xfile.ts initConfig: SpecialFolder.UserDesktop)
    assert paths.default_home() == Path.home() / "Desktop" / "uivision"


def test_home_honours_the_configured_folder():
    assert paths.home("") == paths.default_home()
    assert paths.home("   ") == paths.default_home()
    assert paths.home("  /tmp/uv-home ") == Path("/tmp/uv-home")
    assert paths.home("~/uv-home") == Path.home() / "uv-home"


def test_macro_file_layout(tmp_path):
    got = paths.macro_file(tmp_path, "Python_XClick_Demo")
    assert got == (tmp_path / "macros" / "Python_XClick_Demo.json").resolve()


def test_macro_file_refuses_escapes(tmp_path):
    for bad in ("../evil", "/etc/passwd", "a/../../evil"):
        with pytest.raises(ValueError, match="escapes"):
            paths.macro_file(tmp_path, bad)


def test_runtime_files_live_under_config_uivision(tmp_path):
    cfg = tmp_path / "config"
    assert paths.runtime_dir(cfg) == cfg / "uivision"
    assert paths.autorun_file(cfg) == cfg / "uivision" / "ui.vision.html"
    assert paths.logs_dir(cfg) == cfg / "uivision" / "logs"
    assert paths.log_file(cfg, "20260922-120000") == cfg / "uivision" / "logs" / "run-20260922-120000.txt"
