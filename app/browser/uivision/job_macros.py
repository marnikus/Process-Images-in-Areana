"""Firefox image-job phase macros — one short Ui.Vision macro per phase (2026-09-25).

Design D-1 (`archive/2026-09-25-firefox-image-job/design.md`): Python owns the
job's state machine; each phase is one macro that does ONE thing on the pooled
tab and echoes `ARENA_JOB=<json>` into its savelog. Every macro opens with
`selectWindow ${!cmd_var3}` and an EMPTY Value (never opens a page — E210 when
the tab is gone) and contains no DOM-level click (`macro.refuse_dom_clicks`):
the attach button, the send button and New Chat are native **XClick** rows,
confirmed by the shared RED find rectangle (`macro.FIND_RECT_JS`, target on
`cmd_var2`, budget on `cmd_var1`).

Page JS rides base64 inside a tiny loader (`_LOADER`): Ui.Vision interpolates
`${…}` in every Target, and Chrome's probes use JS template literals — base64
has no `$`, so what runs in the page is byte-identical to what Python built.
The reply is `{token, phase, data}`; `token` is the job's correlation id, so a
stale savelog line of another job never parses as this job's answer.
"""

from __future__ import annotations

import base64
import json
import ntpath
import re
from dataclasses import dataclass

from ..probe_selectors import new_chat_primary, send_click_primary, add_files_primary
from . import autorun, file_dialog, macro, paths
from .job_scripts import UPLOAD_ITEM_ATTR, upload_item_js

MACRO_PREFIX = "Arena_Job_"
REPLY_MARK = "ARENA_JOB="
_REPLY_RE = re.compile(re.escape(REPLY_MARK) + r"(\{.*\})")
_JOB_VAR = "arenaJob"        # where a probe stores its reply
_GUARD_VAR = "arenaGuard"    # the submit guard's reply (read by the click flag)
# Live 2026-09-26: Ui.Vision renders a stored ${var} into executeScript as a JSON STRING
# literal (".data is undefined" in the owner's log) — the flags accept a string or an
# object, and a reply they cannot read never clicks send.
_READ = "var r = ${%s}; try { if (typeof r === 'string') r = JSON.parse(r); } catch (e) { r = null; } "
_FLAG_JS = _READ % _GUARD_VAR + "return r && r.data && r.data.go ? 1 : 0"
# 1 = our preview is missing AND the OS dialog still holds the focus (ESC is safe to send)
UPLOAD_ITEM = f"css=[{UPLOAD_ITEM_ATTR}]"   # the + popup's “Add files” item, tagged by upload_item_js
_ESC_JS = _READ % _JOB_VAR + "return (r && r.data && r.data.matched === 1) || document.hasFocus() ? 0 : 1"

# ideal-size: 12-line JS literal reason=the one loader every phase shares (RULE 16.1.5)
_LOADER = r"""return (function () {
  var wrap = function (data) { return JSON.stringify({token: __TOKEN__, phase: __PHASE__, data: data}); };
  try {
    var bin = atob("__B64__");
    var bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) { bytes[i] = bin.charCodeAt(i); }
    var src = new TextDecoder('utf-8').decode(bytes);
    var value = (new Function('return (' + src + ');'))();
    return Promise.resolve(value).then(wrap, function (e) { return wrap({ok: false, error: String(e)}); });
  } catch (e) { return wrap({ok: false, error: String(e)}); }
})()"""


@dataclass(frozen=True)
class PhaseMacro:
    """One phase run: its commands + the per-run command-line values."""

    phase: str
    commands: tuple
    xclick: str = ""          # cmd_var2 — the XClick locator (css=…)
    wait_ms: int = 3000       # cmd_var1 — the RED find-rect budget
    timeout_sec: int = 60     # savelog deadline for this phase

    @property
    def name(self) -> str:
        return MACRO_PREFIX + self.phase.capitalize()


def css(selector: str) -> str:
    """A site-adapter selector as a Ui.Vision locator."""
    return f"css={selector}"


def loader(token: str, phase: str, js_expr: str) -> str:
    """The executeScript Target: decode the base64 body, run it, wrap the answer."""
    b64 = base64.b64encode(js_expr.encode("utf-8")).decode("ascii")
    return (_LOADER.replace("__B64__", b64).replace("__TOKEN__", json.dumps(token))
            .replace("__PHASE__", json.dumps(phase)))


def _select() -> list:
    return [macro.command("selectWindow", macro.TAB_VAR, "",
                          "reuse the pooled tab (Value EMPTY: never opens a page — E210 if gone)")]


def _probe(token: str, phase: str, js_expr: str, var: str = _JOB_VAR) -> list:
    """executeScript (page JS via the loader) → echo the reply into the savelog."""
    return [macro.command("executeScript", loader(token, phase, js_expr), var, f"{phase} probe"),
            macro.command("echo", REPLY_MARK + "${" + var + "}", "blue",
                          "job reply — the app reads it back from the savelog")]


def _native_click(what: str) -> list:
    """Foreground → RED find rect on cmd_var2 → XClick (native OS input only)."""
    return [macro.command("bringBrowserToForeground", "", "", "native input needs Firefox in front"),
            macro.command("executeScript", macro.FIND_RECT_JS, "", f"find + RED rect: {what}"),
            macro.command("XClick", macro.TARGET_VAR, "", f"native click: {what}")]


def _finish(phase: str, commands: list, **kw) -> PhaseMacro:
    macro.refuse_dom_clicks(commands)
    return PhaseMacro(phase=phase, commands=tuple(commands), **kw)


def probe_macro(token: str, phase: str, js_expr: str, timeout_sec: int = 60) -> PhaseMacro:
    """An observe-only phase (baseline / prompt / observe): no native input."""
    return _finish(phase, _select() + _probe(token, phase, js_expr), timeout_sec=timeout_sec)


def _open_upload_item() -> list:
    """The + opens a popup; its “Add files” item opens the OS dialog (live 2026-09-26).

    Gated on the tag: a UI whose + opens the dialog directly skips the rows."""
    return [macro.command("pause", "700", "", "the + popup opens"),
            macro.command("executeScript", "return " + upload_item_js(), "uploadItem", "tag the Add files item"),
            macro.command("if_v2", "${uploadItem} == 1", "", "popup UI: click its Add files item"),
            macro.command("executeScript", macro.render_find_rect_js(UPLOAD_ITEM, 1500), "",
                          "find + RED rect: Add files item"),
            macro.command("XClick", UPLOAD_ITEM, "", "native click: Add files item (opens the dialog)"),
            macro.command("end", "", "", "")]


def attach_macro(token: str, upload_path: str, wait_js: str) -> PhaseMacro:
    """XClick “Add files” → paste the staged path into the OS dialog → Open → verify; ESC if left open."""
    staged_name = ntpath.basename(str(upload_path))
    commands = (_select() + _native_click("Add files") + _open_upload_item()
                + file_dialog.fill_and_open(upload_path, staged_name)
                + _probe(token, "attach", wait_js)
                + [macro.command("executeScript", _ESC_JS, "attachEsc", "1 = preview missing, dialog up")]
                + file_dialog.escape_when("${attachEsc} == 1"))
    return _finish("attach", commands, xclick=css(add_files_primary()))


def submit_macro(token: str, guard_js: str, ack_js: str) -> PhaseMacro:
    """Guard (not yet sent, our prompt + preview) → ONE XClick on send → ack probe."""
    commands = (_select() + _probe(token, "guard", guard_js, var=_GUARD_VAR)
                + [macro.command("executeScript", _FLAG_JS, "goFlag", "1 = guard passed"),
                   macro.command("if_v2", "${goFlag} == 1", "", "click only when the guard passed")]
                + _native_click("Send message")
                + [macro.command("end", "", "", "")]
                + _probe(token, "submit", ack_js))
    return _finish("submit", commands, xclick=css(send_click_primary()))


def reset_macro(token: str, clean_js: str) -> PhaseMacro:
    """XClick New Chat → wait for the clean page (the `new_chat` rule)."""
    commands = _select() + _native_click("New Chat") + _probe(token, "reset", clean_js)
    return _finish("reset", commands, xclick=css(new_chat_primary()))


def build_document(phase: PhaseMacro) -> dict:
    """The macro file Ui.Vision reads from `<home>/macros/<Name>.json`."""
    return {"Name": macro.validate_macro_name(phase.name), "CreationDate": macro.creation_date(),
            "Commands": list(phase.commands)}


def provision(spec, phase: PhaseMacro) -> str:
    """Write this phase's macro (hard-drive storage) + the autorun page; page path."""
    target = paths.macro_file(paths.home(spec.home), phase.name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(macro.to_json(build_document(phase)), encoding="utf-8")
    paths.logs_dir(spec.config_dir).mkdir(parents=True, exist_ok=True)
    return str(autorun.write_page(paths.autorun_file(spec.config_dir)))


def log_path(config_dir, token: str, phase: str, stamp: str) -> str:
    """A savelog of its own per phase run (a job never inherits another verdict)."""
    return str(paths.logs_dir(config_dir) / f"job-{token}-{phase}-{stamp}.txt")


def parse_replies(lines, token: str) -> dict:
    """Savelog lines → {phase: data} for THIS token (last rendered answer wins)."""
    out: dict = {}
    for line in tuple(lines or ()):
        found = _REPLY_RE.search(str(line))
        reply = _decode(found.group(1)) if found else None
        if reply and reply.get("token") == token and isinstance(reply.get("data"), dict):
            out[str(reply.get("phase") or "")] = reply["data"]
    return out


def _decode(raw: str):
    """One JSON object or None (torn / unrendered lines are not answers)."""
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None
