"""Retained implementation provenance and package asset boundaries."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
UI = ROOT / "src/image_queue/ui"


def test_copied_runtime_modules_are_unchanged_except_documented_titles():
    manifest = json.loads((UI / "retained-manifest.json").read_text())
    for entry in manifest:
        original = (ROOT / entry["source"]).read_bytes()
        assert hashlib.sha256(original).hexdigest() == entry["sha256"]
        if entry["file"] != "js/sash-core.js":
            assert (UI / entry["file"]).read_bytes() == original
    assert "QtWebEngine" not in (UI / "js/sash-core.js").read_text()


def test_packaged_shell_has_no_remote_assets_or_legacy_paths():
    html = (UI / "index.html").read_text()
    assert "https://" not in html
    assert "Old App" not in html
    assert "qrc:///qtwebchannel/qwebchannel.js" in html
    assert "connect-src 'none'" in html
