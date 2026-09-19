"""D5 mutation triage: RecordingManager fail-open facade + probe builders.

Targets manager start (19)/__init__ (5)/drop (3)/set_enabled (2)/abort (2)
and probes (2) — the last untested recording modules.
"""

import asyncio
from types import SimpleNamespace

from app.services.captcha_recording.manager import RecordingManager
from app.services.captcha_recording import probes
from app.services.captcha.signals import SolveOutcome


class ManagerCDP:
    def __init__(self, fail_start=False):
        self.fail_start = fail_start
        self.drains = []
        self.sent = []

    async def evaluate(self, script):
        # install probe = the one carrying the "Install one bounded" comment
        if self.fail_start and "Install one bounded" in script:
            raise RuntimeError("page vanished")
        if "queue.splice" in script:
            return {"ok": True, "changes": self.drains.pop(0) if self.drains else [],
                    "dropped": 0}
        if "cloneNode" in script:
            return {"ok": True, "url": "u", "title": "t", "viewport": {}, "html": "<i/>"}
        return {"ok": True}

    async def send(self, method, params, timeout=5):
        self.sent.append(method)
        return {"result": {}}


def make_manager(tmp_path, name="m", cdp=None, logs=None):
    logs = logs if logs is not None else []
    cdp = cdp or ManagerCDP()
    ctrl = SimpleNamespace(cdp=cdp)
    mgr = RecordingManager(str(tmp_path / name), log=lambda msg, level="info": logs.append((level, msg)))
    return mgr, ctrl, cdp, logs


class TestStart:
    def test_disabled_returns_none(self, tmp_path):
        mgr, ctrl, _, logs = make_manager(tmp_path)
        mgr.set_enabled(False)
        assert asyncio.run(mgr.start(ctrl, {"tab": "T1", "eid": "e"})) is None
        assert mgr._active == {}

    def test_missing_tab_and_bad_cdp(self, tmp_path):
        mgr, ctrl, _, _ = make_manager(tmp_path)
        # NOTE: an empty tab id is NOT rejected — recording starts under tab ""
        # (characterized, D5); the manager only gates on active-tab + callable cdp.send
        rec = asyncio.run(mgr.start(ctrl, {}))
        assert rec is not None
        asyncio.run(mgr.finish(rec, SolveOutcome(status="solved")))
        bad = SimpleNamespace(cdp=SimpleNamespace(evaluate=None))
        assert asyncio.run(mgr.start(bad, {"tab": "T9"})) is None  # send not callable
        no_cdp = SimpleNamespace()
        assert asyncio.run(mgr.start(no_cdp, {"tab": "T9"})) is None

    def test_success_registers_and_logs(self, tmp_path):
        mgr, ctrl, _, logs = make_manager(tmp_path)
        rec = asyncio.run(mgr.start(ctrl, {"tab": "T1", "eid": "e1"}))
        assert rec is not None
        assert mgr._active == {"T1": rec}
        assert logs and logs[0][1] == "started" or "started" in logs[0][1]

    def test_duplicate_tab_rejected(self, tmp_path):
        mgr, ctrl, _, _ = make_manager(tmp_path)
        rec1 = asyncio.run(mgr.start(ctrl, {"tab": "T1", "eid": "e1"}))
        rec2 = asyncio.run(mgr.start(ctrl, {"tab": "T1", "eid": "e2"}))
        assert rec1 is not None
        assert rec2 is None

    def test_start_failure_fail_open(self, tmp_path):
        mgr, ctrl, _, logs = make_manager(tmp_path, cdp=ManagerCDP(fail_start=True))
        assert asyncio.run(mgr.start(ctrl, {"tab": "T1"})) is None
        assert mgr._active == {}
        assert any("skipped" in m for lvl, m in logs)


class TestFinishNoteAbort:
    def test_finish_none_noop(self, tmp_path):
        mgr, _, _, logs = make_manager(tmp_path)
        asyncio.run(mgr.finish(None, SolveOutcome(status="solved")))
        assert logs == []

    def test_finish_drops_recorder(self, tmp_path):
        mgr, ctrl, _, _ = make_manager(tmp_path)
        rec = asyncio.run(mgr.start(ctrl, {"tab": "T1"}))
        asyncio.run(mgr.finish(rec, SolveOutcome(status="solved", method="auto")))
        assert mgr._active == {}

    def test_finish_failure_fail_open(self, tmp_path):
        mgr, ctrl, _, logs = make_manager(tmp_path)
        rec = asyncio.run(mgr.start(ctrl, {"tab": "T1"}))

        async def boom(outcome):
            raise RuntimeError("store gone")
        rec.finish = boom
        asyncio.run(mgr.finish(rec, SolveOutcome()))
        assert mgr._active == {}
        assert any("finish failed" in m for lvl, m in logs)

    def test_note_without_active(self, tmp_path):
        mgr, _, _, logs = make_manager(tmp_path)
        asyncio.run(mgr.note("T9", "token_ready", SolveOutcome()))
        assert logs == []

    def test_note_active(self, tmp_path):
        mgr, ctrl, _, _ = make_manager(tmp_path)
        rec = asyncio.run(mgr.start(ctrl, {"tab": "T1"}))
        asyncio.run(mgr.note("T1", "token_ready",
                             SolveOutcome(status="solved", token_sec=1.0)))
        assert mgr._active == {"T1": rec}

    def test_note_failure_fail_open(self, tmp_path):
        mgr, ctrl, _, logs = make_manager(tmp_path)
        rec = asyncio.run(mgr.start(ctrl, {"tab": "T1"}))

        async def boom(phase, outcome):
            raise RuntimeError("x")
        rec.note_outcome = boom
        asyncio.run(mgr.note("T1", "final", SolveOutcome()))
        assert any("milestone skipped" in m for lvl, m in logs)

    def test_abort_none_noop(self, tmp_path):
        mgr, _, _, logs = make_manager(tmp_path)
        asyncio.run(mgr.abort(None, "why"))
        assert logs == []

    def test_abort_drops_and_fail_open(self, tmp_path):
        mgr, ctrl, _, logs = make_manager(tmp_path)
        rec = asyncio.run(mgr.start(ctrl, {"tab": "T1"}))
        asyncio.run(mgr.abort(rec, "user closed"))
        assert mgr._active == {}
        async def boom(reason):
            raise RuntimeError("y")
        rec2 = asyncio.run(mgr.start(ctrl, {"tab": "T2"}))
        rec2.abort = boom
        asyncio.run(mgr.abort(rec2, "z"))
        assert mgr._active == {}
        assert any("abort failed" in m for lvl, m in logs)


class TestFacade:
    def test_list_count_delete_labels(self, tmp_path):
        mgr, ctrl, _, _ = make_manager(tmp_path)
        rec = asyncio.run(mgr.start(ctrl, {"tab": "T1", "eid": "e1"}))
        assert mgr.count_sessions() == 1
        rows = mgr.list_sessions()
        assert rows[0]["session_id"] == rec.session_id
        row = mgr.set_label(rec.session_id, "bot")
        assert row["actor_label"] == "bot"
        row = mgr.set_result_label(rec.session_id, "passed")
        assert row["result_label"] == "passed"
        details = mgr.get_session(rec.session_id)
        assert details["manifest"]["session_id"] == rec.session_id
        folder = mgr.session_folder(rec.session_id)
        assert folder.endswith(rec.session_id)
        out = mgr.delete_session(rec.session_id)
        assert out["deleted"] is True

    def test_enabled_round_trip(self, tmp_path):
        mgr, _, _, _ = make_manager(tmp_path)
        assert mgr.is_enabled() is True
        assert mgr.set_enabled(False) is False
        assert mgr.is_enabled() is False
        assert mgr.set_enabled(True) is True
        assert mgr.is_enabled() is True


class TestProbes:
    def test_install(self):
        js = probes.install_probe()
        assert js
        assert "\n" != js[0]  # stripped
        assert "queue" in js or "MutationObserver" in js

    def test_drain(self):
        js = probes.drain_probe()
        assert "queue.splice" in js

    def test_snapshot(self):
        assert "cloneNode" in probes.snapshot_probe()

    def test_stop(self):
        js = probes.stop_probe()
        assert js
        assert js == js.strip()
