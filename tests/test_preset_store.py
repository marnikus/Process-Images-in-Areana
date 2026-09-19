"""D4.4: PresetStore CRUD + corrupt-file tolerance (RULE 13: never crash on bad state).

RULE 8: real store against a tmp dir; corruption is written by hand.
"""

import json

import pytest

from app.persistence.preset_store import DEFAULTS, PresetStore

pytestmark = pytest.mark.unit


@pytest.fixture
def store(tmp_path):
    return PresetStore(tmp_path / "presets.json")


def test_missing_file_starts_with_defaults(tmp_path):
    s = PresetStore(tmp_path / "nope" / "p.json")
    assert s.get_url_presets() == []
    assert s.list_prompt_presets() == []
    assert s.list_settings_presets() == []
    assert s.list_arena_presets() == []


def test_corrupt_file_falls_back_to_defaults(tmp_path):
    p = tmp_path / "p.json"
    for bad in ("{not json", "[1, 2, 3]", "null"):
        p.write_text(bad, encoding="utf-8")
        s = PresetStore(p)
        assert s.all_data()["url_presets"] == []
        assert "prompt_presets" in s.all_data()
        s.save()  # repaired on save
        assert json.loads(p.read_text(encoding="utf-8"))["prompt_presets"] == {}


def test_url_preset_crud_and_guards(store):
    assert store.add_url_preset("") is False
    assert store.add_url_preset("  https://arena.ai/c  ") is True
    assert store.add_url_preset("https://arena.ai/c") is False  # duplicate
    assert store.get_url_presets() == ["https://arena.ai/c"]
    assert store.remove_url_preset("https://arena.ai/c") is True
    assert store.remove_url_preset("https://arena.ai/c") is False
    store.set_url_presets(["a", "b"])
    assert store.get_url_presets() == ["a", "b"]
    # persistence round trip
    again = PresetStore(store.path)
    assert again.get_url_presets() == ["a", "b"]
    # deep-copy isolation: mutating the returned list must not touch the store
    out = store.get_url_presets()
    out.append("c")
    assert store.get_url_presets() == ["a", "b"]


def test_prompt_preset_crud(store):
    assert store.load_prompt_preset("p1") is None
    store.save_prompt_preset("p1", "make a [JOB-ID: x]")
    assert store.list_prompt_presets() == ["p1"]
    detailed = store.list_prompt_presets_detailed()
    assert detailed == [{"name": "p1", "template": "make a [JOB-ID: x]"}]
    got = store.load_prompt_preset("p1")
    assert got["template"].startswith("make a")
    got["template"] = "tampered"  # isolation
    assert store.load_prompt_preset("p1")["template"].startswith("make a")
    assert store.delete_prompt_preset("p1") is True
    assert store.delete_prompt_preset("p1") is False
    # long templates truncate in the detailed listing only
    store.save_prompt_preset("long", "x" * 200)
    assert store.list_prompt_presets_detailed()[0]["template"] == "x" * 80
    assert store.load_prompt_preset("long")["template"] == "x" * 200


def test_settings_preset_crud(store):
    assert store.load_settings_preset("s1") is None
    store.save_settings_preset("s1", {"timeouts": {"generation": 90}})
    assert store.list_settings_presets() == ["s1"]
    got = store.load_settings_preset("s1")
    got["timeouts"]["generation"] = 1  # isolation
    assert store.load_settings_preset("s1")["timeouts"]["generation"] == 90
    assert store.delete_settings_preset("s1") is True
    assert store.delete_settings_preset("s1") is False


def test_arena_preset_ordering_and_crud(store):
    store.save_arena_preset("old", {"urls": ["a"], "images": [], "updated_at": "2026-01-01T00:00:00Z"})
    store.save_arena_preset("new", {"urls": ["b", "c"], "images": [1, 2],
                                    "updated_at": "2026-02-01T00:00:00Z"})
    store.save_arena_preset("bad", "not a dict")  # tolerated, filtered on list
    assert store.list_arena_presets() == ["new", "old", "bad"]
    detailed = store.list_arena_presets_detailed()
    assert [d["name"] for d in detailed] == ["new", "old"]  # non-dict doc skipped
    assert detailed[0] == {"name": "new", "url_count": 2, "image_count": 2,
                           "updated_at": "2026-02-01T00:00:00Z"}
    doc = store.load_arena_preset("new")
    doc["urls"].append("tampered")
    assert store.load_arena_preset("new")["urls"] == ["b", "c"]
    assert store.delete_arena_preset("new") is True
    assert store.delete_arena_preset("new") is False
    assert store.load_arena_preset("missing") is None
    # load() re-reads the file (external edits visible)
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    raw["arena_presets"]["revived"] = {"urls": ["r"], "images": [],
                                       "updated_at": "2026-03-01T00:00:00Z"}
    store.path.write_text(json.dumps(raw), encoding="utf-8")
    store.load()
    assert store.load_arena_preset("revived") is not None
    assert DEFAULTS["arena_presets"] == {}  # module default never mutated
