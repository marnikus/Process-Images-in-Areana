"""Firefox's read-only eyes: session store tabs + installed-add-on detection.

RULE 8: real JSON documents in tmp_path profiles; no Firefox, no debugger —
the module only reads files Firefox itself writes, and every refusal (gone,
locked, unparsable) must answer "not seen", never an exception.
"""

import os
import json
from pathlib import Path

import pytest

from app.browser.uivision import desktop, mozlz4, tabs

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


def literals_block(raw: bytes) -> bytes:
    """One match-free LZ4 block (the test fixture's tiny encoder)."""
    out = bytearray()
    rest = len(raw)
    if rest <= 15:
        out.append(rest << 4)
    else:
        out.append(0xF0)
        rest -= 15
        while rest >= 255:
            out.append(255)
            rest -= 255
        out.append(rest)
    out += raw
    return bytes(out)


def write_lz4(path: Path, doc) -> Path:
    """A real `.jsonlz4` file: magic + LE size + LZ4 block."""
    raw = json.dumps(doc).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(mozlz4.MAGIC + len(raw).to_bytes(4, "little") + literals_block(raw))
    return path


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


def test_tab_rows_reads_every_profile_not_just_the_freshest(tmp_path):
    """Two profiles open → BOTH are seen; the last-written one hides nothing."""
    older = write_profile(tmp_path / "a", store=STORE)
    newer = write_profile(tmp_path / "b", store={"windows": [{"tabs": [
        {"entries": [{"url": "https://new.example", "title": "N"}]}]}]})
    import os
    old_now = os.stat(newer / "sessionstore-backups" / "recovery.json").st_mtime + 50
    os.utime(older / "sessionstore-backups" / "recovery.json", (old_now, old_now))
    rows = tabs.tab_rows(profiles=[older, newer])
    assert [r["url"] for r in rows] == ["https://arena.ai/image/direct?model_a=max",
                                        "https://example.com/x", "https://new.example"]


def test_profile_sessions_carries_every_profile_and_the_ini_name(tmp_path, monkeypatch):
    """profile_sessions: one row per answering profile, name from profiles.ini."""
    first = write_profile(tmp_path / "p1", store=STORE)
    second = write_profile(tmp_path / "p2", store={"windows": [{"tabs": [
        {"entries": [{"url": "https://new.example", "title": "N"}]}]}]})
    (write_profile(tmp_path / "empty", store=None))
    monkeypatch.setattr(tabs, "profile_names", lambda roots=None: {first: "Work"})
    sessions = tabs.profile_sessions(profiles=[first, second, tmp_path / "gone"])
    assert [s["name"] for s in sessions] == ["Work", ""]          # the -P handle rides the row
    assert [s["dir"] for s in sessions] == [str(first), str(second)]
    assert sessions[0]["source"] == "recovery.json"
    assert sessions[0]["rows"][0]["url"] == "https://arena.ai/image/direct?model_a=max"
    assert sessions[1]["windows"][0]["tabs"][0]["title"] == "N"


def test_profile_names_maps_dirs_to_ini_names(tmp_path, monkeypatch):
    """`Name=` is the -P handle; a section without one answers '' (dir basename wins)."""
    root = tmp_path / "ff"
    (root / "Profiles" / "abc.work").mkdir(parents=True)
    (root / "Profiles" / "plain.default").mkdir(parents=True)
    (root / "profiles.ini").write_text(
        "[Profile0]\nName=Work\nPath=Profiles/abc.work\nIsRelative=1\n"
        "[Profile1]\nPath=Profiles/plain.default\nIsRelative=1\n", encoding="utf-8")
    monkeypatch.setattr(tabs, "profile_roots", lambda *a: [root / "Profiles"])
    names = tabs.profile_names(roots=[root / "Profiles"])
    assert names[root / "Profiles" / "abc.work"] == "Work"
    assert names[root / "Profiles" / "plain.default"] == ""


def test_session_windows_unions_profiles_and_renumbers(tmp_path):
    """Two profiles → windows of both, globally renumbered, profile-attributed."""
    first = write_profile(tmp_path / "p1", store=None)
    write_lz4(first / "sessionstore-backups" / "recovery.jsonlz4", WIN_STORE)
    second = tmp_path / "p2" / "xyz.play"
    (second / "sessionstore-backups").mkdir(parents=True)
    (second / "sessionstore-backups" / "recovery.json").write_text(json.dumps(
        {"windows": [{"tabs": [{"entries": [{"url": "https://c.example", "title": "C"}]}]}]}),
        encoding="utf-8")
    windows = tabs.session_windows(profiles=[first, second])
    assert [w["index"] for w in windows] == [1, 2, 3]              # renumbered across profiles
    assert [w["profile"] for w in windows] == ["abc.default-release",
                                               "abc.default-release", "xyz.play"]
    assert windows[2]["active"]["title"] == "C"


WIN_STORE = {"windows": [
    {"selected": 2, "tabs": [
        {"entries": [{"url": "https://a.example", "title": "A"}]},
        {"entries": [{"url": "https://arena.ai/x", "title": "Arena"}]}]},
    {"tabs": [{"entries": [{"url": "https://b.example", "title": "B"}]}]},
]}


def test_tab_rows_reads_the_compressed_live_session(tmp_path):
    profile = write_profile(tmp_path, store=None)
    (profile / "sessionstore-backups" / "recovery.json").unlink(missing_ok=True)
    write_lz4(profile / "sessionstore-backups" / "recovery.jsonlz4", STORE)
    rows = tabs.tab_rows(profiles=[profile])
    assert [r["url"] for r in rows] == ["https://arena.ai/image/direct?model_a=max",
                                        "https://example.com/x"]


def test_tab_rows_prefers_live_recovery_then_previous_then_root(tmp_path):
    live = {"windows": [{"tabs": [{"entries": [{"url": "https://live.example", "title": "L"}]}]}]}
    old = {"windows": [{"tabs": [{"entries": [{"url": "https://old.example", "title": "O"}]}]}]}
    profile = write_profile(tmp_path, store=old)          # legacy recovery.json
    write_lz4(profile / "sessionstore-backups" / "recovery.jsonlz4", live)
    assert tabs.tab_rows(profiles=[profile])[0]["url"] == "https://live.example"
    (profile / "sessionstore-backups" / "recovery.jsonlz4").unlink()
    (profile / "sessionstore-backups" / "recovery.json").unlink()
    write_lz4(profile / "sessionstore-backups" / "previous.jsonlz4", old)
    assert tabs.tab_rows(profiles=[profile])[0]["url"] == "https://old.example"
    (profile / "sessionstore-backups" / "previous.jsonlz4").unlink()
    write_lz4(profile / "sessionstore.jsonlz4", old)      # shutdown snapshot, profile root
    assert tabs.tab_rows(profiles=[profile])[0]["url"] == "https://old.example"


def test_tab_rows_ignores_torn_compressed_files(tmp_path):
    profile = write_profile(tmp_path, store=None)
    backups = profile / "sessionstore-backups"
    (backups / "recovery.jsonlz4").write_bytes(mozlz4.MAGIC + b"\x01\x00")
    assert tabs.tab_rows(profiles=[profile]) == []


def test_session_windows_groups_tabs_with_the_active_one(tmp_path):
    profile = write_profile(tmp_path, store=None)
    write_lz4(profile / "sessionstore-backups" / "recovery.jsonlz4", WIN_STORE)
    windows = tabs.session_windows(profiles=[profile])
    assert [w["index"] for w in windows] == [1, 2]
    assert windows[0]["active"]["title"] == "Arena"       # selected=2 → second tab
    assert [t["url"] for t in windows[0]["tabs"]] == ["https://a.example",
                                                      "https://arena.ai/x"]
    assert windows[1]["active"]["title"] == "B"           # no selected → last tab
    assert tabs.session_windows(profiles=[tmp_path / "gone"]) == []


def test_session_source_names_the_file_and_profile(tmp_path):
    profile = write_profile(tmp_path, store=STORE)
    assert tabs.session_source(profiles=[profile]) == ("recovery.json",
                                                        "abc.default-release")
    assert tabs.session_source(profiles=[]) == ("", "")
    assert tabs.session_source(profiles=[tmp_path / "gone"]) == ("", "")


def test_addon_seen_checks_every_profile_not_just_the_first(tmp_path):
    without = write_profile(tmp_path / "n", addons=[{"id": "{ads}", "name": "uBlock"}])
    with_uivision = write_profile(tmp_path / "y", addons=[
        {"id": "{x}", "defaultLocale": {"name": "Ui.Vision RPA"}}])
    assert tabs.addon_seen(profiles=[without, with_uivision]) is True
    assert tabs.addon_seen(profiles=[with_uivision, without]) is True
    assert tabs.addon_seen(profiles=[without]) is False


def test_addon_seen_matches_localized_names_and_install_uris(tmp_path):
    localized = write_profile(tmp_path / "l", addons=[
        {"id": "{x}", "localization": {"en-US": {"name": "Ui.Vision RPA"}}}])
    uri = write_profile(tmp_path / "u", addons=[
        {"id": "{y}", "name": "RPA", "rootURI": "jar:file:///uivision.xpi!/"}])
    assert tabs.addon_seen(profiles=[localized]) is True
    assert tabs.addon_seen(profiles=[uri]) is True


def test_profile_dirs_include_profiles_ini_paths(tmp_path, monkeypatch):
    root = tmp_path / "ff" / "Profiles"
    (root / "plain.default").mkdir(parents=True)
    custom = tmp_path / "ff" / "custom.default"
    custom.mkdir()
    absolute = tmp_path / "elsewhere.default"
    absolute.mkdir()
    (tmp_path / "ff" / "profiles.ini").write_text(
        "[Profile0]\nPath=custom.default\nIsRelative=1\n"
        f"[Profile1]\nPath={absolute}\nIsRelative=0\n"
        "[Profile2]\nPath=gone.default\nIsRelative=1\n", encoding="utf-8")
    monkeypatch.setattr(tabs, "profile_roots", lambda *a: [root])
    found = tabs.profile_dirs()
    assert root / "plain.default" in found
    assert custom in found
    assert absolute in found
    assert all("gone" not in str(p) for p in found)


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


def test_ini_entries_tolerate_junk_sections_and_broken_ini(tmp_path):
    """A broken ini answers []; junk/empty sections contribute no rows, Name rides."""
    (tmp_path / " Profiles").mkdir()               # a dir named with a space, never a match
    good = tmp_path / "real.default"
    good.mkdir()
    ini = tmp_path / "profiles.ini"
    ini.write_text(
        "[General]\nStartWithLastProfile=1\n"
        "[Profile0]\nPath=\n"                       # empty Path → skipped
        "[Profile1]\nPath=gone.default\n"           # missing dir → skipped
        f"[Profile2]\nName=Real\nPath={good}\nIsRelative=0\n", encoding="utf-8")
    assert tabs.ini_entries(ini) == [(good, "Real")]
    broken = tmp_path / "broken.ini"
    broken.write_text("[Profile0\nnot an ini section", encoding="utf-8")
    assert tabs.ini_entries(broken) == []
    assert tabs.ini_entries(tmp_path / "absent.ini") == []


def test_profile_names_prefers_a_later_named_section(tmp_path, monkeypatch):
    """The root ini names the dir without a Name, the parent ini names it: Work wins."""
    root = tmp_path / "ff" / "Profiles"
    named = root / "abc.work"
    named.mkdir(parents=True)
    (root / "profiles.ini").write_text("[Profile0]\nPath=abc.work\nIsRelative=1\n",
                                       encoding="utf-8")
    (root.parent / "profiles.ini").write_text(
        "[Profile0]\nName=Work\nPath=Profiles/abc.work\nIsRelative=1\n", encoding="utf-8")
    monkeypatch.setattr(tabs, "profile_roots", lambda *a: [root])
    names = tabs.profile_names(roots=[root])
    assert names[named] == "Work"          # the -P handle comes from the named section


def _lock(profile: Path) -> Path:
    """A live POSIX profile lock pointing at this test process."""
    link = profile / "lock"
    link.symlink_to(f"127.0.0.1:+{os.getpid()}")
    return link


def test_profile_sessions_default_reads_only_open_profiles(tmp_path, monkeypatch):
    """Closed profiles' stale rows stay out; explicit lists read as given."""
    live = write_profile(tmp_path / "live", store=STORE)
    shut = write_profile(tmp_path / "shut", store=STORE)
    _lock(live)
    monkeypatch.setattr(tabs, "profile_dirs", lambda: [live, shut])
    sessions = tabs.profile_sessions()
    assert [s["dir"] for s in sessions] == [str(live)]
    assert sessions[0]["rows"] and all("arena.ai" in r["url"] or "example.com" in r["url"]
                                       for r in sessions[0]["rows"])
    assert len(tabs.profile_sessions(profiles=[live, shut])) == 2  # explicit: caller's call


def test_addon_seen_default_ignores_closed_profiles(tmp_path, monkeypatch):
    without = write_profile(tmp_path / "n", addons=[{"id": "{ads}", "name": "uBlock"}])
    shut_with = write_profile(tmp_path / "y", addons=[
        {"id": "{x}", "defaultLocale": {"name": "Ui.Vision RPA"}}])
    _lock(without)
    monkeypatch.setattr(tabs, "profile_dirs", lambda: [without, shut_with])
    assert tabs.addon_seen() is False          # the closed one names it — means nothing
    _lock(shut_with)
    assert tabs.addon_seen() is True
