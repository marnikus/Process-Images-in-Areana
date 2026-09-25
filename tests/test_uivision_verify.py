"""The staged delivery wait: receipt → watch → one re-send → the named miss.

RULE 8: SendInput says success while the keys vanish (no tab, no savelog, a
90 s freeze) — every branch below pins one stage of the receipt ladder or one
line of the timeout autopsy.
"""

import time
from types import SimpleNamespace

import pytest

from app.browser.uivision import verify

pytestmark = pytest.mark.unit


async def _noop(_seconds):
    return None


class _Ops:
    """Foreground-title fake: the read, the miss, the unreadable window."""

    def __init__(self, title="", boom=False):
        self.title = title
        self.boom = boom

    def foreground_title(self):
        if self.boom:
            raise AttributeError("windll")
        return self.title


class _Deliver:
    def __init__(self, refuse=False):
        self.refuse = refuse
        self.calls = []

    def __call__(self, hwnd, url):
        self.calls.append((hwnd, url))
        if self.refuse:
            raise OSError("SendInput failed")


def _run(tmp_path, log_text=None, index=1, total=1, name="run-echo.txt"):
    log = tmp_path / name
    if log_text is not None:
        log.write_text(log_text)
    target = SimpleNamespace(profile_name="Work", profile_dir="/ff/p1")
    return SimpleNamespace(log_path=str(log), index=index, total=total,
                           label="Work", target=target)


def _seq(rows, sessions=(), deliver=None, ops=None, rescan=None):
    spec = SimpleNamespace(timeout_sec=0)
    seams = SimpleNamespace(sleep=_noop, stop=None, deliver=deliver, ops=ops)
    probe = rescan if rescan is not None else lambda: list(sessions)
    return SimpleNamespace(spec=spec, seams=seams, rescan=probe,
                           recorder=lambda s, m, level="info": rows.append((s, m, level)))


def _text(rows):
    return " | ".join(f"{s}:{m}" for s, m, _l in rows)


def test_confirm_matches_the_autostart_title_case_insensitively():
    assert verify.confirm_autorun_page(_Ops("Ui.Vision RPA — autorun")) is True
    assert verify.confirm_autorun_page(_Ops("UI.VISION")) is True
    assert verify.confirm_autorun_page(_Ops("Inbox — Thunderbird")) is False
    assert verify.confirm_autorun_page(_Ops("")) is False
    assert verify.confirm_autorun_page(_Ops(boom=True)) is False   # unreadable, not failed


def test_invocation_open_matches_only_this_runs_stamp():
    mine = [{"rows": [{"url": "file:///x/autorun.html?savelog=run-echo.txt&direct=1"}]}]
    assert verify.invocation_open(mine, "run-echo.txt") is True
    stale = [{"rows": [{"url": "file:///x/autorun.html?savelog=run-old.txt&direct=1"}]}]
    assert verify.invocation_open(stale, "run-echo.txt") is False  # another run's tab
    assert verify.invocation_open([], "run-echo.txt") is False
    assert verify.invocation_open(None, "run-echo.txt") is False


def test_tab_state_prefers_the_live_title_over_the_store(tmp_path):
    rows = []
    seq = _seq(rows, sessions=[], ops=_Ops("Ui.Vision RPA"))   # unflushed store, live title
    assert verify._tab_state(seq, _run(tmp_path)) == "open"


def test_tab_state_names_absent_and_unknown(tmp_path):
    seq = _seq([], sessions=[{"rows": [{"url": "https://arena.ai/a"}]}], ops=_Ops("Mail"))
    assert verify._tab_state(seq, _run(tmp_path)) == "absent"

    def _locked():
        raise OSError("the store is mid-write")
    seq = _seq([], rescan=_locked, ops=_Ops("Mail"))
    assert verify._tab_state(seq, _run(tmp_path)) == "unknown"
    seq = _seq([], rescan=lambda: None, ops=_Ops("Mail"))
    assert verify._tab_state(seq, _run(tmp_path)) == "unknown"


async def test_fast_receipt_waits_out_the_run_on_proof(tmp_path):
    rows = []
    deliver = _Deliver()
    run = _run(tmp_path, log_text="Status=OK\n###\n")
    seq = _seq(rows, deliver=deliver, ops=_Ops("Ui.Vision RPA — autorun"))
    verdict = await verify.await_delivery(seq, run, verify.Delivery(
        hwnd=999, url="file:///autorun", deadline=time.time()))
    assert verdict.kind == "ok"
    assert "autorun page confirmed in the foreground" in _text(rows)
    assert deliver.calls == []                                # proven — nothing re-sent


async def test_watch_returns_the_savelog_without_receipt(tmp_path):
    rows = []
    deliver = _Deliver()
    run = _run(tmp_path, log_text="Status=Error: echo\n###\n")
    seq = _seq(rows, deliver=deliver, ops=_Ops("Inbox"))       # title miss, log answers
    verdict = await verify.await_delivery(seq, run, verify.Delivery(
        hwnd=999, url="file:///autorun", deadline=time.time()))
    assert verdict.kind == "error"
    assert "watching the session store" in _text(rows)
    assert deliver.calls == []


async def test_receipt_survives_a_missing_ops_seam(tmp_path):
    rows = []                                                 # seams.ops=None → Win32Ops → False
    run = _run(tmp_path, log_text="Status=OK\n###\n")
    seq = _seq(rows, ops=None)
    verdict = await verify.await_delivery(seq, run, verify.Delivery(
        hwnd=999, url="file:///autorun", deadline=time.time()))
    assert verdict.kind == "ok"                               # ...and the watch still answers


async def test_open_but_silent_tab_gets_progress_and_autopsy(tmp_path):
    rows = []
    deliver = _Deliver()
    run = _run(tmp_path)                                      # no savelog written
    tab = {"url": "file:///x/autorun.html?savelog=run-echo.txt&direct=1"}
    seq = _seq(rows, sessions=[{"rows": [tab]}], deliver=deliver, ops=_Ops("Inbox"))
    verdict = await verify.await_delivery(seq, run, verify.Delivery(
        hwnd=999, url="file:///autorun", deadline=time.time()))
    assert verdict.kind == "timeout"
    text = _text(rows)
    assert "autorun tab is open — the macro is slow or silent" in text
    assert "never answered" in text                           # the silent-tab autopsy
    assert "MANUAL STEP" in text and "file:///autorun" in text
    assert "waiting up to" not in text                        # the wait line would lie now
    assert deliver.calls == []                                # open tab — never re-sent


async def test_absent_tab_resends_once_then_names_the_miss(tmp_path):
    rows = []
    deliver = _Deliver()
    run = _run(tmp_path)
    store = [{"rows": [{"url": "https://arena.ai/a"}]}]       # readable, no invocation tab
    seq = _seq(rows, sessions=store, deliver=deliver, ops=_Ops("Inbox"))
    verdict = await verify.await_delivery(seq, run, verify.Delivery(
        hwnd=999, url="file:///autorun", deadline=time.time()))
    assert verdict.kind == "timeout"
    assert deliver.calls == [(999, "file:///autorun")]        # exactly one re-send
    text = _text(rows)
    assert "re-sending the keystrokes once" in text
    assert "the address-bar keystrokes missed" in text
    assert "the checklist above" in verdict.message
    assert text.count("check:") == 2


async def test_refused_resend_degrades_to_manual(tmp_path):
    rows = []
    deliver = _Deliver(refuse=True)
    run = _run(tmp_path)
    store = [{"rows": [{"url": "https://arena.ai/a"}]}]
    seq = _seq(rows, sessions=store, deliver=deliver, ops=_Ops("Inbox"))
    verdict = await verify.await_delivery(seq, run, verify.Delivery(
        hwnd=999, url="file:///autorun", deadline=time.time()))
    assert verdict.kind == "timeout"
    assert len(deliver.calls) == 1
    text = _text(rows)
    assert "re-send refused (SendInput failed)" in text
    assert "MANUAL STEP" in text


async def test_unknown_store_skips_the_resend(tmp_path):
    rows = []
    deliver = _Deliver()

    def _locked():
        raise OSError("the store is mid-write")
    seq = _seq(rows, rescan=_locked, deliver=deliver, ops=_Ops("Inbox"))
    verdict = await verify.await_delivery(seq, _run(tmp_path), verify.Delivery(
        hwnd=999, url="file:///autorun", deadline=time.time()))
    assert verdict.kind == "timeout"
    assert deliver.calls == []                                # never re-send blind
    assert "unreadable" in _text(rows)
    assert "unreadable" in verdict.message


async def test_autopsy_says_which_timeout_it_was(tmp_path):
    run = _run(tmp_path, index=2, total=2)
    tab = {"url": "file:///x/autorun.html?savelog=run-echo.txt&direct=1"}

    rows = []
    verify.report_timeout_autopsy(_seq(rows, sessions=[{"rows": [tab]}], ops=_Ops("Mail")),
                                  run, "file:///autorun")
    text = _text(rows)
    assert "the autorun tab is open but the macro never answered" in text
    assert "file URLs" in text and "case-exact" in text
    assert "run 2/2 (Work): " in text

    rows = []
    store = [{"rows": [{"url": "https://arena.ai/a"}]}]
    verify.report_timeout_autopsy(_seq(rows, sessions=store, ops=_Ops("Mail")),
                                  run, "file:///autorun")
    text = _text(rows)
    assert "no autorun tab opened — the keystrokes missed or the tab was closed" in text
    assert "MANUAL STEP" in text and "waiting up to" not in text

    def _locked():
        raise OSError("gone")
    rows = []
    verify.report_timeout_autopsy(_seq(rows, rescan=_locked, ops=_Ops("Mail")),
                                  run, "file:///autorun")
    assert "Firefox may have closed" in _text(rows)


async def test_poll_to_deadline_passes_verdicts_through(tmp_path):
    rows = []
    run = _run(tmp_path, log_text="Status=OK\n###\n")
    verdict = await verify.poll_to_deadline(_seq(rows), run, "file:///autorun", time.time())
    assert verdict.kind == "ok"
    assert "wait expired" not in _text(rows)                  # no autopsy without a timeout


def test_addonless_profile_warns_by_name(monkeypatch):
    rows = []
    states = {"/ff/p1": True, "/ff/p2": False, "/ff/p3": None}
    monkeypatch.setattr(verify.tabs, "addon_seen", lambda dirs: states[dirs[0]])
    targets = [SimpleNamespace(profile_name="Has", profile_dir="/ff/p1"),
               SimpleNamespace(profile_name="NoAddon", profile_dir="/ff/p2"),
               SimpleNamespace(profile_name="NoAddon", profile_dir="/ff/p2"),  # once per dir
               SimpleNamespace(profile_name="Dark", profile_dir="/ff/p3"),
               SimpleNamespace(profile_name="", profile_dir="")]
    verify.warn_addonless_profiles(targets, lambda s, m, level="info": rows.append((s, m, level)))
    assert len(rows) == 1
    step, message, level = rows[0]
    assert step == "detect" and level == "warn"
    assert "NoAddon" in message and "extensions.json" in message and "#204" in message


def test_addonless_warn_survives_no_targets():
    verify.warn_addonless_profiles(None, lambda *a: (_ for _ in ()).throw(AssertionError()))
    verify.warn_addonless_profiles([], lambda *a: (_ for _ in ()).throw(AssertionError()))
