"""
Browser Controller using Playwright.
Handles launching persistent context, page readiness, highlighting, file attachment, etc.
"""
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable
import asyncio
import time
from playwright.async_api import async_playwright, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError

from .site_adapter import SELECTORS, get_selector, get_readiness_requirements
from ..core.models import UrlRow
from ..core.enums import UrlStatus

class BrowserController:
    def __init__(self, user_data_dir: str = "./browser_profile", headless: bool = False, slow_mo: int = 0):
        self.user_data_dir = Path(user_data_dir)
        self.headless = headless
        self.slow_mo = slow_mo
        self.playwright = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._log_callback: Optional[Callable[[str], None]] = None

    def set_log_callback(self, cb: Callable[[str], None]):
        self._log_callback = cb

    def _log(self, msg: str):
        if self._log_callback:
            self._log_callback(msg)
        else:
            print(msg)

    async def launch(self):
        """Launch persistent context."""
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        self.playwright = await async_playwright().start()
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.user_data_dir),
            headless=self.headless,
            slow_mo=self.slow_mo,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 800},
        )
        # Use existing page or create new
        if len(self.context.pages) > 0:
            self.page = self.context.pages[0]
        else:
            self.page = await self.context.new_page()
        self._log(f"Browser launched with profile {self.user_data_dir}")

    async def close(self):
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
        self._log("Browser closed")

    async def navigate(self, url: str, timeout: int = 30000) -> bool:
        if not self.page:
            raise RuntimeError("Browser not launched")
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            # Wait a bit for hydration
            await self.page.wait_for_timeout(2000)
            return True
        except Exception as e:
            self._log(f"Navigate failed for {url}: {e}")
            return False

    async def check_url_status(self, url_row: UrlRow, timeout: int = 30000) -> UrlStatus:
        """Validate and open URL, detect readiness."""
        url_row.last_checked = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        # Validate syntax
        from urllib.parse import urlparse
        parsed = urlparse(url_row.url)
        if not parsed.scheme or not parsed.netloc:
            url_row.last_status = UrlStatus.ERROR.value
            url_row.error = "Invalid URL syntax"
            return UrlStatus.ERROR

        # Navigate
        ok = await self.navigate(url_row.url, timeout=timeout)
        if not ok:
            url_row.last_status = UrlStatus.UNAVAILABLE.value
            url_row.error = "Failed to navigate"
            return UrlStatus.UNAVAILABLE

        # Check for security dialog
        if await self.is_security_dialog_visible():
            url_row.last_status = UrlStatus.CAPTCHA_REQUIRED.value
            url_row.error = "Security verification required"
            return UrlStatus.CAPTCHA_REQUIRED

        # Check for sign-in
        if await self.is_sign_in_page():
            url_row.last_status = UrlStatus.AUTH_REQUIRED.value
            url_row.error = "Authentication required"
            return UrlStatus.AUTH_REQUIRED

        # Check readiness
        ready, reasons = await self.is_page_ready()
        if ready:
            url_row.last_status = UrlStatus.READY.value
            url_row.error = None
            return UrlStatus.READY
        else:
            # Determine if unsupported or error
            url_row.last_status = UrlStatus.UNSUPPORTED.value
            url_row.error = f"Not ready: {', '.join(reasons)}"
            return UrlStatus.UNSUPPORTED

    async def is_security_dialog_visible(self) -> bool:
        if not self.page:
            return False
        # Check dialog
        try:
            dialog_selector = get_selector("security_dialog")
            # Use JS to check visible dialog containing Security Verification
            js = """
            () => {
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
            }
            """
            result = await self.page.evaluate(js)
            return bool(result)
        except Exception:
            return False

    async def is_sign_in_page(self) -> bool:
        if not self.page:
            return False
        try:
            js = """
            () => {
                const url = window.location.href.toLowerCase();
                if (url.includes('/auth') || url.includes('/login') || url.includes('/signin')) return true;
                const bodyText = document.body.innerText.toLowerCase();
                if (bodyText.includes('sign in') && bodyText.includes('continue with google')) return true;
                if (bodyText.includes('please log in') || bodyText.includes('authentication required')) return true;
                return false;
            }
            """
            result = await self.page.evaluate(js)
            return bool(result)
        except Exception:
            return False

    async def is_page_ready(self) -> tuple[bool, List[str]]:
        """Check composite readiness gate."""
        if not self.page:
            return False, ["Browser not launched"]
        reasons = []
        # Check each required selector
        for name in get_readiness_requirements():
            sel = get_selector(name)
            found = await self.find_element(sel, timeout=5000)
            if not found:
                reasons.append(f"{name} not found")
        # Check security dialog not visible
        if await self.is_security_dialog_visible():
            reasons.append("Security dialog visible")
        # Check sign-in
        if await self.is_sign_in_page():
            reasons.append("Sign-in page detected")

        ready = len(reasons) == 0
        return ready, reasons

    async def find_element(self, selector_obj, timeout: int = 5000):
        """Find element using primary + fallbacks, with visibility/enabled checks."""
        if not self.page:
            return None
        # Try each selector with playwright locators
        for sel in selector_obj.all_selectors():
            try:
                loc = self.page.locator(sel).first
                # Wait for visible if required
                if selector_obj.mustBeVisible:
                    await loc.wait_for(state="visible", timeout=timeout)
                else:
                    await loc.wait_for(state="attached", timeout=timeout)
                # Check enabled if required
                if selector_obj.mustBeEnabled:
                    # Playwright is_enabled check
                    if not await loc.is_enabled():
                        continue
                # Text condition
                if selector_obj.textCondition:
                    text = await loc.inner_text()
                    if selector_obj.textConditionType == "equals":
                        if text.strip() != selector_obj.textCondition:
                            continue
                    elif selector_obj.textConditionType == "contains":
                        if selector_obj.textCondition not in text:
                            continue
                return loc
            except PlaywrightTimeoutError:
                continue
            except Exception as e:
                # self._log(f"find_element error for {sel}: {e}")
                continue
        return None

    async def highlight_element(self, locator, duration_seconds: float = 2, color: str = "#FF0000", border_width: int = 3):
        """Draw rect above element that is clicking now for several sec (set by user)."""
        if not locator:
            return
        try:
            # Get bounding box
            box = await locator.bounding_box()
            if not box:
                return
            # Inject overlay div
            js = """
            ([x, y, width, height, color, borderWidth, duration]) => {
                const id = 'arena-highlight-' + Date.now();
                const div = document.createElement('div');
                div.id = id;
                div.style.position = 'absolute';
                div.style.left = x + 'px';
                div.style.top = y + 'px';
                div.style.width = width + 'px';
                div.style.height = height + 'px';
                div.style.border = borderWidth + 'px solid ' + color;
                div.style.borderRadius = '4px';
                div.style.pointerEvents = 'none';
                div.style.zIndex = '999999';
                div.style.boxShadow = '0 0 10px ' + color;
                div.style.backgroundColor = color + '20';
                document.body.appendChild(div);
                // Also scroll into view
                div.scrollIntoView({behavior: 'smooth', block: 'center'});
                setTimeout(() => {
                    const el = document.getElementById(id);
                    if (el) el.remove();
                }, duration * 1000);
                return id;
            }
            """
            await self.page.evaluate(js, [box["x"], box["y"], box["width"], box["height"], color, border_width, duration_seconds])
            # Wait for duration
            await self.page.wait_for_timeout(int(duration_seconds * 1000))
        except Exception as e:
            self._log(f"Highlight failed: {e}")

    async def capture_baseline(self) -> Dict[str, Any]:
        """Capture pre-submission baseline: output elements, message order, timestamp, spinner state."""
        if not self.page:
            return {}
        try:
            js = """
            () => {
                const outputs = [];
                const selectors = [
                    'div.no-scrollbar img[src*=".r2.cloudflarestorage.com/"]',
                    'div.no-scrollbar img[src*="messages-prod."]',
                    'div.no-scrollbar img[loading="lazy"].aspect-square',
                    'img.aspect-square.cursor-pointer',
                    'div.flex img[src*=".r2.cloudflarestorage.com/"]',
                    'main img[src*=".r2.cloudflarestorage.com/"]',
                    'img[src*=".r2.cloudflarestorage.com/"]'
                ];
                for (const sel of selectors) {
                    const els = document.querySelectorAll(sel);
                    for (const el of els) {
                        if (!el.src) continue;
                        if (el.src.startsWith('blob:')) continue;
                        if (el.naturalWidth && el.naturalWidth < 50) continue;
                        outputs.push({
                            src: el.src,
                            outerHTML: el.outerHTML.substring(0, 500),
                            complete: el.complete,
                            naturalWidth: el.naturalWidth,
                            naturalHeight: el.naturalHeight,
                            visible: el.offsetParent !== null
                        });
                    }
                    if (outputs.length > 0) break;
                }
                let spinning = false;
                try {
                  const spinners = document.querySelectorAll('div.animate-spin');
                  for (const s of spinners) { if (s.offsetParent !== null) { spinning = true; break; } }
                } catch(e) {}
                const messages = document.querySelectorAll('[data-message-id], div.flex.flex-col.gap-3');
                return {
                    output_count: outputs.length,
                    output_srcs: outputs.map(o => o.src),
                    outputs: outputs,
                    message_count: messages.length,
                    spinning: spinning,
                    timestamp: Date.now(),
                    url: window.location.href
                };
            }
            """
            baseline = await self.page.evaluate(js)
            return baseline
        except Exception as e:
            self._log(f"Baseline capture failed: {e}")
            return {"output_count": 0, "output_srcs": [], "timestamp": int(time.time()*1000), "spinning": False}

    async def attach_image(self, image_path: str, timeout: int = 15000) -> bool:
        """Attach source image through file input."""
        if not self.page:
            return False
        sel = get_selector("file_input")
        loc = await self.find_element(sel, timeout=timeout)
        if not loc:
            self._log("File input not found")
            return False
        try:
            # Playwright set_input_files works even for hidden
            await loc.set_input_files(image_path)
            self._log(f"Attached image {image_path}")
            # Wait for preview
            await self.page.wait_for_timeout(1000)
            return True
        except Exception as e:
            self._log(f"Attach failed: {e}")
            return False

    async def verify_attachment(self, expected_filename: str, timeout: int = 10000) -> tuple[bool, str]:
        """Verify correct attachment preview appears."""
        if not self.page:
            return False, "No page"
        # Check preview container
        sel_container = get_selector("attachment_preview_container")
        container = await self.find_element(sel_container, timeout=2000)
        # Even if container not found, try image directly
        sel_image = get_selector("attachment_preview_image")
        # For filename matching, we need to evaluate JS
        try:
            js = """
            (expectedFilename) => {
                const selectors = [
                    'div.flex.flex-wrap.gap-2 img[alt]',
                    'div.flex.flex-wrap.gap-2 img[src^="blob:"]',
                    'div.group.relative.overflow-hidden.rounded-lg.h-16.w-16 img'
                ];
                for (const sel of selectors) {
                    const els = document.querySelectorAll(sel);
                    for (const el of els) {
                        const alt = el.getAttribute('alt') || '';
                        const src = el.getAttribute('src') || '';
                        const visible = el.offsetParent !== null;
                        if (!visible) continue;
                        // Check filename match if alt present
                        if (expectedFilename && alt && alt.includes(expectedFilename)) {
                            return {found: true, alt: alt, src: src, matched: 'filename'};
                        }
                        // If blob, consider found
                        if (src.startsWith('blob:')) {
                            return {found: true, alt: alt, src: src, matched: 'blob'};
                        }
                        if (alt) {
                            return {found: true, alt: alt, src: src, matched: 'alt_exists'};
                        }
                    }
                }
                return {found: false};
            }
            """
            result = await self.page.evaluate(js, expected_filename)
            if result.get("found"):
                return True, f"Found preview matched via {result.get('matched')}: alt={result.get('alt')}"
            else:
                return False, "Preview not found"
        except Exception as e:
            return False, f"Verification error: {e}"

    async def insert_prompt(self, prompt_text: str, timeout: int = 10000) -> bool:
        """Insert prompt into textarea."""
        if not self.page:
            return False
        sel = get_selector("prompt_textarea")
        loc = await self.find_element(sel, timeout=timeout)
        if not loc:
            self._log("Textarea not found")
            return False
        try:
            # Highlight
            await self.highlight_element(loc, duration_seconds=1)
            # Fill
            await loc.fill(prompt_text)
            # Dispatch events? fill should handle
            await self.page.wait_for_timeout(500)
            return True
        except Exception as e:
            self._log(f"Insert prompt failed: {e}")
            return False

    async def verify_prompt(self, expected_prompt: str) -> tuple[bool, str]:
        """Read back textarea value and compare."""
        if not self.page:
            return False, "No page"
        try:
            js = """
            () => {
                const el = document.querySelector('textarea[name="message"]');
                if (!el) return null;
                return el.value;
            }
            """
            actual = await self.page.evaluate(js)
            if actual is None:
                return False, "Textarea not found on verify"
            if actual == expected_prompt:
                return True, "Exact match"
            else:
                # Provide diff snippet
                return False, f"Mismatch: expected len {len(expected_prompt)}, actual len {len(actual)}"
        except Exception as e:
            return False, f"Verify error: {e}"

    async def submit(self, timeout: int = 10000) -> tuple[bool, str]:
        """Find send button and submit once — waits for enabled after prompt."""
        if not self.page:
            return False, "No page"
        # Wait for button to become enabled (after prompt insertion, React may take time)
        start = time.time()
        last_err = ""
        while (time.time() - start) * 1000 < timeout:
            sel = get_selector("send_button")
            loc = await self.find_element(sel, timeout=2000)
            if loc:
                try:
                    # Check if enabled and visible
                    is_enabled = await loc.is_enabled()
                    is_visible = await loc.is_visible()
                    if is_enabled and is_visible:
                        await self.highlight_element(loc, duration_seconds=1)
                        await loc.click()
                        self._log("Clicked send button once")
                        await self.page.wait_for_timeout(1000)
                        return True, "Clicked"
                    else:
                        last_err = f"Button found but enabled={is_enabled} visible={is_visible}"
                except Exception as e:
                    last_err = str(e)
            else:
                last_err = "Send button not found"
            # Wait a bit and retry
            await self.page.wait_for_timeout(500)
        return False, f"Send button not found or disabled after {timeout}ms: {last_err}"

    async def wait_for_generation(self, baseline: Dict[str, Any], timeout: int = 180000) -> tuple[str, Dict[str, Any]]:
        """
        Wait for generation to finish while handling loading, timeouts, errors, required user actions.
        Understands spinner (Response A/B) as generating indicator — user provided HTML:
        <div class="flex min-w-0 flex-1 items-center gap-2"><div class="h-5 w-5 flex-shrink-0 animate-spin"><canvas></canvas></div><span>Response A</span></div>
        Returns (status, data) where status is completed, needs_review, failed, paused_user_action
        """
        if not self.page:
            return "failed", {"error": "No page"}
        start = time.time()
        poll_interval = 2
        seen_spinning = False

        while (time.time() - start) * 1000 < timeout:
            if await self.is_security_dialog_visible():
                return "paused_user_action", {"reason": "Security verification detected"}
            if await self.is_sign_in_page():
                return "paused_user_action", {"reason": "Authentication required"}

            # Check spinner + new output in one JS call
            js_check = """
            (oldSrcs) => {
              try {
                let spinning = false;
                let spinCount = 0;
                let spinDetails = [];
                try {
                  const spinners = document.querySelectorAll('div.animate-spin');
                  for (const s of spinners) {
                    if (s.offsetParent !== null) {
                      spinning = true; spinCount++;
                      let parent = s.closest('div.flex.min-w-0.flex-1.items-center.gap-2');
                      let label = '';
                      if (parent) { const trunc = parent.querySelector('span.truncate'); if (trunc) label = trunc.textContent.trim(); }
                      spinDetails.push({label: label || 'unknown'});
                    }
                  }
                } catch(e) {}
                const selectors = [
                  'div.no-scrollbar img[src*=".r2.cloudflarestorage.com/"]',
                  'div.no-scrollbar img[src*="messages-prod."]',
                  'div.no-scrollbar img[loading="lazy"].aspect-square',
                  'img.aspect-square.cursor-pointer',
                  'div.flex img[src*=".r2.cloudflarestorage.com/"]',
                  'main img[src*=".r2.cloudflarestorage.com/"]',
                  'img[src*=".r2.cloudflarestorage.com/"]'
                ];
                let newCandidates = [];
                for (const sel of selectors) {
                  try {
                    const els = document.querySelectorAll(sel);
                    for (const el of els) {
                      if (!el.src) continue;
                      if (el.src.startsWith('blob:')) continue;
                      if (oldSrcs.includes(el.src)) continue;
                      if (el.naturalWidth && el.naturalWidth < 50) continue;
                      if (!el.complete) { newCandidates.push({src: el.src, reason: 'not_complete'}); continue; }
                      if (el.naturalWidth === 0) { newCandidates.push({src: el.src, reason: 'zero_width'}); continue; }
                      if (spinning) {
                        return {ready:false, reason:'generating_spinner_visible', src: el.src, spinning: true, spinCount: spinCount, spinDetails: spinDetails};
                      }
                      const rect = el.getBoundingClientRect();
                      return {ready:true, src: el.src, width: el.naturalWidth, height: el.naturalHeight, spinning: false, rect: {x: rect.left, y: rect.top, width: rect.width, height: rect.height}, selector: sel};
                    }
                  } catch(e) {}
                }
                if (newCandidates.length > 0) {
                  return {ready:false, reason: newCandidates[0].reason || 'loading', src: newCandidates[0].src, spinning: spinning, spinCount: spinCount, spinDetails: spinDetails, candidates: newCandidates.length};
                }
                if (spinning) {
                  return {ready:false, reason:'generating_no_new_yet', spinning: true, spinCount: spinCount, spinDetails: spinDetails};
                }
                return {ready:false, reason:'no_new', spinning: false};
              } catch(e) { return {ready:false, reason:String(e), spinning:false}; }
            }
            """
            try:
                old_srcs = baseline.get("output_srcs", [])
                check_result = await self.page.evaluate(js_check, old_srcs)
                if check_result.get("spinning") and not seen_spinning:
                    self._log(f"⏳ Generation started — spinner visible {check_result.get('spinDetails')} (Response A/B processing)")
                    seen_spinning = True
                if check_result.get("ready"):
                    return "completed", {"new_src": check_result.get("src"), "baseline": await self.capture_baseline(), "check": check_result}
            except Exception as e:
                self._log(f"Check new output error: {e}")

            await self.page.wait_for_timeout(poll_interval * 1000)

        return "failed", {"error": f"Generation timeout after {timeout}ms, spinning seen={seen_spinning}", "last_baseline": await self.capture_baseline()}

    async def detect_new_output(self, baseline: Dict[str, Any]) -> tuple[bool, Dict[str, Any]]:
        """Detect a new output image compared to baseline."""
        current = await self.capture_baseline()
        old_srcs = set(baseline.get("output_srcs", []))
        new_outputs = [o for o in current.get("outputs", []) if o.get("src") not in old_srcs]
        if not new_outputs:
            return False, {"reason": "No new src", "current": current}
        # Check if appears after current job (we use timestamp and count)
        # For MVP, if new output exists and is loaded, consider valid
        for out in new_outputs:
            if out.get("complete") and out.get("naturalWidth", 0) > 0:
                return True, {"new_output": out, "current": current}
        return False, {"reason": "New outputs not loaded", "new_outputs": new_outputs, "current": current}

    async def download_image(self, image_src: str, timeout: int = 30000) -> tuple[bool, bytes, str]:
        """
        Download highest-quality available output through permitted mechanism.
        Tries fetch + canvas fallback (handles CORS, blob, r2).
        Returns (success, bytes, error)
        """
        if not self.page:
            return False, b"", "No page"
        try:
            js = """
            async (src) => {
              const tryFetch = async (url) => {
                try {
                  const res = await fetch(url, {credentials: 'include', mode: 'cors'});
                  if (!res.ok) return {ok:false, status:res.status, statusText:res.statusText, method:'fetch'};
                  const buf = await res.arrayBuffer();
                  const contentType = res.headers.get('content-type') || '';
                  const first = new TextDecoder().decode(new Uint8Array(buf.slice(0,100))).toLowerCase();
                  if (first.includes('<html') || first.includes('<!doctype')) return {ok:false, error:'HTML not image', method:'fetch'};
                  return {ok:true, bytes: Array.from(new Uint8Array(buf)), contentType: contentType, method:'fetch'};
                } catch(e) { return {ok:false, error:e.toString(), method:'fetch'}; }
              };
              const tryCanvas = async (url) => {
                try {
                  let imgEl = null;
                  const all = document.querySelectorAll('img');
                  for (const im of all) { if (im.src === url || im.src.includes(url) || url.includes(im.src)) { imgEl = im; break; } }
                  if (!imgEl) imgEl = document.querySelector(`img[src="${url}"]`) || document.querySelector(`img[src*="${url.slice(-30)}"]`);
                  if (!imgEl) return {ok:false, error:'img element not found for canvas', method:'canvas'};
                  if (!imgEl.complete || imgEl.naturalWidth === 0) {
                    await new Promise((res, rej) => {
                      const to = setTimeout(() => rej('timeout'), 5000);
                      imgEl.onload = () => { clearTimeout(to); res(); };
                      imgEl.onerror = () => { clearTimeout(to); rej('load error'); };
                      if (imgEl.complete) { clearTimeout(to); res(); }
                    });
                  }
                  const canvas = document.createElement('canvas');
                  canvas.width = imgEl.naturalWidth || imgEl.width;
                  canvas.height = imgEl.naturalHeight || imgEl.height;
                  if (canvas.width === 0 || canvas.height === 0) return {ok:false, error:'zero dim', method:'canvas'};
                  const ctx = canvas.getContext('2d');
                  try { ctx.drawImage(imgEl, 0, 0); } catch(e) { return {ok:false, error:'drawImage CORS tainted: '+e.toString(), method:'canvas'}; }
                  let dataUrl;
                  try { dataUrl = canvas.toDataURL('image/png'); } catch(e) { return {ok:false, error:'toDataURL CORS: '+e.toString(), method:'canvas'}; }
                  const base64 = dataUrl.split(',')[1];
                  const binary = atob(base64);
                  const bytes = new Uint8Array(binary.length);
                  for (let i=0;i<binary.length;i++) bytes[i] = binary.charCodeAt(i);
                  return {ok:true, bytes: Array.from(bytes), contentType: 'image/png', method:'canvas', width: canvas.width, height: canvas.height};
                } catch(e) { return {ok:false, error:e.toString(), method:'canvas'}; }
              };
              let r = await tryFetch(src);
              if (r.ok) return r;
              let c = await tryCanvas(src);
              if (c.ok) return c;
              return {ok:false, error: `Fetch ${JSON.stringify(r)}; Canvas ${JSON.stringify(c)}`, src: src};
            }
            """
            result = await self.page.evaluate(js, image_src)
            if not result.get("ok"):
                return False, b"", f"Fetch failed: {result}"
            byte_list = result.get("bytes", [])
            data = bytes(byte_list)
            if data[:100].lower().find(b"<html") != -1 or data[:100].lower().find(b"<!doctype") != -1:
                return False, b"", "Downloaded data appears to be HTML, not image"
            return True, data, result.get("contentType", "")
        except Exception as e:
            return False, b"", f"Download exception: {e}"

    async def take_screenshot(self, path: Path):
        if not self.page:
            return
        try:
            await self.page.screenshot(path=str(path), full_page=True)
        except Exception as e:
            self._log(f"Screenshot failed: {e}")
