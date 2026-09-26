"""I-64 · Firefox discovery — the checked, open profiles' matching tabs, stable ids.

Session docs are faked at the `ScanSeams` boundary (and once read from a real
file through the default reader). Positions must be real strip indexes, the
shown history entry must be `entries[index-1]`, an unreadable store keeps the
last answer, and none checked means no Firefox.
"""

import json

import pytest

from app.browser.uivision import tabs
from app.browser.uivision.plan import Patterns
from app.browser.uivision.pool.scan import (DocCache, FoxScanner, ScanSeams, matching_slots,
                                            positioned_windows)

pytestmark = pytest.mark.unit

PROF = "/ff/Profiles/9THrgpBc.Profile1"


def doc(*windows):
    """A session doc: each window a list of (url, title) tabs, one entry each."""
    return {"windows": [{"selected": 1, "tabs": [{"entries": [{"url": u, "title": t}], "index": 1}
                                                  for u, t in window]} for window in windows]}


def scanner_with(docs, open_=(PROF,)):
    seams = ScanSeams(in_use=lambda p: p in open_, names=lambda: {PROF: "Profile1"},
                      doc=lambda p: (docs[p], 1.0, "recovery.jsonlz4") if p in docs else (None, -1.0, ""))
    return FoxScanner(seams=seams)


def test_the_shown_entry_is_index_minus_one_not_the_last():
    back = {"entries": [{"url": "a", "title": "A"}, {"url": "b", "title": "B"}], "index": 1}
    assert tabs.current_entry(back)["url"] == "a"       # after Back, the forward entry stays stored
    assert tabs.current_entry({"entries": [{"url": "a"}, {"url": "b"}]})["url"] == "b"
    assert tabs.current_entry({"entries": [{"url": "a"}], "index": 9})["url"] == "a"
    assert tabs.current_entry({"entries": [{"url": "a"}], "index": "x"})["url"] == "a"
    assert tabs.current_entry({"entries": [], "index": 1}) == {} and tabs.current_entry(None) == {}
    assert tabs.window_rows(doc([("https://a.ai/", "A")]))[0]["active"]["title"] == "A"


def test_session_doc_takes_the_first_candidate_that_lists_a_tab(tmp_path):
    prof = tmp_path / "p.Profile1"
    (prof / "sessionstore-backups").mkdir(parents=True)
    recovery = prof / "sessionstore-backups" / "recovery.jsonlz4"
    recovery.write_bytes(b"x")
    root = prof / "sessionstore.jsonlz4"
    root.write_bytes(b"y")
    docs = {str(recovery): {"windows": []}, str(root): doc([("https://arena.ai/", "LMArena")])}
    got, stamp, source = tabs.session_doc(prof, read=lambda path: docs.get(str(path)))
    assert source == "sessionstore.jsonlz4" and got is docs[str(root)] and stamp > 0
    assert tabs.session_doc(tmp_path / "missing", read=lambda path: None) == (None, -1.0, "")


def test_the_doc_cache_decodes_once_per_file_change(tmp_path):
    path = tmp_path / "recovery.jsonlz4"
    path.write_bytes(b"1")
    calls = []
    cache = DocCache(read=lambda p: calls.append(p) or {"n": len(calls)})
    assert cache(path) == {"n": 1} and cache(path) == {"n": 1} and len(calls) == 1
    path.write_bytes(b"22")                              # size changed → decoded again
    assert cache(path) == {"n": 2}
    assert cache(tmp_path / "gone") is None


def test_positions_are_real_strip_indexes_even_for_url_less_tabs():
    raw = {"windows": [
        {"tabs": [{"entries": []}, {"entries": [{"url": "https://arena.ai/a", "title": "LMArena"}]}]},
        {"tabs": [{"entries": [{"url": "https://x.org", "title": "X"}]},
                  {"entries": [{"url": "https://arena.ai/b", "title": "Chat"}]}]}]}
    wins = positioned_windows(raw)
    assert [len(w) for w in wins] == [2, 2] and wins[0][0] == {"url": "", "title": ""}
    assert matching_slots(wins, Patterns("", "arena.ai")) == [
        (1, 1, 2, "https://arena.ai/a", "LMArena"), (2, 1, 4, "https://arena.ai/b", "Chat")]
    assert matching_slots(wins, Patterns("chat", "")) == [(2, 1, 4, "https://arena.ai/b", "Chat")]
    assert positioned_windows({"windows": "junk"}) == [] and positioned_windows(None) == []


def test_only_checked_open_profiles_are_scanned_and_ids_stay_put():
    docs = {PROF: doc([("https://arena.ai/c/1", "LMArena"), ("https://google.com", "G"),
                       ("https://arena.ai/c/2", "LMArena")])}
    scanner = scanner_with(docs)
    result = scanner.scan([PROF, "/ff/closed", " "], Patterns("", "arena.ai"))
    assert [t.id for t in result.tabs] == ["9THrgpBc.Profile1_tab1", "9THrgpBc.Profile1_tab3"]
    first = result.tabs[0]
    assert (first.profile_label, first.window, first.index, first.conn, first.ws_url, first.type) == \
        ("Profile1", 1, 0, "uivision", "", "page")
    assert scanner.scan([], Patterns()).tabs == []       # none checked → no Firefox
    again = scanner.scan([PROF], Patterns("", "arena.ai"))
    assert [t.id for t in again.tabs] == [t.id for t in result.tabs]
    assert scanner.last_tab("9THrgpBc.Profile1_tab3").url == "https://arena.ai/c/2"
    assert scanner.last_tab("nope") is None


def test_an_unreadable_store_keeps_the_last_tabs_with_a_named_note():
    docs = {PROF: doc([("https://arena.ai/c/1", "LMArena")])}
    scanner = scanner_with(docs)
    scanner.scan([PROF], Patterns())
    docs.clear()
    result = scanner.scan([PROF], Patterns())
    assert [t.id for t in result.tabs] == ["9THrgpBc.Profile1_tab1"]
    assert result.notes == ["Profile1: no readable session store yet — kept 1 tab(s)"]


def test_locate_reads_fresh_and_hands_back_the_window_row():
    docs = {PROF: doc([("https://arena.ai/c/1", "LMArena"), ("https://arena.ai/c/2", "Chat 2")])}
    scanner = scanner_with(docs)
    scanner.scan([PROF], Patterns())
    docs[PROF] = doc([("https://x.org", "X")],
                     [("https://arena.ai/c/1", "LMArena"), ("https://arena.ai/c/2", "Chat 2")])
    found = scanner.locate(PROF, "9THrgpBc.Profile1_tab2", Patterns())
    assert (found.tab.url, found.tab.window, found.tab.index) == ("https://arena.ai/c/2", 2, 1)
    assert found.window_row["index"] == 2 and len(found.windows) == 2
    assert scanner.locate(PROF, "9THrgpBc.Profile1_tab9", Patterns()) is None


def test_the_default_reader_reads_a_real_profile(tmp_path):
    prof = tmp_path / "abcd.Work"
    (prof / "sessionstore-backups").mkdir(parents=True)
    (prof / "sessionstore-backups" / "recovery.json").write_text(
        json.dumps(doc([("https://arena.ai/c/7", "LMArena")])), encoding="utf-8")
    scanner = FoxScanner(seams=ScanSeams(in_use=lambda p: True))
    result = scanner.scan([str(prof)], Patterns("", "arena.ai"))
    assert [(t.id, t.profile_label) for t in result.tabs] == [("abcd.Work_tab1", "abcd.Work")]
