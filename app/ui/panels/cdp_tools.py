"""CDP tools panel — highlight demos, CDP config, connection test flows.

ideal-size(reason): 9-slot CDP surface plus per-key config splits — set/get/
launch each exceed 20 LOC as one function, so read/parse/apply phases live
beside their single callers per RULE 16; splitting the file would scatter
slot+phase pairs. Browser imports stay lazy (fault tolerance, R5–R7
precedent); only run_state.schedule_coro is hoisted (services never
import ui).
"""

import json
from typing import NamedTuple

from app.services.run_state import schedule_coro
from app.ui.qt_compat import Slot

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
        await ctrl.highlight_selector('textarea[name="message"]', color="#FF0000", duration_ms=duration_ms, caption=f"Image {img_id[:8]}" if img_id else "Clicked element")
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


def read_cdp_config(config) -> dict:
    """Configured CDP values (host/port/dir/extra/pattern)."""
    return {
        "host": config.get_state("cdp_host", "127.0.0.1"),
        "port": config.get_state("cdp_port", 9222),
        "user_data_dir": config.get_state("cdp_user_data_dir", "C:\\arena-images-chrome"),
        "extra_args": config.get_state("cdp_extra_args", ""),
        "url_pattern": config.get_state("url_pattern", "arena.ai"),
    }


def cdp_config_payload(bridge) -> str:
    """Configured + live CDP values as a JSON payload."""
    cfg = read_cdp_config(bridge.config)
    host, port = cfg["host"], cfg["port"]
    payload = {
        "host": host,
        "port": int(port),
        "user_data_dir": cfg["user_data_dir"],
        "extra_args": cfg["extra_args"],
        "url_pattern": cfg["url_pattern"],
        "base_url": f"http://{host}:{port}",
        "is_connected": bool(bridge.cdp and bridge.cdp.is_connected),
        "current_host": bridge.cdp._host if bridge.cdp else host,
        "current_port": bridge.cdp._port if bridge.cdp else int(port),
    }
    return json.dumps(payload, ensure_ascii=False)


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


def parse_cdp_config(data, config) -> dict:
    """Configured values from slot JSON (+stored pattern); validates port."""
    pattern = data.get("url_pattern", config.get_state("url_pattern", "arena.ai"))
    cfg = {
        "host": first_present(data, ("host", "cdp_host"), "127.0.0.1"),
        "port": first_present(data, ("port", "cdp_port"), 9222),
        "user_data_dir": first_present(data, ("user_data_dir", "cdp_user_data_dir"), "C:\\arena-images-chrome"),
        "extra_args": first_present(data, ("extra_args", "cdp_extra_args"), ""),
        "url_pattern": pattern.strip() if isinstance(pattern, str) else "arena.ai",
    }
    cfg["port"] = parse_cdp_port(cfg["port"])
    return cfg


def apply_cdp_config(bridge, cfg) -> None:
    """Persist + push host/port/dir to the cdp client and pool."""
    bridge.config.set_state(cdp_host=cfg["host"], cdp_port=cfg["port"],
                            cdp_user_data_dir=cfg["user_data_dir"], cdp_extra_args=cfg["extra_args"],
                            url_pattern=cfg["url_pattern"])
    if bridge.cdp:
        try:
            bridge.cdp.set_host_port(cfg["host"], cfg["port"])
        except Exception:
            pass
    if bridge._page_pool:
        try:
            bridge._page_pool._host = str(cfg["host"])
            bridge._page_pool._port = int(cfg["port"])
        except Exception:
            pass


def build_chrome_commands(port, user_data_dir, extra):
    """Windows (+URL) and linux remote-debugging launch commands."""
    win_cmd = f'"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port={port} --user-data-dir="{user_data_dir}"'
    if extra:
        win_cmd += f" {extra}"
    win_cmd_with_url = win_cmd + " https://arena.ai"
    linux_cmd = f'google-chrome --remote-debugging-port={port} --user-data-dir="{user_data_dir}"'
    if extra:
        linux_cmd += f" {extra}"
    return win_cmd, win_cmd_with_url, linux_cmd


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
            self._log(f"CDP config saved: {cfg['host']}:{cfg['port']} dir={cfg['user_data_dir']}", "success")
            return json.dumps({"ok": True, "host": cfg["host"], "port": cfg["port"], "user_data_dir": cfg["user_data_dir"]})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def get_chrome_launch_command(self):
        try:
            cfg = read_cdp_config(self.config)
            host, port = cfg["host"], cfg["port"]
            win_cmd, win_cmd_with_url, linux_cmd = build_chrome_commands(port, cfg["user_data_dir"], cfg["extra_args"])
            payload = {
                "host": host,
                "port": int(port),
                "user_data_dir": cfg["user_data_dir"],
                "extra_args": cfg["extra_args"],
                "windows": win_cmd,
                "windows_with_url": win_cmd_with_url,
                "linux": linux_cmd,
                "test_url": f"http://{host}:{port}/json/list",
            }
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
