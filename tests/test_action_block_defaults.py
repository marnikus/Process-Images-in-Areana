"""Action-block defaults vs site_adapter — RULE 21 single-source lock (step B9).

Three contracts:
1. MIRROR: every default that is supposed to mirror site_adapter stays a
   member of the adapter inventory (drift in either direction fails).
2. FROZEN: known legacy-divergent defaults are pinned to their exact
   current strings — changing them is a behaviour change that needs the
   Area A RULE 10 decision first (see
   docs/archive/2026-09-19-area-b-review-and-followups/review.md F-3).
3. JS MIRROR: web UI `getDefaultBlocks()` (RULE 3 mirror) matches the
   Python catalog block-for-block.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.browser.probe_selectors import (
    send_click_primary,
    send_presence_selector,
    textarea_primary,
)
from app.browser.site_adapter import SELECTORS, get_selector
from app.core.action_blocks import BLOCK_DEFINITIONS, DEFAULT_STACK_ORDER

REPO = Path(__file__).resolve().parent.parent
# C7 split the panel into action-blocks/*.js; the store owns the default
# catalog + order. The facade is kept as a fallback for pre-split trees.
JS_PANEL_CANDIDATES = [
    REPO / "app" / "ui" / "web" / "js" / "panels" / "action-blocks" / "block-store.js",
    REPO / "app" / "ui" / "web" / "js" / "panels" / "action-blocks.js",
]


def _js_panel_text() -> str:
    for candidate in JS_PANEL_CANDIDATES:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    raise AssertionError(f"action-blocks JS not found in {JS_PANEL_CANDIDATES}")

# --- 1. MIRROR: default_selector -> adapter inventory -------------------------
# (block_id, adapter key). The default must be one of the adapter's
# selectors (primary, a fallback, or the presence selector).
MIRROR_FAMILIES = [
    ("OBSERVE_BASELINE", "output_image"),
    ("HIGHLIGHT_ATTACH", "file_input"),
    ("ATTACH_IMAGE", "file_input"),
    ("HIGHLIGHT_PROMPT", "prompt_textarea"),
    ("INSERT_PROMPT", "prompt_textarea"),
    ("VERIFY_PROMPT", "prompt_textarea"),
    ("HIGHLIGHT_SUBMIT", "send_button"),
    ("SUBMIT", "send_button"),
]


@pytest.mark.unit
@pytest.mark.parametrize("block_id,adapter_key", MIRROR_FAMILIES)
def test_mirror_default_is_in_adapter_inventory(block_id, adapter_key):
    default = BLOCK_DEFINITIONS[block_id]["default_selector"]
    selector = get_selector(adapter_key)
    inventory = set(selector.all_selectors()) | {selector.presence()}
    assert default in inventory, f"{block_id} default drifted from {adapter_key}"


@pytest.mark.unit
def test_attach_click_default_is_in_adapter_inventory():
    click = BLOCK_DEFINITIONS["ATTACH_IMAGE"]["default_click_selector"]
    selector = get_selector("add_files_button")
    assert click in set(selector.all_selectors()) | {selector.presence()}


# Byte-identity of the probe_selectors accessors used by the live paths —
# proves the B9 swaps changed no behaviour (values frozen to pre-B9 strings).
@pytest.mark.unit
def test_probe_accessor_values_frozen_to_pre_b9_strings():
    assert textarea_primary() == 'textarea[name="message"]'
    assert send_presence_selector() == 'button[aria-label="Send message"]'
    assert send_click_primary() == 'button[aria-label="Send message"]:not([disabled])'


# --- 2. FROZEN: known legacy-divergent defaults (Area A RULE 10 pending) ------
# Exact-string pins. Anyone editing these must do it as a deliberate
# behaviour decision (Area A), not a drive-by "fix".
FROZEN_DEFAULTS = {
    # Playwright-only `:has-text()` parts — invalid CSS on the CDP path.
    "CHECK_SECURITY": "div[role=\"dialog\"][data-state=\"open\"], iframe[title*=\"reCAPTCHA\"], div:has-text(\"Security Verification\"), div:has-text(\"captcha\"), [data-testid=\"security-dialog\"]",
    # `div[data-testid="output"] img` / bare `div.no-scrollbar img` not in adapter.
    "WAIT_OUTPUT": "div.no-scrollbar img[src*=\".r2.cloudflarestorage.com/\"], div[data-testid=\"output\"] img, div.no-scrollbar img, img.aspect-square.cursor-pointer, main img[src*=\".r2.cloudflarestorage.com/\"]",
    # Broader prefix of adapter primary `div.flex.flex-wrap.gap-2 img[alt]`.
    "VERIFY_ATTACHMENT": "div.flex.flex-wrap.gap-2 img",
    # Playwright-only text-match selectors.
    "AWAIT_PROCESSING_IMAGE": "div:has-text(\"Processing\"), div:has-text(\"Generating\"), [data-state=\"loading\"], .spinner, [aria-busy=\"true\"]",
}

# Pre-B3 send fallback list (kept for the UI preview only).
FROZEN_SUBMIT_FALLBACK = "form:has(textarea[name=\"message\"]) button[aria-label=\"Send message\"]:not([disabled]), div.flex.items-center.gap-2 button[aria-label=\"Send message\"]:not([disabled]), form button:has(svg):not([disabled])"


@pytest.mark.unit
@pytest.mark.parametrize("block_id", sorted(FROZEN_DEFAULTS))
def test_known_divergent_defaults_are_frozen(block_id):
    assert BLOCK_DEFINITIONS[block_id]["default_selector"] == FROZEN_DEFAULTS[block_id]


@pytest.mark.unit
def test_submit_fallback_list_is_frozen_pre_b3():
    assert BLOCK_DEFINITIONS["SUBMIT"]["default_fallback_selector"] == FROZEN_SUBMIT_FALLBACK


@pytest.mark.unit
def test_submit_fallback_list_is_frozen_pre_b3():
    assert BLOCK_DEFINITIONS["SUBMIT"]["default_fallback_selector"] == FROZEN_SUBMIT_FALLBACK


# Byte-identity alarms for literals that remain outside site_adapter but
# were NOT swapped (other areas' files / behaviour-locked paths). If the
# adapter or the copy changes, this fails — no silent drift possible.
@pytest.mark.unit
def test_cdp_client_attach_list_mirrors_adapter_exactly():
    src = (REPO / "app" / "browser" / "cdp" / "dom.py").read_text(encoding="utf-8")
    m = re.search(r"DEFAULT_FILE_INPUT_SELECTORS = \[\s*'([^']*)',\s*'([^']*)',\s*'([^']*)',\s*\]", src)
    assert m, "cdp dom attach selector list changed shape"
    assert list(m.groups()) == get_selector("file_input").all_selectors()


@pytest.mark.unit
def test_verification_probe_textarea_mirrors_adapter_primary():
    src = (REPO / "app" / "services" / "verification.py").read_text(encoding="utf-8")
    assert f"querySelector('{textarea_primary()}')" in src


# No NEW live selector literal may appear in the files that carry the
# frozen residuals. Every selector-looking literal in these files must be
# in the frozen allowlist below.
_SELECTOR_LITERAL = re.compile(
    r"""['"`](?:button\[aria-|textarea\[name=|input\[type=|img\[(?:src|loading|alt)|div\.no-scrollbar|div\.flex\.|div\[role=|iframe\[title|form button|form:has\()"""
)
FROZEN_LITERALS = {
    "app/ui/bridge.py": {
        'input[type="file"]',                      # HIGHLIGHT_ATTACH fallback (broader than adapter primary)
        "div.flex.flex-wrap.gap-2 img",            # attachment preview highlight (broader than img[alt] primary)
        "div.no-scrollbar img",                    # output highlight fallback (not in adapter)
    },
    "app/services/verification.py": {
        'textarea[name="message"]',                # probe-internal; mirrors adapter primary (alarm above)
    },
    "app/browser/cdp/dom.py": {
        'form input[type="file"][accept*="image"]',
        'input[type="file"][accept*="image"]',
        'input[type="file"]',
    },
    "app/services/single_job_runner.py": set(),    # B9: literal swapped for send_presence_selector()
}


@pytest.mark.unit
@pytest.mark.parametrize("rel", sorted(FROZEN_LITERALS))
def test_no_new_selector_literals_outside_site_adapter(rel):
    src = (REPO / rel).read_text(encoding="utf-8")
    hits = set()
    for m in _SELECTOR_LITERAL.finditer(src):
        literal = src[m.start():]
        literal = literal[: literal.index(m.group(0)[0], 1) + 1]
        hits.add(literal[1:-1])
    unexpected = hits - FROZEN_LITERALS[rel]
    assert not unexpected, f"new live selector literal(s) in {rel}: {unexpected}"


# --- 3. JS MIRROR: web panel getDefaultBlocks() vs Python catalog -------------


def _js_default_blocks():
    src = _js_panel_text()
    defs = re.search(r"getDefaultBlocks\(\) \{.*?const defs = \{(.*?)\n    \};", src, re.S)
    if not defs:  # C7 split: _blockDefs() returns the catalog map
        defs = re.search(r"_blockDefs\(\) \{\s*return \{(.*?)\n    \};", src, re.S)
    assert defs, "getDefaultBlocks()/blockDefs() defs block not found"
    out = {}
    for m in re.finditer(r"(\w+):\s*\{([^}]*)\}", defs.group(1)):
        bid, body = m.group(1), m.group(2)
        fields = dict(re.findall(r"(\w+):\s*('[^']*'|true|false)", body))
        out[bid] = {
            "name": fields.get("name", "").strip("'"),
            "icon": fields.get("icon", "").strip("'"),
            "color": fields.get("color", "").strip("'").lower(),
            "category": fields.get("category", "").strip("'"),
            "required": fields.get("required") == "true",
        }
    return out


# Known pre-existing display-name drift (JS panel label vs Python catalog
# name), caught by this lock on its first run. Aligning them is a UI naming
# decision for Area A (RULE 10); until then both sides are pinned.
KNOWN_JS_NAME_DRIFT = {
    "DOWNLOAD": "Download HQ",                 # Python: "Download Highest Quality"
    "SAVE": "Save *_AI.ext",                   # Python: "Save *_AI.ext Atomically"
}


@pytest.mark.unit
def test_js_default_blocks_mirror_python_catalog():
    js = _js_default_blocks()
    assert set(js) == set(BLOCK_DEFINITIONS), "JS/Python block id sets differ"
    for bid, py_def in BLOCK_DEFINITIONS.items():
        j = js[bid]
        expected_name = KNOWN_JS_NAME_DRIFT.get(bid, py_def["name"])
        assert j["name"] == expected_name, bid
        assert j["icon"] == py_def["icon"], bid
        assert j["color"] == py_def["default_color"].lower(), bid
        assert j["category"] == py_def["category"], bid
        assert j["required"] == py_def.get("required", False), bid


@pytest.mark.unit
def test_js_default_stack_order_mirrors_python():
    src = _js_panel_text()
    m = re.search(r"const order = \[([^\]]*)\]", src)
    if not m:  # C7 split: _blockOrder() returns the default stack order
        m = re.search(r"_blockOrder\(\) \{\s*return \[([^\]]*)\]", src)
    assert m, "JS default stack order array not found"
    js_order = re.findall(r"'(\w+)'", m.group(1))
    assert js_order == DEFAULT_STACK_ORDER
