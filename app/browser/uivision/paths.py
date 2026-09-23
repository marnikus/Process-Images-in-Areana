"""Where Ui.Vision's files live — the XModule home and the app's runtime dir.

Defaults are measured from the extension itself (`src/services/xmodules/xfile.ts
initConfig`, github.com/A9T9/RPA): the XModule home folder is
`<User Desktop>/uivision` unless the user changed it in the extension's
Settings → XModule tab — so the home is a config field here, and hard-drive
storage keeps macros at `<home>/macros/<Name>.json`.

The app's own runtime files (the autorun page and the savelog files) live under
`<config>/uivision/`, which is git-ignored like the rest of `config/` (I-43).
"""

from __future__ import annotations

from pathlib import Path

MACROS_DIR = "macros"
RUNTIME_DIR = "uivision"
AUTORUN_NAME = "ui.vision.html"
LOGS_DIR = "logs"


def default_home() -> Path:
    """The XModule home the extension creates when the user never set one."""
    return Path.home() / "Desktop" / "uivision"


def home(configured: str = "") -> Path:
    """The configured XModule home, or the default when unset."""
    text = (configured or "").strip()
    return Path(text).expanduser() if text else default_home()


def macro_file(home_dir, macro_name: str) -> Path:
    """`<home>/macros/<Name>.json` — refuses a name that escapes the macros dir."""
    root = (Path(home_dir) / MACROS_DIR).resolve()
    path = (root / f"{macro_name}.json").resolve()
    if root not in path.parents:
        raise ValueError(f"macro name escapes the macros dir: {macro_name!r}")
    return path


def runtime_dir(config_dir) -> Path:
    """The app's own Ui.Vision runtime dir (autorun page + logs)."""
    return Path(config_dir) / RUNTIME_DIR


def autorun_file(config_dir) -> Path:
    return runtime_dir(config_dir) / AUTORUN_NAME


def logs_dir(config_dir) -> Path:
    return runtime_dir(config_dir) / LOGS_DIR


def log_file(config_dir, stamp: str) -> Path:
    """One run's savelog file — `savelog=` in the launch URL names exactly this."""
    return logs_dir(config_dir) / f"run-{stamp}.txt"
