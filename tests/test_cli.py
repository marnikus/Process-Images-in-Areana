"""Offline CLI cannot imply browser readiness or echo rejected secrets."""

import subprocess
import sys

import pytest

from image_queue.cli import main
from image_queue.domain.presets import MAX_PRESET_BYTES, dumps_preset
from image_queue.domain.settings import ConnectionPreset


def test_url_check_is_honestly_offline(capsys):
    assert main(["check-url", "https://arena.ai/c/sample"]) == 0
    assert "No Chrome connection" in capsys.readouterr().out


def test_rejected_url_does_not_echo_secret(capsys):
    assert main(["check-url", "https://user:SECRET@arena.ai/"]) == 2
    captured = capsys.readouterr()
    assert "credentials" in captured.err
    assert "SECRET" not in captured.err + captured.out


def test_valid_preset_check_does_not_write(tmp_path, capsys):
    path = tmp_path / "preset.json"
    before = dumps_preset(ConnectionPreset())
    path.write_text(before, encoding="utf-8")
    assert main(["check-preset", str(path)]) == 0
    assert path.read_text(encoding="utf-8") == before
    assert "offline only" in capsys.readouterr().out


@pytest.mark.parametrize("content", [b"\xff", b"{", b" " * (MAX_PRESET_BYTES + 1)])
def test_file_errors_are_actionable(tmp_path, capsys, content):
    path = tmp_path / "private-path.json"
    path.write_bytes(content)
    assert main(["check-preset", str(path)]) == 2
    assert str(path) not in capsys.readouterr().err


def test_missing_file_is_not_valid(tmp_path, capsys):
    assert main(["check-preset", str(tmp_path / "missing")]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_module_entrypoint_runs_installed_package():
    result = subprocess.run(
        [sys.executable, "-m", "image_queue", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "0.1.0"


def test_missing_command_prints_usage():
    with pytest.raises(SystemExit) as raised:
        main([])
    assert raised.value.code == 2


def test_desktop_missing_dependency_is_actionable(monkeypatch, capsys):
    import builtins

    real_import = builtins.__import__

    def unavailable(name, *args, **kwargs):
        if name == "image_queue.desktop.app":
            raise ImportError("simulated missing system graphics library")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", unavailable)
    assert main(["desktop"]) == 2
    assert "Qt system libraries" in capsys.readouterr().err
