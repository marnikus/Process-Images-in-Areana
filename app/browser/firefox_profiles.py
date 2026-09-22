"""Which profile Firefox itself would use — read from `profiles.ini` (round 10).

The Allow prompt (`devtools.debugger.prompt-connection`) is suppressed by a pref **in the profile
that is running**. Round 8 wrote the prefs into the dir configured in Settings
(`C:\\arena-images-firefox` by default), so the owner's real Firefox never saw them and asked on
every connection. This module answers the one question that fixes it: where does Firefox keep the
profile it starts with?

Firefox's own rules, in order:

1. `[Install*] Default=` — the profile the current installation uses (a path relative to the ini);
2. `[Profile*] Default=1` — the profile marked default;
3. the only `[Profile*]` present.

Roots per OS: `%APPDATA%\\Mozilla\\Firefox`, `~/Library/Application Support/Firefox`,
`~/.mozilla/firefox`. Two overrides exist for tests and portable copies:
`ARENA_FIREFOX_PROFILES_INI` (the ini file) and `ARENA_FIREFOX_PROFILE_DIR` (the directory itself).
Nothing here writes anything.

RULE 18: leaf module, small pure functions.
"""

from __future__ import annotations

import configparser
import os
from pathlib import Path

INI_NAME = "profiles.ini"
INI_ENV = "ARENA_FIREFOX_PROFILES_INI"
DIR_ENV = "ARENA_FIREFOX_PROFILE_DIR"


def profiles_root() -> Path:
    """The directory Firefox keeps `profiles.ini` in, per OS (`/` when it cannot be told)."""
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", "")) / "Mozilla" / "Firefox"
    if sys_is_macos():
        return Path.home() / "Library" / "Application Support" / "Firefox"
    return Path.home() / ".mozilla" / "firefox"


def sys_is_macos() -> bool:
    """True on darwin (kept tiny so the path rules stay independent of `sys` import order)."""
    import sys
    return sys.platform == "darwin"


def profiles_ini_path() -> Path:
    """The ini this app reads: the override, else the OS root's own `profiles.ini`."""
    override = (os.environ.get(INI_ENV) or "").strip()
    return Path(override) if override else profiles_root() / INI_NAME


def _relative(path_text: str, base: Path) -> str:
    """Resolve a (possibly relative) profile path against the ini's folder."""
    path = Path(path_text)
    return str(path if path.is_absolute() else base / path)


def _install_default(parser, base: Path) -> str:
    """`[Install*] Default=` — what the running installation actually uses."""
    for section in parser.sections():
        if section.lower().startswith("install") and parser.has_option(section, "Default"):
            value = (parser.get(section, "Default") or "").strip()
            if value:
                return _relative(value, base)
    return ""


def _profile_default(parser, base: Path) -> str:
    """The profile marked `Default=1`, else the only profile there is."""
    profiles = [s for s in parser.sections() if s.lower().startswith("profile")]
    for section in profiles:
        if (parser.get(section, "Default", fallback="") or "").strip() in ("1", "true"):
            return _relative((parser.get(section, "Path", fallback="") or "").strip(), base)
    if len(profiles) == 1:
        return _relative((parser.get(profiles[0], "Path", fallback="") or "").strip(), base)
    return ""


def parse_default_profile(text: str, base_dir) -> str:
    """The default profile directory inside one ini's text ("" when the text names none)."""
    parser = configparser.ConfigParser(strict=False)
    try:
        parser.read_string(text or "")
    except Exception:
        return ""
    base = Path(str(base_dir or "."))
    return _install_default(parser, base) or _profile_default(parser, base)


def _ini_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def default_profile_dir() -> str:
    """The directory of the profile Firefox starts with ("" when it cannot be determined)."""
    override = (os.environ.get(DIR_ENV) or "").strip()
    if override:
        return override
    ini = profiles_ini_path()
    return parse_default_profile(_ini_text(ini), ini.parent)


def profile_source() -> str:
    """Where that answer came from: `override` / `profiles.ini` / `unknown`."""
    if (os.environ.get(DIR_ENV) or "").strip():
        return "override"
    return "profiles.ini" if default_profile_dir() else "unknown"


def used_profile_dir(configured: str) -> str:
    """The dir a browser's profile work happens in: the configured one, else Firefox's own."""
    return (configured or "").strip() or default_profile_dir()
