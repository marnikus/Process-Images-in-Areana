"""RULE 21 enforcement — site_adapter is the single selector source.

Two gates:
1. Lint: no selector literal from the site_adapter inventory may appear in
   the probe file sources (placeholders only) — prevents selector drift.
2. Wiring: the built probe payloads must carry exactly the site_adapter
   lists, so editing site_adapter is the only way to change a probe.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.browser import cdp_arena, new_chat, output_probes, probe_selectors
from app.browser.site_adapter import SELECTORS, get_readiness_requirements, get_selector

ROOT = Path(__file__).resolve().parent.parent

# Files that SEND probes to the page. Selectors must arrive via
# probe_selectors; literals live in site_adapter.py only.
PROBE_FILES = [
    "app/browser/cdp_arena.py",
    "app/browser/dom_highlight.py",
    "app/browser/new_chat.py",
    "app/browser/output_probes.py",
]


def _selector_inventory():
    """Every element-finding selector site_adapter owns."""
    needles = {}
    for name, sel in SELECTORS.items():
        for s in sel.all_selectors() + [sel.presence()]:
            needles[s] = name
        if name == "model_label" and sel.scope:
            needles[sel.scope] = f"{name}.scope"  # probed by the spinner label lookup
    return needles


@pytest.mark.unit
def test_probe_sources_carry_no_selector_literals():
    """Lint: probe files contain placeholders, not selector literals."""
    inventory = _selector_inventory()
    assert inventory, "site_adapter inventory must not be empty"
    leaked = []
    for rel in PROBE_FILES:
        source = (ROOT / rel).read_text(encoding="utf-8")
        for needle, key in inventory.items():
            if needle in source:
                leaked.append(f"{rel}: {key} -> {needle}")
    assert not leaked, "selector literals outside site_adapter (RULE 21):\n" + "\n".join(leaked)


@pytest.mark.unit
def test_composer_payloads_receive_site_adapter_lists():
    payloads = {
        cdp_arena.JS_INSERT_PROMPT: probe_selectors.textarea_selectors(),
        cdp_arena.JS_CLICK_SEND: probe_selectors.send_click_selectors(),
        cdp_arena.JS_VERIFY_ATTACHMENT: probe_selectors.attachment_preview_selectors(),
    }
    for js, selectors in payloads.items():
        assert json.dumps(selectors) in js, "payload not wired to site_adapter list"
    assert json.dumps(probe_selectors.send_presence_selector()) in cdp_arena.JS_SEND_STATE
    assert json.dumps(probe_selectors.textarea_primary()) in cdp_arena.JS_VERIFY_PROMPT


@pytest.mark.unit
def test_output_payloads_receive_site_adapter_lists():
    expected = get_selector("output_image").all_selectors()
    assert output_probes.SELECTORS_V3 == expected
    for js in (output_probes.JS_BASELINE_V3, output_probes.JS_CHECK_NEW_OUTPUT_V3):
        assert json.dumps(expected) in js
        assert json.dumps(probe_selectors.spinner_selector()) in js
    label = probe_selectors.model_label_probe()
    assert json.dumps(label["scope"]) in output_probes.JS_CHECK_NEW_OUTPUT_V3
    assert json.dumps(label["label"]) in output_probes.JS_CHECK_NEW_OUTPUT_V3


@pytest.mark.unit
def test_readiness_and_security_derive_from_site_adapter():
    reqs = get_readiness_requirements()
    checks = probe_selectors.readiness_checks()
    assert [c["name"] for c in checks] == [k.split("_")[0] for k in reqs]
    for check, key in zip(checks, reqs):
        assert check["sel"] == get_selector(key).presence()
        assert json.dumps(check["sel"]) in cdp_arena.JS_PAGE_READY
    dialog = probe_selectors.security_dialog_check()
    assert dialog["sel"] == get_selector("security_dialog").primary
    assert json.dumps(dialog["sel"]) in cdp_arena.JS_PAGE_READY
    assert json.dumps(dialog["text"]) in cdp_arena.JS_PAGE_READY


@pytest.mark.unit
def test_spinner_probe_uses_site_adapter_spinner():
    assert json.dumps(probe_selectors.spinner_selector()) in cdp_arena.JS_IS_GENERATING
    assert get_selector("processing_spinner").primary == probe_selectors.spinner_selector()


@pytest.mark.unit
def test_new_chat_candidates_use_site_adapter_selectors():
    expected = get_selector("new_chat_button").all_selectors()
    assert [c[0] for c in new_chat.NEW_CHAT_CANDIDATES] == expected
    assert new_chat.NEW_CHAT_CANDIDATES[0][2] == "New Chat"  # semantic entries prove label


@pytest.mark.unit
def test_new_chat_builder_payloads_use_site_adapter_primary():
    for builder in (new_chat.build_page_loaded_js, new_chat.build_composer_empty_js):
        js = builder()
        assert "__TEXTAREA_PRIMARY__" not in js
        assert get_selector("prompt_textarea").primary in js


@pytest.mark.unit
def test_no_leftover_placeholders_in_built_payloads():
    for name in (
        "JS_INSERT_PROMPT", "JS_SEND_STATE", "JS_VERIFY_PROMPT", "JS_CLICK_SEND",
        "JS_VERIFY_ATTACHMENT", "JS_PAGE_READY", "JS_IS_GENERATING",
    ):
        assert "__" not in getattr(cdp_arena, name), f"{name} has an unfilled placeholder"
