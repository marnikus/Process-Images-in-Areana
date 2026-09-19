"""file_service tests (R12/d): OS reveal + clipboard subprocess chains."""

import os
import subprocess

import pytest

from app.ui.services import file_service as fs


class Rec:
    def __init__(self):
        self.calls = []

    def __call__(self, *a, **kw):
        self.calls.append((a, kw))


def test_resolve_existing_and_parent(tmp_path):
    f = tmp_path / "a.png"
    f.write_text("x")
    p, err = fs._resolve_reveal_target(str(f))
    assert err is None and p == f
    p, err = fs._resolve_reveal_target(str(tmp_path / "missing.png"))
    assert err is None and p == tmp_path
    p, err = fs._resolve_reveal_target(str(tmp_path / "nodir" / "missing.png"))
    assert p is None and "does not exist" in err


def test_reveal_dispatch_per_os(tmp_path, monkeypatch):
    f = tmp_path / "a.png"
    f.write_text("x")
    popen = Rec()
    monkeypatch.setattr(subprocess, "Popen", popen)
    startfile = Rec()
    monkeypatch.setattr(os, "startfile", startfile, raising=False)
    fs._reveal_on_system(f, "Windows")
    assert "explorer" in popen.calls[-1][0][0]
    fs._reveal_on_system(tmp_path, "Windows")
    assert startfile.calls and startfile.calls[-1][0][0] == str(tmp_path)
    fs._reveal_on_system(f, "Darwin")
    assert popen.calls[-1][0][0][:2] == ["open", "-R"]
    fs._reveal_on_system(tmp_path, "Darwin")
    assert popen.calls[-1][0][0] == ["open", str(tmp_path)]
    fs._reveal_on_system(f, "Linux")
    assert popen.calls[-1][0][0][:2] == ["xdg-open", str(tmp_path)]
    fs._reveal_on_system(tmp_path, "Linux")
    assert popen.calls[-1][0][0] == ["xdg-open", str(tmp_path)]


def test_reveal_path_ok_and_failures(tmp_path, monkeypatch):
    logs = Rec()
    monkeypatch.setattr(subprocess, "Popen", Rec())
    res = fs.reveal_path(str(tmp_path), log=logs)
    assert res["ok"] is True and "Revealed" in logs.calls[-1][0][0]
    res = fs.reveal_path(str(tmp_path / "nodir" / "x.png"))
    assert res["ok"] is False and "does not exist" in res["error"]

    def boom(*a, **kw):
        raise OSError("no xdg")
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(fs.platform, "system", lambda: "Linux")
    res = fs.reveal_path(str(tmp_path))
    assert res["ok"] is False and res["error"] == "no xdg"


def test_copy_windows_clip_then_powershell(monkeypatch):
    logs = Rec()
    run = Rec()
    monkeypatch.setattr(subprocess, "run", run)
    res = fs._copy_windows("hello", logs)
    assert res == {"ok": True, "path": "hello", "fallback": "clip"}

    seen = []

    def flaky(*a, **kw):
        seen.append(a)
        if len(seen) == 1:
            raise subprocess.CalledProcessError(1, "clip")
        return None
    monkeypatch.setattr(subprocess, "run", flaky)
    res = fs._copy_windows("it's", logs)
    assert res["fallback"] == "powershell"
    assert "it''s" in seen[-1][0][-1]  # quote-doubling, Unicode-safe path

    def always_fail(*a, **kw):
        raise subprocess.CalledProcessError(1, "x")
    monkeypatch.setattr(subprocess, "run", always_fail)
    res = fs._copy_windows("hello", logs)
    assert res["ok"] is False and "clip/powershell failed" in res["error"]


def test_copy_mac_and_linux(monkeypatch):
    logs = Rec()
    monkeypatch.setattr(subprocess, "run", Rec())
    res = fs._copy_mac("hi", logs)
    assert res["fallback"] == "pbcopy" and "pbcopy" in logs.calls[-1][0][0]
    with pytest.raises(subprocess.CalledProcessError):
        def boom(*a, **kw):
            raise subprocess.CalledProcessError(1, "pbcopy")
        monkeypatch.setattr(subprocess, "run", boom)
        fs._copy_mac("hi", None)
    monkeypatch.setattr(subprocess, "run", Rec())
    res = fs._copy_linux("hi", logs)
    assert res["fallback"] == "xclip"

    def xsel_only(cmd, **kw):
        if cmd[0] == "xclip":
            raise FileNotFoundError("no xclip")
        return None
    monkeypatch.setattr(subprocess, "run", xsel_only)
    res = fs._copy_linux("hi", logs)
    assert res["fallback"] == "xsel"

    def neither(cmd, **kw):
        raise FileNotFoundError("none")
    monkeypatch.setattr(subprocess, "run", neither)
    res = fs._copy_linux("hi", None)
    assert res["ok"] is False and "xclip/xsel failed" in res["error"]


def test_copy_dispatch_by_platform(monkeypatch):
    monkeypatch.setattr(subprocess, "run", Rec())
    monkeypatch.setattr(fs.platform, "system", lambda: "Windows")
    assert fs.copy_text_to_clipboard("a")["fallback"] == "clip"
    monkeypatch.setattr(fs.platform, "system", lambda: "Darwin")
    assert fs.copy_text_to_clipboard("a")["fallback"] == "pbcopy"
    monkeypatch.setattr(fs.platform, "system", lambda: "Linux")
    assert fs.copy_text_to_clipboard("a")["fallback"] == "xclip"
