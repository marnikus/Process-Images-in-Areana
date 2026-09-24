"""Finding + starting Firefox — no debugger, no driver, no remote control.

The owner's critical rule, enforced here: the argv is
`[binary, autorun-url]` (single / fallback run — `build_argv`) or
`[binary, -P <profile>, autorun-url]` when the run targets one named profile
(`profile_argv`, 2026-09-23 multi-profile fix). Nothing else may ever ride
along. No `-no-remote`, no `--start-debugger-server`, no geckodriver / Selenium /
Playwright / Puppeteer. A running Firefox hands the URL to its existing instance
and opens it in a new tab; `-P <name>` chooses WHICH instance — Firefox's own
per-profile remoting hands the URL to that profile's running instance (or starts
that profile when it is down), which is why `-no-remote` would still be wrong:
it would start a second, isolated browser. A test pins the argv and bans the
deleted vocabulary from this package.

`launch_resilient` is the runner's entry: plain `Popen` first, then the
Windows-native fallbacks for the classic `[WinError 5] Access is denied`
(executing a *folder* instead of `firefox.exe`, argv[0]-with-path quirks —
answered by `executable=` + `cwd=` — and sandboxed launchers, answered by
`ShellExecute` / the shell). Whatever still refuses becomes one `LaunchError`
carrying every attempt plus the binary's diagnosis, so the run ends `blocked`
with a fix instead of crashing on a bare OS error.
"""

from __future__ import annotations

import os
import shutil
import subprocess

DEFAULT_BINARIES = {
    "windows": r"C:\Program Files\Mozilla Firefox\firefox.exe",
    "linux": "firefox",
    "macos": "/Applications/Firefox.app/Contents/MacOS/firefox",
}

# Words that must never appear in a launch argv (the deleted debugger approach).
BANNED_ARG_MARKERS = ("start-debugger-server", "remote-debugging-port", "no-remote",
                      "geckodriver", "selenium", "playwright", "puppeteer", "marionette")


_UNIX_CANDIDATES = ("firefox", "/usr/bin/firefox", "/snap/bin/firefox",
                    "/usr/local/bin/firefox")


def _win_candidates() -> list:
    """Mozilla Firefox under each real program-files root of this machine."""
    keys = ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")
    roots = [os.environ.get(k, "") or d
             for k, d in zip(keys, (r"C:\Program Files", r"C:\Program Files (x86)", ""))]
    return [os.path.join(r, "Mozilla Firefox", "firefox.exe") for r in roots if r]


def candidate_binaries(os_name: str = "") -> list:
    """Common install places of this OS (the search order for a blank field)."""
    from app.browser.browsers import current_os
    makers = {"windows": _win_candidates, "macos": lambda: [DEFAULT_BINARIES["macos"]]}
    return makers.get(os_name or current_os(), lambda: list(_UNIX_CANDIDATES))()


def _configured(configured: str) -> str:
    """The field's value, quote-trimmed ('' when blank)."""
    return (configured or "").strip().strip('"')


def _first_existing(name: str) -> str:
    """The first common install place that really holds Firefox ('' when none)."""
    return next((c for c in candidate_binaries(name) if binary_exists(c)), "")


def resolve_binary(configured: str = "", os_name: str = "") -> str:
    """The configured binary, else the first existing common install, else default."""
    from app.browser.browsers import current_os
    name = os_name or current_os()
    return _configured(configured) or _first_existing(name) or \
        DEFAULT_BINARIES.get(name, DEFAULT_BINARIES["linux"])


def binary_exists(binary: str) -> bool:
    """A path must be a FILE on disk (a folder is not launchable — WinError 5).

    A bare name is trusted to PATH (`which`). The file check matters: the old
    `exists` answered True for a folder, and asking Windows to *execute* a
    folder fails with exactly `[WinError 5] Access is denied`.
    """
    if os.path.isabs(binary) or os.path.sep in binary or (os.name == "nt" and "/" in binary):
        return os.path.isfile(binary)
    return shutil.which(binary) is not None


class LaunchError(OSError):
    """Firefox would not start — every attempt plus the binary's diagnosis."""


def diagnose_binary(binary: str) -> str:
    """One guidance sentence naming why `binary` cannot (or could not) start."""
    text = (binary or "").strip()
    if not text:
        return ("no Firefox binary configured or found — install Firefox, or put its FULL "
                "path in the window's Firefox binary field (`where firefox` in cmd)")
    if os.path.isdir(text):
        return (f"{text!r} is a FOLDER, not firefox.exe — executing a folder is exactly "
                f"what Windows refuses with [WinError 5]; append “Mozilla Firefox\\firefox.exe”")
    if not os.path.exists(text):
        return (f"no file at {text!r} — check the window's Firefox binary field "
                f"(`where firefox` in cmd shows the real path)")
    try:
        size = os.path.getsize(text)
    except OSError:
        size = -1
    return (f"{text!r} exists ({size} bytes) but Windows refused to start it — a launcher "
            f"quirk (antivirus / AppLocker / Store-python sandbox); the run retried through "
            f"the native shell, and if that failed too, start Firefox once by hand and re-run")


def _checked(argv: list) -> list:
    """The argv after the banned-vocabulary scan — the critical rule's one gate."""
    bad = [marker for arg in argv for marker in BANNED_ARG_MARKERS if marker in str(arg).lower()]
    if bad:
        raise ValueError(f"launch refuses debugger/driver vocabulary: {', '.join(sorted(set(bad)))}")
    return argv


def build_argv(binary: str, url: str) -> list:
    """`[binary, -new-tab, url]` — the single-run launch line (the critical rule as code).

    `-new-tab` opens the autostart URL as a tab, not a new window.
    """
    return _checked([binary, "-new-tab", url])


def profile_args(name: str = "", profile_dir: str = "") -> tuple:
    """The argv prefix aiming Firefox at ONE profile ('' answers nothing).

    `-P <name>` is Firefox's own per-profile selector: the URL is handed to the
    running instance of that named profile, or that profile is started. A
    directory no `profiles.ini` names falls back to `-profile <dir>` (same
    remoting, keyed on the profile directory). Neither flag is debugger
    vocabulary; the banned scan still runs over the assembled argv.
    """
    if (name or "").strip():
        return ("-P", name.strip())
    if (profile_dir or "").strip():
        return ("-profile", profile_dir)
    return ()


def profile_argv(binary: str, url: str, profile_args: tuple = ()) -> list:
    """`[binary, *profile-args, -new-tab, url]` — one run aimed at one profile instance.

    `-new-tab` forces the autostart URL to open as a tab in the existing
    Firefox window instead of a separate window (2026-09-24, owner fix:
    the autostart page was opening as a new window per run, which was
    disruptive and left orphan windows after the macro finished).
    """
    return _checked([binary, *(profile_args or ()), "-new-tab", url])


def launch(argv, popen=None):
    """Start Firefox with the autorun URL; returns the process handle (Popen seam)."""
    factory = popen or subprocess.Popen
    return factory(argv)


def launch_resilient(argv, popen=None):
    """Start Firefox, falling back through the Windows-native launchers on refusal.

    The injected `popen` seam stays single-attempt (tests are deterministic);
    the real path retries a refused `Popen` through `_windows_fallbacks` and
    raises one `LaunchError` naming every attempt when nothing starts Firefox.
    """
    factory = popen or subprocess.Popen
    try:
        return factory(argv)
    except OSError as first:
        attempts = [f"start: {first}"]
        if popen is not None or os.name != "nt":
            raise LaunchError(_launch_failed(argv, attempts)) from first
        return _windows_fallbacks(argv, attempts)


def _windows_fallbacks(argv, attempts):
    """Popen-with-cwd → ShellExecute → default browser; else one LaunchError."""
    binary = argv[0] if argv else ""
    url = argv[1] if len(argv) > 1 else ""
    try:
        return _launch_with_cwd(binary, url)
    except OSError as exc:
        attempts.append(f"retry from its own folder: {exc}")
    try:
        return _shell_execute(binary, url)
    except (OSError, AttributeError) as exc:
        attempts.append(f"native shell open: {exc}")
    try:
        os.startfile(url)                      # Windows-only: the shell opens the URL
        from types import SimpleNamespace
        return SimpleNamespace(pid="?")        # the shell gives no handle
    except (OSError, AttributeError) as exc:
        attempts.append(f"default browser: {exc}")
    raise LaunchError(_launch_failed(argv, attempts))


def _launch_with_cwd(binary: str, url: str):
    """The StackOverflow WinError-5 fix: bare argv[0] + `executable=` + `cwd=`."""
    parent = os.path.dirname(os.path.abspath(binary)) or None
    return subprocess.Popen([os.path.basename(binary) or binary, url],
                            executable=binary, cwd=parent)


def _shell_execute(binary: str, url: str):
    """Windows' own launcher — elevation-aware where raw CreateProcess is not."""
    import ctypes
    from types import SimpleNamespace
    handle = ctypes.windll.shell32.ShellExecuteW(None, "open", binary, f'"{url}"', None, 1)
    if handle is None or int(handle) <= 32:
        raise OSError(f"ShellExecute refused {binary!r} (code {handle})")
    return SimpleNamespace(pid="?")


def _launch_failed(argv, attempts: list) -> str:
    """Every attempt plus the binary's diagnosis — the whole `blocked` story."""
    binary = argv[0] if argv else ""
    return f"Firefox would not start from {binary!r} ({'; '.join(attempts)}). {diagnose_binary(binary)}"
