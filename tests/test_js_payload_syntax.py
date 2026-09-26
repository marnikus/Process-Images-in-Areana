"""Every JS payload the app sends through Runtime.evaluate must be valid JS (B9).

Field case (bugfix-verification.md §B9): `_LABEL_JS` in dom_highlight_js.py
lost one closing brace, so every FIND / HIGHLIGHT probe was a SyntaxError
("Unexpected token 'catch'") — visual clicks, VERIFY_ATTACHMENT, New-chat
reset and every HIGHLIGHT block failed with "no data returned from the page",
and no test ever executed the generated JS.

Two lanes, both over the REAL builders (RULE 8):
  * bracket balance — always runs (no node needed): a string/regex/comment
    aware scan that would have caught §B9 on the first run;
  * `node --check` — the definitive parser, when node is on PATH (the JS
    lane `tests/js/test_dom_probes.mjs` also executes the probes for real).
"""

from __future__ import annotations

import itertools
import os
import shutil
import subprocess
import tempfile

import pytest

from app.browser import captcha_probes
from app.browser import dom_highlight as dh
from app.browser import new_chat
from app.browser import output_probes
from app.browser import processing_probe
from app.browser import recording_probes
from app.browser import worker_badge
from app.browser.cdp_arena import js_snippets
from app.browser.uivision import file_dialog as uivision_file_dialog
from app.browser.uivision import job_macros as uivision_job_macros
from app.browser.uivision import job_scripts as uivision_job_scripts
from app.browser.uivision import macro as uivision_macro
from app.utils import page_errors
from app.browser.probe_requests import (MATCH_CONTAINS, MATCH_EXACT, ClickProbeSpec,
                                        FindProbeSpec, HighlightSpec)

pytestmark = pytest.mark.unit


def _find_variants() -> dict:
    out = {}
    for label, text, mode, hl in itertools.product([None, "span"], [None, "New Chat"],
                                                   [MATCH_EXACT, MATCH_CONTAINS], [True, False]):
        spec = FindProbeSpec(label_selector=label, match_text=text, match_mode=mode,
                             highlight=hl, highlight_ms=10)
        out[f"find[{label},{text},{mode},{hl}]"] = dh.build_find_probe("button", spec)
    return out


def _click_variants() -> dict:
    out = {}
    for cs, hl, click in itertools.product([None, "svg"], [True, False], [True, False]):
        out[f"click[{cs},{hl},{click}]"] = dh.build_click_probe(cs, ClickProbeSpec(highlight=hl, do_click=click))
    return out


def payloads() -> dict:
    """Name → JS text, for everything the pipeline can evaluate."""
    out = {}
    out.update(_find_variants())
    out.update(_click_variants())
    out["highlight[label,match]"] = dh.build_highlight_probe(
        "div", HighlightSpec(label_selector="b", match_text="x", clear_first=True))
    out["highlight[plain]"] = dh.build_highlight_probe("div")
    out["clear"] = dh.build_clear_probe()
    out["highlight_js_from_spec"] = dh.build_highlight_js_from_spec(dh.HighlightJsSpec(selector="button"))
    out["highlight_rect"] = dh.build_highlight_rect_js_from_spec(dh.HighlightRectSpec(1, 2, 3, 4))
    out["clear_js"] = dh.build_clear_js()
    out["watcher_overlay"] = dh.build_watcher_overlay_js("wait", "generation", 60, "sub")
    out["watcher_overlay_spec"] = dh.build_watcher_overlay_js_from_spec(dh.WatcherOverlaySpec(kind="captcha"))
    out["watcher_clear"] = dh.build_watcher_clear_js()
    out["worker_badge"] = worker_badge.build_worker_badge_js(worker_badge.WorkerBadgeSpec(worker_no=3, tab_id="AB'C\"D"))
    out["worker_badge_clear"] = worker_badge.build_worker_badge_clear_js()
    out["new_chat.page_loaded"] = new_chat.build_page_loaded_js()
    out["new_chat.composer_empty"] = new_chat.build_composer_empty_js()
    out["output.baseline"] = output_probes.build_baseline_js()
    out["output.check"] = output_probes.build_check_js(["https://x/old.png"], "20260920-000000-ABCD", [])
    out["processing.default"] = processing_probe.build_processing_probe(
        'div:has-text("Processing"), [aria-busy="true"], .spinner', "Processing")
    out["processing.bare"] = processing_probe.build_processing_probe("", "")
    out["captcha.detect"] = captcha_probes.build_detect_js()
    out["captcha.visible"] = captcha_probes.build_visible_js()
    out["captcha.inject"] = captcha_probes.build_inject_js("tok'en", "site\"key")
    out["recording.observer"] = recording_probes.build_observer_js()
    out["recording.netwrap"] = recording_probes.build_netwrap_js()
    out["recording.flush"] = recording_probes.build_flush_js()
    out["recording.snapshot"] = recording_probes.build_snapshot_js()
    out["page_errors.scan"] = page_errors.build_error_scan_js()
    # the Firefox macro's find-rect script: registered RENDERED (the extension
    # substitutes ${!cmd_varN} with JSON.stringify before executeScript runs it)
    out["uivision.find_rect.element"] = uivision_macro.render_find_rect_js(
        "xpath=//a[span[text()='New Chat']]", 3000)
    out["uivision.find_rect.image"] = uivision_macro.render_find_rect_js("button.png@@0.8", 3000)
    out.update(_firefox_job_payloads())
    for name in sorted(n for n in dir(js_snippets) if n.startswith("JS_")):
        out[f"snippet.{name}"] = _as_statement(getattr(js_snippets, name))
    return {k: _as_statement(v) for k, v in out.items()}


_JOB_BASELINE = {"srcs": ["https://x/old.png"], "outputs": []}

# every page-JS body of the Firefox image job, built by the REAL builders (audit F11)
_JOB_BODIES = {
    "baseline_js": lambda js: js.baseline_js(True),
    "attach_wait_js": lambda js: js.attach_wait_js("arena_c1.png", 50),
    "prompt_js": lambda js: js.prompt_js("[JOB-ID: c1]\nčervená `${x}` \"q\""),
    "guard_js": lambda js: js.guard_js("c1", "ab" * 32, "arena_c1.png"),
    "ack_js": lambda js: js.ack_js("c1", 50),
    "observe_js": lambda js: js.observe_js("c1", _JOB_BASELINE, 50, True),
    "clean_js": lambda js: js.clean_js(50),
    "security_js": lambda js: js.security_js(True),
    "upload_item_js": lambda js: js.upload_item_js(),
}


def _firefox_job_payloads() -> dict:
    """Each job body as the loader evaluates it, plus the loader Target itself.

    The Target is an `executeScript` function BODY (it `return`s), so it is
    checked wrapped in the anonymous function Ui.Vision puts around it.
    """
    out = {}
    for name, build in _JOB_BODIES.items():
        body = build(uivision_job_scripts)
        out[f"uivision.job.{name}"] = f";({body})"
        out[f"uivision.job_loader.{name}"] = (
            f"(function () {{ {uivision_job_macros.loader('c1', name, body)} }})")
    out["uivision.file_dialog.still_open_js"] = (
        f"(function () {{ {uivision_file_dialog.still_open_js('arena_c1.png')} }})")
    return out


def test_every_firefox_job_script_is_in_the_syntax_lane():
    module = uivision_job_scripts
    builders = {n for n in dir(module) if n.endswith("_js") and not n.startswith("_")
                and getattr(getattr(module, n), "__module__", "") == module.__name__}  # own, not re-imported
    assert builders == set(_JOB_BODIES), f"register {sorted(builders ^ set(_JOB_BODIES))} in _JOB_BODIES"


def _as_statement(js: str) -> str:
    """Bare function / arrow expressions are evaluated as `;(expr)(...)` by the
    app; wrap them the same way so `node --check` sees a statement."""
    head = js.lstrip()
    return f";({js})" if head.startswith(("async", "(", "function")) and not head.startswith((";(", "(function")) else js


# every JS builder in the browser layer must be represented above — a new
# `build_*` that is not listed here fails this test until it is added
_BUILDERS_COVERED = {
    dh: {"build_find_probe", "build_click_probe", "build_highlight_probe", "build_clear_probe",
         "build_highlight_js_from_spec", "build_clear_js", "build_highlight_rect_js_from_spec",
         "build_watcher_overlay_js", "build_watcher_overlay_js_from_spec", "build_watcher_clear_js"},
    new_chat: {"build_page_loaded_js", "build_composer_empty_js"},
    output_probes: {"build_baseline_js", "build_check_js"},
    processing_probe: {"build_processing_probe"},
    captcha_probes: {"build_detect_js", "build_visible_js", "build_inject_js"},
    recording_probes: {"build_observer_js", "build_netwrap_js", "build_flush_js", "build_snapshot_js"},
    page_errors: {"build_error_scan_js"},
    uivision_macro: {"build_commands", "build_macro", "render_find_rect_js"},
}


@pytest.mark.parametrize("module", list(_BUILDERS_COVERED), ids=lambda m: m.__name__)
def test_every_js_builder_is_in_the_syntax_lane(module):
    builders = {n for n in dir(module) if n.startswith("build_") and callable(getattr(module, n))}
    missing = builders - _BUILDERS_COVERED[module]
    assert not missing, f"add {sorted(missing)} to payloads() in {__file__}"


# ---- lane 1: bracket balance (always) ----

_OPEN = {"(": ")", "[": "]", "{": "}"}
_CLOSE = {v: k for k, v in _OPEN.items()}
_REGEX_PRECEDERS = set("(,=:[!&|?{};+-*%<>~^")


class _Scan:
    """Minimal JS lexer: skips strings, template literals, regex literals and
    comments, and tracks bracket nesting in code."""

    def __init__(self, src: str):
        self.src, self.i, self.n = src, 0, len(src)
        self.stack: list = []
        self.last_code = ""  # last significant code char (regex-vs-divide decision)

    def _skip_quoted(self, quote: str) -> None:
        self.i += 1
        while self.i < self.n and self.src[self.i] != quote:
            self.i += 2 if self.src[self.i] == "\\" else 1
        self.i += 1

    def _skip_regex(self) -> None:
        self.i += 1
        in_class = False
        while self.i < self.n:
            ch = self.src[self.i]
            if ch == "\\":
                self.i += 2
                continue
            if ch == "[":
                in_class = True
            elif ch == "]":
                in_class = False
            elif ch == "/" and not in_class:
                break
            self.i += 1
        self.i += 1

    def _skip_comment(self) -> bool:
        nxt = self.src[self.i + 1] if self.i + 1 < self.n else ""
        if nxt == "/":
            self.i = self.src.find("\n", self.i)
            self.i = self.n if self.i < 0 else self.i
            return True
        if nxt == "*":
            end = self.src.find("*/", self.i + 2)
            self.i = self.n if end < 0 else end + 2
            return True
        return False

    def _slash(self) -> None:
        if self._skip_comment():
            return
        if self.last_code == "" or self.last_code in _REGEX_PRECEDERS:
            self._skip_regex()
        else:
            self.i += 1  # division

    def _bracket(self, ch: str, errors: list) -> None:
        if ch in _OPEN:
            self.stack.append((ch, self.i))
        else:
            if not self.stack or self.stack[-1][0] != _CLOSE[ch]:
                errors.append(f"unexpected '{ch}' at offset {self.i}")
            else:
                self.stack.pop()

    def run(self) -> list:
        errors: list = []
        while self.i < self.n:
            ch = self.src[self.i]
            if ch in "'\"`":
                self._skip_quoted(ch)
                self.last_code = "'"
                continue
            if ch == "/":
                self._slash()
                self.last_code = ")"
                continue
            if ch in _OPEN or ch in _CLOSE:
                self._bracket(ch, errors)
            if not ch.isspace():
                self.last_code = ch
            self.i += 1
        errors += [f"unclosed '{c}' opened at offset {pos}" for c, pos in self.stack]
        return errors


def bracket_errors(js: str) -> list:
    return _Scan(js).run()


_B9_FIXED = ("(function(){ try { for (var i=0;i<1;i++) { if (a) { var c = 1; if (c) { x = 1; } } }"
             " } catch (err) { z = '}'; y = /[}]/g; } })()")
# exactly the §B9 defect: the `if (a) {` block never closes → `for` never closes → `} catch` is bogus
_B9_BROKEN = ("(function(){ try { for (var i=0;i<1;i++) { if (a) { var c = 1; if (c) { x = 1; } }"
              " } catch (err) { z = '}'; y = /[}]/g; } })()")


def test_bracket_scanner_catches_the_b9_shape():
    assert bracket_errors(_B9_FIXED) == []
    errs = bracket_errors(_B9_BROKEN)
    assert errs == ["unexpected ')' at offset 123",          # `})()` meets an unclosed `{`
                    "unclosed '(' opened at offset 0",
                    "unclosed '{' opened at offset 11"]     # the `(function(){` body never closes


def test_bracket_scanner_ignores_brackets_in_strings_regexes_and_comments():
    ok = "var a = '{[('; var b = \"}\"; var c = `)]`; var d = /[{(]+/g; x = 10/2; // }}}\n /* ((( */ f(a, [b], {c: 1});"
    assert bracket_errors(ok) == []


@pytest.mark.parametrize("name", sorted(payloads()))
def test_payload_brackets_balance(name):
    js = payloads()[name]
    assert bracket_errors(js) == [], f"{name}: unbalanced brackets"


# ---- lane 2: the real parser, when node exists ----

node = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")


@node
def test_payloads_parse_with_node():
    failures = []
    for name, js in payloads().items():
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(js)
            path = f.name
        try:
            r = subprocess.run(["node", "--check", path], capture_output=True, text=True, timeout=30)
        finally:
            os.unlink(path)
        if r.returncode != 0:
            tail = (r.stderr.strip().splitlines() or ["?"])[-1]
            failures.append(f"{name}: {tail[:120]}")
    assert failures == []
