"""Offline foundation validation only; never opens a browser or modifies a file."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from image_queue import __version__
from image_queue.domain.presets import MAX_PRESET_BYTES, loads_preset
from image_queue.domain.urls import validate_url
from image_queue.domain.validation import ContractError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "check-url", help="Validate exact URL syntax, not reachability"
    ).add_argument("url")
    commands.add_parser("check-preset", help="Validate a local connection preset").add_argument(
        "path"
    )
    commands.add_parser("desktop", help="Open the local dark workspace").add_argument("--data-dir")
    return parser


def _read_preset(path: str) -> None:
    with Path(path).open("rb") as handle:
        data = handle.read(MAX_PRESET_BYTES + 1)
    if len(data) > MAX_PRESET_BYTES:
        raise ContractError("preset: exceeds 1 MiB limit")
    loads_preset(data.decode("utf-8"))


def _desktop(directory: str | None) -> int:
    try:
        from image_queue.desktop.app import launch
    except ImportError:
        print(
            "Desktop requires the desktop extra and Qt system libraries; see docs/WORKSPACE.md",
            file=sys.stderr,
        )
        return 2
    return launch(Path(directory) if directory else None)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "desktop":
        return _desktop(arguments.data_dir)
    try:
        if arguments.command == "check-url":
            validate_url(arguments.url)
        else:
            _read_preset(arguments.path)
    except ContractError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (OSError, UnicodeError):
        print(
            "preset: cannot read UTF-8 file; check path, encoding and permissions", file=sys.stderr
        )
        return 2
    print("Valid (offline only). No Chrome connection or page readiness has been tested.")
    return 0
