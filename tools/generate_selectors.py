#!/usr/bin/env python3
"""RULE 21 selector generator — keeps app/browser/site_adapter.py in lockstep with live probes.

Live code is the source of truth. This tool extracts every CSS selector
expression the live probes actually use, classifies each primary per RULE 21
(semantic > structural > class fragment), and regenerates the SELECTORS map
between the generated markers in app/browser/site_adapter.py.

Sources scanned:
  * JS probe constants in app/browser/cdp_arena.py (region-scoped)
  * whole-file probe queries in app/browser/new_chat.py, output_probes.py
  * SELECTORS_V3 (AST), NEW_CHAT_CANDIDATES (AST), attach_image_cdp defaults (AST)
  * BLOCK_DEFINITIONS selector defaults in app/core/action_blocks.py (AST)
  * plain-JS captcha probes in app/browser/captcha_js/*.js

Usage:
    python tools/generate_selectors.py            # --check: fail if the map drifted
    python tools/generate_selectors.py --write    # regenerate the generated block
    python tools/generate_selectors.py --report   # print the RULE 21 tier report
    python tools/generate_selectors.py --dump     # print every extracted selector (debug)

Generated entries keep the EXACT live order (primary = chain[0], fallbacks =
the rest), because tests/js/*.mjs execute the real probe strings against DOM
stubs (RULE 8) — the map mirrors what the probes try, it never reorders them.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE_ADAPTER = ROOT / "app" / "browser" / "site_adapter.py"
BEGIN_MARK = "# >>> generated:SELECTORS begin"
END_MARK = "# <<< generated:SELECTORS end"

# Scan patterns, generic element probes and internal overlay attrs — not
# site selectors (they are element walks, not locators).
EXCLUDES = {
    "img", "ol", "div", "span", "button", "script",
    "div, span, p, pre", "button, [role=\"button\"]",
    "[data-arena-highlight]",
}

RE_ARRAY = re.compile(r"const\s+sels\s*=\s*\[(.+?)\];", re.S)
RE_QUERY = re.compile(r"""querySelector(?:All)?\(\s*(?:'([^']*)'|"([^"]*)")\s*\)""")
RE_CHECKS = re.compile(r"\{sels:\s*\[(.*?)\]\s*,\s*name:\s*'([^']*)'", re.S)
RE_CLOSEST = re.compile(r"""closest\(\s*(?:'([^']*)'|"([^"]*)")\s*\)""")


# ---------------------------------------------------------------- extraction

def _split_array(inner: str) -> list[str]:
    return re.findall(r"'([^']*)'", inner)


def extract_pairs(region: str, kind: str) -> list[tuple[str, str]]:
    """Ordered (slot, selector) pairs from one text region."""
    if kind == "array":
        m = RE_ARRAY.search(region)
        return [(str(i), s) for i, s in enumerate(_split_array(m.group(1))) if m]
    if kind == "query":
        return [(str(i), m.group(1) or m.group(2)) for i, m in enumerate(RE_QUERY.finditer(region))]
    if kind == "checks":
        pairs = []
        for chain, name in RE_CHECKS.findall(region):
            for i, sel in enumerate(_split_array(chain)):
                pairs.append((f"{name}:{i}", sel))
        return pairs
    if kind == "closest":
        return [(str(i), m.group(1) or m.group(2)) for i, m in enumerate(RE_CLOSEST.finditer(region))]
    if kind.startswith("const:"):
        const = kind.split(":", 1)[1]
        m = re.search(rf"const\s+{const}\s*=\s*'([^']+)'", region)
        return [(const, m.group(1))] if m else []
    raise ValueError(kind)


def resolve_js_concat(src: str, const: str) -> str:
    """Resolve `const X = A + 'lit' + 'lit'` where A is a same-file string const."""
    literals = dict(re.findall(r"const\s+(\w+)\s*=\s*'([^']+)'", src))
    m = re.search(rf"const\s+{const}\s*=\s*(.+?);", src)
    if not m:
        raise ValueError(f"{const} not found")
    expr = m.group(1)
    for name, lit in literals.items():
        expr = expr.replace(name, f"'{lit}'")
    return "".join(re.findall(r"'([^']+)'", expr))  # JS + is plain concatenation


def _triple_quoted(src: str, const: str) -> str:
    m = re.search(rf"{const}\s*=\s*\"\"\"", src)
    if not m:
        raise ValueError(f"{const} not found")
    start = src.index('"""', m.start()) + 3
    end = src.index('"""', start)
    return src[start:end]


def _ast_file(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"))


def _ast_list_const(tree: ast.AST, name: str) -> list[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if getattr(t, "id", None) == name and isinstance(node.value, ast.List):
                    return [e.value for e in node.value.elts if isinstance(e, ast.Constant)]
        elif isinstance(node, ast.AnnAssign):
            if getattr(node.target, "id", None) == name and isinstance(node.value, ast.List):
                return [e.value for e in node.value.elts if isinstance(e, ast.Constant)]
    raise ValueError(f"{name} not found")


def _ast_tuples_first(tree: ast.AST, name: str) -> list[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if getattr(t, "id", None) == name and isinstance(node.value, ast.Tuple):
                    return [t0.elts[0].value for t0 in node.value.elts if isinstance(t0, ast.Tuple)
                            and isinstance(t0.elts[0], ast.Constant)]
    raise ValueError(f"{name} not found")


def _attach_defaults(tree: ast.AST) -> list[str]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "attach_image_cdp":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assign):
                    for t in sub.targets:
                        if getattr(t, "id", None) == "selectors" and isinstance(sub.value, ast.List):
                            return [e.value for e in sub.value.elts if isinstance(e, ast.Constant)]
    raise ValueError("attach_image_cdp defaults not found")


def _block_defaults(tree: ast.AST) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "BLOCK_DEFINITIONS" for t in node.targets):
            d = node.value
            for k, val in zip(d.keys, d.values):
                for kk, v in zip(val.keys, val.values):
                    if kk.value in ("default_selector", "default_click_selector") and isinstance(v, ast.Constant) and v.value:
                        out.append((f"{k.value}:{kk.value}", v.value))
    return out


def collect() -> dict[str, list[tuple[str, str]]]:
    """context_id -> ordered (slot, selector) pairs (raw, before excludes)."""
    ctx: dict[str, list[tuple[str, str]]] = {}
    _collect_arena(ctx)
    _collect_newchat(ctx)
    _collect_output_probes(ctx)
    _collect_cdp_client(ctx)
    _collect_action_blocks(ctx)
    _collect_captcha_js(ctx)
    return ctx


def _collect_arena(ctx: dict) -> None:
    """The 8 JS probe constants in cdp_arena.py (region-scoped by const name)."""
    arena = (ROOT / "app/browser/cdp_arena.py").read_text(encoding="utf-8")
    regions = {
        "arena_find": ("JS_FIND_TEXTAREA", "array"),
        "arena_insert": ("JS_INSERT_PROMPT", "array"),
        "arena_verify_prompt": ("JS_VERIFY_PROMPT", "query"),
        "arena_send_state": ("JS_SEND_STATE", "query"),
        "arena_click_send": ("JS_CLICK_SEND", "array"),
        "arena_verify_attach": ("JS_VERIFY_ATTACHMENT", "array"),
        "arena_page_ready": ("JS_PAGE_READY", "checks"),
        "arena_page_ready_dialog": ("JS_PAGE_READY", "query"),
        "arena_generating": ("JS_IS_GENERATING", "query"),
    }
    for cid, (const, kind) in regions.items():
        ctx[cid] = extract_pairs(_triple_quoted(arena, const), kind)


def _collect_newchat(ctx: dict) -> None:
    newchat = ROOT / "app/browser/new_chat.py"
    ctx["newchat_queries"] = extract_pairs(newchat.read_text(encoding="utf-8"), "query")
    ctx["newchat_candidates"] = [(str(i), s) for i, s in
                                 enumerate(_ast_tuples_first(_ast_file(newchat), "NEW_CHAT_CANDIDATES"))]


def _collect_output_probes(ctx: dict) -> None:
    outp = ROOT / "app/browser/output_probes.py"
    ctx["out_queries"] = extract_pairs(outp.read_text(encoding="utf-8"), "query")
    ctx["out_closest"] = extract_pairs(outp.read_text(encoding="utf-8"), "closest")
    ctx["out_list"] = [(str(i), s) for i, s in
                       enumerate(_ast_list_const(_ast_file(outp), "SELECTORS_V3"))]


def _collect_cdp_client(ctx: dict) -> None:
    cdp = _ast_file(ROOT / "app/browser/cdp_client.py")
    ctx["attach_defaults"] = [(str(i), s) for i, s in enumerate(_attach_defaults(cdp))]


def _collect_action_blocks(ctx: dict) -> None:
    ab = _ast_file(ROOT / "app/core/action_blocks.py")
    ctx["block_defaults"] = _block_defaults(ab)


def _collect_captcha_js(ctx: dict) -> None:
    jsdir = ROOT / "app/browser/captcha_js"
    detect = (jsdir / "detect.js").read_text(encoding="utf-8")
    ctx["detect_consts"] = (extract_pairs(detect, "const:IFRAME") + extract_pairs(detect, "const:WIDGET"))
    if not any(s == "WIDGET" for s, _ in ctx["detect_consts"]):
        ctx["detect_consts"] += [("WIDGET", resolve_js_concat(detect, "WIDGET"))]
    ctx["visible_consts"] = extract_pairs((jsdir / "visible.js").read_text(encoding="utf-8"), "const:IFRAME")
    ctx["inject_consts"] = extract_pairs((jsdir / "inject.js").read_text(encoding="utf-8"), "const:SEL")
    for name in ("detect", "visible", "continue_click", "inject"):
        src = (jsdir / f"{name}.js").read_text(encoding="utf-8")
        for kind in ("query", "closest"):
            pairs = extract_pairs(src, kind)
            if pairs:
                ctx[f"{name}_{kind}"] = pairs


def visible(ctx: dict[str, list[tuple[str, str]]]) -> dict[str, list[tuple[str, str]]]:
    """Drop excludes; keep order and slots intact."""
    return {c: [(s, sel) for s, sel in pairs if sel not in EXCLUDES and "${" not in sel]
            for c, pairs in ctx.items()}


# ------------------------------------------------------------- RULE 21 tiers

SEMANTIC_MARKERS = (
    "[aria-label", "[name=", "[role=", "[type=", "[placeholder", "[title=",
    "[href=", "[alt", "[data-state", "[aria-busy", ":has-text",
)


RE_CLASS = re.compile(r"\.[A-Za-z_\-]")


def tier_of(selector: str) -> str:
    """RULE 21: semantic > structural > class fragment (evaluated on the primary part).

    class fragment = the discriminator is a (Tailwind/BEM) class name;
    structural = :has, descendant chains, ids, bare attribute selectors.
    """
    first = selector.split(",")[0].strip()
    if any(m in first for m in SEMANTIC_MARKERS):
        return "semantic"
    if RE_CLASS.search(first):
        return "class-fragment"
    return "structural"


# ------------------------------------------------------------ entry registry
# (name, [(context, slot), ...] in chain order, metadata)
META_DEFAULT = dict(scope=None, mustBeVisible=True, mustBeEnabled=False, expectedCount=0,
                    textCondition=None, verification="")

ENTRIES: list[tuple[str, list[tuple[str, str]], dict]] = [
    ("prompt_textarea", [("arena_find", "0"), ("arena_find", "1"), ("arena_find", "2"),
                         ("arena_insert", "0"), ("arena_insert", "1"), ("arena_insert", "2"),
                         ("arena_verify_prompt", "0"), ("arena_page_ready", "prompt:0"),
                         ("newchat_queries", "0"), ("newchat_queries", "1"),
                         ("block_defaults", "HIGHLIGHT_PROMPT:default_selector"),
                         ("block_defaults", "INSERT_PROMPT:default_selector"),
                         ("block_defaults", "VERIFY_PROMPT:default_selector")],
     dict(scope="form", mustBeEnabled=True, expectedCount=1,
          verification="after insertion, textarea.value equals expected prompt exactly (RULE 22 read-back)")),
    ("send_button", [("arena_send_state", "0"), ("arena_page_ready", "send:0"),
                     ("block_defaults", "HIGHLIGHT_SUBMIT:default_selector")],
     dict(scope="form", mustBeEnabled=True, expectedCount=1,
          verification="wait for disabled->enabled transition before click; state probe checks .disabled itself")),
    ("send_button_click", [("arena_click_send", "0"), ("arena_click_send", "1"), ("arena_click_send", "2"),
                           ("block_defaults", "SUBMIT:default_selector")],
     dict(scope="form", mustBeEnabled=True, expectedCount=1,
          verification="click once; JS loop additionally requires visible + not disabled")),
    ("file_input", [("arena_page_ready", "file:0"), ("attach_defaults", "2"),
                    ("block_defaults", "HIGHLIGHT_ATTACH:default_selector"),
                    ("block_defaults", "ATTACH_IMAGE:default_selector")],
     dict(scope="form", mustBeVisible=False, mustBeEnabled=True, expectedCount=1,
          verification="hidden input; CDP DOM.setFileInputFiles can set files")),
    ("file_input_cdp", [("attach_defaults", "0"), ("attach_defaults", "1")],
     dict(scope="form", mustBeVisible=False, mustBeEnabled=True, expectedCount=1,
          verification="attach_image_cdp scope-first chain (form-scoped, accept-constrained)")),
    ("output_region", [("arena_page_ready", "output:0"), ("arena_page_ready", "output:1")],
     dict(expectedCount=1, verification="output observation container (or app shell) exists — readiness sanity check, the other four checks are the real gates")),
    ("security_dialog", [("arena_page_ready_dialog", "0"), ("detect_query", "0"),
                         ("visible_query", "0"), ("continue_click_query", "0"),
                         ("inject_query", "0")],
     dict(expectedCount=0, textCondition="Security Verification",
          verification="if visible → USER_ACTION_REQUIRED, pause, show page to user (RULE 20)")),
    ("processing_spinner", [("arena_generating", "0"), ("out_queries", "0"), ("out_queries", "1")],
     dict(verification="spinner visible near model label = generating; wait for it to disappear",
          tierNote="state detector — a fallback that false-positives (bare tag/aria-busy) extends waits; safe alternative needs live verification (RULE 22); animate-spin is a core Tailwind utility")),
    ("attachment_preview_image", [("arena_verify_attach", "0"), ("arena_verify_attach", "1"),
                                  ("arena_verify_attach", "2")],
     dict(scope="form", expectedCount=1,
          verification="preview is new, visible, inside the active composer area")),
    ("output_image", [("out_list", "0"), ("out_list", "1"), ("out_list", "2"), ("out_list", "3"),
                      ("out_list", "4"), ("out_list", "5"), ("out_list", "6"), ("out_list", "7"),
                      ("out_list", "8"), ("out_list", "9"), ("out_list", "10"), ("out_list", "11"),
                      ("out_list", "12"), ("out_list", "13"), ("out_list", "14"),
                      ("block_defaults", "OBSERVE_BASELINE:default_selector")],
     dict(verification="capture all srcs before submit; new output must be new vs baseline (RULE 15)")),
    ("wait_output_default", [("block_defaults", "WAIT_OUTPUT:default_selector")],
     dict(verification="WAIT_OUTPUT block default selector list (user-configurable, RULE 3)",
          tierNote="user-configurable block default; a broad structural part (bare main img) risks false output detection (e.g. attachment previews)")),
    ("spinner_check_default", [("block_defaults", "AWAIT_PROCESSING_IMAGE:default_selector")],
     dict(verification="AWAIT_PROCESSING_IMAGE block default (Playwright :has-text parts)")),
    ("model_label", [("out_queries", "2")],
     dict(scope="div.flex.min-w-0.flex-1.items-center.gap-2",
          verification="model/answer label span next to the spinner",
          tierNote="informational only — a miss degrades to label 'unknown' (pre-existing miss path, no behaviour at risk)")),
    ("model_label_scope", [("out_closest", "0")],
     dict(verification="closest() scope for reading the model label",
          tierNote="closest() takes one selector list — a broad comma part matches the nearest div and inverts the scope; a JS-level fallback is not representable in the map model")),
    ("message_list_reverse", [("out_queries", "3"), ("out_queries", "10")],
     dict(verification="ol with flex-col-reverse → newest message renders first",
          tierNote="a false positive flips the layout direction (output correlation inverts); generic `ol` is too broad")),
    ("message_container", [("out_closest", "1")],
     dict(verification="message bubble container holding the output image",
          tierNote="closest() list already carries the structural `div[data-message-id]` part (tier = primary part only)")),
    ("message_container_plain", [("out_closest", "3"), ("out_closest", "4")],
     dict(verification="message container fallback without data-message-id",
          tierNote="closest() to the job bubble; on drift the detection degrades gracefully via the structural output_image chains (src patterns, main scope)")),
    ("new_chat_button", [("newchat_candidates", "0"), ("newchat_candidates", "1"),
                         ("newchat_candidates", "2")],
     dict(scope="li[data-sidebar=\"menu-item\"]", mustBeEnabled=True, expectedCount=1,
          textCondition="New Chat", verification="click returns to a clean new chat")),
    ("recaptcha_iframe", [("detect_consts", "IFRAME"), ("visible_consts", "IFRAME")],
     dict(verification="challenge iframe — badge anchor excluded by geometry + closest(.grecaptcha-badge)")),
    ("recaptcha_widget", [("detect_consts", "WIDGET")],
     dict(verification="any reCAPTCHA widget (badge anchor or challenge frame)")),
    ("recaptcha_response_field", [("detect_query", "1")],
     dict(mustBeVisible=False, verification="token field read-back (verify the solve token landed)")),
    ("recaptcha_response_field_inject", [("inject_consts", "SEL")],
     dict(mustBeVisible=False, verification="token fields written by the inject probe (every field)")),
    ("grecaptcha_badge", [("detect_closest", "0"), ("visible_closest", "0")],
     dict(mustBeVisible=False, verification="badge identity exclusion — never a visible challenge",
          tierNote="Google-owned stable class; a false negative prompts a manual solve (visible, recoverable) — no semantic equivalent exists")),
    ("captcha_integration_script", [("detect_query", "2")],
     dict(mustBeVisible=False, verification="enterprise vs unknown integration detection")),
    ("captcha_image", [("detect_query", "3")],
     dict(verification="image CAPTCHA inside the dialog")),
    ("sitekey_attr", [("detect_query", "4"), ("detect_query", "5")],
     dict(mustBeVisible=False, verification="sitekey read — dialog-scoped first, then document")),
    ("add_files_button", [("block_defaults", "ATTACH_IMAGE:default_click_selector")],
     dict(scope="form", mustBeEnabled=True, expectedCount=1,
          verification="click triggers file chooser (ATTACH_IMAGE click_selector)")),
    ("attachment_preview_block", [("block_defaults", "VERIFY_ATTACHMENT:default_selector")],
     dict(scope="form", expectedCount=1, verification="VERIFY_ATTACHMENT block default",
          tierNote="user-configurable block default (RULE 3); `form img` can't be live-verified — risks a false 'verified'")),
    ("security_check_default", [("block_defaults", "CHECK_SECURITY:default_selector")],
     dict(verification="CHECK_SECURITY block default (Playwright :has-text parts, user-configurable)")),
    ("recaptcha_dialog_scope", [("inject_closest", "0")],
     dict(verification="dialog scope for token-field scoping in the inject probe")),
    ("recaptcha_callback_attr", [("inject_query", "1"), ("inject_query", "2")],
     dict(mustBeVisible=False, verification="data-callback on the widget — solve-callback search")),
    ("recaptcha_anchor_iframe", [("inject_query", "3"), ("inject_query", "4")],
     dict(verification="anchor iframe src pattern")),
]


def build_chains(ctx: dict[str, list[tuple[str, str]]]) -> tuple[dict[str, list[str]], list[str]]:
    """name -> chain (deduped, live order) + coverage errors."""
    slots: dict[str, dict[str, str]] = {c: {s: sel for s, sel in pairs} for c, pairs in ctx.items()}
    refs_seen: set[tuple[str, str]] = set()
    chains, errors = {}, []
    for name, refs, _meta in ENTRIES:
        chain: list[str] = []
        for cid, slot in refs:
            if slot not in slots.get(cid, {}):
                errors.append(f"{name}: slot ({cid},{slot}) does not exist")
                continue
            if (cid, slot) in refs_seen:
                errors.append(f"slot ({cid},{slot}) referenced twice")
            refs_seen.add((cid, slot))
            sel = slots[cid][slot]
            if sel not in chain:
                chain.append(sel)
        chains[name] = chain
    errors.extend(_coverage_errors(ctx, refs_seen))
    return chains, errors


def _coverage_errors(ctx: dict, refs_seen: set) -> list[str]:
    """Every non-excluded extracted selector must be owned by exactly one entry."""
    errors = []
    for cid, pairs in ctx.items():
        for slot, sel in pairs:
            if sel in EXCLUDES or "${" in sel:
                continue
            if (cid, slot) not in refs_seen:
                errors.append(f"UNCOVERED {cid}[{slot}] = {sel!r}")
    return errors


# --------------------------------------------------------------- rendering

def render_block(chains: dict[str, list[str]], date: str) -> str:
    lines = [BEGIN_MARK,
             "# Generated by tools/generate_selectors.py — do not edit by hand.",
             "# Chains keep exact live order (primary = chain[0], fallbacks = rest):",
             "# tests/js/*.mjs execute the real probe strings (RULE 8).",
             "SELECTORS: Dict[str, SelectorObject] = {"]
    for name, refs, meta in ENTRIES:
        lines.extend(_render_entry(name, chains[name], meta, refs, date))
    lines += ["}", ""]
    return "\n".join(lines) + END_MARK + "\n"


def _render_entry(name: str, chain: list[str], meta: dict, refs: list, date: str) -> list:
    m = {**META_DEFAULT, **meta}
    tct = "contains" if m["textCondition"] else "equals"
    ev = "; ".join(dict.fromkeys(cid for cid, _ in refs))
    lines = [f"    {name!r}: SelectorObject(", f"        name={name!r},",
             f"        primary={chain[0]!r},"]
    if len(chain) > 1:
        lines.append(f"        fallbacks={chain[1:]!r},")
    lines += [f"        scope={m['scope']!r},",
              f"        mustBeVisible={m['mustBeVisible']},",
              f"        mustBeEnabled={m['mustBeEnabled']},",
              f"        expectedCount={m['expectedCount']},",
              f"        textCondition={m['textCondition']!r},",
              f"        textConditionType={tct!r},",
              f"        verification={m['verification']!r},",
              f"        evidence={ev!r},",
              f"        lastVerified={date!r},",
              f"        tier={tier_of(chain[0])!r},",
              "    ),"]
    return lines


def write_site_adapter(block: str) -> None:
    src = SITE_ADAPTER.read_text(encoding="utf-8")
    b = src.index(BEGIN_MARK)
    e = src.index(END_MARK) + len(END_MARK)
    rest = src[e:].lstrip("\n")  # idempotent: exactly one blank line after the marker
    SITE_ADAPTER.write_text(src[:b] + block.rstrip("\n") + "\n\n" + rest, encoding="utf-8")


def current_map() -> dict[str, list[str]]:
    import importlib
    sys.path.insert(0, str(ROOT))
    import app.browser.site_adapter as sa
    importlib.reload(sa)
    return {n: sel.all_selectors() for n, sel in sa.SELECTORS.items()}


def check(ctx: dict[str, list[tuple[str, str]]]) -> int:
    chains, errors = build_chains(ctx)
    if errors:
        print("\n".join(f"  ✗ {e}" for e in errors))
    live = current_map()
    if set(live) != set(chains):
        errors.append(f"entry set differs: map={sorted(set(live) - set(chains))} code={sorted(set(chains) - set(live))}")
    for name in live:
        if name in chains and live[name] != chains[name]:
            errors.append(f"chain drift {name}:\n    map={live[name]}\n    code={chains[name]}")
    if errors:
        print(f"DRIFT — {len(errors)} problem(s). Run: python tools/generate_selectors.py --write")
        return 1
    print(f"OK — {len(chains)} entries in lockstep with live probes ({date_str()}).")
    return 0


def date_str() -> str:
    from datetime import date
    return date.today().isoformat()


def report(ctx: dict[str, list[tuple[str, str]]]) -> int:
    chains, errors = build_chains(ctx)
    for name, _refs, meta in ENTRIES:
        chain = chains[name]
        t = tier_of(chain[0])
        flag = ""
        if t == "class-fragment" and len(chain) == 1:
            note = meta.get("tierNote")
            flag = (f"  · sole class-fragment — accepted: {note}" if note
                    else "  ⚠ sole class-fragment (RULE 21: add a semantic/structural fallback)")
        elif t == "class-fragment":
            flag = "  · class-fragment primary (fallbacks reach better tiers)"
        print(f"  {t:15s} {name:32s} {len(chain):2d} sel{flag}")
    if errors:
        print("\n" + "\n".join(f"  ✗ {e}" for e in errors))
        return 1
    return 0


def main() -> int:
    args = set(sys.argv[1:])
    try:
        ctx = visible(collect())
    except (ValueError, FileNotFoundError) as e:
        print(f"extraction failed: {e}")
        return 1
    if "--dump" in args:
        return _dump(ctx)
    if "--write" in args:
        return _write(ctx)
    if "--report" in args:
        return report(ctx)
    return check(ctx)


def _dump(ctx: dict) -> int:
    for cid, pairs in sorted(ctx.items()):
        print(f"== {cid}")
        for slot, sel in pairs:
            print(f"   [{slot}] {sel}")
    return 0


def _write(ctx: dict) -> int:
    chains, errors = build_chains(ctx)
    if errors:
        print("\n".join(f"  ✗ {e}" for e in errors))
        return 1
    write_site_adapter(render_block(chains, date_str()))
    print(f"written — {len(chains)} entries")
    return check(ctx)


if __name__ == "__main__":
    raise SystemExit(main())
