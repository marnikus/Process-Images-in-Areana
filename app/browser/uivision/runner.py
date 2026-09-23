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


@dataclass(frozen=True)
class RunSeams:
    """The injected boundaries — defaults are the real ones."""

    stop: object = None       # callable → True when the user pressed Stop
    sleep: object = None      # async sleep (tests shorten the poll)
    popen: object = None      # subprocess factory (tests fake the launch)
    tabs: object = None       # callable → open-tab rows (tests fake the store)
    addon: object = None      # callable → extension-seen tri-state
    probe: object = None      # callable → desktop-module-listening bool


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
    if spec.storage != "xfile":
        report("provision", "storage=browser: import this macro ONCE in the Ui.Vision UI "
                            "(Macros tab → Import) — the browser cannot read it from disk",
               "warn")
    page = autorun.write_page(paths.autorun_file(spec.config_dir))
    report("provision", f"autorun page ready: {page}")
    return page, log_path


def _detect_phase(spec: RunSpec, report, seams: RunSeams) -> None:
    """The pre-run eyes: what Firefox and the plugin show, before anything runs."""
    _detect_tabs(spec, report, seams)
    _detect_plugin(report, seams)


def _detect_tabs(spec: RunSpec, report, seams: RunSeams) -> None:
    """What Firefox shows without a debugger: windows, open tabs, the pattern."""
    rows = seams.tabs() if seams.tabs else tabs.tab_rows()
    seen = tabs.match_urls(rows, spec.pattern)
    tail = "; ".join(r["url"][:60] for r in rows[:4]) if rows else \
        "no session store readable — is Firefox running?"
    report("detect", f"firefox open tabs seen: {len(rows)}" + (f" — {tail}" if rows else f" ({tail})"))
    if seen:
        report("detect", f"pattern “{spec.pattern}” matches {len(seen)} open tab(s) — {seen[0][:80]}")
    else:
        report("detect", f"no OPEN tab matches “{spec.pattern}” — the macro opens "
                         f"{(spec.url or 'the URL field')[:70]} itself", "warn")
    wins = desktop.find_windows(spec.pattern)
    note = "" if wins or os_is_windows() else " (window listing is Windows-only)"
    report("detect", f"firefox windows matching the pattern: {len(wins)}{note}")


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


def _foreground(spec: RunSpec, report) -> None:
    """Find the pattern's Firefox windows and raise them (critical rule: visible+front)."""
    matches, raised = desktop.foreground(spec.pattern)
    if not matches:
        report("foreground", f"no Firefox window matches “{spec.pattern}” — launching anyway; "
                             f"the macro's own open+bringBrowserToForeground takes over", "warn")
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
        report("launch", f"Firefox not found at {binary!r} — set the binary path in the window",
               "error")
        return None
    url = autorun.launch_url(autorun.LaunchSpec(
        page_path=str(page), macro=spec.macro, storage=spec.storage,
        log_path=str(log_path), url=spec.url, target=spec.target))
    report("launch", f"starting Firefox with the autorun URL (macro={spec.macro}, "
                     f"storage={spec.storage}, savelog={log_path.name})")
    process = launch.launch(launch.build_argv(binary, url), popen=popen)
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
    _detect_phase(spec, recorder, seams)
    if _stopped(seams):
        return _result("stopped", "stopped before the run began", recorder)
    try:
        page, log_path = _provision(spec, recorder)
    except (ValueError, OSError) as exc:
        recorder("provision", f"cannot prepare the run: {exc}", "error")
        return _result("blocked", str(exc), recorder)
    _foreground(spec, recorder)
    if _stopped(seams):
        return _result("stopped", "stopped before launching Firefox", recorder)
    process = _launch(spec, (page, log_path), recorder, seams.popen)
    if process is None:
        return _result("blocked", "Firefox was not found — nothing was launched", recorder)
    verdict = await logread.poll_log(log_path, time.time() + float(spec.timeout_sec),
                                     sleep=seams.sleep, stop=seams.stop)
    recorder("result", f"{verdict.kind}: {verdict.message}",
             "info" if verdict.kind == "stopped" else _result_level(verdict.kind))
    return _result(verdict.kind, verdict.message, recorder, verdict.lines)
