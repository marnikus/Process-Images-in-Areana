"""CDP Arena Controller — automation for arena.ai via CDPClient (already opened Chrome).

Implements:
- attach image as reference (via DOM.setFileInputFiles)
- insert prompt with JOB-ID token
- submit once
- baseline capture / new output detection
- download validation
- highlight rectangle with configurable duration (saved in preset)

Uses semantic selectors from site_adapter, with fallbacks.
"""

import json
import time
import asyncio
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple, Callable

from .cdp_client import CDPClient
from .site_adapter import SELECTORS, get_selector

log = logging.getLogger("arena")

# JS snippets for operations
JS_FIND_TEXTAREA = """
(() => {
  const sels = [
    'textarea[name="message"]',
    'textarea[name="message"][autocomplete="off"]',
    'textarea[placeholder^="Describe how you want to edit"]',
    'textarea[placeholder^="Describe the image you want to generate"]',
    'textarea[placeholder^="Describe"]',
    'textarea[rows="1"]'
  ];
  for (const sel of sels) {
    const el = document.querySelector(sel);
    if (el && el.offsetParent !== null) return sel;
  }
  return null;
})()
"""

JS_INSERT_PROMPT = """
((promptText) => {
  try {
    const sels = [
      'textarea[name="message"]',
      'textarea[name="message"][autocomplete="off"]',
      'textarea[placeholder^="Describe how you want to edit"]',
      'textarea[placeholder^="Describe the image you want to generate"]',
      'textarea[placeholder^="Describe"]',
      'textarea[rows="1"]'
    ];
    let ta = null;
    for (const sel of sels) {
      const el = document.querySelector(sel);
      if (el && el.offsetParent !== null) { ta = el; break; }
    }
    if (!ta) return {ok:false, error:'textarea not found'};
    ta.focus();
    // Use native setter to trigger React
    const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
    nativeSetter.call(ta, promptText);
    ta.dispatchEvent(new Event('input', {bubbles:true}));
    ta.dispatchEvent(new Event('change', {bubbles:true}));
    // Also set value directly as fallback
    ta.value = promptText;
    return {ok:true, value: ta.value, len: ta.value.length};
  } catch(e) { return {ok:false, error:String(e)}; }
})
"""

JS_VERIFY_PROMPT = """
((expected) => {
  try {
    const el = document.querySelector('textarea[name="message"]');
    if (!el) return {ok:false, error:'not found'};
    return {ok: el.value === expected, actual: el.value, expected: expected, actualLen: el.value.length, expectedLen: expected.length};
  } catch(e) { return {ok:false, error:String(e)}; }
})
"""

JS_FIND_SEND_BUTTON = """
(() => {
  const sels = [
    'button[aria-label="Send message"]',
    'button[type="submit"][aria-label="Send message"]',
    'form button:has(svg):last-child',
    'form button[type="submit"]'
  ];
  for (const sel of sels) {
    try {
      const els = document.querySelectorAll(sel);
      for (const el of els) {
        if (el.offsetParent !== null && !el.disabled) return sel;
      }
    } catch(e) {}
  }
  return null;
})()
"""

JS_CLICK_SEND = """
(() => {
  try {
    const sels = [
      'button[aria-label="Send message"]',
      'button[type="submit"][aria-label="Send message"]',
      'form button[type="submit"]'
    ];
    let btn = null;
    for (const sel of sels) {
      const els = document.querySelectorAll(sel);
      for (const el of els) {
        if (el.offsetParent !== null && !el.disabled) { btn = el; break; }
      }
      if (btn) break;
    }
    if (!btn) return {ok:false, error:'send button not found or disabled'};
    btn.click();
    return {ok:true};
  } catch(e) { return {ok:false, error:String(e)}; }
})()
"""

JS_BASELINE = """
(() => {
  try {
    const outputs = [];
    const selectors = [
      'div.no-scrollbar img[src*=".r2.cloudflarestorage.com/"]',
      'div.no-scrollbar img[src*="messages-prod."]',
      'div.no-scrollbar img[loading="lazy"].aspect-square',
      'img.aspect-square.cursor-pointer',
      'img.cursor-pointer',
      'div.flex.flex-wrap img[src^="blob:"]'
    ];
    for (const sel of selectors) {
      const els = document.querySelectorAll(sel);
      for (const el of els) {
        if (!el.src) continue;
        outputs.push({
          src: el.src,
          complete: el.complete,
          naturalWidth: el.naturalWidth,
          naturalHeight: el.naturalHeight,
          visible: el.offsetParent !== null
        });
      }
      if (outputs.length > 0) break;
    }
    return {
      output_count: outputs.length,
      output_srcs: outputs.map(o => o.src),
      outputs: outputs,
      timestamp: Date.now(),
      url: window.location.href
    };
  } catch(e) {
    return {output_count:0, output_srcs:[], error:String(e), timestamp:Date.now()};
  }
})()
"""

JS_CHECK_NEW_OUTPUT = """
((oldSrcs) => {
  try {
    const selectors = [
      'div.no-scrollbar img[src*=".r2.cloudflarestorage.com/"]',
      'div.no-scrollbar img[src*="messages-prod."]',
      'div.no-scrollbar img[loading="lazy"].aspect-square',
      'img.aspect-square.cursor-pointer',
      'img.cursor-pointer'
    ];
    for (const sel of selectors) {
      const els = document.querySelectorAll(sel);
      for (const el of els) {
        if (!el.src) continue;
        if (oldSrcs.includes(el.src)) continue;
        if (!el.complete) return {ready:false, reason:'not_complete', src: el.src};
        if (el.naturalWidth === 0) return {ready:false, reason:'zero_width', src: el.src};
        if (el.offsetParent === null) continue;
        return {ready:true, src: el.src, width: el.naturalWidth, height: el.naturalHeight};
      }
    }
    return {ready:false, reason:'no_new'};
  } catch(e) { return {ready:false, reason:String(e)}; }
})
"""

JS_VERIFY_ATTACHMENT = """
((expectedFilename) => {
  try {
    const selectors = [
      'div.flex.flex-wrap.gap-2 img[alt]',
      'div.flex.flex-wrap.gap-2 img[src^="blob:"]',
      'div.group.relative.overflow-hidden.rounded-lg.h-16.w-16 img',
      'form img[src^="blob:"]',
      'form img[alt]'
    ];
    for (const sel of selectors) {
      const els = document.querySelectorAll(sel);
      for (const el of els) {
        if (el.offsetParent === null) continue;
        const alt = el.getAttribute('alt') || '';
        const src = el.getAttribute('src') || '';
        if (src.startsWith('blob:')) {
          return {found:true, alt: alt, src: src, matched:'blob'};
        }
        if (expectedFilename && alt && alt.toLowerCase().includes(expectedFilename.toLowerCase())) {
          return {found:true, alt: alt, src: src, matched:'filename'};
        }
        if (alt) {
          return {found:true, alt: alt, src: src, matched:'alt_exists'};
        }
      }
    }
    return {found:false};
  } catch(e) { return {found:false, error:String(e)}; }
})
"""

JS_DOWNLOAD_IMAGE = """
async (src) => {
  try {
    const res = await fetch(src);
    if (!res.ok) return {ok:false, status:res.status, statusText:res.statusText};
    const buf = await res.arrayBuffer();
    const contentType = res.headers.get('content-type') || '';
    return {ok:true, bytes: Array.from(new Uint8Array(buf)), contentType: contentType};
  } catch(e) {
    return {ok:false, error:e.toString()};
  }
}
"""

class CDPArenaController:
    def __init__(self, cdp_client: CDPClient, log_callback: Optional[Callable[[str], None]] = None):
        self.cdp = cdp_client
        self._log_callback = log_callback

    def set_log_callback(self, cb: Callable[[str], None]):
        self._log_callback = cb

    def _log(self, msg: str, level: str = "info"):
        log.info(msg)
        if self._log_callback:
            try:
                self._log_callback(msg)
            except Exception:
                pass

    async def ensure_connected(self) -> bool:
        if self.cdp.is_connected:
            return True
        self._log("CDP not connected — cannot automate", "warn")
        return False

    async def capture_baseline(self) -> Dict[str, Any]:
        js = f"({JS_BASELINE})()"
        result = await self.cdp.evaluate(js)
        if not result:
            return {"output_count": 0, "output_srcs": [], "timestamp": int(time.time()*1000)}
        return result

    async def attach_image(self, image_path: str) -> Tuple[bool, str]:
        if not await self.ensure_connected():
            return False, "Not connected"
        # Use CDP DOM.setFileInputFiles
        ok, reason = await self.cdp.attach_image_cdp(image_path)
        if not ok:
            self._log(f"Attach via CDP failed: {reason}", "warn")
            return False, reason
        self._log(f"Attached {image_path}: {reason}")
        # Wait a bit for preview to appear
        await asyncio.sleep(1)
        # Verify
        verified, vreason = await self.verify_attachment(Path(image_path).name)
        if verified:
            self._log(f"Attachment verified: {vreason}")
            return True, vreason
        else:
            self._log(f"Attachment not yet visible: {vreason}, waiting 2s", "warn")
            await asyncio.sleep(2)
            verified2, vreason2 = await self.verify_attachment(Path(image_path).name)
            return verified2, vreason2

    async def verify_attachment(self, expected_filename: str) -> Tuple[bool, str]:
        js = f"({JS_VERIFY_ATTACHMENT})({json.dumps(expected_filename)})"
        result = await self.cdp.evaluate(js)
        if not result:
            return False, "No result from verify"
        if result.get("found"):
            return True, f"Found via {result.get('matched')} alt={result.get('alt')}"
        return False, f"Preview not found: {result}"

    async def insert_prompt(self, prompt_text: str) -> Tuple[bool, str]:
        if not await self.ensure_connected():
            return False, "Not connected"
        # Highlight textarea before insert if possible
        try:
            await self.highlight_selector('textarea[name="message"]', color="#00AAFF", duration_ms=1000, caption="Prompt input")
        except Exception:
            pass
        # Build JS that calls the function with arg
        js = f"({JS_INSERT_PROMPT})({json.dumps(prompt_text)})"
        result = await self.cdp.evaluate(js)
        if not result:
            return False, "No result"
        if result.get("ok"):
            return True, f"Inserted len {result.get('len')}"
        return False, result.get("error", "Unknown")

    async def verify_prompt(self, expected: str) -> Tuple[bool, str]:
        js = f"({JS_VERIFY_PROMPT})({json.dumps(expected)})"
        result = await self.cdp.evaluate(js)
        if not result:
            return False, "No result"
        if result.get("ok"):
            return True, "Exact match"
        # Provide diff
        actual = result.get("actual", "")
        return False, f"Mismatch actual len {len(actual)} expected len {len(expected)}: {result}"

    async def submit(self) -> Tuple[bool, str]:
        if not await self.ensure_connected():
            return False, "Not connected"
        try:
            await self.highlight_selector('button[aria-label="Send message"]', color="#FFAA00", duration_ms=1000, caption="Send")
        except Exception:
            pass
        js = f"({JS_CLICK_SEND})()"
        result = await self.cdp.evaluate(js)
        if not result:
            return False, "No result"
        if result.get("ok"):
            return True, "Clicked"
        return False, result.get("error", "Failed")

    async def wait_for_new_output(self, baseline: Dict[str, Any], timeout_ms: int = 180000) -> Tuple[str, Dict[str, Any]]:
        """Poll for new output, return status."""
        old_srcs = baseline.get("output_srcs", []) or []
        start = time.time()
        poll = 2
        while (time.time() - start) * 1000 < timeout_ms:
            # Check security dialog? Could be detected via JS
            js_check = f"({JS_CHECK_NEW_OUTPUT})({json.dumps(old_srcs)})"
            result = await self.cdp.evaluate(js_check)
            if result and result.get("ready"):
                return "completed", {"new_src": result.get("src"), "check": result, "baseline": baseline}
            # Wait
            await asyncio.sleep(poll)
        # Timeout
        final_baseline = await self.capture_baseline()
        return "failed", {"error": f"Timeout after {timeout_ms}ms", "last_baseline": final_baseline}

    async def download_image(self, src: str) -> Tuple[bool, bytes, str]:
        js = f"({JS_DOWNLOAD_IMAGE})({json.dumps(src)})"
        # evaluate returns value, but we need to await promise — our evaluate already awaits
        result = await self.cdp.evaluate(js)
        if not result:
            return False, b"", "No result"
        if not result.get("ok"):
            return False, b"", f"Fetch failed {result}"
        byte_list = result.get("bytes", [])
        data = bytes(byte_list)
        if data[:100].lower().find(b"<html") != -1:
            return False, b"", "Downloaded HTML not image"
        return True, data, result.get("contentType", "")

    async def highlight_selector(self, selector: str, color: str = "#FF0000", duration_ms: int = 2000, caption: str = ""):
        try:
            from .dom_highlight import build_highlight_js
            js = build_highlight_js(selector, color, duration_ms, caption, clear_first=True)
            await self.cdp.evaluate(js)
        except Exception as e:
            log.debug(f"highlight_selector failed: {e}")

    async def clear_highlights(self):
        try:
            from .dom_highlight import build_clear_js
            js = build_clear_js()
            await self.cdp.evaluate(js)
        except Exception as e:
            log.debug(f"clear_highlights failed: {e}")

    async def is_page_ready(self) -> Tuple[bool, List[str]]:
        """Check readiness via JS."""
        js = """
        (() => {
          const reasons = [];
          const checks = [
            {sel: 'textarea[name="message"]', name: 'prompt_textarea'},
            {sel: 'button[aria-label="Send message"]', name: 'send_button'},
            {sel: 'input[type="file"]', name: 'file_input'},
            {sel: 'div.no-scrollbar', name: 'output_region'}
          ];
          for (const c of checks) {
            const el = document.querySelector(c.sel);
            if (!el) reasons.push(c.name + ' not found');
            else if (el.offsetParent === null) reasons.push(c.name + ' not visible');
          }
          // security dialog
          const dialogs = document.querySelectorAll('div[role="dialog"][data-state="open"]');
          for (const d of dialogs) {
            if (d.innerText && d.innerText.includes('Security Verification')) reasons.push('Security dialog visible');
          }
          return {ready: reasons.length===0, reasons: reasons};
        })()
        """
        result = await self.cdp.evaluate(js)
        if not result:
            return False, ["No result from readiness check"]
        return bool(result.get("ready")), result.get("reasons", [])

    async def is_security_dialog_visible(self) -> bool:
        js = """
        (() => {
          const dialogs = document.querySelectorAll('div[role="dialog"][data-state="open"]');
          for (const d of dialogs) {
            if (d.innerText && d.innerText.includes('Security Verification')) return true;
            if (d.querySelector('iframe[title="reCAPTCHA"]')) return true;
          }
          const iframes = document.querySelectorAll('iframe[title="reCAPTCHA"]');
          for (const f of iframes) {
            const style = window.getComputedStyle(f);
            if (style.display !== 'none' && f.offsetParent !== null) return true;
          }
          return false;
        })()
        """
        result = await self.cdp.evaluate(js)
        return bool(result)
