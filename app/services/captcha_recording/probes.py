"""Builders for the exact page agents used by captcha recordings."""

from pathlib import Path

_JS = Path(__file__).parent / "recording_js"


def _read(name: str) -> str:
    return (_JS / name).read_text(encoding="utf-8").strip()


def install_probe() -> str:
    return _read("install.js")


def drain_probe() -> str:
    return _read("drain.js")


def snapshot_probe() -> str:
    return _read("snapshot.js")


def stop_probe() -> str:
    return _read("stop.js")
