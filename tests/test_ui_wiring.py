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


# ── Global-name contract (2026-10-03) ─────────────────────────────────────────
# A top-level `const X = {...}` in a classic <script> is a LEXICAL global: it is
# NOT `window.X`. Boot.bootPanels / _restoreArenaPanels resolve panels through
# window[name] and 22 modules reach the bridge through `window.App.bridge`, so
# every name read that way must be published (`window.X = X`). Before this guard
# 14 of 17 panels were never init()ed — Browse/Scan/URL/Run buttons were dead.

_JS_BUILTINS = {
    "location", "getSelection", "confirm", "prompt", "alert", "setTimeout", "setInterval",
    "clearTimeout", "clearInterval", "innerWidth", "innerHeight", "addEventListener",
    "removeEventListener", "qt", "QWebChannel", "requestAnimationFrame", "getComputedStyle",
    "open", "scrollTo", "devicePixelRatio", "localStorage", "document", "navigator",
    "matchMedia", "event", "onerror", "console", "dispatchEvent", "CustomEvent", "Event",
    "name", "screen", "performance", "close", "focus", "scrollY", "scrollX", "outerWidth",
    "outerHeight", "history", "parent", "top", "self", "frames", "origin", "print",
}
_ASSIGN_RE = re.compile(r"(?:window|globalThis)\.([A-Za-z_$][\w$]*)\s*=(?!=)")
_READ_RE = re.compile(r"(?:window|globalThis)\.([A-Za-z_$][\w$]*)\b(?!\s*=[^=])")
_CONST_RE = re.compile(r"^(?:const|let)\s+([A-Z][\w$]*)\s*=", re.M)


def _js_sources() -> dict:
    return {p: p.read_text(encoding="utf-8") for p in sorted((WEB / "js").rglob("*.js"))}


def _published_globals(sources: dict) -> set:
    published = set()
    for src in sources.values():
        published |= set(_ASSIGN_RE.findall(src))
    return published


def _panel_init_names() -> list:
    src = (WEB / "js" / "arena-app.js").read_text(encoding="utf-8")
    block = re.search(r"_PANEL_INITS\s*=\s*\[(.*?)\]", src, re.S)
    assert block, "arena-app.js must keep the _PANEL_INITS registry"
    return re.findall(r"'([A-Za-z]+)'", block.group(1))


@pytest.mark.unit
def test_every_boot_panel_is_published_on_window():
    """Boot.bootPanels(name) does window[name] — a const-only panel never inits."""
    sources = _js_sources()
    published = _published_globals(sources)
    names = _panel_init_names()
    assert len(names) >= 15, names
    unpublished = [n for n in names if n not in published]
    assert unpublished == [], (
        f"panels in _PANEL_INITS never reach window[name] (dead init, dead buttons): "
        f"{unpublished} — end each module with `window.X = X;`")
    assert "App" in published, "arena-app.js must publish `window.App = App`"


@pytest.mark.unit
def test_every_window_dot_name_read_is_published_somewhere():
    """Any `window.Name` read must have a `window.Name =` writer in some loaded module."""
    sources = _js_sources()
    published = _published_globals(sources)
    declared_consts = set()
    for src in sources.values():
        declared_consts |= set(_CONST_RE.findall(src))
    dangling = {}
    for path, src in sources.items():
        for name in set(_READ_RE.findall(src)):
            if name in published or name in _JS_BUILTINS:
                continue
            if name[:1].isupper() or name in declared_consts:
                dangling.setdefault(name, []).append(path.relative_to(WEB / "js").as_posix())
    assert dangling == {}, f"window.X read but X is only a lexical const (undefined at runtime): {dangling}"


def _strip_js_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


@pytest.mark.unit
def test_panel_export_lines_match_their_const():
    """The export line must name the const actually declared in that file."""
    for path, raw in _js_sources().items():
        src = _strip_js_comments(raw)
        for name in _ASSIGN_RE.findall(src):
            if re.search(rf"window\.{name}\s*=\s*{name}\s*;", src):
                assert re.search(rf"^(?:const|let)\s+{name}\s*=|^function\s+{name}\b", src, re.M), (
                    f"{path.name}: `window.{name} = {name}` but no `const {name}` in this file")


def test_url_table_header_declares_the_tab_column():
    """D-5/D-7: the URL list shows the readable tab id in its own Tab column —
    the header and the row template must stay in step, or every cell shifts."""
    html = (WEB / "index.html").read_text(encoding="utf-8")
    header = re.search(r'<table class="url-table">\s*<thead><tr>(.*?)</tr></thead>', html, re.S)
    assert header, "URL table header not found"
    heads = re.findall(r"<th>(.*?)</th>", header.group(1))
    assert heads[:4] == ["En", "URL", "Tab", "Status"], heads
    assert heads[-1] == "Actions"
    src = (WEB / "js" / "panels" / "url-list" / "render.js").read_text(encoding="utf-8")
    body = src[src.index("rowHtml(u) {"):src.index("  render(urls)")]
    assert body.count("<td") == len(heads), "row cells must match the declared columns"


# ── the app's one Firefox socket is released on close (round 11) ─────────────

def _class_methods(tree: ast.Module, name: str) -> dict:
    """{method name: node} of one class in the module under test."""
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return {item.name: item for item in node.body
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))}
    return {}


def _called_names(node: ast.AST) -> set:
    """Every attribute/keyword-less name called inside a function body."""
    out = set()
    for item in ast.walk(node):
        if isinstance(item, ast.Call):
            func = item.func
            out.add(func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", ""))
    return out


def _imported_names(node: ast.AST) -> set:
    """Module paths imported anywhere inside a function body (lazy imports count)."""
    out = set()
    for item in ast.walk(node):
        if isinstance(item, ast.ImportFrom) and item.module:
            out.add(item.module)
        elif isinstance(item, ast.Import):
            out.update(alias.name for alias in item.names)
    return out


def test_closing_the_window_drops_the_cdp_socket_inside_a_guard():
    """The client disconnect is what close owes the browser — and it must never fail the close.

    `QMainWindow` cannot be imported in this sandbox (no libGL, as everywhere else in
    this file), so the wiring is pinned by AST: `closeEvent` must route through
    `_drop_browser_sockets`, and that helper must disconnect the CDP client inside a
    guard. The deleted Firefox DevTools session (I-62) must not come back here.
    """
    tree = ast.parse(MAIN_WINDOW.read_text(encoding="utf-8"))
    methods = _class_methods(tree, "MainWindow")
    assert "closeEvent" in methods and "_drop_browser_sockets" in methods, sorted(methods)
    assert "_drop_browser_sockets" in _called_names(methods["closeEvent"]), \
        "closing the window must drop the browser sockets"
    body = methods["_drop_browser_sockets"]
    assert "disconnect" in _called_names(body), "the CDP client is disconnected by name"
    assert not any("rdp" in name for name in _imported_names(body)), \
        "the Firefox debugger approach is deleted (I-62)"
    assert any(isinstance(item, ast.Try) for item in ast.walk(body)), \
        "a browser that stopped answering must not break the close"
