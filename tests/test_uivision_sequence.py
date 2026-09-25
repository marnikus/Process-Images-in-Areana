"""The sequence's real-path re-checks — re-read before launch, verify the handoff.

The two refusals are different answers (RULE 4): a target that vanished before
its launch is `blocked` WITHOUT aborting (move on to the next profile); a
launch refusal or a mis-routed handoff sets `abort_rest` (the same condition
would bite every later run). The OS re-checks only run when no seam stands in
for the stores — here `tabs.*` are monkeypatched, the seam stays real.
"""

from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from app.browser.uivision import logread, plan, sequence, tabs
from app.browser.uivision import runner as runner_mod
from app.browser.uivision.runner import RunSeams, RunSpec

pytestmark = pytest.mark.unit

OK_LOG = "Status=OK\n###\necho: done — XClick fired (native OS input)"

# The E212 the owner's runs ended with: the pinned cleanup pair's selectWindow
# matched no tab. The work commands (tab select, XClick, echo) all preceded it
# and succeeded — the macro stops at its first failure.
MISS_LOG = ("Status=Error: E212: failed to find the tab with locator "
            "'title=*Ui.Vision Autostart Page*'\n###\n"
            "echo: done — XClick fired (native OS input)")

# A REAL work failure: the not-found names the run's own tab locator, not the
# cleanup pair's — the click never happened and the error must stay an error.
USER_TAB_MISS_LOG = ("Status=Error: E212: failed to find the tab with locator "
                     "'title=*Tab A*'\n###\n[selectWindow] no match")


def make_spec(tmp_path, **over):
    kw = dict(pattern="", url_pattern="arena.ai", target="css=#go",
              macro="Python_XClick_Demo", storage="xfile", home="",
              binary=str(tmp_path / "firefox"), timeout_sec=30, pause_ms=1500,
              config_dir=str(tmp_path / "config"))
    kw.update(over)
    return RunSpec(**kw)


def make_runs(tmp_path, names, stamp="S"):
    """One target per profile — the planner's per-profile model."""
    targets = [plan.Target(profile_name=name, profile_dir=f"/ff/{name.lower()}",
                           url=f"https://arena.ai/{name.lower()}/1",
                           title=f"Tab {name}") for name in names]
    return plan.runs(targets, plan.Search("", "arena.ai"), tmp_path / "config", stamp)


def make_sequence(tmp_path, spec, seams):
    """A Sequence with a steps-collecting recorder → (sequence, report rows)."""
    rows = []
    recorder = runner_mod._Recorder(lambda step, message, level="info":
                                    rows.append((step, message, level)))
    seq = sequence.Sequence(spec, seams, recorder)
    seq.page = str(tmp_path / "ui.vision.html")
    return seq, rows


def fake_popen():
    calls = []
    return calls, (lambda argv: calls.append(argv) or SimpleNamespace(pid=42))


def write_log(tmp_path, name, text=OK_LOG):
    log = tmp_path / "config" / "uivision" / "logs" / name
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(text, encoding="utf-8")


async def noop_sleep(_sec):
    pass


def rows_for(url, title):
    return [{"url": url, "title": title}]


# ── the fresh-locator re-check (real path only) ──────────────────────────────

async def test_profile_closed_before_launch_is_skipped_and_the_rest_continues(
        tmp_path, monkeypatch):
    """A vanished target is skipped (no launch) — the NEXT profile still runs."""
    (tmp_path / "firefox").write_text("#!/bin/sh\n")
    write_log(tmp_path, "run-S-2.txt")
    runs = make_runs(tmp_path, ["A", "B"])
    monkeypatch.setattr(tabs, "profile_open",
                        lambda d, checker=None: (d == "/ff/b", ""))
    monkeypatch.setattr(tabs, "tab_rows",
                        lambda profiles: rows_for(runs[1].target.url, "Tab B"))
    calls, popen = fake_popen()
    seq, rows = make_sequence(tmp_path, make_spec(tmp_path),
                              RunSeams(sleep=noop_sleep, popen=popen,
                                       handoff_window_sec=0.0))
    outcome = await seq.execute(runs)
    assert outcome.kind == "blocked"                          # the skip is the roll-up
    assert "not running any more" in outcome.message
    assert len(calls) == 1                                    # only run 2 launched
    assert calls[0][1:3] == ["-P", "B"]
    assert any(step == "launch" and "skipped (nothing launched)" in msg
               for step, msg, _lvl in rows)


async def test_tab_gone_or_titleless_is_skipped_without_a_launch(tmp_path, monkeypatch):
    (tmp_path / "firefox").write_text("#!/bin/sh\n")
    runs = make_runs(tmp_path, ["A"])
    monkeypatch.setattr(tabs, "profile_open", lambda d, checker=None: (True, ""))
    monkeypatch.setattr(tabs, "tab_rows", lambda profiles: [])   # the row is gone
    calls, popen = fake_popen()
    seq, _rows = make_sequence(tmp_path, make_spec(tmp_path),
                               RunSeams(sleep=noop_sleep, popen=popen))
    outcome = await seq.execute(runs)
    assert outcome.kind == "blocked"
    assert "no usable title" in outcome.message
    assert calls == []                                        # nothing was launched


async def test_renamed_tab_rebuilds_the_selector_from_the_fresh_title(
        tmp_path, monkeypatch):
    """The launch-time re-read: a changed title rebuilds cmd_var3 from the NEW title."""
    (tmp_path / "firefox").write_text("#!/bin/sh\n")
    write_log(tmp_path, "run-S.txt")
    runs = make_runs(tmp_path, ["A"])
    fresh = "Renamed Tab"
    monkeypatch.setattr(tabs, "profile_open", lambda d, checker=None: (True, ""))
    monkeypatch.setattr(tabs, "tab_rows", lambda profiles: rows_for(runs[0].target.url, fresh))
    calls, popen = fake_popen()
    seq, rows = make_sequence(tmp_path, make_spec(tmp_path),
                              RunSeams(sleep=noop_sleep, popen=popen,
                                       handoff_window_sec=0.0))
    outcome = await seq.execute(runs)
    assert outcome.kind == "ok"
    assert runs[0].selector == "title=*Renamed Tab*"          # rebuilt in place
    assert parse_qs(urlsplit(calls[0][-1]).query)["cmd_var3"] == ["title=*Renamed Tab*"]
    assert any("locator was rebuilt" in msg for _step, msg, _lvl in rows)


# ── the handoff verification (real path only) ────────────────────────────────

async def test_handoff_misroute_names_both_profiles_and_aborts_the_rest(
        tmp_path, monkeypatch):
    """The autorun tab in ANOTHER profile: named, error, and the rest is not attempted."""
    (tmp_path / "firefox").write_text("#!/bin/sh\n")
    runs = make_runs(tmp_path, ["A", "B"])
    monkeypatch.setattr(tabs, "profile_open", lambda d, checker=None: (True, ""))
    monkeypatch.setattr(tabs, "tab_rows",
                        lambda profiles: rows_for(runs[0].target.url, "Tab A"))
    monkeypatch.setattr(tabs, "autorun_tab_seen", lambda profiles=None, checker=None:
                        {"/ff/zz": True})                     # the marker in a third profile
    calls, popen = fake_popen()
    seq, rows = make_sequence(tmp_path, make_spec(tmp_path),
                              RunSeams(sleep=noop_sleep, popen=popen,
                                       handoff_window_sec=1.0))
    outcome = await seq.execute(runs)
    assert outcome.kind == "error"
    assert 'profile “A”' in outcome.message and 'profile “zz”' in outcome.message
    assert "duplicate" in outcome.message and "Name=" in outcome.message
    assert len(calls) == 1                                    # run 2 was never attempted
    assert any(step == "handoff" and lvl == "error" for step, _msg, lvl in rows)


async def test_handoff_marker_in_the_target_profile_proceeds(tmp_path, monkeypatch):
    (tmp_path / "firefox").write_text("#!/bin/sh\n")
    write_log(tmp_path, "run-S.txt")
    runs = make_runs(tmp_path, ["A"])
    monkeypatch.setattr(tabs, "profile_open", lambda d, checker=None: (True, ""))
    monkeypatch.setattr(tabs, "tab_rows",
                        lambda profiles: rows_for(runs[0].target.url, "Tab A"))
    monkeypatch.setattr(tabs, "autorun_tab_seen", lambda profiles=None, checker=None:
                        {"/ff/a": True})                      # the marker where it belongs
    calls, popen = fake_popen()
    seq, _rows = make_sequence(tmp_path, make_spec(tmp_path),
                               RunSeams(sleep=noop_sleep, popen=popen,
                                        handoff_window_sec=1.0))
    outcome = await seq.execute(runs)
    assert outcome.kind == "ok" and len(calls) == 1


async def test_handoff_with_no_marker_in_the_window_defers_to_the_savelog(
        tmp_path, monkeypatch):
    """Window expires with the marker nowhere: no error — the savelog is the verdict."""
    (tmp_path / "firefox").write_text("#!/bin/sh\n")
    write_log(tmp_path, "run-S.txt")
    runs = make_runs(tmp_path, ["A"])
    monkeypatch.setattr(tabs, "profile_open", lambda d, checker=None: (True, ""))
    monkeypatch.setattr(tabs, "tab_rows",
                        lambda profiles: rows_for(runs[0].target.url, "Tab A"))
    monkeypatch.setattr(tabs, "autorun_tab_seen", lambda profiles=None, checker=None: {})
    calls, popen = fake_popen()
    seq, _rows = make_sequence(tmp_path, make_spec(tmp_path),
                               RunSeams(sleep=noop_sleep, popen=popen,
                                        handoff_window_sec=0.0))
    outcome = await seq.execute(runs)
    assert outcome.kind == "ok" and len(calls) == 1


async def test_handoff_sleep_glitch_is_swallowed(tmp_path, monkeypatch):
    """A glitching injected sleep in the handoff window must not cancel the run."""
    (tmp_path / "firefox").write_text("#!/bin/sh\n")
    write_log(tmp_path, "run-S.txt")
    runs = make_runs(tmp_path, ["A"])

    async def bad_sleep(sec):
        raise ValueError("boom")

    monkeypatch.setattr(tabs, "profile_open", lambda d, checker=None: (True, ""))
    monkeypatch.setattr(tabs, "tab_rows",
                        lambda profiles: rows_for(runs[0].target.url, "Tab A"))
    monkeypatch.setattr(tabs, "autorun_tab_seen", lambda profiles=None, checker=None:
                        {"/ff/a": True})                     # found on the first (glitched) tick
    calls, popen = fake_popen()
    seq, _rows = make_sequence(tmp_path, make_spec(tmp_path),
                               RunSeams(sleep=bad_sleep, popen=popen,
                                        handoff_window_sec=1.0))
    outcome = await seq.execute(runs)
    assert outcome.kind == "ok" and len(calls) == 1


# ── the inter-run delay ──────────────────────────────────────────────────────

def two_profile_sessions(names):
    return [{"name": n, "dir": f"/ff/{n.lower()}", "rows": [
        {"url": f"https://arena.ai/{n.lower()}/1", "title": f"Tab {n}"}],
        "windows": [], "source": "", "stamp": 1.0} for n in names]


async def test_inter_run_delay_zero_skips_the_wait(tmp_path):
    """inter_run_delay_sec=0: no wait line, no sleep — the second run goes right away."""
    (tmp_path / "firefox").write_text("#!/bin/sh\n")
    write_log(tmp_path, "run-S.txt")
    write_log(tmp_path, "run-S-2.txt")
    runs = make_runs(tmp_path, ["A", "B"])
    sleeps = []

    async def spy_sleep(sec):
        sleeps.append(sec)

    calls, popen = fake_popen()
    spec = make_spec(tmp_path, inter_run_delay_sec=0)
    seq, rows = make_sequence(tmp_path, spec, RunSeams(
        sleep=spy_sleep, popen=popen, profiles=lambda: two_profile_sessions(["A", "B"])))
    outcome = await seq.execute(runs)
    assert outcome.kind == "ok" and len(calls) == 2
    assert sleeps == [] and not any(step == "delay" for step, _m, _l in rows)


async def test_inter_run_delay_glitch_is_swallowed(tmp_path):
    """A glitching sleep between runs must not kill the sequence — run 2 still runs."""
    (tmp_path / "firefox").write_text("#!/bin/sh\n")
    write_log(tmp_path, "run-S.txt")
    write_log(tmp_path, "run-S-2.txt")
    runs = make_runs(tmp_path, ["A", "B"])

    async def bad_sleep(sec):
        raise ValueError("boom")

    calls, popen = fake_popen()
    seq, _rows = make_sequence(tmp_path, make_spec(tmp_path), RunSeams(
        sleep=bad_sleep, popen=popen, profiles=lambda: two_profile_sessions(["A", "B"])))
    outcome = await seq.execute(runs)
    assert outcome.kind == "ok" and len(calls) == 2

# ── the cleanup-pair miss is rescored (the work succeeded, the tab lingers) ──

async def test_cleanup_miss_is_rescored_ok_with_the_miss_named(tmp_path, monkeypatch):
    """E212 on the pinned autostart-tab locator: the click fired, the macro's
    own tab-close missed its tab — ok, with the backstop named, lines kept."""
    (tmp_path / "firefox").write_text("#!/bin/sh\n")
    write_log(tmp_path, "run-S.txt", MISS_LOG)
    runs = make_runs(tmp_path, ["A"])
    monkeypatch.setattr(tabs, "profile_open", lambda d, checker=None: (True, ""))
    monkeypatch.setattr(tabs, "tab_rows",
                        lambda profiles: rows_for(runs[0].target.url, "Tab A"))
    calls, popen = fake_popen()
    seq, _rows = make_sequence(tmp_path, make_spec(tmp_path),
                               RunSeams(sleep=noop_sleep, popen=popen,
                                        handoff_window_sec=0.0))
    outcome = await seq.execute(runs)
    assert outcome.kind == "ok"
    assert "XClick fired" in outcome.message and "backstop" in outcome.message
    assert any("XClick fired" in line for line in outcome.lines)  # the savelog shows


async def test_cleanup_miss_rolls_up_ok_across_runs(tmp_path):
    """Both runs end with the cleanup miss: the sequence answers all ok."""
    (tmp_path / "firefox").write_text("#!/bin/sh\n")
    write_log(tmp_path, "run-S.txt", MISS_LOG)
    write_log(tmp_path, "run-S-2.txt", MISS_LOG)
    runs = make_runs(tmp_path, ["A", "B"])
    calls, popen = fake_popen()
    seq, _rows = make_sequence(tmp_path, make_spec(tmp_path), RunSeams(
        sleep=noop_sleep, popen=popen, profiles=lambda: two_profile_sessions(["A", "B"])))
    outcome = await seq.execute(runs)
    assert outcome.kind == "ok" and "all 2 run(s) ok" in outcome.message
    assert len(calls) == 2


async def test_a_miss_on_the_run_tab_stays_an_error(tmp_path, monkeypatch):
    """The not-found names the RUN's tab locator — the click never happened."""
    (tmp_path / "firefox").write_text("#!/bin/sh\n")
    write_log(tmp_path, "run-S.txt", USER_TAB_MISS_LOG)
    runs = make_runs(tmp_path, ["A"])
    monkeypatch.setattr(tabs, "profile_open", lambda d, checker=None: (True, ""))
    monkeypatch.setattr(tabs, "tab_rows",
                        lambda profiles: rows_for(runs[0].target.url, "Tab A"))
    calls, popen = fake_popen()
    seq, _rows = make_sequence(tmp_path, make_spec(tmp_path),
                               RunSeams(sleep=noop_sleep, popen=popen,
                                        handoff_window_sec=0.0))
    outcome = await seq.execute(runs)
    assert outcome.kind == "error"
    assert "Tab A" in outcome.message


# ── rescore_cleanup_miss unit (the seams above cover the wiring) ─────────────

def test_rescore_passes_everything_but_the_cleanup_miss_through():
    ok = logread.LogResult(kind="ok", message="macro completed")
    timed = logread.LogResult(kind="timeout", message="no status line")
    dom = logread.LogResult(kind="error", message="E225: DOM failed to be ready in 30sec.")
    assert sequence.rescore_cleanup_miss(ok) is ok
    assert sequence.rescore_cleanup_miss(timed) is timed
    assert sequence.rescore_cleanup_miss(dom) is dom


def test_rescore_handles_the_E210_wording_too():
    """V9's original code (E210) carries the same wording — rescored as well."""
    err = logread.LogResult(
        kind="error",
        message="E210: failed to find the tab with locator "
                "'title=*Ui.Vision Autostart Page*'")
    got = sequence.rescore_cleanup_miss(err)
    assert got.kind == "ok" and got.abort_rest is False
