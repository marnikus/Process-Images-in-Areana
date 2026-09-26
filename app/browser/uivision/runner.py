"""One framework-test run: detect → provision → plan → execute.

No Qt and no bridge in here — the runner is browser-layer mechanics with
injected seams (report callback, stop predicate, sleep/Popen), which the panel
wires to `bridge._log` + the `firefox_auto_updated` signal (RULE 2/5) and to
the window's Stop button (RULE 7: the predicate is checked before every phase,
before every planned run and inside the poll — `sequence.py` owns the loop).

Multi-profile (2026-09-23, owner fix): the detect phase reads EVERY open
Firefox profile's session store, the plan targets EVERY tab matching the
pattern, and each target is one macro run aimed at its own profile instance
(`-P name`, or `-profile dir` when the profile has no ini name — `plan.py`
renders them). One run per open profile (2026-09-24 first-run fix): the first
matching tab of each profile is the run's target, extra matches are reported
but never re-run a profile. Runs execute in order, each with its own savelog;
a single run behaves exactly as before (the OS handoff, the pattern glob,
`run-<stamp>.txt`). Profiles that are closed on disk are skipped — the lock
probe (`profiles.open_sessions`) decides "open", never file freshness.

Outcome kinds are distinct answers, never one invented "failed" (RULE 4):
`ok` / `error` are the extension's own verdicts from the savelog file,
`timeout` means the file never answered, `stopped` means the user stopped,
`blocked` means the run never started (bad macro name, missing Firefox, …).
"""

# ideal-size: ~490 lines reason=detect/report half + provision + wait-for-tab phase +
# orchestration of the uivision package; the executor lives in sequence.py, the planner
# in plan.py, the profile filter in profiles.py, and every function stays within the
# RULE 18 band (max ~20 lines).

from __future__ import annotations

import time
from dataclasses import dataclass

from . import autorun, desktop, macro, paths, plan, profiles, tabs
from .sequence import RunResult, Sequence


@dataclass(frozen=True)
class RunSpec:
    """One validated run: the window's config + where the app's files live.

    There is no URL field: the macro reuses the run's tab and never opens a
    page (2026-09-23, owner rule) — the pattern IS the navigation.
    """

    pattern: str
    target: str
    macro: str
    storage: str          # "xfile" (hard drive) or "browser" (import once in the extension)
    home: str             # XModule home folder ('' = the extension's default)
    binary: str           # Firefox binary ('' = this OS's default)
    timeout_sec: int
    pause_ms: int         # the macro's wait + confirmation-rect budget (ms)
    config_dir: str
    url_pattern: str = ""  # tab-URL substring ('' = any URL); appended last so positional
                           # constructors survive (the I-53 corollary pattern)
    selected_profiles: tuple = ()  # profile dirs checked in the UI (() = every profile)
    skip_no_match: bool = False   # True = skip profiles with no matching tabs; False = wait
    wait_timeout_sec: int = 60    # when skip_no_match is off, seconds to wait for a tab (10…300)
    inter_run_delay_sec: int = 3  # seconds to wait between runs (gives Firefox time to process)


@dataclass(frozen=True)
class RunSeams:
    """The injected boundaries — defaults are the real ones."""

    stop: object = None       # callable → True when the user pressed Stop
    sleep: object = None      # async sleep (tests shorten the poll)
    popen: object = None      # subprocess factory (tests fake the launch)
    tabs: object = None       # callable → open-tab rows (tests fake the store)
    addon: object = None      # callable → extension-seen tri-state
    probe: object = None      # callable → desktop-module-listening bool
    windows: object = None    # callable → per-window session rows (tests fake them)
    profiles: object = None   # callable → per-profile session rows (tests fake them)


class Recorder:
    """Collects the reported steps so the result can carry them (one mutable box)."""

    def __init__(self, report):
        self._report = report
        self.steps: list = []

    def __call__(self, step: str, message: str, level: str = "info") -> None:
        self.steps.append((step, message))
        self._report(step, message, level)


def _patterns(spec: RunSpec) -> plan.Patterns:
    """The spec's two tab filters as one value — threaded through plan and macro."""
    return plan.Patterns(spec.pattern, spec.url_pattern)


def macro_target(spec: RunSpec):
    """Where the macro JSON is written: the XModule home, or the import artefact."""
    if spec.storage == "xfile":
        return paths.macro_file(paths.home(spec.home), spec.macro)
    return paths.runtime_dir(spec.config_dir) / paths.MACROS_DIR / f"{spec.macro}.json"


def _provision(spec: RunSpec, report) -> object:
    """Write the macro + the autorun page; returns the page path.

    The macro file is written once and shared by every planned run — per-run
    values (selector, pause budget) ride `cmd_var1..3`, never the file.
    """
    paths.logs_dir(spec.config_dir).mkdir(parents=True, exist_ok=True)
    target = macro_target(spec)
    target.parent.mkdir(parents=True, exist_ok=True)
    document = macro.build_macro(spec.macro, _patterns(spec))
    target.write_text(macro.to_json(document), encoding="utf-8")
    report("provision", f"macro written: {target}")
    if spec.storage == "xfile":
        report("provision", f"the extension’s own Home directory (Ui.Vision Settings → "
                            f"Setup XModules2) must be “{spec.home or '<Desktop>/uivision'}” "
                            f"in hard-drive mode, or it looks for the macro elsewhere")
    if spec.storage != "xfile":
        report("provision", "storage=browser: import this macro ONCE in the Ui.Vision UI "
                            "(Macros tab → Import) — the browser cannot read it from disk",
               "warn")
    page = autorun.write_page(paths.autorun_file(spec.config_dir))
    report("provision", f"autorun page ready: {page}")
    return page


TAB_LOG_CAP = 50


def _report_tab_rows(rows, report) -> None:
    """One detect line per open tab (capped) — the owner wants the whole list."""
    for pos, row in enumerate(rows[:TAB_LOG_CAP], 1):
        report("detect", f"firefox tab {pos}: {row['url'][:110]} — {row['title'][:40]}")
    if len(rows) > TAB_LOG_CAP:
        report("detect", f"+{len(rows) - TAB_LOG_CAP} more open tab(s)")


def _report_matches(targets, spec: RunSpec, structured: bool, report) -> None:
    """The search's verdict: every matching tab, or why the macro cannot find one."""
    if not targets:
        _report_no_matches(spec, report)
        return
    if not structured:
        report("detect", f"search {plan.describe_search(_patterns(spec))} "
                         f"matches {len(targets)} open tab(s):")
        for pos, target in enumerate(targets, 1):
            report("detect", f"match {pos}: {target.url[:110]}")
        return
    profiles = sorted({plan.profile_label(t.profile_name, t.profile_dir) or "?"
                       for t in targets})
    report("detect", f"search {plan.describe_search(_patterns(spec))} — "
                     f"{len(targets)} open tab(s) match in {len(profiles)} profile(s): "
                     f"{', '.join(profiles)}")
    for pos, target in enumerate(targets, 1):
        where = plan.profile_label(target.profile_name, target.profile_dir) or "?"
        report("detect", f"match {pos}: {target.url[:110]} — {target.title[:40]} "
                         f'(profile “{where}”)')


def _report_no_matches(spec: RunSpec, report) -> None:
    """Why nothing matches: the search's own phrase, or a silent store + no filters."""
    search = plan.describe_search(_patterns(spec))
    if search == plan.ANY_TAB:
        report("detect", "no session store readable and both patterns are empty — "
                         "nothing to search", "warn")
        return
    report("detect", f"no OPEN tab matches {search} in any Firefox profile — the "
                     f"macro will NOT open anything and will fail (E210): open the "
                     f"page in the matching Firefox first", "warn")


def _report_plan(targets, spec: RunSpec, structured: bool, report) -> None:
    """The run-plan lines: what will actually run (one per profile) + the blank warning."""
    if len(targets) >= 2:
        report("detect", f"run plan: {plan.summarize(targets, structured)}")
    _report_blank_search(targets, spec, report)


def _report_blank_search(targets, spec: RunSpec, report) -> None:
    """Both patterns blank means EVERY open profile runs once — never quietly (RULE 4)."""
    if (spec.pattern or "").strip() or (spec.url_pattern or "").strip():
        return
    report("detect", f"both patterns are empty — the macro will run once per open "
                     f"profile ({len(targets)} run(s)); set a title or URL pattern "
                     f"to narrow the search", "warn")



def _load_profiles(seams: RunSeams) -> list:
    """Per-profile sessions: the profiles seam, the flat tabs seam, or the OPEN stores."""
    if seams.profiles is not None:
        return seams.profiles()
    if seams.tabs is not None:
        return [plan.anonymous_session(seams.tabs())]
    return profiles.open_sessions(tabs.profile_sessions())


def _report_profiles(report) -> None:
    """Open profiles by name, plus how many closed ones were skipped (bug #4)."""
    names = [path.name for path in tabs.open_profile_dirs()]
    closed = len(tabs.profile_dirs()) - len(names)
    quiet = f" ({', '.join(names[:6])})" if names else " (is Firefox installed?)"
    note = f" — {closed} closed profile(s) skipped" if closed > 0 else ""
    report("detect", f"firefox profiles scanned: {len(names)}{quiet}{note}")


def _report_source(sessions, report) -> None:
    """Which session file fed the rows — the freshest profile's own receipt."""
    freshest = max(sessions, key=lambda session: session.get("stamp", -1.0), default=None)
    if freshest and freshest.get("source"):
        report("detect", f"session source: {freshest['source']} in "
                         f"{freshest.get('name') or freshest.get('dir', '')}")


def _report_windows(sessions, seams: RunSeams, report) -> None:
    """One line per session window: its tabs and the active (OS-title) one.

    The `windows` seam (a test fake, one unnamed browser) keeps the plain
    format; the per-profile sessions carry their profile in the line.
    """
    if seams.windows is not None:
        for window in seams.windows() or []:
            _report_window(window, "", report)
        return
    for session in sessions or []:
        _report_profile_windows(session, report)


def _report_profile_windows(session, report) -> None:
    """One profile's windows, its profile named in every line."""
    where = plan.profile_label(session.get("name", ""), session.get("dir", ""))
    for window in session.get("windows") or []:
        _report_window(window, f' (profile “{where}”)' if where else "", report)


def _report_window(window, suffix: str, report) -> None:
    """One window line: index, profile, tab count, the active tab's title."""
    active = (window.get("active") or {}).get("title", "")
    report("detect", f"firefox window {window.get('index', '?')}{suffix}: "
                     f"{len(window.get('tabs', []))} tab(s) — active “{active[:60]}”")


def os_is_windows() -> bool:
    """One named predicate keeps the detect line readable (RULE 18)."""
    import os
    return os.name == "nt"


def _addon_line(addon) -> tuple:
    """(message, level) naming the extension check's three answers."""
    if addon is True:
        return "Ui.Vision extension: installed in the Firefox profile", "info"
    if addon is False:
        return ("Ui.Vision extension NOT found in any Firefox profile — install "
                "the add-on and switch on ‘Allow access to file URLs’", "warn")
    return "Ui.Vision extension: unknown (no Firefox profile readable)", "warn"


def _detect_plugin(report, seams: RunSeams) -> None:
    """Extension in the profile + the native-input module on its port."""
    addon = seams.addon() if seams.addon else tabs.addon_seen()
    message, level = _addon_line(addon)
    report("detect", message, level)
    live = seams.probe() if seams.probe else desktop.desktop_module_listening()
    if live:
        report("detect", f"Desktop Automation module (XClick’s native input): listening on "
                         f"127.0.0.1:{desktop.DESKTOP_APP_PORT}", "success")
    else:
        report("detect", f"Desktop Automation module NOT listening on 127.0.0.1:"
                         f"{desktop.DESKTOP_APP_PORT} — install ‘Ui.Vision for Desktop’ "
                         f"(XModules) or XClick cannot fire", "warn")


def _report_open_tabs(sessions, real: bool, recorder: Recorder) -> None:
    """The flat tab list across every profile + the freshest store's receipt."""
    rows = [row for session in sessions for row in session["rows"]]
    quiet = "" if rows else " (no session store readable — is Firefox running?)"
    recorder("detect", f"firefox open tabs seen: {len(rows)}{quiet}")
    if real and rows:
        _report_source(sessions, recorder)
    _report_tab_rows(rows, recorder)


def _detect_phase(spec: RunSpec, recorder: Recorder, seams: RunSeams) -> list:
    """The pre-run eyes: EVERY open profile's tabs, the matches, ONE run per profile."""
    sessions = _load_profiles(seams)
    real = seams.tabs is None and seams.profiles is None
    structured = real or seams.profiles is not None
    targets = plan.plan_targets(sessions, _patterns(spec))
    targets = _apply_profile_filter(targets, spec, sessions, recorder)
    targets = _drop_unaddressable(targets, spec, recorder)
    planned = plan.one_per_profile(targets)       # one run per open profile (bug #3)
    if real:
        _report_profiles(recorder)
    _report_open_tabs(sessions, real, recorder)
    _report_matches(targets, spec, structured, recorder)
    _report_windows(sessions, seams, recorder)
    _report_plan(planned, spec, structured, recorder)
    wins = desktop.find_windows(spec.pattern)
    note = "" if wins or os_is_windows() else " (window listing is Windows-only)"
    recorder("detect", f"firefox windows matching the pattern: {len(wins)}{note}")
    _detect_plugin(recorder, seams)
    return planned


def _drop_unaddressable(targets, spec: RunSpec, recorder: Recorder) -> list:
    """Warn per titleless match and keep only tabs the macro can actually select."""
    addressable, titleless = plan.split_unaddressable(targets, _patterns(spec))
    for target in titleless:
        recorder("detect", f"tab {target.url[:90]} matched but has no TITLE — "
                           f"selectWindow can only pick a tab by title; open the page "
                           f"so Firefox gives it one, or it cannot run", "warn")
    return addressable


def _apply_profile_filter(targets, spec: RunSpec, sessions, recorder: Recorder) -> list:
    """Keep only targets in selected profiles; skip or warn per unmatched one."""
    selected = list(spec.selected_profiles or ())
    kept = profiles.filter_targets(targets, selected)
    dropped = len(targets or []) - len(kept)
    if dropped:
        recorder("detect", f"profile filter: {dropped} tab(s) dropped — only "
                           f"{len(profiles.selected_set(selected))} selected profile(s) run")
    unmatched = profiles.unmatched_profiles(sessions, kept, selected)
    for name in unmatched:
        _report_unmatched_profile(name, spec.skip_no_match, spec.wait_timeout_sec, recorder)
    return kept


def _report_unmatched_profile(name: str, skip: bool, wait_sec: int, recorder: Recorder) -> None:
    """One profile with no matching tabs — skip (move on) or wait (warn)."""
    if skip:
        recorder("detect", f'profile "{name}": no matching tab — skipped (skip_no_match)', "warn")
    else:
        recorder("detect", f'profile "{name}": no matching tab — waiting up to {wait_sec}s '
                           f"for the user to open one", "warn")


def _stopped(seams: RunSeams) -> bool:
    return bool(seams.stop and seams.stop())


def _result(kind: str, message: str, recorder: Recorder, lines: tuple = ()) -> RunResult:
    return RunResult(kind=kind, message=message, steps=tuple(recorder.steps), lines=lines)


def _blocked_no_search(recorder: Recorder) -> RunResult:
    """Both patterns blank and no readable tab: nothing to search, nothing opened."""
    recorder("launch", "no tab-title and no URL pattern set (and no open tab readable) "
                       "— the macro finds the run's tab by title or URL and never "
                       "opens a page: set a pattern first", "error")
    return _result("blocked", "no tab-title and no URL pattern — nothing to search, "
                              "nothing opened", recorder)


def _blocked_no_url_match(recorder: Recorder, url_pattern: str) -> RunResult:
    """URL-only search with no match: the fallback selector needs a title pattern."""
    recorder("launch", f"URL “{url_pattern}” matched no open tab in any profile's "
                       f"session store — the macro selects tabs by TITLE, so open the "
                       f"page (Firefox then knows the tab) or add a title pattern",
             "error")
    return _result("blocked", f"URL “{url_pattern}” matched no open tab — and a "
                              f"URL-only search cannot select a tab without its "
                              f"title", recorder)


def _fallback_or_block(spec: RunSpec, recorder: Recorder, targets: list):
    """The no-match decision: None to continue, or the block that names why.

    A title pattern still buys today's fallback single run (its title glob,
    E210 in the extension if no tab); a URL-only search cannot build one.
    When `skip_no_match` is on and every selected profile had zero matching
    tabs, the run ends cleanly as `blocked` with a skip message instead of
    the generic "no tab" error (RULE 4: name the cause).
    """
    if targets:
        return None
    if spec.skip_no_match and spec.selected_profiles:
        recorder("launch", "every selected profile had no matching tab — all skipped "
                           "(skip_no_match is on)", "warn")
        return _result("blocked", "all selected profiles skipped — no matching tab "
                                  "in any selected profile", recorder)
    title = (spec.pattern or "").strip()
    url = (spec.url_pattern or "").strip()
    if not title and not url:
        return _blocked_no_search(recorder)
    if not title:
        return _blocked_no_url_match(recorder, url)
    return None


# ── wait for unmatched profiles (skip_no_match off) ──────────────────────────

async def _wait_for_unmatched(spec: RunSpec, seams: RunSeams,
                              recorder: Recorder, targets: list) -> list:
    """Poll unmatched profiles for a matching tab; skip after timeout (RULE 7).

    Only waits when the user has explicitly selected profiles — anonymous
    sessions (the flat `tabs` seam, or a blank selection with no profiles
    seam) never wait, because there is no profile to poll.
    """
    if spec.skip_no_match:
        return targets
    selected = list(spec.selected_profiles or ())
    if not selected:
        return targets                       # no explicit profile selection → no wait
    sessions = _load_profiles(seams)
    unmatched = profiles.unmatched_profiles(sessions, targets, selected)
    if not unmatched:
        return targets
    sleep_fn = seams.sleep or _default_sleep
    timeout = max(10, min(300, spec.wait_timeout_sec))
    for name in unmatched:
        targets = await _poll_one_profile(name, spec, timeout, sleep_fn,
                                          seams, recorder, targets)
        if _stopped(seams):
            break
    return targets


async def _poll_one_profile(name, spec, timeout, sleep_fn, seams, recorder, targets):
    """Poll one profile every 5s until a tab appears or timeout expires."""
    deadline = time.time() + timeout
    recorder("wait", f'waiting for a matching tab in "{name}" '
                     f"(timeout {timeout}s — open the page in Firefox)", "info")
    while time.time() < deadline and not _stopped(seams):
        await _safe_sleep(sleep_fn, min(5, max(1, deadline - time.time())))
        found = _find_new_targets(_load_profiles(seams), name, spec)
        if found:
            recorder("wait", f'"{name}": {len(found)} matching tab(s) appeared', "success")
            return targets + plan.one_per_profile(found)   # still one run per profile
    recorder("wait", f'"{name}": no matching tab after {timeout}s — skipped', "warn")
    return targets


async def _safe_sleep(sleep_fn, seconds: float) -> None:
    """Run the injected sleep, swallowing non-cancellation errors."""
    import asyncio
    try:
        await sleep_fn(seconds)
    except asyncio.CancelledError:
        raise
    except Exception:
        pass


def _find_new_targets(sessions: list, profile_name: str, spec: RunSpec) -> list:
    """Re-scan one profile by label for matching tabs ([] when still empty)."""
    for session in sessions or []:
        label = plan.profile_label(session.get("name", ""), session.get("dir", ""))
        if label != profile_name:
            continue
        windows = tuple(session.get("windows") or ())
        found = []
        for row in session.get("rows") or []:
            if plan.matches(str(row.get("title", "")), str(row.get("url", "")),
                            _patterns(spec)):
                found.append(plan.Target(
                    profile_name=str(session.get("name", "")),
                    profile_dir=str(session.get("dir", "")),
                    url=str(row.get("url", "")),
                    title=str(row.get("title", "")),
                    windows=windows))
        return found
    return []


async def _default_sleep(seconds: float) -> None:
    """Real async sleep — the seam's default (tests inject a fast one)."""
    import asyncio
    await asyncio.sleep(seconds)


async def run_test(spec: RunSpec, report, seams: RunSeams = None) -> RunResult:
    """One framework test end to end; every phase reports through `report`."""
    seams = seams or RunSeams()
    recorder = Recorder(report)
    targets = _detect_phase(spec, recorder, seams)
    if _stopped(seams):
        return _result("stopped", "stopped before the run began", recorder)
    targets = await _wait_for_unmatched(spec, seams, recorder, targets)
    blocked = _fallback_or_block(spec, recorder, targets)
    if blocked is not None:
        return blocked
    try:
        page = _provision(spec, recorder)
    except (ValueError, OSError) as exc:
        recorder("provision", f"cannot prepare the run: {exc}", "error")
        return _result("blocked", str(exc), recorder)
    if not targets:
        targets = [plan.Target()]          # today's single run: the OS handoff decides
    runs = plan.runs(targets, _patterns(spec), spec.config_dir,
                     time.strftime("%Y%m%d-%H%M%S"))
    executor = Sequence(spec, seams, recorder)
    executor.page = str(page)
    return await executor.execute(runs)
