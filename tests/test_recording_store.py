"""RecordingStore + RecordingService — disk round-trip and lifecycle.

RULE 8: real store against a tmp dir, real service against a fake ctrl.
Empty vs broken kept distinct (RULE 4); corrupt headers skipped, not fatal.
"""

import json

import pytest

from app.services.recording import payloads
from app.services.recording.recorder import RecordingService
from app.services.recording.session import RecordingSession
from app.services.recording.store import RecordingStore

DETECT = {"url": "https://arena.ai/c/1", "trigger": "check-security",
          "kind": "recaptcha_enterprise", "sitekey": "6Le3key"}


@pytest.fixture
def store(tmp_path):
    return RecordingStore(str(tmp_path / "recordings"))


def make_session(tab="TAB123"):
    return RecordingSession.create(tab, DETECT)


@pytest.mark.unit
def test_store_create_and_finalize_round_trip(store):
    s = make_session()
    assert store.create(s, "<html>first</html>") is True
    assert store.create(s) is False  # same id twice -> refused
    s.finalize("solved", "auto")
    store.finalize(s)
    headers, skipped = store.list_sessions()
    assert skipped == [] and len(headers) == 1
    assert headers[0]["outcome"] == "solved" and headers[0]["id"] == s.id
    assert headers[0]["counters"]["snapshots"] == 1


@pytest.mark.unit
def test_store_events_and_snapshots(store):
    s = make_session()
    store.create(s)
    store.append_event(s, "state", {"note": "detected"})
    store.append_event(s, "mutation", {"sel": "div.x", "added": 2})
    store.append_event(s, "network", {"url": "https://arena.ai/api/x", "host": "arena.ai"})
    name = store.add_snapshot(s, "<html><body>snap</body></html>")
    assert name == "0000.html"
    events = store.load_events(s.id)
    assert [e["kind"] for e in events] == ["state", "mutation", "network", "snapshot"]
    assert store.load_snapshot(s.id, name).startswith("<html>")
    assert store.load_snapshot(s.id, "../evil") == ""  # path safety
    assert store.load_snapshot(s.id, "9999.html") == ""


@pytest.mark.unit
def test_store_list_skips_corrupt_header(store):
    s = make_session()
    store.create(s)
    bad_dir = store.root / "20990101-000000-BADBAD"
    bad_dir.mkdir()
    (bad_dir / "session.json").write_text("not json at all", encoding="utf-8")
    headers, skipped = store.list_sessions()
    assert len(headers) == 1  # the good one survives
    assert any("BADBAD" in r and "unreadable" in r for r in skipped)


@pytest.mark.unit
def test_store_label_validates_and_persists(store):
    s = make_session()
    store.create(s)
    ok, info = store.set_label(s.id, "bot_pass")
    assert ok and info == "bot_pass"
    headers, _ = store.list_sessions()
    assert headers[0]["label"] == "bot_pass"
    assert store.set_label(s.id, "nonsense")[0] is False
    assert store.set_label("unknown-id", "manual_pass")[0] is False


@pytest.mark.unit
def test_store_delete(store):
    s = make_session()
    store.create(s)
    assert store.delete(s.id) is True
    assert store.list_sessions()[0] == []
    assert store.delete(s.id) is False


class FakeCdp:
    """Scripted CDP double: canned probe answers, records evaluations."""

    def __init__(self, snapshot_html="<html>live</html>", fail=False):
        self.evaluated = []
        self._html = snapshot_html
        self._fail = fail
        self.flush_calls = 0

    async def evaluate(self, js):
        self.evaluated.append(js[:60])
        if self._fail:
            raise RuntimeError("cdp down")
        if "MutationObserver" in js or "__arenaRecNetInst" in js:
            return "installed"
        if "__arenaRecMut.splice" in js:  # flush
            self.flush_calls += 1
            return {"ok": True,
                    "mutations": [{"ts": "2026-09-18T13:23:16Z", "kind": "mutation",
                                   "mut": "childList", "sel": "div.dialog", "added": 1}],
                    "requests": [{"ts": "2026-09-18T13:23:17Z", "kind": "network",
                                  "via": "fetch", "method": "POST",
                                  "url": "https://arena.ai/api/chat?token=SECRET&x=1",
                                  "status": 200}]}
        if "cloneNode" in js:  # snapshot
            return {"ok": True, "redacted": 1, "length": len(self._html), "html": self._html}
        return None


class FakeCtrl:
    def __init__(self, cdp):
        self.cdp = cdp


@pytest.mark.asyncio
@pytest.mark.unit
async def test_service_start_edge_stop_lifecycle(tmp_path):
    svc = RecordingService(str(tmp_path / "rec"))
    cdp = FakeCdp()
    ctrl = FakeCtrl(cdp)
    session = await svc.start(ctrl, "TAB1", {**DETECT, "url": "https://arena.ai/c/9"})
    assert session is not None and svc._active.get("TAB1") is session
    await svc.start(ctrl, "TAB1", DETECT)  # second start on same tab: deduped
    assert len(svc._active) == 1
    await svc.edge(ctrl, "TAB1", "token injected", snapshot=True)
    svc.stop("TAB1", "solved", "auto")
    assert "TAB1" not in svc._active
    payload = payloads.detail_payload(svc.store, session.id)
    assert payload["ok"] is True
    kinds = [e["kind"] for e in payload["events"]]
    assert "mutation" in kinds and "network" in kinds and kinds.count("state") >= 2
    net = next(e for e in payload["events"] if e["kind"] == "network")
    assert "SECRET" not in net["url"]  # URL redacted before storage
    assert payload["session"]["outcome"] == "solved"
    assert payload["timeline"]["by_kind"]["mutation"] >= 1


@pytest.mark.asyncio
@pytest.mark.unit
async def test_service_fail_open_when_cdp_down(tmp_path):
    svc = RecordingService(str(tmp_path / "rec"))
    ctrl = FakeCtrl(FakeCdp(fail=True))
    session = await svc.start(ctrl, "TAB2", {**DETECT, "url": "https://arena.ai", "trigger": "job"})
    assert session is not None  # session created even without snapshot
    await svc.edge(ctrl, "TAB2", "note")  # must not raise
    svc.stop("TAB2", "page_error")
    payload = payloads.list_payload(svc)
    assert payload["ok"] and payload["sessions"][0]["outcome"] == "page_error"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_service_disabled_records_nothing(tmp_path):
    svc = RecordingService(str(tmp_path / "rec"))
    svc.set_enabled(False)
    assert svc.enabled() is False
    assert RecordingService(str(tmp_path / "rec")).enabled() is False  # persisted
    ctrl = FakeCtrl(FakeCdp())
    assert await svc.start(ctrl, "TAB3", DETECT) is None
    assert payloads.list_payload(svc)["sessions"] == []
    svc.set_enabled(True)  # round-trips through settings.json
    assert RecordingService(str(tmp_path / "rec")).enabled() is True


@pytest.mark.asyncio
@pytest.mark.unit
async def test_service_label_delete_diff_payloads(tmp_path):
    svc = RecordingService(str(tmp_path / "rec"))
    ctrl = FakeCtrl(FakeCdp())
    s1 = await svc.start(ctrl, "TABA", {**DETECT, "url": "https://arena.ai/c/1"})
    svc.stop("TABA", "manual")
    s2 = await svc.start(ctrl, "TABB", {**DETECT, "url": "https://arena.ai/c/2"})
    svc.stop("TABB", "solved")
    assert payloads.label_payload(svc.store, s1.id, "manual_pass")["ok"] is True
    # both sessions recorded one identical snapshot each -> empty diff
    d = payloads.diff_payload(svc.store, {"session_a": s1.id, "name_a": "0000.html",
                                          "session_b": s2.id, "name_b": "0000.html"})
    assert d["ok"] is True and d["identical"] is True
    assert payloads.delete_payload(svc, s2.id)["ok"] is True
    assert payloads.delete_payload(svc, "missing000")["ok"] is False
