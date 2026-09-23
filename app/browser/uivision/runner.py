"""One framework-test run: provision → foreground → launch → poll → result.

No Qt and no bridge in here — the runner is browser-layer mechanics with three
injected seams (report callback, stop predicate, sleep/Popen), which the panel
wires to `bridge._log` + the `firefox_auto_updated` signal (RULE 2/5) and to
the window's Stop button (RULE 7: the predicate is checked before every phase
and inside the poll).

Outcome kinds are distinct answers, never one invented "failed" (RULE 4):
`ok` / `error` are the extension's own verdicts from the savelog file,
`timeout` means the file never answered, `stopped` means the user stopped,
`blocked` means the run never started (bad macro name, missing Firefox, …).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from . import autorun, desktop, launch, logread, macro, paths, tabs


@dataclass(frozen=True)
class RunSpec:
    """One validated run: the window's config + where the app's files live."""
    pattern: str
    url: str
    target: str
    macro: str
    storage: str          # "xfile" (hard drive) or "browser" (import once in the extension)
    home: str             # XModule home folder ('' = the extension's default)
    binary: str           # Firefox binary ('' = this OS's default)
    timeout_sec: int
    pause_ms: int
    config_dir: str
    mode: str = "find"    # find = parse open tabs only | macro = official trigger


@dataclass(frozen=True)
class RunSeams:
    """The injected boundaries — defaults are the real ones."""

    stop: object = None       # callable → True when the user pressed Stop
    sleep: object = None      # async sleep (tests shorten the poll)
    popen: object = None      # subprocess factory (tests fake the launch)
    tabs: object = None       # callable → open-tab rows (tests fake the store)
    addon: object = None      # callable → extension-seen tri-state
    probe: object = None      # callable → desktop-module-listening bool
    running: object = None    # callable → is a Firefox live right now


@dataclass
class RunResult:
    """What one run answered: the kind, the message, the steps, the macro's log."""

    kind: str                 # ok | error | timeout | stopped | blocked
    message: str
    steps: tuple = ()
    lines: tuple = ()


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


def _provision(spec: RunSpec, report) -> tuple:
    """Write the macro + the autorun page; returns (page_path, log_path)."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    log_path = paths.log_file(spec.config_dir, stamp)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    target = _macro_target(spec)
    target.parent.mkdir(parents=True, exist_ok=True)
    document = macro.build_macro(spec.macro, spec.pause_ms)
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
    return page, log_path


def _detect_phase(spec: RunSpec, report, seams: RunSeams) -> tuple:
    """The pre-run eyes: what Firefox and the plugin show, before anything runs."""
    seen_rows = _detect_tabs(spec, report, seams)
    _detect_plugin(report, seams)
    return seen_rows


TAB_LOG_CAP = 50
RUNNING_WINDOW_SEC = 120


def _report_tab_rows(rows, report) -> None:
    """One detect line per open tab (capped) — the owner wants the whole list."""
    for pos, row in enumerate(rows[:TAB_LOG_CAP], 1):
        report("detect", f"firefox tab {pos}: {row['url'][:110]} — {row['title'][:40]}")
    if len(rows) > TAB_LOG_CAP:
        report("detect", f"+{len(rows) - TAB_LOG_CAP} more open tab(s)")


def _report_profiles(report) -> None:
    """Name every profile dir checked — the remote-debug line when none answers."""
    dirs = tabs.profile_dirs()
    named = [f"{str(d)[:60]}{' (running)' if tabs.lock_held(d) else ''}"
             for d in dirs[:6]]
    tail = "; ".join(named) if dirs else "none on this OS's roots"
    report("detect", f"profiles checked: {len(dirs)} — {tail}")


def _report_matches(spec: RunSpec, seen, report) -> None:
    """The pattern's verdict: every matching tab, or the macro's own open plan."""
    if not seen:
        report("detect", f"no OPEN tab matches “{spec.pattern}” — the macro opens "
                         f"{(spec.url or 'the URL field')[:70]} itself", "warn")
        return
    report("detect", f"pattern “{spec.pattern}” matches {len(seen)} open tab(s):")
    for pos, url in enumerate(seen, 1):
        report("detect", f"match {pos}: {url[:110]}")


def _detect_tabs(spec: RunSpec, report, seams: RunSeams) -> tuple:
    """What Firefox shows without a debugger: every open tab, the pattern, windows."""
    rows = seams.tabs() if seams.tabs else tabs.tab_rows()
    seen = tabs.match_urls(rows, spec.pattern)
    quiet = "" if rows else " (no session store readable — is Firefox running?)"
    report("detect", f"firefox open tabs seen: {len(rows)}{quiet}")
    if not rows:
        _report_profiles(report)
    _report_tab_rows(rows, report)
    _report_matches(spec, seen, report)
    wins = desktop.find_windows(spec.pattern)
    note = "" if wins or os_is_windows() else " (window listing is Windows-only)"
    report("detect", f"firefox windows matching the pattern: {len(wins)}{note}")
    return rows, seen


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


def _result_level(kind: str) -> str:
    """The log level one verdict kind deserves."""
    if kind == "ok":
        return "success"
    return "warn" if kind == "timeout" else "error"


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


def _find_verdict(spec: RunSpec, rows, seen, recorder) -> RunResult:
    """The parse-only answer — the owner's rule: read what exists, open nothing."""
    if not rows:
        recorder("find", "no Firefox session store readable — is Firefox running?", "error")
        return _result("blocked", "Firefox shows no open tabs (session store unreadable)",
                       recorder)
    if not seen:
        recorder("find", f"no open tab matches “{spec.pattern}” among {len(rows)} tab(s)",
                 "error")
        return _result("error", f"no open tab matches “{spec.pattern}” "
                                 f"({len(rows)} tab(s) seen)", recorder)
    recorder("find", f"{len(seen)} of {len(rows)} open tab(s) match “{spec.pattern}”",
             "success")
    return _result("ok", f"{len(seen)} of {len(rows)} open tab(s) match "
                         f"“{spec.pattern}” — {seen[0][:80]}", recorder)


def _firefox_running(seams: RunSeams) -> bool:
    """A live Firefox: OS windows, or a session store written in the last 2 min."""
    if seams.running:
        return bool(seams.running())
    if desktop.firefox_windows():
        return True
    return tabs.store_fresh(RUNNING_WINDOW_SEC)


def _popen(argv, popen, report):
    """The OS exec, named-failure style (a .lnk/folder/alias says Access denied)."""
    try:
        return launch.launch(argv, popen=popen)
    except OSError as exc:
        report("launch", f"the OS refused to exec {argv[0]!r}: {exc} — the binary field "
                         f"needs the REAL firefox.exe (shortcut → Properties → Target); "
                         f"a .lnk, a folder or a WindowsApps alias answers ‘Access "
                         f"denied’", "error")
        return None


def _start(spec: RunSpec, files, recorder, seams: RunSeams):
    """Running-gate + launch: this window never starts a NEW Firefox (owner)."""
    if not _firefox_running(seams):
        recorder("launch", "Firefox is NOT running — start your Firefox (with the "
                           "extension) first; this window never launches a new one",
                 "error")
        return None
    return _launch(spec, files, recorder, seams.popen)


def _foreground(spec: RunSpec, report) -> None:
    """Find the pattern's Firefox windows and raise them (critical rule: visible+front)."""
    matches, raised = desktop.foreground(spec.pattern)
    if not matches:
        report("foreground", f"no Firefox window matches “{spec.pattern}” — launching anyway; "
                             f"the macro's own open+bringBrowserToForeground takes over", "warn")
        return
    titles = "; ".join(title[:60] for _hwnd, title in matches[:3])
    report("foreground", f"{raised}/{len(matches)} Firefox window(s) on top — {titles}")


def _missing_binary(binary: str, report) -> None:
    """The not-found line: where to read the real path + every place looked."""
    report("launch", f"Firefox not found at {binary!r} — put its FULL path in the "
                     f"window’s Firefox binary field (Firefox shortcut → Properties → "
                     f"Target, or `where firefox` in cmd); looked at: "
                     f"{'; '.join(launch.candidate_binaries())}", "error")


def _launch(spec: RunSpec, files, report, popen):
    """Resolve the binary, build the official launch URL and start Firefox.

    `files` is `_provision`'s (page, log_path) pair — one argument keeps the
    signature at four parameters (RULE 16).
    """
    page, log_path = files
    binary = launch.resolve_binary(spec.binary)
    if not launch.binary_exists(binary):
        _missing_binary(binary, report)
        return None
    url = autorun.launch_url(autorun.LaunchSpec(
        page_path=str(page), macro=spec.macro, storage=spec.storage,
        log_path=str(log_path), url=spec.url, target=spec.target))
    report("launch", f"starting Firefox with the autorun URL (macro={spec.macro}, "
                     f"storage={spec.storage}, savelog={log_path.name})")
    process = _popen(launch.build_argv(binary, url), popen, report)
    if process is None:
        return None
    report("launch", f"launched (pid {getattr(process, 'pid', '?')}) — waiting for the savelog file")
    return process


def _stopped(seams: RunSeams) -> bool:
    return bool(seams.stop and seams.stop())


def _result(kind: str, message: str, recorder: _Recorder, lines: tuple = ()) -> RunResult:
    return RunResult(kind=kind, message=message, steps=tuple(recorder.steps), lines=lines)


async def run_test(spec: RunSpec, report, seams: RunSeams = None) -> RunResult:
    """One framework test end to end; every phase reports through `report`."""
    seams = seams or RunSeams()
    recorder = _Recorder(report)
    rows, seen = _detect_phase(spec, recorder, seams)
    if _stopped(seams):
        return _result("stopped", "stopped before the run began", recorder)
    if spec.mode != "macro":
        return _find_verdict(spec, rows, seen, recorder)
    try:
        page, log_path = _provision(spec, recorder)
    except (ValueError, OSError) as exc:
        recorder("provision", f"cannot prepare the run: {exc}", "error")
        return _result("blocked", str(exc), recorder)
    return await _macro_phase(spec, (page, log_path), recorder, seams)


async def _macro_phase(spec: RunSpec, files, recorder, seams: RunSeams) -> RunResult:
    """foreground → running-gate → launch → poll the savelog verdict."""
    page, log_path = files
    _foreground(spec, recorder)
    if _stopped(seams):
        return _result("stopped", "stopped before launching Firefox", recorder)
    process = _start(spec, files, recorder, seams)
    if process is None:
        return _result("blocked", "Firefox was not launched (not found, refused, or "
                                  "not running) — see the launch line above", recorder)
    verdict = await logread.poll_log(log_path, time.time() + float(spec.timeout_sec),
                                     sleep=seams.sleep, stop=seams.stop)
    recorder("result", f"{verdict.kind}: {verdict.message}",
             "info" if verdict.kind == "stopped" else _result_level(verdict.kind))
    return _result(verdict.kind, verdict.message, recorder, verdict.lines)
