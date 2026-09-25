"""Both Firefox lanes through the REAL `Sequence` — only the Firefox process is faked.

2026-09-25 owner bug: the identify macro drew `2# mailreceiverpro@gmail.com`
on the page, yet the app logged "identify crashed: AttributeError" and kept
the profile name in the URL List / Page Pool. `Sequence._final` reads
`recorder.steps`; the lanes handed it a bare callable, and the lane tests
faked `Sequence`, so the gap was invisible. These tests run the real
foreground → launch → poll → roll-up path: the fake launch writes the
savelog exactly as the Ui.Vision extension does (status line, `###`, log rows).
"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from app.browser.page_pool import PagePool, tab_label_of
from app.browser.uivision import job_macros as uv_job
from app.browser.uivision import pool_tabs as pt
from app.browser.uivision import sequence as seq_mod
from app.browser.uivision.sequence import StepRecorder
from app.services import firefox_lane as fl
from app.services.live import firefox_identity as fi
from tests.test_firefox_lane import CfgBridge, ff_page

pytestmark = pytest.mark.unit

EMAIL = "mailreceiverpro@gmail.com"


def savelog_for(email: str, no: int = 2) -> str:
    reply = json.dumps({"email": email, "via": "scope", "overlay": "ok",
                        "text": f"{no}# {email}"})
    return ("Status=OK\n###\n"
            "[info] Executing: | selectWindow | title=*Arena* | |\n"
            "[info] Executing: | echo | ARENA_IDENTITY=${arenaIdentity} | blue |\n"
            f"[echo] ARENA_IDENTITY={reply}\n")


class FakeFirefox:
    """`launch_resilient` stand-in: writes the savelog named in the autorun URL."""

    def __init__(self, body: str):
        self.body, self.launches = body, []

    def __call__(self, argv, popen=None):
        url = next(arg for arg in argv if "savelog=" in arg)
        path = parse_qs(urlsplit(url).query or urlsplit(url).fragment)["savelog"][0]
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self.body)
        self.launches.append(path)
        return SimpleNamespace(pid=4242)


@pytest.fixture
def real_lane(monkeypatch, tmp_path):
    monkeypatch.setattr(seq_mod.launch, "resolve_binary", lambda binary: "/fake/firefox")
    monkeypatch.setattr(seq_mod.launch, "binary_exists", lambda binary: True)
    monkeypatch.setattr(seq_mod.desktop, "foreground_tab_window", lambda needle, wins: None)
    monkeypatch.setattr(seq_mod.desktop, "foreground", lambda needle: ([], 0))
    monkeypatch.setattr(fl.uv_tabs, "profile_sessions", lambda profiles=None: [])
    monkeypatch.setattr(fl, "_LAST_AT", 0.0)
    monkeypatch.setattr(fl, "_MACRO_LOCK", asyncio.Lock())
    cfg = {"storage": "xfile", "home": str(tmp_path / "uv"), "target": "css=.x",
           "gap_sec": 0}
    bridge = CfgBridge(cfg)
    bridge.config.dir = str(tmp_path / "cfg")
    return SimpleNamespace(bridge=bridge, mp=monkeypatch)


def fake_firefox(lane, body):
    firefox = FakeFirefox(body)
    lane.mp.setattr(seq_mod.launch, "launch_resilient", firefox)
    return firefox


def test_step_recorder_keeps_steps_and_forwards():
    seen = []
    recorder = StepRecorder(lambda step, msg, level="info": seen.append((step, msg, level)))
    recorder("launch", "go", "warn")
    assert recorder.steps == [("launch", "go")] and seen == [("launch", "go", "warn")]


@pytest.mark.asyncio
async def test_identify_through_the_real_sequence_returns_the_echoed_account(real_lane):
    firefox = fake_firefox(real_lane, savelog_for(EMAIL))
    kind, message, lines = await fl.run_identify(real_lane.bridge, ff_page(),
                                                 fl.uv_identify.payload(2, "user-2"))
    assert (kind, message) == ("ok", "macro completed"), message
    assert len(firefox.launches) == 1 and "identify-" in firefox.launches[0]
    assert fl.uv_identify.parse_reply(lines)["email"] == EMAIL


@pytest.mark.asyncio
async def test_job_phase_through_the_real_sequence_returns_its_reply(real_lane):
    """A phase macro runs the real path; its `ARENA_JOB=` echo comes back parsed for THIS job."""
    reply = json.dumps({"token": "c1", "phase": "baseline", "data": {"srcs": [], "composer_len": 0}})
    firefox = fake_firefox(real_lane, "Status=OK\n###\n"
                                      "[info] Executing: | echo | ARENA_JOB=${arenaJob} | blue |\n"
                                      f"[echo] ARENA_JOB={reply}\n")
    phase = uv_job.probe_macro("c1", "baseline", "({srcs: []})")
    kind, message, lines = await fl.run_phase(real_lane.bridge, ff_page(), phase, "c1")
    assert (kind, message) == ("ok", "macro completed"), message
    assert len(firefox.launches) == 1 and "job-c1-baseline-" in firefox.launches[0]
    assert uv_job.parse_replies(lines, "c1") == {"baseline": {"srcs": [], "composer_len": 0}}
    written = Path(real_lane.bridge.config.get_state("firefox_auto")["home"]) / "macros"
    assert (written / "Arena_Job_Baseline.json").is_file()   # provisioned to hard-drive storage


@pytest.mark.asyncio
async def test_detected_account_replaces_the_profile_label_in_pool_and_url_list(real_lane):
    """The owner's screenshots: overlay drawn, but rows kept “user-2” — never again."""
    fake_firefox(real_lane, savelog_for(EMAIL))
    logs = []
    pool = PagePool(logger=lambda m, l="info": None)
    tab = pt.FirefoxTab(id="9THrgpBc.Profile 1_tab8", url="https://arena.ai/image/direct",
                        title="Arena chat", profile="user-2",
                        profile_dir="/ff/9THrgpBc.Profile 1",
                        ws_url=pt.ws_for("9THrgpBc.Profile 1_tab8"))
    pool.add_page(pt.page_for(tab))
    bridge = real_lane.bridge
    bridge._page_pool, bridge._emit_pool_status = pool, lambda: None
    bridge._log = lambda m, level="info": logs.append((level, m))
    real_lane.mp.setattr(fi, "schedule_coro", lambda b, coro: coro.close())
    assert pool.status_snapshot()["pages"][0]["tab_label"] == "user-2"
    assert fi.observe(bridge, [tab]) is True
    assert await fi.drain(bridge) == 1
    snap = pool.status_snapshot()["pages"][0]
    assert (snap["tab_label"], snap["name_source"]) == (EMAIL, "detected")
    assert tab_label_of(pool, tab.id) == EMAIL             # URL List TAB column
    assert not [m for level, m in logs if level == "warn"]
