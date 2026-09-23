"""One framework-test run: detect → provision → plan → execute.

No Qt and no bridge in here — the runner is browser-layer mechanics with
injected seams (report callback, stop predicate, sleep/Popen), which the panel
wires to `bridge._log` + the `firefox_auto_updated` signal (RULE 2/5) and to
the window's Stop button (RULE 7: the predicate is checked before every phase,
before every planned run and inside the poll — `sequence.py` owns the loop).

Multi-profile (2026-09-23, owner fix): the detect phase reads EVERY Firefox
profile's session store, the plan targets EVERY tab matching the pattern, and
each target is one macro run aimed at its own profile instance (`-P name`, or
`-profile dir` when the profile has no ini name — `plan.py` renders them). Runs
execute in order, each with its own savelog; a single run behaves exactly as
before (the OS handoff, the pattern glob, `run-<stamp>.txt`).

Outcome kinds are distinct answers, never one invented "failed" (RULE 4):
`ok` / `error` are the extension's own verdicts from the savelog file,
`timeout` means the file never answered, `stopped` means the user stopped,
`blocked` means the run never started (bad macro name, missing Firefox, …).
"""

# ideal-size: ~320 lines reason=detect/report half + provision + orchestration of the
# uivision package; the executor already lives in sequence.py, the planner in plan.py.

from __future__ import annotations

import time
from dataclasses import dataclass

from . import autorun, desktop, macro, paths, plan, tabs
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


class _Recorder:
    """Collects the reported steps so the result can carry them (one mutable box)."""

    def __init__(self, report):
        self._report = report
        self.steps: list = []

    def __call__(self, step: str, message: str, level: str = "info") -> None:
        self.steps.append((step, message))
        self._report(step, message, level)


def _macro_target(spec: RunSpec):
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
    target = _macro_target(spec)
    target.parent.mkdir(parents=True, exist_ok=True)
    document = macro.build_macro(spec.macro)     # per-run values ride cmd_var1..3, not the file
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


def _report_matches(targets, pattern: str, structured: bool, report) -> None:
    """The pattern's verdict: every matching tab, or why the macro cannot find its tab."""
    if not targets:
        _report_no_matches(pattern, report)
        return
    if not structured:
        report("detect", f"pattern “{pattern}” matches {len(targets)} open tab(s):")
        for pos, target in enumerate(targets, 1):
            report("detect", f"match {pos}: {target.url[:110]}")
        return
    profiles = sorted({plan.profile_label(t.profile_name, t.profile_dir) or "?"
                       for t in targets})
    report("detect", f"pattern “{pattern}” matches {len(targets)} open tab(s) "
                     f"in {len(profiles)} profile(s): {', '.join(profiles)}")
    for pos, target in enumerate(targets, 1):
        where = plan.profile_label(target.profile_name, target.profile_dir) or "?"
        report("detect", f"match {pos}: {target.url[:110]} — {target.title[:40]} "
                         f'(profile “{where}”)')


def _report_no_matches(pattern: str, report) -> None:
    """Why nothing matches: no open tab (E210 ahead) or no pattern at all."""
    if (pattern or "").strip():
        report("detect", f"no OPEN tab matches “{pattern}” in any Firefox profile — the "
                         f"macro will NOT open anything and will fail (E210): open the "
                         f"page in the matching Firefox first", "warn")
    else:
        report("detect", "no window-title pattern set — the run will be blocked before "
                         "launching (the macro reuses a tab, it never opens one)", "warn")


def _report_clashes(targets, pattern: str, report) -> None:
    """Duplicate selectors inside one profile cannot each hit their own tab — say so."""
    for selector, label, count in plan.clashes(targets, pattern):
        report("detect", f"profile “{label}”: {count} tab(s) match “{selector}” — the "
                         f"title selector cannot tell them apart; each run lands on "
                         f"the first one", "warn")


def _report_plan(targets, structured: bool, pattern: str, report) -> None:
    """The run-plan line when it adds news (a single run self-describes)."""
    if len(targets) >= 2:
        report("detect", f"run plan: {plan.summarize(targets, structured)}")
        _report_clashes(targets, pattern, report)


def _load_profiles(seams: RunSeams) -> list:
    """Per-profile sessions: the profiles seam, the flat tabs seam, or the real stores."""
    if seams.profiles is not None:
        return seams.profiles()
    if seams.tabs is not None:
        return [plan.anonymous_session(seams.tabs())]
    return tabs.profile_sessions()


def _report_profiles(report) -> None:
    """How many Firefox profiles were scanned, by name — an empty scan explains itself."""
    names = [path.name for path in tabs.profile_dirs()]
    quiet = f" ({', '.join(names[:6])})" if names else " (is Firefox installed?)"
    report("detect", f"firefox profiles scanned: {len(names)}{quiet}")


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


def tab_target(pattern: str) -> str | None:
    """The fallback run's selectWindow target: the pattern's tab, or None.

    It never returns `tab=open` — the macro must not open a page (owner rule), so
    a blank pattern is a run that cannot be satisfied, not a fresh tab.
    """
    text = (pattern or "").strip()
    return f"title=*{text}*" if text else None


def _report_open_tabs(sessions, real: bool, recorder: _Recorder) -> None:
    """The flat tab list across every profile + the freshest store's receipt."""
    rows = [row for session in sessions for row in session["rows"]]
    quiet = "" if rows else " (no session store readable — is Firefox running?)"
    recorder("detect", f"firefox open tabs seen: {len(rows)}{quiet}")
    if real and rows:
        _report_source(sessions, recorder)
    _report_tab_rows(rows, recorder)


def _detect_phase(spec: RunSpec, recorder: _Recorder, seams: RunSeams) -> list:
    """The pre-run eyes: EVERY profile's tabs, the pattern's matches, the run plan."""
    sessions = _load_profiles(seams)
    real = seams.tabs is None and seams.profiles is None
    structured = real or seams.profiles is not None
    targets = plan.plan_targets(sessions, spec.pattern)
    if real:
        _report_profiles(recorder)
    _report_open_tabs(sessions, real, recorder)
    _report_matches(targets, spec.pattern, structured, recorder)
    _report_windows(sessions, seams, recorder)
    _report_plan(targets, structured, spec.pattern, recorder)
    wins = desktop.find_windows(spec.pattern)
    note = "" if wins or os_is_windows() else " (window listing is Windows-only)"
    recorder("detect", f"firefox windows matching the pattern: {len(wins)}{note}")
    _detect_plugin(recorder, seams)
    return targets


def _stopped(seams: RunSeams) -> bool:
    return bool(seams.stop and seams.stop())


def _result(kind: str, message: str, recorder: _Recorder, lines: tuple = ()) -> RunResult:
    return RunResult(kind=kind, message=message, steps=tuple(recorder.steps), lines=lines)


def _blocked_no_pattern(recorder: _Recorder) -> RunResult:
    """Blank pattern: the macro has no tab to reuse and it never opens one."""
    recorder("launch", "no window-title pattern set — the macro finds the run's tab "
                       "by title and never opens a page: set the pattern first", "error")
    return _result("blocked", "no window-title pattern — nothing to reuse, nothing opened",
                   recorder)


async def run_test(spec: RunSpec, report, seams: RunSeams = None) -> RunResult:
    """One framework test end to end; every phase reports through `report`."""
    seams = seams or RunSeams()
    recorder = _Recorder(report)
    targets = _detect_phase(spec, recorder, seams)
    if _stopped(seams):
        return _result("stopped", "stopped before the run began", recorder)
    if tab_target(spec.pattern) is None:
        return _blocked_no_pattern(recorder)
    try:
        page = _provision(spec, recorder)
    except (ValueError, OSError) as exc:
        recorder("provision", f"cannot prepare the run: {exc}", "error")
        return _result("blocked", str(exc), recorder)
    if not targets:
        targets = [plan.Target()]          # today's single run: the OS handoff decides
    runs = plan.runs(targets, spec.pattern, spec.config_dir, time.strftime("%Y%m%d-%H%M%S"))
    executor = Sequence(spec, seams, recorder)
    executor.page = str(page)
    return await executor.execute(runs)
