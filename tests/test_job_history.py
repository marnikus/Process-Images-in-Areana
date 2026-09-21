"""Job History — store, clamp, record paths, slots (RULE 8).

The real `JobHistoryStore` / record helpers against stub bridges (records
emitted payloads): sequential job numbers survive reload, both settle-site
adapters build the same wire row, and every entry point fails soft — a
settle site never breaks because history did.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.persistence.config_manager import ConfigManager
from app.services import job_history as jh
from app.services.job_history import HistoryInput, JobHistoryStore
from app.ui.panels.app_settings import apply_history_limit
from app.ui.panels.job_history import JobHistoryMixin

from tests.test_multi_page_dispatcher_run import make_img

pytestmark = pytest.mark.unit


class FakeSignal:
    def __init__(self):
        self.sent = []

    def emit(self, payload):
        self.sent.append(payload)

    def connect(self, _fn):
        pass


def raising_signal():
    sig = FakeSignal()

    def _boom(_payload):
        raise RuntimeError("qt gone")

    sig.emit = _boom
    return sig


def make_bridge(tmp_path=None, **kw):
    logs = []
    ns = {"_log": lambda m, l="info": logs.append((l, m)),
          "job_history_updated": FakeSignal(), "_logs": logs}
    if tmp_path is not None:
        ns["config"] = ConfigManager(str(tmp_path / "cfg"))
    ns.update(kw)
    return SimpleNamespace(**ns)


def make_pool(worker_no=2):
    page = SimpleNamespace(worker_no=worker_no) if worker_no is not None else None
    return SimpleNamespace(get_page=lambda _tid: page)


def finished_input(bridge, failed=False, err="", out="/tmp/out/a_AI.png"):
    img = make_img("a.png")
    img.output_path = "" if failed else out
    return HistoryInput(bridge=bridge, pool=make_pool(), img=img,
                        tab_id="tab-abc", job_id="corr-1",
                        failed=failed, err=err)


# ── clamp + limit ────────────────────────────────────────────────────────────

def test_clamp_bounds_and_garbage():
    assert jh.clamp_history_limit(None) == 50
    assert jh.clamp_history_limit("") == 50
    assert jh.clamp_history_limit("xx") == 50
    assert jh.clamp_history_limit(0) == 5
    assert jh.clamp_history_limit(4) == 5
    assert jh.clamp_history_limit(501) == 500
    assert jh.clamp_history_limit(17) == 17


def test_history_limit_default_stored_and_garbage(tmp_path):
    assert jh.history_limit(SimpleNamespace()) == 50
    bridge = make_bridge(tmp_path)
    assert jh.history_limit(bridge) == 50
    bridge.config.set_state(job_history_limit=7)
    assert jh.history_limit(bridge) == 7
    bridge.config.set_state(job_history_limit="junk")
    assert jh.history_limit(bridge) == 50


# ── store ────────────────────────────────────────────────────────────────────

def test_store_sequential_numbers_newest_first():
    store = JobHistoryStore()
    first = store.append({"job_id": "a"})
    second = store.append({"job_id": "b"})
    assert (first["job_no"], second["job_no"]) == (1, 2)
    assert store.next_no == 3 and store.total == 2
    rows = store.recent(50)
    assert [r["job_id"] for r in rows] == ["b", "a"]
    assert [r["job_no"] for r in store.recent(1)] == [2]
    assert store.recent(0) == [] and store.recent(-3) == []


def test_store_trims_to_cap():
    store = JobHistoryStore(cap=3)
    for i in range(5):
        store.append({"job_id": f"j{i}"})
    assert store.total == 3
    assert [r["job_no"] for r in store.recent(9)] == [5, 4, 3]
    store.clear()
    assert store.total == 0 and store.recent(9) == []
    assert store.next_no == 6  # ids are never reused


def test_store_persists_and_survives_reload(tmp_path):
    path = tmp_path / "job_history.json"
    store = JobHistoryStore(path)
    store.append({"job_id": "a", "status": "completed"})
    assert path.exists()
    again = JobHistoryStore(path)
    assert again.total == 1 and again.next_no == 2
    assert again.recent(9)[0]["job_id"] == "a"


def test_store_recovers_from_corrupt_file(tmp_path):
    path = tmp_path / "job_history.json"
    path.write_text("{nope", encoding="utf-8")
    store = JobHistoryStore(path)
    assert store.total == 0 and store.next_no == 1
    path.write_text(json.dumps({"next_job_no": "xx", "entries": [{"a": 1}, 7, "x"]}), encoding="utf-8")
    store = JobHistoryStore(path)
    assert store.total == 1 and store.next_no == 1  # bad rows dropped, counting restarts


def test_coerce_saved_shapes():
    assert jh._coerce_saved(None) == (1, [])
    assert jh._coerce_saved([]) == (1, [])
    nxt, rows = jh._coerce_saved({"next_job_no": 4, "entries": [{"a": 1}]})
    assert (nxt, rows) == (4, [{"a": 1}])


def test_store_of_caches_and_runs_memory_only_without_config():
    bridge = SimpleNamespace()
    assert jh.store_of(bridge) is jh.store_of(bridge)
    row = jh.store_of(bridge).append({"job_id": "m"})
    assert row["job_no"] == 1


def test_iso_falls_back_to_epoch_zero():
    assert jh._iso("garbage").startswith("1970-01-01")


# ── note / take side channel ────────────────────────────────────────────────

def test_note_take_lifecycle_and_unknown_job_defaults():
    bridge = SimpleNamespace()
    jh.note_job_started(bridge, "")
    jh.note_captcha_count(bridge, "", 3)
    assert not hasattr(bridge, "_job_started_at")  # empty ids never noted
    jh.note_job_started(bridge, "j1")
    jh.note_captcha_count(bridge, "j1", 2)
    started, captcha = jh._take_context(bridge, "j1")
    assert captcha == 2 and started > 0
    assert bridge._job_started_at == {} and bridge._job_captcha == {}  # popped once
    started2, captcha2 = jh._take_context(bridge, "j1")
    assert captcha2 == 0 and started2 >= started  # unknown job: now, 0
    bridge._job_started_at["j2"] = "junk"  # garbage values fail soft
    assert jh._take_context(bridge, "j2")[1] == 0
    assert jh._take_context(SimpleNamespace(), "j3")[1] == 0


def test_runner_drain_notes_the_count_for_history():
    from app.services.single_job_runner import _emit_captcha_job_lines

    logs = []
    ctx = SimpleNamespace(ctrl=SimpleNamespace(_captcha_reports=[{"eid": "e1"}, {"eid": "e2"}]),
                          bridge=SimpleNamespace(_log=lambda m, l="info": logs.append(m)),
                          corr_id="c", tab_id="t", job_id="job-9",
                          img=SimpleNamespace(relative_path="a.png"))
    _emit_captcha_job_lines(ctx, False, "")
    assert ctx.bridge._job_captcha == {"job-9": 2}
    assert len([m for m in logs if "CAPTCHA_JOB" in m]) == 2  # join lines unchanged


# ── record ───────────────────────────────────────────────────────────────────

def test_record_completed_row_fields_and_emit():
    bridge = make_bridge()
    jh.note_job_started(bridge, "corr-1")
    jh.note_captcha_count(bridge, "corr-1", 1)
    row = jh.record_history(finished_input(bridge))
    assert row["job_no"] == 1
    assert row["status"] == "completed" and row["error"] == ""
    assert row["tab_id"] == "tab-abc" and row["worker_no"] == 2
    assert row["image"] == "a.png" and row["image_id"] == "i-a.png"
    assert row["folder"] == str(Path("/tmp/out")) and row["output_path"] == "/tmp/out/a_AI.png"
    assert row["started"] <= row["finished"]
    assert row["started_at"] <= row["finished_at"] and row["captcha"] == 1
    pushed = json.loads(bridge.job_history_updated.sent[-1])
    assert pushed["limit"] == 50 and pushed["total"] == 1
    assert pushed["entries"][0]["job_no"] == 1


def test_record_failed_row_has_no_destination_and_truncates_error():
    bridge = make_bridge()
    row = jh.record_history(finished_input(bridge, failed=True, err="E" * 900))
    assert row["status"] == "failed"
    assert row["folder"] == "" and row["output_path"] == ""  # RULE 4: no destination
    assert len(row["error"]) == jh.ERROR_KEEP
    assert row["captcha"] == 0


def test_record_adapters_build_the_same_row():
    bridge = make_bridge()
    dispatch_ctx = SimpleNamespace(bridge=bridge, pool=make_pool(4), img=make_img("d.png"),
                                   tab_id="tab-d", job_id="jd", corr_id="jd",
                                   failed=False, err="")
    dispatch_ctx.img.output_path = "/tmp/d_AI.png"
    d_row = jh.record_dispatch_result(dispatch_ctx)
    batch_bridge = make_bridge()
    res = SimpleNamespace(img=make_img("s.png"), failed=True, error="nope",
                          job_id="js", corr_id="js")
    b_row = jh.record_batch_result(SimpleNamespace(bridge=batch_bridge, tab_id="tab-s"), res)
    assert (d_row["worker_no"], d_row["status"]) == (4, "completed")
    assert b_row["worker_no"] == ""  # sequential tab without a pool page
    assert (b_row["status"], b_row["error"]) == ("failed", "nope")


def test_record_never_raises_and_emit_tolerates_dead_signals():
    assert jh.record_history(None) is None
    assert jh.record_history(HistoryInput(bridge=None, pool=None, img=SimpleNamespace(),
                                          tab_id="", job_id="", failed=True, err="x")) is not None
    jh.emit_history(SimpleNamespace())  # no signal: fine
    jh.emit_history(SimpleNamespace(job_history_updated=raising_signal()))  # dead Qt: fine


def test_worker_no_variants():
    assert jh.worker_no_of(None, "t") == ""
    assert jh.worker_no_of(make_pool(None), "t") == ""
    assert jh.worker_no_of(make_pool(0), "t") == ""
    assert jh.worker_no_of(make_pool(3), "t") == 3

    class _Boom:
        def get_page(self, _tid):
            raise RuntimeError("gone")

    assert jh.worker_no_of(_Boom(), "t") == ""


def test_emit_payload_respects_the_limit(tmp_path):
    bridge = make_bridge(tmp_path)
    for i in range(7):
        jh.note_job_started(bridge, f"j{i}")
        rec = finished_input(bridge)
        rec.job_id = f"j{i}"
        jh.record_history(rec)
    bridge.config.set_state(job_history_limit=5)
    jh.emit_history(bridge)
    pushed = json.loads(bridge.job_history_updated.sent[-1])
    assert [e["job_id"] for e in pushed["entries"]] == ["j6", "j5", "j4", "j3", "j2"]
    assert pushed["total"] == 7 and pushed["limit"] == 5 and pushed["next_job_no"] == 8


def test_history_payload_never_raises():
    assert jh.history_payload(SimpleNamespace(_job_history=object()))["entries"] == []


# ── slots + settings ─────────────────────────────────────────────────────────

def make_host(tmp_path):
    class Host(JobHistoryMixin):
        pass

    host = Host()
    host.config = ConfigManager(str(tmp_path / "cfg"))
    host.job_history_updated = FakeSignal()
    logs = []
    host._log = lambda m, l="info": logs.append((l, m))
    return host, logs


def test_get_job_history_slot_returns_the_payload(tmp_path):
    host, _ = make_host(tmp_path)
    payload = json.loads(host.get_job_history())
    assert payload["entries"] == [] and payload["limit"] == 50
    assert payload["total"] == 0 and payload["next_job_no"] == 1


def test_clear_job_history_slot_empties_and_pushes(tmp_path):
    host, logs = make_host(tmp_path)
    jh.record_history(finished_input(host))
    assert json.loads(host.clear_job_history()) == {"ok": True}
    assert json.loads(host.get_job_history())["total"] == 0
    assert json.loads(host.job_history_updated.sent[-1])["entries"] == []
    assert any("cleared" in m for _, m in logs)


def test_clear_job_history_reports_failures(tmp_path):
    host, _ = make_host(tmp_path)

    def _boom(_m, _l="info"):
        raise RuntimeError("log gone")

    host._log = _boom
    assert json.loads(host.clear_job_history())["ok"] is False


def test_history_payload_json_never_raises(tmp_path, monkeypatch):
    from app.ui.panels import job_history as panel_mod

    host, _ = make_host(tmp_path)
    monkeypatch.setattr(jh, "history_payload", lambda _b: (_ for _ in ()).throw(RuntimeError("x")))
    assert json.loads(panel_mod.history_payload_json(host))["entries"] == []


def test_apply_history_limit_clamps_persists_pushes(tmp_path):
    host, logs = make_host(tmp_path)
    apply_history_limit(host, {})
    assert host.job_history_updated.sent == []  # absent key: untouched
    apply_history_limit(host, {jh.LIMIT_KEY: 9999})
    assert host.config.get_state(jh.LIMIT_KEY) == 500
    pushed = json.loads(host.job_history_updated.sent[-1])
    assert pushed["limit"] == 500
    assert any("500" in m for _, m in logs)
