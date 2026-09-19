"""UI wiring contract — the names that tie Python, QWebChannel and the JS panels.

Regression (2026-09-19): a merge kept `MainWindow._build_ui()`'s call to
`CaptchaRecordingsBridge(manager, self)` but dropped both its import and the
`registerObject("captchaRecordings", …)` line, so the app died at startup with
`NameError` and the Records window lost its bridge. These tests pin the contract
without needing Qt WebEngine (the sandbox/CI has no libGL).
"""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "app" / "ui" / "web"
MAIN_WINDOW = ROOT / "app" / "ui" / "main_window.py"
BRIDGE_READY = WEB / "js" / "core" / "bridge-ready.js"
RECORDINGS_BRIDGE = ROOT / "app" / "ui" / "services" / "captcha_recordings_bridge.py"
RECORDINGS_PANELS = (WEB / "js" / "panels" / "captcha-recordings.js",
                     WEB / "js" / "panels" / "captcha-recording-comparison.js")


def _slotted_methods(path: Path) -> set:
    """Names of methods decorated with @Slot in the given module."""
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for dec in item.decorator_list:
                    if (isinstance(dec, ast.Name) and dec.id == "Slot") or isinstance(dec, ast.Call):
                        names.add(item.name)
    return names


def _registered_objects() -> set:
    return set(re.findall(r'registerObject\(\s*"([^"]+)"', MAIN_WINDOW.read_text(encoding="utf-8")))


def test_main_window_registers_the_recordings_bridge():
    source = MAIN_WINDOW.read_text(encoding="utf-8")
    assert "from app.ui.services.captcha_recordings_bridge import CaptchaRecordingsBridge" in source
    assert "self.recordings_bridge = CaptchaRecordingsBridge(" in source
    assert "captchaRecordings" in _registered_objects()


def test_every_js_channel_object_is_registered_in_python():
    used = set()
    for js in (WEB / "js").rglob("*.js"):
        used |= set(re.findall(r"ch\.objects\.([A-Za-z_][A-Za-z0-9_]*)", js.read_text(encoding="utf-8")))
    registered = _registered_objects()
    assert used, "expected at least the main bridge channel object"
    assert used <= registered, f"JS reads unregistered channel objects: {sorted(used - registered)}"


def test_js_reads_the_recordings_bridge_under_the_registered_name():
    ready = BRIDGE_READY.read_text(encoding="utf-8")
    assert "ch.objects.captchaRecordings" in ready
    assert "window.CaptchaRecordingsBridge" in ready


def test_recordings_panels_only_call_qt_slots():
    slotted = _slotted_methods(RECORDINGS_BRIDGE)
    called = set()
    for panel in RECORDINGS_PANELS:
        # the panels alias the channel object to a local `bridge` (or use window.*)
        for match in re.finditer(r"bridge\.([a-z_][a-z0-9_]*)\(|bridge\?\.([a-z_][a-z0-9_]*)",
                                 panel.read_text(encoding="utf-8")):
            called.add(match.group(1) or match.group(2))
    assert called, "expected the recordings panels to call bridge methods"
    assert called <= slotted, f"JS calls non-slots: {sorted(called - slotted)}"


@pytest.mark.unit
def test_index_html_assets_and_script_coverage():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    refs = [r for r in re.findall(r'(?:src|href)="([^"]+)"', html)
            if not r.startswith(("http", "#", "data:", "mailto:"))]
    missing = [r for r in refs if not r.startswith("qrc:") and not (WEB / r).exists()]
    assert missing == []

    on_disk = {f"js/{p.relative_to(WEB / 'js')}".replace("\\", "/")
               for p in (WEB / "js").rglob("*.js")}
    referenced = {r for r in refs if r.endswith(".js")}
    orphans = sorted(on_disk - referenced)
    assert orphans == [], f"JS files no page loads (dead UI): {orphans}"
