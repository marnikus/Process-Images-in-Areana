"""In-page watcher popup: small, top-center, draggable (2026-09-17).

The overlay JS is a template string, so these tests assert on the built
markers: default position, compact sizes, and drag handlers.
"""

import pytest

from app.browser.dom_highlight import (
    WATCHER_ATTR,
    build_watcher_clear_js,
    build_watcher_overlay_js,
)


@pytest.mark.unit
def test_overlay_defaults_to_top_center():
    js = build_watcher_overlay_js()
    assert "left:50%" in js
    assert "translateX(-50%)" in js
    assert "left:2%" not in js


@pytest.mark.unit
def test_overlay_is_compact():
    js = build_watcher_overlay_js()
    assert "max-width:380px" in js
    assert "min-height:160px" not in js
    assert "font-size:52px" not in js  # old giant icon


@pytest.mark.unit
def test_overlay_is_draggable_and_remembers_position():
    js = build_watcher_overlay_js()
    assert "pointer-events:auto" in js
    assert "mousedown" in js and "mousemove" in js and "mouseup" in js
    assert "__arenaWatcherPos" in js
    assert "cursor:grab" in js
    assert "user-select:none" in js


@pytest.mark.unit
def test_overlay_pulse_is_drag_safe():
    js = build_watcher_overlay_js(kind="generation")
    assert "arenaWatcherPulse2" in js  # transform-free pulse
    assert "translateY(-50%)" not in js  # would fight dragged position


@pytest.mark.unit
def test_overlay_kinds_keep_identity():
    gen = build_watcher_overlay_js(kind="generation")
    cap = build_watcher_overlay_js(kind="captcha")
    assert "⏳" in gen and "🛡️" in cap
    assert "shown" in gen


@pytest.mark.unit
def test_clear_still_clears():
    js = build_watcher_clear_js()
    assert WATCHER_ATTR in js and "cleared" in js
