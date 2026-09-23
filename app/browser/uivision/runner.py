"""One framework-test run: provision → foreground → launch → poll → result.

No Qt and no bridge in here — the runner is browser-layer mechanics with three
injected seams (report callback, stop predicate, sleep/Popen), which the panel
wires to `bridge._log` + the `firefox_auto_updated` signal (RULE 2/5) and to
the window's Stop button (RULE 7: the predicate is checked before every phase
and inside the poll).

Outcome kinds are distinct answers, never one invented "failed" (RULE 4):
`ok` / `error` are the extension's own verdicts from the savelog file,
`timeout` means the file never answered, `stopped` means the user stopped,
`blocked` means the run never started (bad macro name, missing Firefox,
missing extension, …).
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


def _touch_savelog(log_path) -> None:
    """Fail fast when the savelog path is unwritable (an empty file polls as a wait)."""
    try:
        log_path.touch(exist_ok=True)
    except OSError as exc:
        raise OSError(f"savelog file is not writable: {log_path} ({exc})") from exc


def _provision(spec: RunSpec, report) -> tuple:
    """Write the macro + the autorun page; returns (page_path, log_path)."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    log_path = paths.log_file(spec.config_dir, stamp)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _touch_savelog(log_path)
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
    """The pre-run eyes: what Firefox and the plugin show, before anything runs.

    Returns (session windows, extension tri-state) — the foreground targets the
    window holding the pattern's tab, and a timeout explains itself against the
    extension state instead of shrugging.
    """
    windows = _detect_tabs(spec, report, seams)
    return windows, _detect_plugin(report, seams)


TAB_LOG_CAP = 50


def _report_tab_rows(rows, report) -> None:
    """One detect line per open tab (capped) — the owner wants the whole list."""
    for pos, row in enumerate(rows[:TAB_LOG_CAP], 1):
        report("detect", f"firefox tab {pos}: {row['url'][:110]} — {row['title'][:40]}")
    if len(rows) > TAB_LOG_CAP:
        report("detect", f"+{len(rows) - TAB_LOG_CAP} more open tab(s)")


def _report_matches(spec: RunSpec, seen, report) -> None:
    """The pattern's verdict: every matching tab, or the selectWindow's warning."""
    if not seen:
        report("detect", f"no OPEN tab matches “{spec.pattern}” — open the page first: "
                         f"the macro never opens pages, a missing tab fails the run", "warn")
        return
    report("detect", f"pattern “{spec.pattern}” matches {len(seen)} open tab(s):")
    for pos, url in enumerate(seen, 1):
        report("detect", f"match {pos}: {url[:110]}")


def _detect_tabs(spec: RunSpec, report, seams: RunSeams) -> list:
    """What Firefox shows without a debugger: every open tab, the pattern, windows."""
    rows = seams.tabs() if seams.tabs else tabs.tab_rows()
    real = seams.tabs is None
    if real:
        _report_profiles(report)
    quiet = "" if rows else " (no session store readable — is Firefox running?)"
    report("detect", f"firefox open tabs seen: {len(rows)}{quiet}")
    if real and rows:
        _report_source(report)
    _report_tab_rows(rows, report)
    _report_matches(spec, tabs.match_urls(rows, spec.pattern), report)
    windows = _session_windows(seams, real)
    _report_windows(windows, report)
    wins = desktop.find_windows(spec.pattern)
    note = "" if wins or os_is_windows() else " (window listing is Windows-only)"
    report("detect", f"firefox windows matching the pattern: {len(wins)}{note}")
    return windows


def _report_profiles(report) -> None:
    """How many Firefox profiles were scanned, by name — an empty scan explains itself."""
    names = [path.name for path in tabs.profile_dirs()]
    quiet = f" ({', '.join(names[:6])})" if names else " (is Firefox installed?)"
    report("detect", f"firefox profiles scanned: {len(names)}{quiet}")


def _report_source(report) -> None:
    """Which session file fed the tab rows — the detect line's own receipt."""
    source, profile = tabs.session_source()
    if source:
        report("detect", f"session source: {source} in {profile}")


def _session_windows(seams: RunSeams, real: bool) -> list:
    """Per-window session rows: the seam's, the store's, or none when faked."""
    if seams.windows:
        return seams.windows()
    return tabs.session_windows() if real else []


def _report_windows(windows: list, report) -> None:
    """One line per session window: its tabs and the active (OS-title) one."""
    for window in windows or []:
        active = (window.get("active") or {}).get("title", "")
        report("detect", f"firefox window {window.get('index', '?')}: "
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
        return ("Ui.Vision extension NOT found in any Firefox profile — install it from "
                "addons.mozilla.org/firefox/addon/rpa and enable it (Firefox needs no "
                "file-URL toggle — that one is Chrome-only)", "warn")
    return "Ui.Vision extension: unknown (no Firefox profile readable)", "warn"


def _result_level(kind: str) -> str:
    """The log level one verdict kind deserves."""
    if kind == "ok":
        return "success"
    return "warn" if kind == "timeout" else "error"


def _detect_plugin(report, seams: RunSeams):
    """Extension in the profile + the native-input module on its port (returns the tri-state)."""
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
    return addon


def tab_target(pattern: str) -> str:
    """The macro's selectWindow target — the pattern's already-open tab, never a new page."""
    text = (pattern or "").strip()
    if not text:
        raise ValueError("the pattern is blank — the run never opens pages, "
                         "so it needs the tab's title to find your tab")
    return f"title=*{text}*"


def _stray_savelog(name: str, roots=None):
    """The savelog under a download dir (the no-FileAccess landing spot), else None."""
    from pathlib import Path
    for root in roots if roots is not None else [Path.home() / "Downloads"]:
        try:
            candidate = Path(root) / name
        except Exception:
            continue
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _timeout_note(spec: RunSpec, log_path, addon) -> str:
    """What a silent savelog means: the stray-download case or the extension checklist."""
    stray = _stray_savelog(log_path.name)
    if stray is not None:
        return (f" — but the macro DID run: its log landed in {stray} instead (the FileAccess "
                f"XModule did not honour the full savelog= path — reinstall the XModules "
                f"or check their setup)")
    if addon is False:
        where = ("the Ui.Vision extension was NOT found in any Firefox profile — install it "
                 "from addons.mozilla.org/firefox/addon/rpa and enable it")
    elif addon is None:
        where = ("no Firefox profile answered the extension check — install Ui.Vision in the "
                 "profile this Firefox uses and enable it")
    else:
        where = ("the Ui.Vision extension IS installed, so it never started from the autorun "
                 "page — check it is enabled (about:addons) and that no alert blocks "
                 "the trigger tab")
    expecting = spec.home or "<Desktop>/uivision"
    return (f" — {where}; in hard-drive mode also set its own Home directory to “{expecting}” "
            f"(Ui.Vision Settings → Setup XModules2)")


def _foreground(spec: RunSpec, report, session_windows: list) -> None:
    """Raise the window holding the pattern's tab (critical rule: visible+front).

    The session mapping goes first, so one window rises instead of every title
    match; when nothing maps, the plain title matches take over, and when even
    those are silent the macro still finds the tab itself (or fails loudly).
    """
    mapped = desktop.foreground_tab_window(spec.pattern, session_windows or [])
    if mapped:
        matches, raised = mapped
        titles = "; ".join(title[:60] for _hwnd, title in matches[:3])
        report("foreground", f"{raised}/{len(matches)} Firefox window(s) on top — {titles} "
                             f"(holds the tab matching “{spec.pattern}”)")
        return
    matches, raised = desktop.foreground(spec.pattern)
    if not matches:
        report("foreground", f"no Firefox window matches “{spec.pattern}” — launching anyway; "
                             f"the macro's own selectWindow+bringBrowserToForeground takes over", "warn")
        return
    titles = "; ".join(title[:60] for _hwnd, title in matches[:3])
    report("foreground", f"{raised}/{len(matches)} Firefox window(s) on top — {titles}")


def _launch(spec: RunSpec, files, report, popen):
    """Resolve the binary, build the official launch URL and start Firefox.

    `files` is `_provision`'s (page, log_path) pair — one argument keeps the
    signature at four parameters (RULE 16).
    """
    page, log_path = files
    binary = launch.resolve_binary(spec.binary)
    if not launch.binary_exists(binary):
        report("launch", f"Firefox not found at {binary!r} — put its FULL path in the "
                         f"window’s Firefox binary field (Firefox shortcut → Properties → "
                         f"Target, or `where firefox` in cmd); looked at: "
                         f"{'; '.join(launch.candidate_binaries())}", "error")
        return None
    url = autorun.launch_url(autorun.LaunchSpec(
        page_path=str(page), macro=spec.macro, storage=spec.storage,
        log_path=str(log_path), url=spec.url, target=spec.target,
        tab=tab_target(spec.pattern)))
    report("launch", f"starting Firefox with the autorun URL (macro={spec.macro}, "
                     f"storage={spec.storage}, savelog={log_path.name}, "
                     f"tab={tab_target(spec.pattern)})")
    process = launch.launch_resilient(launch.build_argv(binary, url), popen=popen)
    report("launch", f"launched (pid {getattr(process, 'pid', '?')}) — waiting for the savelog file")
    return process


def _stopped(seams: RunSeams) -> bool:
    return bool(seams.stop and seams.stop())


def _addon_check_skipped() -> bool:
    """True when the operator overrode the no-extension refusal (exotic setups).

    The override exists for Firefox the scanner cannot see (Portable, a custom
    `-profile` outside the roots and `profiles.ini`) — set
    `ARENA_UIVISION_ALLOW_NO_ADDON=1` to launch anyway.
    """
    import os
    return os.environ.get("ARENA_UIVISION_ALLOW_NO_ADDON", "").strip() == "1"


def _refuse_without_addon(recorder: _Recorder) -> RunResult:
    """The `blocked` answer when no scanned profile has the extension installed."""
    names = [path.name for path in tabs.profile_dirs()]
    scanned = f" (scanned: {', '.join(names)})" if names else ""
    recorder("run", f"Ui.Vision extension NOT found in any Firefox profile{scanned} — "
                    f"refusing to open the trigger page into Error #204; install the add-on "
                    f"from addons.mozilla.org/firefox/addon/rpa in this profile and enable it "
                    f"(Firefox needs no file-URL toggle; ARENA_UIVISION_ALLOW_NO_ADDON=1 "
                    f"launches anyway)", "error")
    return _result("blocked", "Ui.Vision extension is not installed — the run would only "
                              "open the trigger page to Error #204", recorder)


def _result(kind: str, message: str, recorder: _Recorder, lines: tuple = ()) -> RunResult:
    return RunResult(kind=kind, message=message, steps=tuple(recorder.steps), lines=lines)


async def run_test(spec: RunSpec, report, seams: RunSeams = None) -> RunResult:
    """One framework test end to end; every phase reports through `report`."""
    seams = seams or RunSeams()
    recorder = _Recorder(report)
    session_windows, addon = _detect_phase(spec, recorder, seams)
    if _stopped(seams):
        return _result("stopped", "stopped before the run began", recorder)
    if not (spec.pattern or "").strip():
        recorder("run", "pattern is blank — set it to your tab's title (e.g. Arena); "
                        "the run reuses your open tab and never opens pages", "error")
        return _result("blocked", "pattern is blank — the run needs your tab's title", recorder)
    if addon is False and not _addon_check_skipped():
        return _refuse_without_addon(recorder)
    if addon is False:
        recorder("run", "proceeding without the extension (ARENA_UIVISION_ALLOW_NO_ADDON=1) — "
                        "expect Error #204 unless it is installed after all", "warn")
    try:
        page, log_path = _provision(spec, recorder)
    except (ValueError, OSError) as exc:
        recorder("provision", f"cannot prepare the run: {exc}", "error")
        return _result("blocked", str(exc), recorder)
    _foreground(spec, recorder, session_windows)
    if _stopped(seams):
        return _result("stopped", "stopped before launching Firefox", recorder)
    try:
        process = _launch(spec, (page, log_path), recorder, seams.popen)
    except OSError as exc:
        recorder("launch", f"Firefox would not start: {exc}", "error")
        return _result("blocked", f"Firefox would not start: {exc}", recorder)
    if process is None:
        return _result("blocked", "Firefox was not found — nothing was launched", recorder)
    verdict = await logread.poll_log(log_path, time.time() + float(spec.timeout_sec),
                                     sleep=seams.sleep, stop=seams.stop)
    if verdict.kind == "timeout":
        verdict = logread.LogResult(kind="timeout",
                                    message=verdict.message + _timeout_note(spec, log_path, addon),
                                    lines=verdict.lines)
    recorder("result", f"{verdict.kind}: {verdict.message}",
             "info" if verdict.kind == "stopped" else _result_level(verdict.kind))
    return _result(verdict.kind, verdict.message, recorder, verdict.lines)
