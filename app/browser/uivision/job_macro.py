# ideal-size: ~330 lines reason=the five macro documents and their baking rules are one ABI: a stage's payload shape, its guards and its name belong in one place, or a payload edit has to touch three files (RULE 18.2)
"""The Firefox image job's macro documents — five stages, one run each.

A stage macro is the `identify.py` shape applied to one job phase: `selectWindow`
on the pooled tab with an EMPTY Value (reuse, never open — `E210` if it is gone),
`bringBrowserToForeground` (native input lands on the foreground window), the
stage's probes/clicks, and one `echo` per answer so the savelog carries the facts
(`job_replies` reads them).

Two command-line values ride the launch, exactly as the framework test's do:
`${!cmd_var1}` = the stage's in-page budget (the launch's `pause_ms`) and
`${!cmd_var3}` = the tab target. Everything else is **baked into the file** —
the probe bodies receive their payload as an inline `JSON.parse("…")` literal
(`_bake`), so the prompt (multiline Unicode), the image path, the token and the
selector lists never travel through a command line or through XType, and no
probe depends on `${!cmd_var2}` (its body falls back to `{}` if it is unset).
Each stage gets a per-job name, so the extension can never serve a cached
document.

Every click is `XClick` (native OS input) and `refuse_dom_clicks` runs on every
document, so a JS-level mouse command can never slip in.

Imports: browser layer only (probe builders, probe_selectors, sibling modules).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .. import probe_selectors
from . import autorun
from . import job_probes
from . import job_replies
from . import job_submit_probes
from . import macro as uv_macro
from . import paths

STAGES = ("prepare", "submit", "probe", "fetch", "newchat")
PREFIX = "Arena_Job_"
# The token-container scan's element set — Chrome's own (`output_probes` walks
# `div, span, p, pre`); structural, not a site selector.
TOKEN_SCAN = ("div", "span", "p", "pre")
UNTIL = {"prepare": "ready", "newchat": "clean"}

BUDGET_MS = {"prepare": 20000, "submit": 0, "probe": 4000, "fetch": 30000, "newchat": 12000}
GENERATION_FALLBACK_MS = 180000
MAX_GENERATION_MS = 600000

# The savelog markers — one answer per line, last occurrence wins (job_replies).
STATE_MARK = job_replies.STATE_MARK
STATE2_MARK = "ARENA_STATE2="
ATTACH_MARK = job_replies.ATTACH_MARK
ATTACH_SEL_MARK = "ARENA_ATTACH_SEL="
REMOVE_SEL_MARK = "ARENA_REMOVE_SEL="
PROMPT_MARK = job_replies.PROMPT_MARK
GUARD_MARK = job_replies.GUARD_MARK
WHY_MARK = "ARENA_WHY="
SEND_SEL_MARK = "ARENA_SEND_SEL="
SUBMIT_MARK = job_replies.SUBMIT_MARK
RESULT_MARK = job_replies.RESULT_MARK
DATA_MARK = job_replies.DATA_MARK
NEWCHAT_SEL_MARK = "ARENA_NEWCHAT_SEL="


@dataclass(frozen=True)
class StageInputs:
    """Everything one stage macro bakes in — plus the launch's own number.

    `budget_ms` becomes the launch's `pause_ms` (`${!cmd_var1}`, the probes' wait
    budget); the tab target (`${!cmd_var3}`) is the lane's. The click locator is
    found in the page at run time (`job_probes` locate → a macro variable), so
    `${!cmd_var2}` stays unused — a stored selector beats a pre-guessed one.
    """

    stage: str
    token: str = ""
    image_path: str = ""
    file_name: str = ""
    prompt: str = ""
    baseline: tuple = ()
    src: str = ""
    budget_ms: int = 0
    extra: dict = field(default_factory=dict)


def job_selectors() -> dict:
    """Every selector list the job's probes receive — `probe_selectors` only (RULE 21)."""
    dialog = probe_selectors.security_dialog_check()
    return {
        "textarea": probe_selectors.textarea_selectors(),
        "send": probe_selectors.send_click_selectors(),
        "preview": probe_selectors.attachment_preview_selectors(),
        "output": probe_selectors.output_image_selectors(),
        "spinner": [probe_selectors.spinner_selector()],
        "security": [dialog["sel"]],
        "newchat": probe_selectors.new_chat_selectors(),
        "attach": probe_selectors.add_files_selectors(),
        "remove": probe_selectors.remove_file_selectors(),
        "blocks": list(TOKEN_SCAN),
        "readiness": probe_selectors.readiness_checks(),
    }


def payload(inputs: StageInputs) -> str:
    """The probe payload for one stage (compact JSON, exact Unicode, RULE 21 selectors)."""
    data = {
        "job": inputs.stage,
        "sel": job_selectors(),
        "secText": probe_selectors.security_dialog_text(),
        "file": inputs.file_name,
        "prompt": inputs.prompt,
        "expect": job_replies.prompt_hash(inputs.prompt) if inputs.prompt else "",
        "token": inputs.token,
        "baseline": list(inputs.baseline),
        "src": inputs.src,
        "until": UNTIL.get(inputs.stage, ""),
    }
    data.update(inputs.extra)
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def macro_name(stage: str, token: str) -> str:
    """`Arena_Job_<Stage>_<token>` — one file per job and stage (no cache, traceable)."""
    if stage not in STAGES:
        raise ValueError(f"unknown job stage: {stage!r}")
    safe = "".join(ch for ch in str(token or "") if ch.isalnum() or ch in "-_")[:40]
    return uv_macro.validate_macro_name(f"{PREFIX}{stage.title()}_{safe or 'run'}")


def budget_for(stage: str, timeout_ms: int = 0) -> int:
    """The stage's in-page budget (ms); the submit's is the generation timeout."""
    if stage == "submit":
        want = int(timeout_ms or 0) or GENERATION_FALLBACK_MS
        return max(1000, min(MAX_GENERATION_MS, want))
    return BUDGET_MS.get(stage, 5000)


def generation_timeout_ms(bridge) -> int:
    """The configured generation timeout in ms (Chrome's `timeouts.generation`)."""
    try:
        seconds = int(bridge.state.settings.timeouts.get("generation", 180))
    except Exception:
        seconds = 180
    return max(1000, min(MAX_GENERATION_MS, seconds * 1000))


def _bake(body: str, inputs: StageInputs) -> str:
    """Bake the payload into a probe body; `${!cmd_var1}` stays the run's budget."""
    return body.replace(uv_macro.TARGET_VAR, json.dumps(payload(inputs), ensure_ascii=False))


def _locate(inputs: StageInputs, key: str, pick: str = "first", **extra) -> str:
    """A locate probe body for one site_adapter list (never a selector literal)."""
    data = {"list": job_selectors()[key], "pick": pick, "key": key, "enabledOnly": True}
    data.update(extra)
    return _bake(job_probes.build_locate_js(),
                 StageInputs(stage=inputs.stage, token=inputs.token, extra=data))


def _tab_commands() -> list:
    """Reuse the pooled tab and raise its window — never open or close anything."""
    return [
        uv_macro.command("selectWindow", uv_macro.TAB_VAR, "",
                         "reuse the pooled tab (Value EMPTY: never opens a page — E210 if gone)"),
        uv_macro.command("bringBrowserToForeground", "", "",
                         "native input lands on the foreground window"),
    ]


def _js(body: str, var: str, desc: str) -> dict:
    return uv_macro.command("executeScript", body, var, desc)


def _echo(mark: str, var: str, desc: str) -> dict:
    return uv_macro.command("echo", f"{mark}${{{var}}}", "blue", desc)


def _guarded_click(loc_var: str, desc: str) -> list:
    """One native click behind a non-empty locator guard (never a JS click)."""
    return [uv_macro.command("if", f'"${{{loc_var}}}" != ""', "", desc),
            uv_macro.command("XClick", f"${{{loc_var}}}", "", desc),
            uv_macro.command("end", "", "", "end of the guarded click")]


def _prepare_baseline(inputs: StageInputs) -> list:
    """Baseline snapshot, then drop at most one stale tile (a refusal risk otherwise)."""
    state = _bake(job_probes.build_state_js(), inputs)
    return [_js(state, "arenaState", "baseline before attaching"),
            _echo(STATE_MARK, "arenaState", "baseline answer"),
            _js(_locate(inputs, "remove", "last"), "arenaRemove",
                "locate the last stale tile's remove button"),
            _echo(REMOVE_SEL_MARK, "arenaRemove", "stale-tile locator"),
            uv_macro.command("if", '"${arenaRemove}" != ""', "", "clear one stale attachment first"),
            uv_macro.command("XClick", "${arenaRemove}", "", "drop the stale tile (never submitted)"),
            uv_macro.command("pause", "500", "", "let React drop the tile"),
            _js(state, "arenaState2", "baseline after the cleanup"),
            _echo(STATE2_MARK, "arenaState2", "post-cleanup baseline"),
            uv_macro.command("end", "", "", "end of the stale-tile cleanup")]


def _prepare_attach(inputs: StageInputs) -> list:
    """The native attach: XClick the Add files button, XType the path, one Enter."""
    return [_js(_locate(inputs, "attach"), "arenaAttach", "locate the Add files button"),
            _echo(ATTACH_SEL_MARK, "arenaAttach", "attach-button locator"),
            uv_macro.command("if", '"${arenaAttach}" != ""', "", "open the native file dialog"),
            uv_macro.command("XClick", "${arenaAttach}", "", "native click on Add files"),
            uv_macro.command("pause", "1500", "", "the OS dialog needs a moment"),
            uv_macro.command("XType", inputs.image_path, "", "type the absolute path into the dialog"),
            uv_macro.command("XType", "${KEY_ENTER}", "", "confirm the dialog (once)"),
            uv_macro.command("end", "", "", "end of the attach block")]


def _prepare_verify(inputs: StageInputs) -> list:
    """Prove the attachment, insert the prompt, read it back, run the guard."""
    return [_js(_bake(job_probes.build_attach_js(), inputs), "arenaAttachRep",
                "wait for exactly one new preview matching the sent file"),
            _echo(ATTACH_MARK, "arenaAttachRep", "attachment answer"),
            _js(_bake(job_submit_probes.build_prompt_js(), inputs), "arenaPrompt",
                "insert the final prompt, read it back"),
            _echo(PROMPT_MARK, "arenaPrompt", "prompt answer"),
            _js(_bake(job_submit_probes.build_guard_js(), inputs), "arenaGuard",
                "pre-submit checkpoint"),
            _echo(GUARD_MARK, "arenaGuard", "checkpoint answer"),
            _js(_bake(job_submit_probes.build_guard_why_js(), inputs), "arenaWhy",
                "why the checkpoint refused (read-only)"),
            _echo(WHY_MARK, "arenaWhy", "checkpoint reason")]


def prepare_commands(inputs: StageInputs) -> list:
    """Baseline → cleanup → attach → prompt → guard (the whole pre-submit half)."""
    return [*_tab_commands(), *_prepare_baseline(inputs), *_prepare_attach(inputs),
            *_prepare_verify(inputs)]


def _submit_verify(inputs: StageInputs) -> list:
    """Re-insert/read back the prompt and re-run the guard in front of the click."""
    return [_js(_bake(job_submit_probes.build_prompt_js(), inputs), "arenaPrompt",
                "re-insert and read back the prompt"),
            _echo(PROMPT_MARK, "arenaPrompt", "prompt answer"),
            _js(_bake(job_submit_probes.build_guard_js(), inputs), "arenaGuard",
                "pre-submit checkpoint"),
            _echo(GUARD_MARK, "arenaGuard", "checkpoint answer"),
            _js(_bake(job_submit_probes.build_guard_why_js(), inputs), "arenaWhy",
                "why the checkpoint refused (read-only)"),
            _echo(WHY_MARK, "arenaWhy", "checkpoint reason"),
            _js(_locate(inputs, "send"), "arenaSend", "locate the enabled Send button"),
            _echo(SEND_SEL_MARK, "arenaSend", "send-button locator")]


def _submit_click() -> list:
    """Exactly one XClick, only through the guard, with the click count recorded."""
    return [uv_macro.command("store", "0", "arenaSubmit", "no click yet"),
            uv_macro.command("if", '"${arenaGuard}" == "true"', "", "the only path to a click"),
            uv_macro.command("XClick", "${arenaSend}", "", "ONE native click on Send"),
            uv_macro.command("store", "1", "arenaSubmit", "the click happened"),
            uv_macro.command("end", "", "", "end of the guarded submit"),
            _echo(SUBMIT_MARK, "arenaSubmit", "submit count (exactly-once evidence)")]


def submit_commands(inputs: StageInputs) -> list:
    """Verify → the guarded single Send click → wait for the correlated result."""
    return [*_tab_commands(), *_submit_verify(inputs), *_submit_click(),
            _js(_bake(job_submit_probes.build_result_js(), inputs), "arenaResult",
                "wait for the correlated new output image"),
            _echo(RESULT_MARK, "arenaResult", "result answer")]


def probe_commands(inputs: StageInputs) -> list:
    """Observation only: what the page holds now (recovery evidence, no clicks)."""
    return [*_tab_commands(),
            _js(_bake(job_probes.build_state_js(), inputs), "arenaState", "page state now"),
            _echo(STATE_MARK, "arenaState", "state answer"),
            _js(_bake(job_submit_probes.build_result_js(), inputs), "arenaResult",
                "any correlated result already on the page"),
            _echo(RESULT_MARK, "arenaResult", "result answer")]


def fetch_commands(inputs: StageInputs) -> list:
    """The page's own fetch → canvas for the correlated src; base64 rides the log."""
    return [*_tab_commands(),
            _js(_bake(job_probes.build_fetch_js(), inputs), "arenaData",
                "fetch the correlated image in-page (credentials), canvas fallback"),
            _echo(DATA_MARK, "arenaData", "image bytes as base64")]


def newchat_commands(inputs: StageInputs) -> list:
    """Native New Chat click, then prove the clean composer in the page."""
    return [*_tab_commands(),
            _js(_locate(inputs, "newchat"), "arenaNewChat", "locate the New Chat link"),
            _echo(NEWCHAT_SEL_MARK, "arenaNewChat", "new-chat locator"),
            *_guarded_click("arenaNewChat", "native click on New Chat"),
            uv_macro.command("pause", "800", "", "let the fresh chat render"),
            _js(_bake(job_probes.build_state_js(), inputs), "arenaState", "prove the clean page"),
            _echo(STATE_MARK, "arenaState", "clean-state answer")]


_BUILDERS = {"prepare": prepare_commands, "submit": submit_commands, "probe": probe_commands,
             "fetch": fetch_commands, "newchat": newchat_commands}


def build_document(inputs: StageInputs) -> dict:
    """The macro document for one stage (`<home>/macros/<Name>.json`)."""
    commands = _BUILDERS[inputs.stage](inputs)
    uv_macro.refuse_dom_clicks(commands)
    return {"Name": macro_name(inputs.stage, inputs.token),
            "CreationDate": uv_macro.creation_date(), "Commands": commands}


def write_stage(spec, inputs: StageInputs):
    """Write one stage's macro (hard-drive storage) and return its path."""
    target = paths.macro_file(paths.home(spec.home), macro_name(inputs.stage, inputs.token))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(uv_macro.to_json(build_document(inputs)), encoding="utf-8")
    return target


def page(spec) -> str:
    """The shared autorun page every stage launches through."""
    paths.logs_dir(spec.config_dir).mkdir(parents=True, exist_ok=True)
    return str(autorun.write_page(paths.autorun_file(spec.config_dir)))


def log_path(config_dir, stage: str, stamp: str) -> str:
    """A savelog name of its own — two stages never share one verdict file."""
    return str(paths.logs_dir(config_dir) / f"{stage}-{stamp}.txt")
