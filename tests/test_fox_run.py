"""I-64 · One pool run: per-run macro → scoped foreground → launch → savelog verdict.

The launch/poll half is the framework's `Sequence` (same seams: popen, sleep,
stop). A pool run needs storage=xfile, raises only its tab's own window
(never raise-all) and reads its OWN savelog (a unique stamp).
"""

import json
from urllib.parse import parse_qs, urlsplit

import pytest

from app.browser.uivision.pool import run as pool_run
from app.browser.uivision.pool.macro import PoolStep
from app.browser.uivision.pool.run import (PoolJob, PoolRunSpec, PoolSequence, planned_run,
                                           run_pool_job, run_stamp)
from app.browser.uivision.pool.scan import FoxTab
from app.browser.uivision.runner import Recorder, RunSeams

pytestmark = pytest.mark.unit

OK_LOG = "Status=OK\n###\necho: done — XClick fired (native OS input)"
ROW = {"index": 1, "active": {"url": "https://arena.ai/c/2", "title": "LMArena"},
       "tabs": [{"url": "https://arena.ai/c/1", "title": "LMArena"},
                {"url": "https://arena.ai/c/2", "title": "LMArena"}]}


def make_job(tmp_path, storage="xfile", macro="Python_XClick_Demo_pool", offset=1, row=ROW):
    spec = PoolRunSpec(binary=str(tmp_path / "firefox"), macro=macro, storage=storage,
                       home=str(tmp_path / "uivhome"), config_dir=str(tmp_path / "config"),
                       pause_ms=1500, target="xpath=//b", timeout_sec=30)
    tab = FoxTab(id="9THrgpBc.Profile1_tab2", url="https://arena.ai/c/2", title="LMArena",
                 profile_dir=str(tmp_path / "9THrgpBc.Profile1"), profile_name="Profile1",
                 window=1, index=1)
    return PoolJob(spec=spec, tab=tab, window_row=row,
                   step=PoolStep("LMArena", offset, "arena.ai", "xpath=//b", 1500))


class FakePopen:
    def __init__(self):
        self.calls = []

    def __call__(self, argv):
        self.calls.append(argv)
        return type("P", (), {"pid": 77})()


def reports():
    rows = []
    return rows, lambda step, message, level="info": rows.append((step, message, level))


async def noop_sleep(_sec):
    pass


@pytest.mark.asyncio
async def test_a_pool_run_writes_its_macro_launches_its_profile_and_reads_its_verdict(tmp_path, monkeypatch):
    monkeypatch.setattr(pool_run, "run_stamp", lambda: "pool-STAMP")
    monkeypatch.setattr(pool_run.desktop, "foreground_tab_window", lambda needle, rows: None)
    (tmp_path / "firefox").write_text("#!/bin/sh\n")
    job = make_job(tmp_path)
    log = tmp_path / "config" / "uivision" / "logs" / "run-pool-STAMP.txt"

    async def extension_answers(_sec):
        log.write_text(OK_LOG, encoding="utf-8")

    popen, (rows, report) = FakePopen(), reports()
    result = await run_pool_job(job, report, RunSeams(sleep=extension_answers, popen=popen))

    assert result.kind == "ok"
    doc = json.loads((tmp_path / "uivhome" / "macros" / "Python_XClick_Demo_pool.json").read_text())
    assert [doc["Commands"][0]["Target"], doc["Commands"][3]["Target"]] == ["title=LMArena", "tab=1"]
    argv = popen.calls[0]
    assert argv[1:4] == ["-profile", job.tab.profile_dir, "-new-tab"]     # ONE profile's instance
    query = parse_qs(urlsplit(argv[4]).query)
    assert query["macro"] == ["Python_XClick_Demo_pool"] and query["storage"] == ["xfile"]
    assert query["savelog"][0].endswith("run-pool-STAMP.txt")
    assert any(step == "provision" and "tab=1" in msg for step, msg, _lvl in rows)
    assert any(step == "foreground" and "never raise-all" in msg for step, msg, _lvl in rows)


@pytest.mark.asyncio
async def test_browser_storage_is_refused_before_anything_is_written(tmp_path):
    popen, (_rows, report) = FakePopen(), reports()
    result = await run_pool_job(make_job(tmp_path, storage="browser"), report,
                                RunSeams(sleep=noop_sleep, popen=popen))
    assert result.kind == "blocked" and "storage=xfile" in result.message
    assert popen.calls == [] and not (tmp_path / "uivhome").exists()


@pytest.mark.asyncio
async def test_a_bad_macro_name_blocks_the_run_by_name(tmp_path):
    popen, (_rows, report) = FakePopen(), reports()
    result = await run_pool_job(make_job(tmp_path, macro="bad name"), report,
                                RunSeams(sleep=noop_sleep, popen=popen))
    assert result.kind == "blocked" and "cannot prepare the run" in result.message
    assert popen.calls == []


def test_the_foreground_raises_only_the_tab_window(tmp_path, monkeypatch):
    job = make_job(tmp_path)
    seen = []
    monkeypatch.setattr(pool_run.desktop, "foreground_tab_window",
                        lambda needle, rows: seen.append((needle, rows)) or ([(1, "LMArena — Mozilla Firefox")], 1))
    monkeypatch.setattr(pool_run.desktop, "foreground", lambda *a: pytest.fail("raise-all must never run"))
    rows, report = reports()
    PoolSequence(job.spec, RunSeams(), Recorder(report))._foreground(planned_run(job, "S"))
    assert seen == [(job.tab.url, [ROW])]
    assert "1/1 Firefox window(s) on top" in rows[0][1]


def test_a_tab_without_a_window_row_touches_no_window(tmp_path, monkeypatch):
    job = make_job(tmp_path, row={})
    monkeypatch.setattr(pool_run.desktop, "foreground_tab_window", lambda *a: pytest.fail("no row → no map"))
    rows, report = reports()
    PoolSequence(job.spec, RunSeams(), Recorder(report))._foreground(planned_run(job, "S"))
    assert rows[0][2] == "warn" and "nothing raised" in rows[0][1]


def test_the_planned_run_names_the_profile_the_tab_and_its_own_savelog(tmp_path):
    run = planned_run(make_job(tmp_path), "pool-X")
    assert run.profile_args == ("-profile", str(tmp_path / "9THrgpBc.Profile1"))
    assert run.selector == "title=LMArena" and run.label == "Profile1 · 9THrgpBc.Profile1_tab2"
    assert run.log_path.endswith("run-pool-X.txt") and run.total == 1
    assert run_stamp() != run_stamp()                     # two quick runs never share a savelog
