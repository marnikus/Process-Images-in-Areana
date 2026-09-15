import os
import tempfile
from pathlib import Path
from unittest import mock

from app.core.reveal import build_reveal_command, reveal_in_file_manager


def test_windows_selects_file():
    cmd = build_reveal_command("C:/pics/photo_AI.jpg", platform="win32")
    assert cmd[0] == "explorer"
    assert cmd[1] == "/select,"
    assert cmd[2].endswith("photo_AI.jpg")
    assert cmd[2] == os.path.normpath("C:/pics/photo_AI.jpg")  # explorer-friendly


def test_macos_reveals_file():
    cmd = build_reveal_command("/pics/photo_AI.jpg", platform="darwin")
    assert cmd == ["open", "-R", "/pics/photo_AI.jpg"]


def test_linux_opens_parent_dir():
    cmd = build_reveal_command("/pics/photo_AI.jpg", platform="linux")
    assert cmd == ["xdg-open", "/pics"]


def test_missing_file_does_not_launch():
    with mock.patch("app.core.reveal.subprocess.Popen") as popen:
        ok, err = reveal_in_file_manager("/nonexistent/nope.jpg")
        assert ok is False
        assert "not found" in err
        popen.assert_not_called()


def test_empty_path_fails():
    ok, _ = reveal_in_file_manager("")
    assert ok is False


def test_existing_file_launches_command():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "photo_AI.jpg"
        p.write_bytes(b"fake")
        with mock.patch("app.core.reveal.subprocess.Popen") as popen:
            ok, err = reveal_in_file_manager(str(p))
            assert ok is True
            assert err == ""
            popen.assert_called_once()
            assert popen.call_args.args[0] == build_reveal_command(str(p))


def test_launch_error_returns_message():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "photo_AI.jpg"
        p.write_bytes(b"fake")
        with mock.patch("app.core.reveal.subprocess.Popen", side_effect=OSError("nope")):
            ok, err = reveal_in_file_manager(str(p))
            assert ok is False
            assert "nope" in err
