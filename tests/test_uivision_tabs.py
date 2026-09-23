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


def test_addon_seen_scans_past_a_stale_profile(tmp_path):
    stale = write_profile(tmp_path / "old", addons=[{"id": "{ads}", "name": "uBlock"}])
    live = write_profile(tmp_path / "new", addons=[
        {"id": "{u}", "defaultLocale": {"name": "Ui.Vision RPA"}}])
    assert tabs.addon_seen(profiles=[stale, live]) is True


def test_profile_roots_per_os_store_and_dirs(tmp_path):
    env = {"APPDATA": str(tmp_path / "roaming"), "LOCALAPPDATA": str(tmp_path / "local")}
    pkg = env and tmp_path / "local" / "Packages" / "MozillaMediaLLC.Firefox_abc"
    (pkg / "LocalCache" / "Roaming" / "Mozilla" / "Firefox").mkdir(parents=True)
    win = tabs.profile_roots("nt", "win32", env, tmp_path)
    assert win == [tmp_path / "roaming" / "Mozilla" / "Firefox",
                   pkg / "LocalCache" / "Roaming" / "Mozilla" / "Firefox"]
    assert tabs.profile_roots("nt", "win32", {}, tmp_path) == []
    mac = tabs.profile_roots("posix", "darwin", {}, tmp_path)
    assert mac == [tmp_path / "Library" / "Application Support" / "Firefox"]
    linux = tabs.profile_roots("posix", "linux", {}, tmp_path)
    assert linux[0] == tmp_path / ".mozilla" / "firefox"
    assert tabs._dirs_under([tmp_path / "gone"]) == []


def test_profile_dirs_follows_profiles_ini_and_store(tmp_path):
    root = tmp_path / "roaming" / "Mozilla" / "Firefox"
    moved = tmp_path / "elsewhere" / "prof.move"
    (root / "Profiles" / "a.default").mkdir(parents=True)
    moved.mkdir(parents=True)
    (root / "profiles.ini").write_text(
        "\n".join(["[Profile0]", "Name=a", "IsRelative=1", "Path=Profiles/a.default",
                   "[Profile1]", "Name=moved", "IsRelative=0", "Path=" + str(moved)]) + "\n",
        encoding="utf-8")
    found = tabs.profile_dirs({"APPDATA": "", "LOCALAPPDATA": ""},
                              roots=[root], os_name="nt")
    assert root / "Profiles" / "a.default" in found
    assert moved in found
    assert tabs._ini_profiles(root / "profiles.ini") == [
        ("Profiles/a.default", True), (str(moved), False)]
    assert tabs._ini_profiles(root / "no.ini") == []


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


def test_store_mtime_and_freshness(tmp_path):
    import os
    import time as _time
    profile = write_profile(tmp_path, store=STORE)
    stamp = tabs.store_mtime(profiles=[profile])
    assert stamp and abs(stamp - os.stat(profile / "sessionstore-backups" /
                                         "recovery.json").st_mtime) < 1
    assert tabs.store_mtime(profiles=[tmp_path / "gone"]) is None
    assert tabs.store_fresh(60, now=stamp + 10, profiles=[profile]) is True
    assert tabs.store_fresh(60, now=stamp + 61, profiles=[profile]) is False


def test_store_fresh_without_any_profile():
    assert tabs.store_fresh(60, now=1e12) is False
