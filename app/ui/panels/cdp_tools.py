"""CDP tools panel — highlight demos, browser config, connection test flows.

ideal-size(reason): 9-slot CDP surface plus per-key config splits — set/get/
launch each exceed 20 LOC as one function, so read/parse/apply phases live
beside their single callers per RULE 16; splitting the file would scatter
slot+phase pairs. The browser table (Chrome — the one registered browser) lives
in app/browser/browsers.py — this module only resolves it for the panel.
Browser imports stay lazy (fault tolerance, R5–R7
precedent); only run_state.schedule_coro is hoisted (services never
import ui).
"""

import json
from typing import NamedTuple

from app.services.run_state import schedule_coro
from app.ui.qt_compat import Slot
from app.browser import browsers
from app.browser.probe_selectors import textarea_primary

HighlightArgs = NamedTuple("HighlightArgs", [("selector", str), ("color", str),
                                             ("duration_ms", int), ("caption", str)])


def emit_highlight_demo(bridge) -> None:
    """Static overlay rect for the click-demo highlight."""
    duration = bridge.config.get_state("highlight_duration", 3)
    rect = {
        "x": 200,
        "y": 200,
        "width": 320,
        "height": 180,
        "duration": duration,
        "label": "Clicked element"
    }
    bridge.highlight_rect.emit(json.dumps(rect))


async def do_highlight_demo_cdp(bridge, img_id: str) -> None:
    """Live demo: highlight the composer box + overlay the image rect."""
    try:
        duration = bridge.config.get_state("highlight_duration", 3)
        duration_ms = int(duration * 1000) if duration else 2000
        from app.browser.cdp_arena import CDPArenaController
        ctrl = CDPArenaController(bridge.cdp, log_callback=lambda m: bridge._log(m, "info"))
        await ctrl.highlight_selector(textarea_primary(), color="#FF0000", duration_ms=duration_ms, caption=f"Image {img_id[:8]}" if img_id else "Clicked element")
        bridge.highlight_rect.emit(json.dumps({"x": 200, "y": 200, "width": 320, "height": 180, "duration": duration, "label": f"Image {img_id}" if img_id else "Clicked element"}))
    except Exception as e:
        bridge._log(f"Highlight failed: {e}", "warn")


def report_highlight_result(bridge, args, result_json) -> None:
    """Parse probe output; overlay the rect or log not-found."""
    try:
        data = json.loads(result_json) if isinstance(result_json, str) else result_json
        if data.get("found") and data.get("rect"):
            r = data["rect"]
            rect = {
                "x": r.get("x", 0), "y": r.get("y", 0),
                "width": r.get("width", 100), "height": r.get("height", 100),
                "duration": (args.duration_ms or 2000) / 1000,
                "label": args.caption or args.selector,
                "color": args.color,
            }
            bridge.highlight_rect.emit(json.dumps(rect))
            bridge._log(f"🔍 Highlighted {args.selector} at {r}", "success")
        else:
            bridge._log(f"⚠ Highlight not found: {args.selector}", "warn")
    except Exception as e:
        bridge._log(f"Highlight parse failed: {e}", "warn")


async def do_highlight(bridge, args) -> None:
    """Evaluate the highlight probe; report found/rect to the UI."""
    from app.browser.dom_highlight import build_highlight_js
    try:
        js = build_highlight_js(args.selector, args.color or "#FF0000", args.duration_ms or 2000, args.caption or args.selector, clear_first=True)
        result_json = await bridge.cdp.evaluate(js)
        if result_json:
            report_highlight_result(bridge, args, result_json)
    except Exception as e:
        bridge._log(f"Highlight failed: {e}", "error")


async def do_clear_highlights(bridge) -> None:
    """Clear page highlights via the clear probe."""
    try:
        from app.browser.dom_highlight import build_clear_js
        js = build_clear_js()
        await bridge.cdp.evaluate(js)
        bridge._log("Highlights cleared", "info")
    except Exception as e:
        bridge._log(f"Clear highlights failed: {e}", "error")


def active_browser_id(config) -> str:
    """The selected browser id (an unknown stored value falls back to Chrome)."""
    stored = config.get_state("active_browser", browsers.default_profile().id)
    profile = browsers.profile_of(stored)
    return profile.id if profile else browsers.default_profile().id


def browser_settings(config) -> dict:
    """Per-browser rows to work from: stored override -> legacy cdp_* -> registry default.

    Empty values mean "not set" (the registry default wins), so a panel that
    sends blank fields for a browser it never configured cannot erase it. The
    legacy `cdp_user_data_dir`/`cdp_extra_args` pair keeps feeding Chrome until
    the browser map has a row of its own.
    """
    stored = config.get_state("cdp_browsers", {}) or {}
    legacy = {"user_data_dir": config.get_state("cdp_user_data_dir", ""),
              "extra_args": config.get_state("cdp_extra_args", "")}
    default_id = browsers.default_profile().id
    rows = {}
    for profile in browsers.PROFILES:
        saved = dict(stored.get(profile.id) or {})
        was = legacy if profile.id == default_id else {}
        rows[profile.id] = {
            "enabled": bool(saved.get("enabled", True)),
            "user_data_dir": saved.get("user_data_dir") or was.get("user_data_dir") or profile.data_dir_default,
            "extra_args": saved.get("extra_args") or was.get("extra_args") or profile.extra_args_default,
            "port": saved.get("port") or 0,
        }
    return rows


def read_cdp_config(config) -> dict:
    """Configured values: shared host + BASE port + the active browser's dir/args."""
    entries = browser_settings(config)
    active = active_browser_id(config)
    row = entries[active]
    return {
        "host": config.get_state("cdp_host", "127.0.0.1"),
        "port": config.get_state("cdp_port", 9222),
        "user_data_dir": row["user_data_dir"],
        "extra_args": row["extra_args"],
        "url_pattern": config.get_state("url_pattern", "arena.ai"),
        "browser": active,
        "browsers": entries,
    }


def resolved_port(cfg, browser_id: str) -> int:
    """The endpoint one browser listens on: shared base + its registry offset."""
    profile = browsers.profile_of(browser_id) or browsers.default_profile()
    return browsers.resolve_port(cfg["port"], profile, (cfg["browsers"].get(profile.id) or {}).get("port"))


def test_hint(host: str, port) -> str:
    """How to reach the debug channel — Chrome's CDP endpoint answers `/json/list`."""
    return f"http://{host}:{port}/json/list"


def browser_row(cfg, profile) -> dict:
    """One browser as the panel needs it: endpoint, dir, commands, capabilities."""
    entry = cfg["browsers"].get(profile.id) or {}
    port = resolved_port({"port": cfg["port"], "browsers": {profile.id: entry}}, profile.id)
    data_dir = entry.get("user_data_dir") or profile.data_dir_default
    extra = entry.get("extra_args") if entry.get("extra_args") is not None else profile.extra_args_default
    caps = browsers.capabilities(profile)
    host = cfg["host"]
    return {
        "id": profile.id, "label": profile.label, "protocol": profile.protocol,
        "port_offset": profile.port_offset, "resolved_port": port,
        "user_data_dir": data_dir, "extra_args": extra, "dir_flag": profile.dir_flag,
        "binary": profile.binary(browsers.current_os()), "notes": profile.notes,
        "enabled": bool(entry.get("enabled", True)),
        "capabilities": caps,
        "unavailable": sorted(browsers.CAPABILITIES - set(caps)),
        "test_url": test_hint(host, port),
        "commands": browsers.launch_commands(profile, browsers.endpoint(port, data_dir, extra)),
    }


def browser_rows(config) -> list:
    """Every registered browser as a panel row, in registry order."""
    cfg = read_cdp_config(config)
    return [browser_row(cfg, profile) for profile in browsers.PROFILES]


def active_browser_row(config) -> dict:
    """The selected browser's row (the endpoint the automation connects to)."""
    cfg = read_cdp_config(config)
    rows = browser_rows(config)
    return next((r for r in rows if r["id"] == cfg["browser"]), rows[0])


def scan_targets(rows, host: str) -> list:
    """Every endpoint one pass will ask — the Settings window shows what is scanned (D-9).

    Built from the same browser rows the panel renders, so the line cannot drift from
    what `live_tab_rows` actually does: `base + offset` per browser (or the row's own
    port), its own channel, and a browser switched off marked as off.
    """
    return [{"id": r["id"], "label": r["label"], "host": host, "port": r["resolved_port"],
             "protocol": r["protocol"], "enabled": bool(r["enabled"])} for r in rows]


def cdp_config_payload(bridge) -> str:
    """Configured + live CDP values as a JSON payload (+ the whole browser table)."""
    cfg = read_cdp_config(bridge.config)
    rows = browser_rows(bridge.config)
    row = active_browser_row(bridge.config)
    host = cfg["host"]
    base = parse_cdp_port(cfg["port"]) if str(cfg["port"]).isdigit() else 9222
    payload = {
        "host": host,
        "port": base,
        "url_pattern": cfg["url_pattern"],
        "browser": row["id"],
        "active_browser": row["id"],
        "user_data_dir": row["user_data_dir"],
        "extra_args": row["extra_args"],
        "resolved_port": row["resolved_port"],
        "browsers": rows,
        "base_url": f"http://{host}:{base}",
        "scan_targets": scan_targets(rows, host),
        "scan_line": _scan_line(scan_targets(rows, host)),
        "is_connected": bool(bridge.cdp and bridge.cdp.is_connected),
        "current_host": getattr(bridge.cdp, "_host", host) if bridge.cdp else host,
        "current_port": getattr(bridge.cdp, "_port", base) if bridge.cdp else base,
    }
    return json.dumps(payload, ensure_ascii=False)


def _scan_line(targets) -> str:
    """The one-sentence Settings line ("a browser off says off")."""
    return browsers.scan_line(targets)


def first_present(data, keys, default):
    """First truthy data[key] over aliases, else default."""
    for k in keys:
        v = data.get(k)
        if v:
            return v
    return default


def parse_cdp_port(port) -> int:
    """Validated port int; ValueError carries the slot's error text."""
    try:
        port_i = int(port)
    except Exception:
        raise ValueError("invalid port")
    if not (1 <= port_i <= 65535):
        raise ValueError("port must be 1-65535")
    return port_i


def merge_browser_map(sent, known) -> dict:
    """Panel rows over the known ones: a blank/absent field keeps what was there.

    A resolved `port` the panel sends is deliberately NOT stored — the endpoint
    is always base + registry offset, so changing the base port moves every
    browser. A hand-edited `port` in session.json survives.
    """
    rows = {}
    for profile in browsers.PROFILES:
        row = dict(known.get(profile.id) or {})
        incoming = (sent or {}).get(profile.id) or {}
        if "enabled" in incoming:
            row["enabled"] = bool(incoming["enabled"])
        for key in ("user_data_dir", "extra_args"):
            if incoming.get(key):
                row[key] = incoming[key]
        rows[profile.id] = row
    return rows


def parse_cdp_config(data, config) -> dict:
    """Configured values from slot JSON; validates the port and the browser id."""
    pattern = data.get("url_pattern", config.get_state("url_pattern", "arena.ai"))
    wanted = first_present(data, ("browser", "active_browser"), active_browser_id(config))
    profile = browsers.profile_of(wanted)
    if profile is None:
        raise ValueError(f"unknown browser '{wanted}' — registered: {', '.join(browsers.profile_ids())}")
    cfg = {
        "host": first_present(data, ("host", "cdp_host"), "127.0.0.1"),
        "port": first_present(data, ("port", "cdp_port"), 9222),
        "url_pattern": pattern.strip() if isinstance(pattern, str) else "arena.ai",
        "browser": profile.id,
        "browsers": merge_browser_map(data.get("browsers"), browser_settings(config)),
    }
    cfg["port"] = parse_cdp_port(cfg["port"])
    flat_dir = first_present(data, ("user_data_dir", "cdp_user_data_dir"), "")
    if flat_dir and not (data.get("browsers") or {}).get(profile.id):
        cfg["browsers"][cfg["browser"]]["user_data_dir"] = flat_dir
    flat_extra = first_present(data, ("extra_args", "cdp_extra_args"), "")
    if flat_extra and not (data.get("browsers") or {}).get(profile.id):
        cfg["browsers"][cfg["browser"]]["extra_args"] = flat_extra
    row = cfg["browsers"][cfg["browser"]]
    cfg["user_data_dir"] = row["user_data_dir"]
    cfg["extra_args"] = row["extra_args"]
    return cfg


def apply_cdp_config(bridge, cfg) -> None:
    """Persist the shared host/base port + every browser row; push the ACTIVE endpoint."""
    rows = cfg["browsers"]
    default = browsers.default_profile().id
    bridge.config.set_state(cdp_host=cfg["host"], cdp_port=cfg["port"], url_pattern=cfg["url_pattern"],
                            active_browser=cfg["browser"], cdp_browsers=rows,
                            cdp_user_data_dir=rows[default]["user_data_dir"],
                            cdp_extra_args=rows[default]["extra_args"])
    profile = browsers.profile_of(cfg["browser"]) or browsers.default_profile()
    push_endpoint(bridge, profile, cfg["host"], resolved_port(cfg, cfg["browser"]))


def push_endpoint(bridge, profile, host, port) -> None:
    """Tell the live client (and its pool) which endpoint it now drives.

    Each push is best effort, so a duck-typed client that only has one of the
    setters still gets that one.
    """
    cdp = getattr(bridge, "cdp", None)
    if cdp is not None:
        try:
            cdp.set_host_port(host, port)
        except Exception:
            pass
    pool = getattr(bridge, "_page_pool", None)
    if pool is not None:
        try:
            pool._host = str(host)
            pool._port = int(port)
            pool._browser = profile.id   # pool rows then name their browser (D-3)
        except Exception:
            pass


def test_image_match(im, image_id) -> bool:
    """True when the row answers the test request (id, or selected)."""
    return im.id == image_id or (not image_id and im.selected)


def find_test_image(images, image_id):
    """Image by id (or the selected one); first-selected fallback."""
    for im in images:
        if test_image_match(im, image_id):
            return im
    sel = [i for i in images if i.selected]
    return sel[0] if sel else None


async def do_cdp_attach_test(bridge, image_path: str) -> None:
    """Attach smoke test: one image through the arena controller."""
    try:
        from app.browser.cdp_arena import CDPArenaController
        ctrl = CDPArenaController(bridge.cdp, log_callback=lambda m: bridge._log(m, "info"))
        ok, reason = await ctrl.attach_image(image_path)
        if ok:
            bridge._log(f"✅ Attach test success: {reason}", "success")
        else:
            bridge._log(f"❌ Attach test failed: {reason}", "error")
    except Exception as e:
        bridge._log(f"Attach test exception: {e}", "error")


async def do_cdp_prompt_test(bridge, prompt_text: str) -> None:
    """Prompt smoke test: insert + verify through the controller."""
    try:
        from app.browser.cdp_arena import CDPArenaController
        ctrl = CDPArenaController(bridge.cdp, log_callback=lambda m: bridge._log(m, "info"))
        ok, reason = await ctrl.insert_prompt(prompt_text)
        if ok:
            bridge._log(f"✅ Prompt insert success: {reason}", "success")
            verified, vreason = await ctrl.verify_prompt(prompt_text)
            bridge._log(f"Verify prompt: {verified} {vreason}", "info" if verified else "warn")
        else:
            bridge._log(f"❌ Prompt insert failed: {reason}", "error")
    except Exception as e:
        bridge._log(f"Prompt test exception: {e}", "error")


async def run_flow_prompt(bridge, ctrl, prompt_template) -> bool:
    """Insert the correlated prompt; True when accepted."""
    from app.utils.correlation import generate_correlation_id, build_final_prompt
    cid = generate_correlation_id()
    final = build_final_prompt(cid, prompt_template)
    ok, reason = await ctrl.insert_prompt(final)
    bridge._log(f"Insert prompt [{cid}]: {ok} {reason}", "success" if ok else "error")
    return ok


async def do_cdp_full_flow_test(bridge, image_path: str, prompt_template: str) -> None:
    """Attach + prompt + submit smoke flow (without waiting)."""
    try:
        from app.browser.cdp_arena import CDPArenaController
        ctrl = CDPArenaController(bridge.cdp, log_callback=lambda m: bridge._log(m, "info"))
        baseline = await ctrl.capture_baseline()
        bridge._log(f"Baseline {baseline.get('output_count')} outputs", "info")
        ok, reason = await ctrl.attach_image(image_path)
        bridge._log(f"Attach: {ok} {reason}", "success" if ok else "error")
        if not ok:
            return
        if not await run_flow_prompt(bridge, ctrl, prompt_template):
            return
        ok, reason = await ctrl.submit()
        bridge._log(f"Submit: {ok} {reason}", "success" if ok else "error")
    except Exception as e:
        bridge._log(f"Full flow test exception: {e}", "error")


class CdpToolsMixin:
    """CDP tool slots: highlight demos, config, connection test flows."""

    @Slot(str, result=str)
    def highlight_image(self, img_id: str):
        emit_highlight_demo(self)
        if self.cdp and self.cdp.is_connected:
            schedule_coro(self, do_highlight_demo_cdp(self, img_id))
        return json.dumps({"ok": True})

    @Slot(str, str, int, str, result=str)
    def highlight_selector(self, selector: str, color: str, duration_ms: int, caption: str):
        if not self.cdp or not self.cdp.is_connected:
            # fallback to UI overlay
            rect = {
                "x": 200, "y": 200, "width": 320, "height": 180,
                "duration": duration_ms / 1000 if duration_ms > 0 else 2,
                "label": caption or selector,
                "color": color
            }
            self.highlight_rect.emit(json.dumps(rect))
            return json.dumps({"ok": True, "fallback": True})
        # schedule async highlight
        schedule_coro(self, do_highlight(self, HighlightArgs(selector, color, duration_ms, caption)))
        return json.dumps({"ok": True})

    @Slot(result=str)
    def clear_highlights(self):
        if not self.cdp or not self.cdp.is_connected:
            return json.dumps({"ok": True})
        schedule_coro(self, do_clear_highlights(self))
        return json.dumps({"ok": True})

    @Slot(result=str)
    def get_cdp_config(self):
        try:
            return cdp_config_payload(self)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @Slot(str, result=str)
    def set_cdp_config(self, config_json: str):
        try:
            data = json.loads(config_json or "{}")
            cfg = parse_cdp_config(data, self.config)
            apply_cdp_config(self, cfg)
            port = resolved_port(cfg, cfg["browser"])
            self._log(f"Browser config saved: {cfg['browser']} on {cfg['host']}:{port} "
                      f"(base {cfg['port']}) dir={cfg['user_data_dir']}", "success")
            reply = {"ok": True, "browser": cfg["browser"], "host": cfg["host"],
                     "port": port, "base_port": cfg["port"],
                     "user_data_dir": cfg["user_data_dir"]}
            return json.dumps(reply)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def get_chrome_launch_command(self):
        """The ACTIVE browser's launch commands + its facts."""
        try:
            cfg = read_cdp_config(self.config)
            row = active_browser_row(self.config)
            payload = {
                "host": cfg["host"],
                "port": parse_cdp_port(cfg["port"]),
                "url_pattern": cfg["url_pattern"],
                "browser": row["id"],
                "protocol": row["protocol"],
                "resolved_port": row["resolved_port"],
                "user_data_dir": row["user_data_dir"],
                "extra_args": row["extra_args"],
                "capabilities": row["capabilities"],
                "unavailable": row["unavailable"],
                "notes": row["notes"],
                "test_url": row["test_url"],
                "browsers": browser_rows(self.config),
            }
            payload.update(row["commands"])
            return json.dumps(payload, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @Slot(str, result=str)
    def cdp_attach_image_test(self, image_id: str):
        if not self.cdp or not self.cdp.is_connected:
            return json.dumps({"ok": False, "error": "CDP not connected"})
        img = find_test_image(self.state.images, image_id)
        if not img:
            return json.dumps({"ok": False, "error": "No image found, select one in queue"})
        self._log(f"🧪 Testing attach for {img.absolute_path}", "info")
        schedule_coro(self, do_cdp_attach_test(self, img.absolute_path))
        return json.dumps({"ok": True, "path": img.absolute_path})

    @Slot(str, result=str)
    def cdp_insert_prompt_test(self, prompt_text: str):
        if not self.cdp or not self.cdp.is_connected:
            return json.dumps({"ok": False, "error": "CDP not connected"})
        txt = prompt_text or self.state.prompt.get("user_prompt", "") or "Test prompt [JOB-ID: test123]"
        self._log(f"🧪 Testing prompt insert: {txt[:80]}...", "info")
        schedule_coro(self, do_cdp_prompt_test(self, txt))
        return json.dumps({"ok": True})

    @Slot(result=str)
    def cdp_test_full_flow(self):
        if not self.cdp or not self.cdp.is_connected:
            return json.dumps({"ok": False, "error": "CDP not connected"})
        sel = [i for i in self.state.images if i.selected]
        if not sel:
            return json.dumps({"ok": False, "error": "No selected image"})
        prompt = self.state.prompt.get("user_prompt", "")
        if not prompt:
            return json.dumps({"ok": False, "error": "Empty prompt"})
        self._log("🧪 Testing full flow: attach + prompt + submit (without waiting)", "info")
        schedule_coro(self, do_cdp_full_flow_test(self, sel[0].absolute_path, prompt))
        return json.dumps({"ok": True})
