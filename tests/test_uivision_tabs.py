"""Firefox's read-only eyes: session store tabs + installed-add-on detection.

RULE 8: real JSON documents in tmp_path profiles; no Firefox, no debugger —
the module only reads files Firefox itself writes, and every refusal (gone,
locked, unparsable) must answer "not seen", never an exception.
"""

import json
from pathlib import Path

import pytest

from app.browser.uivision import desktop, tabs

pytestmark = pytest.mark.unit


def write_profile(root: Path, store=None, addons=None) -> Path:
    profile = root / "abc.default-release"
    (profile / "sessionstore-backups").mkdir(parents=True)
    if store is not None:
        (profile / "sessionstore-backups" / "recovery.json").write_text(
            json.dumps(store), encoding="utf-8")
    if addons is not None:
        (profile / "extensions.json").write_text(
            json.dumps({"addons": addons}), encoding="utf-8")
    return profile


STORE = {"windows": [{"tabs": [
    {"entries": [{"url": "https://arena.ai/image/direct?model_a=max", "title": "Arena"}]},
    {"entries": [{"url": "about:home", "title": ""},
                 {"url": "https://example.com/x", "title": "Ex"}]},
    {"entries": []},
]}]}


def test_tab_rows_reads_every_tabs_last_entry(tmp_path):
    profile = write_profile(tmp_path, store=STORE)
    rows = tabs.tab_rows(profiles=[profile])
    assert [r["url"] for r in rows] == ["https://arena.ai/image/direct?model_a=max",
                                        "https://example.com/x"]
    assert rows[0]["title"] == "Arena"


def test_tab_rows_tolerates_junk_and_absence(tmp_path):
    broken = write_profile(tmp_path, store=None)
    (broken / "sessionstore-backups" / "recovery.json").write_text("{not json", encoding="utf-8")
    assert tabs.tab_rows(profiles=[broken]) == []
    assert tabs.tab_rows(profiles=[tmp_path / "gone"]) == []
    assert tabs.tab_rows(profiles=[]) == []


def test_freshest_profile_wins(tmp_path):
    older = write_profile(tmp_path / "a", store=STORE)
    newer = write_profile(tmp_path / "b", store={"windows": [{"tabs": [
        {"entries": [{"url": "https://new.example", "title": "N"}]}]}]})
    import os
    old_now = os.stat(newer / "sessionstore-backups" / "recovery.json").st_mtime + 50
    os.utime(older / "sessionstore-backups" / "recovery.json", (old_now, old_now))
    rows = tabs.tab_rows(profiles=[older, newer])
    assert [r["url"] for r in rows] == ["https://arena.ai/image/direct?model_a=max",
                                        "https://example.com/x"]


def test_match_urls_case_insensitive_and_blank_matches_none():
    rows = [{"url": "https://Arena.ai/x", "title": ""}]
    assert tabs.match_urls(rows, "arena.ai") == ["https://Arena.ai/x"]
    assert tabs.match_urls(rows, "") == []
    assert tabs.match_urls(rows, "   ") == []
    assert tabs.match_urls(None, "arena") == []


def test_addon_seen_tri_state(tmp_path):
    with_uivision = write_profile(tmp_path / "y", addons=[
        {"id": "{x}", "defaultLocale": {"name": "Ui.Vision RPA"}}])
    without = write_profile(tmp_path / "n", addons=[{"id": "{ads}", "name": "uBlock"}])
    silent = write_profile(tmp_path / "s", store=STORE)
    assert tabs.addon_seen(profiles=[with_uivision]) is True
    assert tabs.addon_seen(profiles=[without]) is False
    assert tabs.addon_seen(profiles=[silent]) is None
    assert tabs.addon_seen(profiles=[]) is None


def test_profile_roots_per_os_and_dirs_under_them(tmp_path):
    win = tabs.profile_roots("nt", "win32", str(tmp_path), tmp_path)
    assert win == [tmp_path / "Mozilla" / "Firefox" / "Profiles"]
    assert tabs.profile_roots("nt", "win32", "", tmp_path) == []
    mac = tabs.profile_roots("posix", "darwin", "", tmp_path)
    assert mac == [tmp_path / "Library" / "Application Support" / "Firefox" / "Profiles"]
    linux = tabs.profile_roots("posix", "linux", "", tmp_path)
    assert linux[0] == tmp_path / ".mozilla" / "firefox"
    (win[0] / "p.default").mkdir(parents=True)
    assert tabs._dirs_under(win) == [win[0] / "p.default"]
    assert tabs._dirs_under([tmp_path / "gone"]) == []


def test_desktop_module_probe_refuses_and_accepts(monkeypatch):
    import socket

    def refuse(*_a, **_k):
        raise OSError("nothing listening")

    monkeypatch.setattr(socket, "create_connection", refuse)
    assert desktop.desktop_module_listening(timeout=0.05) is False

    class FakeSock:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr(socket, "create_connection", lambda *_a, **_k: FakeSock())
    assert desktop.desktop_module_listening() is True
