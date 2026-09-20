"""URL queue slots (2026-10-02 bugfix): one commit path, validated edits, JSON everywhere."""

import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from app.core.models import UrlRow
from app.ui.panels import url_queue
from app.ui.panels.url_queue import MAX_URL_LEN, UrlQueueMixin

pytestmark = pytest.mark.unit


class BookmarkStore:
    """Preset-store double (config.presets)."""

    def __init__(self):
        self.items = []

    def get_url_presets(self):
        return list(self.items)

    def add_url_preset(self, url):
        if url in self.items:
            return False
        self.items.append(url)
        return True

    def remove_url_preset(self, url):
        if url not in self.items:
            return False
        self.items.remove(url)
        return True


class Host(UrlQueueMixin):
    def __init__(self, urls=()):
        self.state = SimpleNamespace(urls=list(urls))
        self.state.to_dict = lambda: {"urls": [asdict(u) for u in self.state.urls]}
        self.saves = 0
        self.pushed = []
        self.logs = []
        self._save_arena = lambda: setattr(self, "saves", self.saves + 1)
        self._log = lambda m, l="info": self.logs.append((m, l))
        self.undo_service = SimpleNamespace(push=lambda k, v: self.pushed.append(k), history=lambda: ([], 0))
        self.undo_state_changed = SimpleNamespace(emit=lambda *a: None)
        self.history_changed = SimpleNamespace(emit=lambda *a: None)
        self.stored = {}
        self.bookmarks = BookmarkStore()
        self.config = SimpleNamespace(presets=self.bookmarks, set_state=lambda **kw: self.stored.update(kw))
        self.emitted = []
        self.url_presets_updated = SimpleNamespace(emit=lambda p: self.emitted.append(("urls", p)))
        self.presets_changed = SimpleNamespace(emit=lambda k, p: self.emitted.append((k, p)))


def test_every_row_mutation_goes_through_commit():
    host = Host()
    added = json.loads(host.add_url("https://arena.ai/a"))
    assert added["ok"] is True and host.saves == 1 and host.pushed == ["urls"]
    rid = added["id"]
    assert json.loads(host.toggle_url(rid)) == {"ok": True, "enabled": False}
    assert json.loads(host.edit_url(rid, "https://arena.ai/b")) == {"ok": True, "url": "https://arena.ai/b"}
    assert json.loads(host.remove_url(rid)) == {"ok": True}
    assert host.saves == 4 and host.pushed == ["urls"] * 4
    assert json.loads(host.remove_url(rid)) == {"ok": False, "error": "not found"}
    assert host.saves == 4  # failures never persist


def test_edit_url_is_validated_like_add():
    row = UrlRow.create("https://arena.ai/a", enabled=True)
    other = UrlRow.create("https://arena.ai/b", enabled=True)
    host = Host([row, other])
    assert json.loads(host.edit_url(row.id, ""))["error"] == "empty URL"
    assert json.loads(host.edit_url(row.id, "arena.ai/x"))["error"] == "URL must start with http:// or https://"
    assert json.loads(host.edit_url(row.id, "https://arena.ai/b"))["error"] == "URL already exists"
    assert json.loads(host.edit_url(row.id, "https://arena.ai/a"))["ok"] is True  # same value is fine
    assert json.loads(host.edit_url("missing", "https://arena.ai/z"))["error"] == "not found"
    too_long = "https://arena.ai/" + "x" * MAX_URL_LEN
    assert json.loads(host.edit_url(row.id, too_long))["error"].startswith("URL too long")
    assert json.loads(host.add_url(too_long))["error"].startswith("URL too long")
    assert json.loads(host.add_url("  https://arena.ai/a  "))["error"] == "URL already exists"
    assert row.url == "https://arena.ai/a" and row.last_status == "unchecked"


def test_preset_slots_return_json_and_emit():
    host = Host()
    assert json.loads(host.add_url_preset("  ")) == {"ok": False, "error": "empty URL"}
    first = json.loads(host.add_url_preset("https://arena.ai/x"))
    assert first == {"ok": True, "added": True, "presets": ["https://arena.ai/x"]}
    again = json.loads(host.add_url_preset("https://arena.ai/x"))
    assert again["ok"] is True and again["added"] is False
    assert [k for k, _ in host.emitted] == ["urls", "urls", "urls", "urls"]  # both signals per call
    assert json.loads(host.remove_url_preset("https://arena.ai/x")) == {"ok": True, "removed": True, "presets": []}
    assert json.loads(host.remove_url_preset("nope"))["removed"] is False
    assert json.loads(host.set_last_url_preset("")) == {"ok": False, "error": "empty URL"}
    assert json.loads(host.set_last_url_preset("https://arena.ai/x")) == {"ok": True}
    assert host.stored == {"last_url_preset": "https://arena.ai/x"}

    def boom(url):
        raise RuntimeError("disk")

    host.bookmarks.add_url_preset = boom
    host.bookmarks.remove_url_preset = boom
    assert json.loads(host.add_url_preset("https://a"))["error"] == "disk"
    assert json.loads(host.remove_url_preset("https://a"))["error"] == "disk"


def test_commit_helper_and_duplicate_check():
    host = Host([UrlRow.create("https://arena.ai/a", enabled=True)])
    url_queue.commit_urls(host)
    assert host.saves == 1 and host.pushed == ["urls"]
    assert url_queue._duplicate_url(host.state.urls, "https://arena.ai/a")
    assert not url_queue._duplicate_url(host.state.urls, "https://arena.ai/a", skip_id=host.state.urls[0].id)
