"""CDP Arena Controller — thin delegation to output_* modules.

Fixes:
- Early-break, inner <p> container, flex-col-reverse misdetect, no fallback
- Delegates baseline/check/wait to output_probes, output_state, output_wait
- 3s stabilization before download per user request
"""

import json
import time
import asyncio
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple, Callable

from .cdp_client import CDPClient
from .output_probes import build_baseline_js, build_check_js
from .output_state import flatten_diagnostics, build_order_check_text
from .output_wait import wait_for_new_output_loop

log = logging.getLogger("arena")

JS_FIND_TEXTAREA = """
(() => {
  const sels = ['textarea[name="message"]','textarea[placeholder^="Describe"]','textarea[rows="1"]'];
  for (const sel of sels) { const el=document.querySelector(sel); if(el&&el.offsetParent!==null) return sel; }
  return null;
})
"""

JS_INSERT_PROMPT = """
((promptText) => {
  try {
    const el=document.querySelector('textarea[name="message"]')||document.querySelector('textarea[placeholder^="Describe"]');
    if(!el) return {ok:false,error:'textarea not found'};
    el.focus();
    const setter=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;
    setter.call(el,promptText);
    el.dispatchEvent(new Event('input',{bubbles:true}));
    el.dispatchEvent(new Event('change',{bubbles:true}));
    el.value=promptText;
    return {ok:true,len:el.value.length};
  } catch(e){return {ok:false,error:String(e)};}
})
"""

JS_VERIFY_PROMPT = """
((expected)=>{
  try{
    const el=document.querySelector('textarea[name="message"]');
    if(!el) return {ok:false,error:'not found'};
    return {ok:el.value===expected,actual:el.value};
  }catch(e){return {ok:false,error:String(e)};}
})
"""

JS_CLICK_SEND = """
(() => {
  try{
    const sels=['button[aria-label="Send message"]:not([disabled])','form button[aria-label="Send message"]','button[aria-label="Send message"]'];
    let btn=null; let used=null;
    for(const sel of sels){
      const els=document.querySelectorAll(sel);
      for(const el of els){
        if(el.offsetParent!==null&&!el.disabled){btn=el;used=sel;break;}
      }
      if(btn) break;
    }
    if(!btn) return {ok:false,error:'send not found'};
    btn.focus();
    btn.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));
    btn.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));
    btn.click();
    return {ok:true,sel:used};
  }catch(e){return {ok:false,error:String(e)};}
})
"""

JS_VERIFY_ATTACHMENT = """
((expectedFilename)=>{
  try{
    const sels=['div.flex.flex-wrap.gap-2 img[alt]','div.flex.flex-wrap.gap-2 img[src^="blob:"]','form img[src^="blob:"]'];
    for(const sel of sels){
      const els=document.querySelectorAll(sel);
      for(const el of els){
        if(el.offsetParent===null) continue;
        const alt=el.getAttribute('alt')||'';
        const src=el.getAttribute('src')||'';
        if(src.startsWith('blob:')) return {found:true,alt,src,matched:'blob'};
        if(alt) return {found:true,alt,src,matched:'alt'};
      }
    }
    return {found:false};
  }catch(e){return {found:false,error:String(e)};}
})
"""

JS_DOWNLOAD_IMAGE = """
async (src) => {
  const tryFetch=async(url)=>{
    try{
      const res=await fetch(url,{credentials:'include',mode:'cors'});
      if(!res.ok) return {ok:false,status:res.status,method:'fetch'};
      const buf=await res.arrayBuffer();
      const first=new Uint8Array(buf.slice(0,100));
      const text=new TextDecoder().decode(first).toLowerCase();
      if(text.includes('<html')||text.includes('<!doctype')) return {ok:false,error:'HTML',method:'fetch'};
      return {ok:true,bytes:Array.from(new Uint8Array(buf)),contentType:res.headers.get('content-type')||'',method:'fetch'};
    }catch(e){return {ok:false,error:e.toString(),method:'fetch'};}
  };
  const tryCanvas=async(url)=>{
    try{
      let imgEl=null;
      const all=document.querySelectorAll('img');
      for(const im of all){if(im.src===url){imgEl=im;break;}}
      if(!imgEl) imgEl=document.querySelector(`img[src="${url}"]`);
      if(!imgEl) return {ok:false,error:'img not found',method:'canvas'};
      if(!imgEl.complete||imgEl.naturalWidth===0){
        await new Promise((res,rej)=>{
          const to=setTimeout(()=>rej('timeout'),5000);
          imgEl.onload=()=>{clearTimeout(to);res();};
          imgEl.onerror=()=>{clearTimeout(to);rej('load error');};
          if(imgEl.complete){clearTimeout(to);res();}
        });
      }
      const canvas=document.createElement('canvas');
      canvas.width=imgEl.naturalWidth||imgEl.width;
      canvas.height=imgEl.naturalHeight||imgEl.height;
      if(canvas.width===0) return {ok:false,error:'zero dim',method:'canvas'};
      const ctx=canvas.getContext('2d');
      ctx.drawImage(imgEl,0,0);
      const dataUrl=canvas.toDataURL('image/png');
      const base64=dataUrl.split(',')[1];
      const binary=atob(base64);
      const bytes=new Uint8Array(binary.length);
      for(let i=0;i<binary.length;i++) bytes[i]=binary.charCodeAt(i);
      return {ok:true,bytes:Array.from(bytes),contentType:'image/png',method:'canvas'};
    }catch(e){return {ok:false,error:e.toString(),method:'canvas'};}
  };
  let r=await tryFetch(src);
  if(r.ok) return r;
  let c=await tryCanvas(src);
  if(c.ok) return c;
  return {ok:false,error:`Fetch ${JSON.stringify(r)} Canvas ${JSON.stringify(c)}`,src};
}
"""

JS_PAGE_READY = """
;(() => {
  const reasons=[];
  const checks=[{sel:'textarea[name="message"]',name:'prompt'},{sel:'button[aria-label="Send message"]',name:'send'},{sel:'input[type="file"]',name:'file'},{sel:'div.no-scrollbar',name:'output'}];
  for(const c of checks){
    const el=document.querySelector(c.sel);
    if(!el) reasons.push(c.name+' not found');
    else if(el.offsetParent===null) reasons.push(c.name+' not visible');
  }
  const dialogs=document.querySelectorAll('div[role="dialog"][data-state="open"]');
  for(const d of dialogs){ if(d.innerText&&d.innerText.includes('Security Verification')) reasons.push('Security dialog'); }
  return {ready:reasons.length===0,reasons};
})()
"""

JS_SECURITY_DIALOG = """
;(() => {
  const dialogs=document.querySelectorAll('div[role="dialog"][data-state="open"]');
  for(const d of dialogs){
    if(d.innerText&&d.innerText.includes('Security Verification')) return true;
    if(d.querySelector('iframe[title="reCAPTCHA"]')) return true;
  }
  const iframes=document.querySelectorAll('iframe[title="reCAPTCHA"]');
  for(const f of iframes){ if(f.offsetParent!==null) return true; }
  return false;
})()
"""

JS_IS_GENERATING = """
;(() => {
  let spinning=false; let count=0; let details=[];
  try{
    const spinners=document.querySelectorAll('div.animate-spin');
    for(const s of spinners){ if(s.offsetParent!==null){spinning=true;count++;details.push({label:'generating'});} }
  }catch(e){}
  return {spinning:spinning,spinCount:count,details:details,isGenerating:spinning};
})()
"""

JS_CLICK_NEW_CHAT = """
(() => {
  try{
    function isVisible(el){
      if(!el) return false;
      try{
        const st=window.getComputedStyle(el);
        if(st && (st.display==='none' || st.visibility==='hidden')) return false;
        const rect=el.getBoundingClientRect();
        if(rect.width===0 && rect.height===0){
          // still allow if has size via parent? check offsetParent fallback
          if(el.offsetParent===null){
            // fixed/sticky may have null offsetParent but rect zero means hidden
            // allow if rect is from hidden sidebar collapsed? check parent visible
            const parentVisible = el.closest('li[data-sidebar="menu-item"]') || el.closest('nav') || el.closest('[data-sidebar]');
            if(parentVisible){
              const pr = parentVisible.getBoundingClientRect();
              if(pr.width===0 && pr.height===0) return false;
            }
          }
        }
        return true;
      }catch(e){ return !!el.offsetParent; }
    }
    function hasNewChatText(el){
      try{
        const txt=(el.innerText||el.textContent||'').toLowerCase();
        return txt.includes('new chat');
      }catch(e){return false;}
    }
    const sels=[
      'a[href="/image/direct"]',
      'a[href*="/image/direct"]',
      'li[data-sidebar="menu-item"] a[href="/image/direct"]',
      'li[data-sidebar="menu-item"] a[href*="/image/direct"]',
      'a[data-sidebar="menu-button"][href="/image/direct"]',
      'a[data-sidebar="menu-button"][href*="/image/direct"]',
      'a[data-sidebar="menu-button"]'
    ];
    // 1) href based - prefer visible with New Chat text
    for(const sel of sels){
      try{
        const els=document.querySelectorAll(sel);
        for(const el of els){
          if(!isVisible(el)) continue;
          if(hasNewChatText(el)){
            try{ el.scrollIntoView({block:'center'}); }catch(e){}
            el.focus();
            el.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));
            el.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));
            el.click();
            return {ok:true,sel:sel,method:'text_match'};
          }
        }
      }catch(e){continue;}
    }
    // 1b) href based any visible (fallback, even without text check)
    for(const sel of sels){
      try{
        const els=document.querySelectorAll(sel);
        for(const el of els){
          if(!isVisible(el)) continue;
          // check href contains direct
          const href=(el.getAttribute('href')||'');
          if(href.includes('/image/direct') || sel.includes('menu-button')){
            // extra check for menu-button: must have New Chat in nearby text
            if(sel==='a[data-sidebar="menu-button"]' && !hasNewChatText(el) && !hasNewChatText(el.parentElement||{})) continue;
            try{ el.scrollIntoView({block:'center'}); }catch(e){}
            el.focus();
            el.click();
            return {ok:true,sel:sel,method:'fallback_href'};
          }
        }
      }catch(e){continue;}
    }
    // 2) search all elements containing New Chat text - find closest anchor/button
    try{
      const all = document.querySelectorAll('li[data-sidebar="menu-item"], li[data-sidebar="menu-item"] a, a, button, [role="button"], span, div');
      for(const el of all){
        if(!isVisible(el)) continue;
        if(hasNewChatText(el)){
          let target = el.closest('a[href*="/image/direct"]') || el.closest('a') || el.closest('button') || el;
          if(target){
            try{ target.scrollIntoView({block:'center'}); }catch(e){}
            try{ target.focus(); }catch(e){}
            target.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));
            target.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));
            target.click();
            return {ok:true, sel:'text:New Chat', method:'text_scan', text:(el.innerText||el.textContent||'').slice(0,50)};
          }
        }
      }
    }catch(e){}
    // 3) specific span New Chat
    try{
      const spans=document.querySelectorAll('span');
      for(const sp of spans){
        if(!isVisible(sp)) continue;
        const t=(sp.innerText||'').trim().toLowerCase();
        if(t==='new chat'){
          let a=sp.closest('a');
          if(a){
            a.click();
            return {ok:true,sel:'span New Chat',method:'span'};
          }
        }
      }
    }catch(e){}
    // 4) report not found - caller will try navigation fallback
    return {ok:false,error:'new chat not found, will try navigation fallback', tried:true};
  }catch(e){return {ok:false,error:String(e)};}
})()
"""

JS_CLICK_NEW_CHAT_EVAL = """
(( ) => {
  const res = (%s)();
  return res;
})
"""


class CDPArenaController:
    def __init__(self, cdp_client: CDPClient, log_callback=None):
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
        self._log("CDP not connected", "warn")
        return False

    async def capture_baseline(self) -> Dict[str, Any]:
        # ideal-size: 6 lines reason=delegates to probe
        js = build_baseline_js()
        result = await self.cdp.evaluate(js)
        if not result:
            return {"output_count": 0, "output_srcs": [], "timestamp": int(time.time()*1000)}
        return result

    async def attach_image(self, image_path: str) -> Tuple[bool, str]:
        # ideal-size: 12 lines reason=attach via CDP then verify
        if not await self.ensure_connected():
            return False, "Not connected"
        ok, reason = await self.cdp.attach_image_cdp(image_path)
        if not ok:
            self._log(f"Attach failed: {reason}", "warn")
            return False, reason
        self._log(f"Attached {image_path}: {reason}")
        await asyncio.sleep(1)
        verified, vreason = await self.verify_attachment(Path(image_path).name)
        if verified:
            return True, vreason
        await asyncio.sleep(2)
        return await self.verify_attachment(Path(image_path).name)

    async def verify_attachment(self, expected_filename: str) -> Tuple[bool, str]:
        # ideal-size: 7 lines reason=verify blob preview
        js = f";({JS_VERIFY_ATTACHMENT})({json.dumps(expected_filename)})"
        result = await self.cdp.evaluate(js)
        if not result:
            return False, "No result"
        if result.get("found"):
            return True, f"Found via {result.get('matched')}"
        return False, f"Not found: {result}"

    async def insert_prompt(self, prompt_text: str) -> Tuple[bool, str]:
        # ideal-size: 9 lines reason=insert with highlight
        if not await self.ensure_connected():
            return False, "Not connected"
        try:
            await self.highlight_selector('textarea[name="message"]', color="#00AAFF", duration_ms=1000, caption="Prompt")
        except Exception:
            pass
        js = f";({JS_INSERT_PROMPT})({json.dumps(prompt_text)})"
        result = await self.cdp.evaluate(js)
        if not result:
            return False, "No result"
        if result.get("ok"):
            return True, f"Inserted len {result.get('len')}"
        return False, result.get("error", "Unknown")

    async def verify_prompt(self, expected: str) -> Tuple[bool, str]:
        # ideal-size: 6 lines reason=verify exact match
        js = f";({JS_VERIFY_PROMPT})({json.dumps(expected)})"
        result = await self.cdp.evaluate(js)
        if not result:
            return False, "No result"
        if result.get("ok"):
            return True, "Exact match"
        return False, f"Mismatch: {result}"

    async def submit(self) -> Tuple[bool, str]:
        # ideal-size: 9 lines reason=click send with highlight
        if not await self.ensure_connected():
            return False, "Not connected"
        try:
            await self.highlight_selector('button[aria-label="Send message"]', color="#FFAA00", duration_ms=1000, caption="Send")
        except Exception:
            pass
        js = f";({JS_CLICK_SEND})()"
        result = await self.cdp.evaluate(js)
        if not result:
            return False, "No result"
        if result.get("ok"):
            return True, "Clicked"
        return False, result.get("error", "Failed")

    async def wait_for_new_output(self, baseline: Dict[str, Any], timeout_ms: int = 180000, correlation_id: Optional[str] = None, cancel_check=None) -> Tuple[str, Dict[str, Any]]:
        # ideal-size: 20 lines reason=delegates to wait loop with 3s stabilization
        old_srcs = baseline.get("output_srcs", []) or []
        old_outputs = baseline.get("outputs", []) or []

        async def check_fn():
            js = build_check_js(old_srcs, correlation_id, old_outputs)
            res = await self.cdp.evaluate(js)
            return flatten_diagnostics(res) if res else {"ready": False, "reason": "no_result"}

        def log_cb(msg: str):
            self._log(msg)

        try:
            result = await wait_for_new_output_loop(
                check_fn=check_fn,
                log_cb=log_cb,
                cancel_check=cancel_check,
                timeout=timeout_ms / 1000.0,
                poll_interval=2.0,
            )
            if result.get("ready"):
                rect = result.get("rect")
                return "completed", {"new_src": result.get("src"), "check": result, "baseline": baseline, "rect": rect}
            if result.get("reason") == "cancelled":
                return "failed", {"error": "Cancelled", "cancelled": True}
            final_baseline = await self.capture_baseline()
            return "failed", {"error": f"Timeout after {timeout_ms}ms", "last_baseline": final_baseline, "last_check": result}
        except Exception as e:
            return "failed", {"error": str(e)}

    async def _python_download(self, src: str) -> Tuple[bool, bytes, str]:
        def sync_fetch(url: str):
            import urllib.request, ssl
            hdr = {"User-Agent": "Mozilla/5.0 Chrome/120", "Accept": "image/*,*/*;q=0.8"}
            req = urllib.request.Request(url, headers=hdr)
            ctx = ssl.create_default_context()
            try:
                with urllib.request.urlopen(req, timeout=45, context=ctx) as r:
                    return r.read(), r.headers.get("Content-Type", "") or "", 200
            except Exception:
                with urllib.request.urlopen(req, timeout=45) as r2:
                    return r2.read(), getattr(r2.headers, 'get', lambda k,d="": d)("Content-Type", "") or "", 200
        loop = asyncio.get_event_loop()
        try:
            data, ctype, _ = await loop.run_in_executor(None, lambda: sync_fetch(src))
            if not data or len(data) < 100:
                return False, b"", f"Too small {len(data)}"
            low = data[:200].lower()
            if b"<html" in low or b"<!doctype" in low:
                return False, b"", f"HTML page: {data[:500].decode(errors='ignore')[:200]}"
            self._log(f"Python download {len(data)} bytes {ctype} {src[:60]}...", "success")
            return True, data, ctype
        except Exception as e:
            return False, b"", f"Python download failed: {e}"

    async def download_image(self, src: str) -> Tuple[bool, bytes, str]:
        # ideal-size: 20 lines reason=JS fetch then Python fallback
        js = f";({JS_DOWNLOAD_IMAGE})({json.dumps(src)})"
        try:
            result = await self.cdp.evaluate(js)
            if result and result.get("ok"):
                data = bytes(result.get("bytes", []))
                if len(data) > 100 and b"<html" not in data[:100].lower():
                    return True, data, result.get("contentType", "")
                self._log(f"JS returned HTML/small {len(data)}, trying Python", "warn")
            else:
                err = result.get("error") if result else "No result"
                self._log(f"JS download failed {str(err)[:120]} trying Python", "warn")
        except Exception as e:
            self._log(f"JS download exc {e} trying Python", "warn")

        ok, data, ctype = await self._python_download(src)
        if ok:
            return True, data, ctype

        return False, b"", f"All methods failed for {src[:120]}"

    def report(self, message: str, level: str = "info"):
        self._log(message, level)

    async def highlight_selector(self, selector: str, color: str = "#FF0000", duration_ms: int = 2000, caption: str = "") -> dict | None:
        # ideal-size: 14 lines reason=highlight via dom_highlight probe
        try:
            from .dom_highlight import build_highlight_probe, build_highlight_js, build_clear_js
            from .probe_requests import HighlightSpec
            spec = HighlightSpec(color=color, caption=caption or selector[:40], highlight_ms=duration_ms, clear_first=True)
            js = build_highlight_probe(selector, spec)
            raw = await self.cdp.evaluate(js)
            if raw:
                try:
                    data = json.loads(raw) if isinstance(raw, str) else raw
                    if isinstance(data, dict) and data.get("rect"):
                        return data.get("rect")
                except Exception:
                    pass
            js2 = build_highlight_js(selector, color, duration_ms, caption, clear_first=True)
            raw2 = await self.cdp.evaluate(js2)
            if raw2:
                try:
                    data2 = json.loads(raw2) if isinstance(raw2, str) else raw2
                    if isinstance(data2, dict) and data2.get("rect"):
                        return data2.get("rect")
                except Exception:
                    pass
            return {"x": 100, "y": 100, "width": 200, "height": 100}
        except Exception as e:
            log.debug(f"highlight failed {e}")
            return None

    async def clear_highlights(self):
        # ideal-size: 5 lines reason=clear overlay
        try:
            from .dom_highlight import build_clear_js
            js = build_clear_js()
            await self.cdp.evaluate(js)
        except Exception as e:
            log.debug(f"clear failed {e}")

    async def show_watcher_overlay(self, message: str = "wait for finish generation", kind: str = "generation", timeout_sec: int = 600, elapsed_sec: int = 0) -> bool:
        # ideal-size: 10 lines reason=show watcher overlay with timeout from win settings
        try:
            from .dom_highlight import build_watcher_overlay_js
            js = build_watcher_overlay_js(message=message, kind=kind, timeout_sec=timeout_sec, elapsed_sec=elapsed_sec)
            raw = await self.cdp.evaluate(js)
            if raw:
                try:
                    data = json.loads(raw) if isinstance(raw, str) else raw
                    return bool(data.get("shown")) if isinstance(data, dict) else True
                except Exception:
                    return True
            return False
        except Exception as e:
            log.debug(f"watcher overlay failed {e}")
            return False

    async def hide_watcher_overlay(self) -> bool:
        # ideal-size: 5 lines reason=hide overlay
        try:
            from .dom_highlight import build_watcher_clear_js
            js = build_watcher_clear_js()
            await self.cdp.evaluate(js)
            return True
        except Exception as e:
            log.debug(f"hide watcher failed {e}")
            return False

    async def is_page_ready(self) -> Tuple[bool, List[str]]:
        # ideal-size: 5 lines reason=readiness check
        result = await self.cdp.evaluate(JS_PAGE_READY)
        if not result:
            return False, ["No result"]
        return bool(result.get("ready")), result.get("reasons", [])

    async def is_security_dialog_visible(self) -> bool:
        # ideal-size: 3 lines reason=security dialog check
        result = await self.cdp.evaluate(JS_SECURITY_DIALOG)
        return bool(result)

    async def is_generating(self) -> Tuple[bool, Dict[str, Any]]:
        # ideal-size: 7 lines reason=spinner check
        try:
            result = await self.cdp.evaluate(JS_IS_GENERATING)
            if not result:
                return False, {}
            is_gen = bool(result.get("isGenerating") or result.get("spinning"))
            return is_gen, result
        except Exception as e:
            log.debug(f"is_generating failed {e}")
            return False, {"error": str(e)}

    async def get_generation_state(self, correlation_id: Optional[str] = None) -> Dict[str, Any]:
        # ideal-size: 6 lines reason=detailed state
        js = build_check_js([], correlation_id, [])
        try:
            result = await self.cdp.evaluate(js)
            return result or {}
        except Exception as e:
            return {"error": str(e), "spinning": False}

    async def _try_js_navigation(self) -> Tuple[bool, str]:
        # ideal-size: 12 lines reason=navigate via JS location
        try:
            js_nav = """
            (() => {
              try{
                const origin = window.location.origin || 'https://arena.ai';
                const target = origin + '/image/direct';
                // try pushState first to avoid full reload flicker? use href for clean chat
                window.location.href = '/image/direct';
                return {ok:true, url: target};
              }catch(e){ return {ok:false, error:String(e)}; }
            })()
            """
            res = await self.cdp.evaluate(js_nav)
            if res and res.get("ok"):
                self._log(f"🔄 Navigating to new chat via JS location {res.get('url')}", "info")
                return True, f"JS nav {res.get('url')}"
            return False, res.get("error","js nav failed") if res else "no result"
        except Exception as e:
            return False, str(e)

    async def _try_cdp_navigation(self) -> Tuple[bool, str]:
        # ideal-size: 12 lines reason=navigate via CDP Page.navigate
        try:
            # build target url from current url or default arena.ai
            base = "https://arena.ai"
            try:
                cur = getattr(self.cdp, '_current_url', '') or ''
                if cur and '://' in cur:
                    from urllib.parse import urlparse
                    p = urlparse(cur)
                    base = f"{p.scheme}://{p.netloc}"
            except Exception:
                pass
            target = base.rstrip('/') + '/image/direct'
            await self.cdp.send("Page.navigate", {"url": target}, timeout=15)
            self._log(f"🔄 CDP Page.navigate to {target}", "info")
            return True, f"CDP nav {target}"
        except Exception as e:
            return False, str(e)

    async def click_new_chat(self) -> Tuple[bool, str]:
        # ideal-size: 22 lines reason=robust click with fallbacks per spec
        if not await self.ensure_connected():
            return False, "Not connected"
        try:
            await self.highlight_selector('a[href="/image/direct"]', color="#00AAFF", duration_ms=800, caption="New Chat")
        except Exception:
            pass
        # 1) try JS click selectors
        try:
            js = f";({JS_CLICK_NEW_CHAT})()"
            result = await self.cdp.evaluate(js)
            if result and result.get("ok"):
                self._log(f"✅ New Chat clicked via {result.get('sel')} {result.get('method')} {result.get('text','')}", "success")
                return True, f"Clicked {result.get('sel')} {result.get('method')}"
            else:
                err = result.get("error","") if result else "No result"
                self._log(f"⚠ New Chat JS click failed {err}, trying JS navigation", "warn")
        except Exception as e:
            self._log(f"⚠ New Chat JS click exception {e}, trying JS navigation", "warn")

        # 2) JS location fallback
        ok_nav, reason_nav = await self._try_js_navigation()
        if ok_nav:
            await asyncio.sleep(1.5)
            return True, reason_nav

        # 3) CDP Page.navigate fallback
        ok_cdp, reason_cdp = await self._try_cdp_navigation()
        if ok_cdp:
            await asyncio.sleep(1.5)
            return True, reason_cdp

        return False, f"All click/nav failed: {reason_nav} / {reason_cdp}"

    async def reset_to_new_chat(self, timeout_sec: int = 15) -> Tuple[bool, str]:
        # ideal-size: 28 lines reason=click or navigate then wait ready
        ok, reason = await self.click_new_chat()
        if not ok:
            self._log(f"⚠ New Chat click/nav failed {reason}, trying reload as last resort", "warn")
            # try reload only as last resort, but still try to ensure new chat via nav after reload
            await self.reload_page()
            # after reload, try again navigation to /image/direct
            ok2, reason2 = await self._try_js_navigation()
            if ok2:
                ok = True
                reason = reason2
            else:
                ok3, reason3 = await self._try_cdp_navigation()
                if ok3:
                    ok = True
                    reason = reason3
                else:
                    return False, f"Reset failed {reason} / {reason2} / {reason3}"

        self._log(f"🔄 New Chat triggered {reason}, waiting page ready full load", "info")
        await asyncio.sleep(1.5)
        for i in range(max(1, timeout_sec)):
            try:
                ready, reasons = await self.is_page_ready()
                if ready:
                    self._log(f"✅ New Chat ready after {i+1}s — clean new chat, ready for next job", "success")
                    return True, "Ready after new chat"
                if i % 3 == 0:
                    self._log(f"⏳ Waiting new chat ready {i+1}s: {reasons}", "info")
            except Exception as e:
                self._log(f"Ready check failed {e}", "warn")
            await asyncio.sleep(1)

        # Even if not fully ready, consider success if we navigated to /image/direct
        try:
            cur_url = await self.cdp.evaluate("window.location.href")
            if cur_url and "/image/direct" in str(cur_url):
                self._log(f"✅ New Chat URL detected {cur_url} but not fully ready after timeout", "success")
                return True, f"URL {cur_url} but not fully ready"
        except Exception:
            pass

        self._log("⚠ New Chat triggered but not fully ready after timeout, still marking as ready", "warn")
        return True, "Clicked/nav but not fully ready"

    async def reload_page(self) -> Tuple[bool, str]:
        # ideal-size: 14 lines reason=reload via CDP then JS fallback
        try:
            self._log("🔄 Reloading page after timeout", "warn")
            try:
                await self.cdp.send("Page.reload", {}, timeout=15)
            except Exception as e:
                self._log(f"Page.reload failed {e}, trying location.reload", "warn")
                try:
                    await self.cdp.evaluate("window.location.reload(); true")
                except Exception as e2:
                    return False, f"Both reload failed: {e} / {e2}"
            await asyncio.sleep(4)
            for i in range(10):
                ready, _ = await self.is_page_ready()
                if ready:
                    self._log(f"✅ Reloaded ready after {i+1}s", "success")
                    return True, "Reloaded and ready"
                await asyncio.sleep(1)
            self._log("⚠ Reloaded but not fully ready", "warn")
            return True, "Reloaded not fully ready"
        except Exception as e:
            self._log(f"Reload failed {e}", "error")
            return False, str(e)
