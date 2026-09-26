"""JS snippets for Arena controller (C3 split).

RULE 21: every selector that reaches the page is injected from
`app/browser/probe_selectors` (single source = `site_adapter.py`); the
payloads below carry `__PLACEHOLDER__` markers only. `_inject` fills them
with JSON so a selector edit happens in site_adapter alone.
"""
import json

from ..probe_selectors import (
    attachment_preview_selectors,
    readiness_checks,
    security_dialog_check,
    send_click_selectors,
    send_presence_selector,
    spinner_selector,
    textarea_primary,
    textarea_selectors,
)
from ..captcha_probes import build_visible_js


def _inject(js: str, **payloads: str) -> str:
    """Fill __NAME__ placeholders with JSON selector payloads (RULE 21)."""
    for key, value in payloads.items():
        js = js.replace(f"__{key.upper()}__", value)
    return js


JS_FIND_TEXTAREA = _inject("""
(() => {
  const sels = __TEXTAREA_SELECTORS__;
  for (const sel of sels) { const el=document.querySelector(sel); if(el&&el.offsetParent!==null) return sel; }
  return null;
})
""", TEXTAREA_SELECTORS=json.dumps(textarea_selectors()))

JS_INSERT_PROMPT = _inject("""
((promptText) => {
  try {
    const sels=__TEXTAREA_SELECTORS__;
    let el=null;
    for(const sel of sels){
      const els=document.querySelectorAll(sel);
      for(const cand of els){ if(cand.offsetParent!==null){ el=cand; break; } }
      if(el) break;
    }
    if(!el){
      const any=document.querySelector(sels.join(','));
      return {ok:false,error:any?'textarea hidden':'textarea not found'};
    }
    el.focus();
    const setter=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;
    setter.call(el,promptText);
    el.dispatchEvent(new Event('input',{bubbles:true}));
    el.dispatchEvent(new Event('change',{bubbles:true}));
    el.value=promptText;
    return {ok:true,len:el.value.length};
  } catch(e){return {ok:false,error:String(e)};}
})
""", TEXTAREA_SELECTORS=json.dumps(textarea_selectors()))

JS_SEND_STATE = _inject("""
(() => {
  try{
    const els=document.querySelectorAll(__SEND_PRESENCE_SELECTOR__);
    if(!els.length) return {found:false,visible:false,enabled:false};
    let visible=false, enabled=false;
    for(const el of els){
      if(el.offsetParent===null) continue;
      visible=true;
      if(!el.disabled){ enabled=true; break; }
    }
    return {found:true,visible:visible,enabled:enabled};
  }catch(e){return {found:false,visible:false,enabled:false};}
})
""", SEND_PRESENCE_SELECTOR=json.dumps(send_presence_selector()))

JS_VERIFY_PROMPT = _inject("""
((expected)=>{
  try{
    const el=document.querySelector(__TEXTAREA_PRIMARY__);
    if(!el) return {ok:false,error:'not found'};
    return {ok:el.value===expected,actual:el.value};
  }catch(e){return {ok:false,error:String(e)};}
})
""", TEXTAREA_PRIMARY=json.dumps(textarea_primary()))

JS_CLICK_SEND = _inject("""
(() => {
  try{
    const sels=__SEND_CLICK_SELECTORS__;
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
""", SEND_CLICK_SELECTORS=json.dumps(send_click_selectors()))

JS_VERIFY_ATTACHMENT = _inject("""
((expectedFilename)=>{
  try{
    const sels=__ATTACHMENT_PREVIEW_SELECTORS__;
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
""", ATTACHMENT_PREVIEW_SELECTORS=json.dumps(attachment_preview_selectors()))

# Page-side download in slices (2026-09-26, design D-1): the image is fetched
# ONCE into `window.__arenaDl[key]` as base64 and only its size comes back; the
# Python side pulls `JS_READ_SLOT` slices and frees the slot. The old snippet
# returned the whole image as a JSON number array in one reply (~4 bytes per
# image byte) — a 20 MB PNG closed the socket with 1009 "message too big".
# Fetch order: no credentials (presigned R2 src), with credentials (same-origin /
# blob:), then the page's own <img> via canvas (PNG re-encode, last resort).
JS_FETCH_TO_SLOT = """
async (src, key) => {
  const store = (window.__arenaDl = window.__arenaDl || {});
  const toB64 = (blob) => new Promise((ok, no) => {
    const r = new FileReader();
    r.onload = () => ok(String(r.result).split(',')[1] || '');
    r.onerror = () => no(r.error || new Error('read failed'));
    r.readAsDataURL(blob);
  });
  const viaFetch = async (credentials) => {
    const res = await fetch(src, {credentials});
    if (!res.ok) throw new Error('HTTP ' + res.status);
    return res.blob();
  };
  const viaCanvas = async () => {
    const img = Array.from(document.images).find((im) => im.src === src);
    if (!img || !img.naturalWidth) throw new Error('img not on page');
    const c = document.createElement('canvas');
    c.width = img.naturalWidth; c.height = img.naturalHeight;
    c.getContext('2d').drawImage(img, 0, 0);
    return new Promise((ok, no) => c.toBlob((b) => (b ? ok(b) : no(new Error('canvas empty'))), 'image/png'));
  };
  const tries = [['fetch', () => viaFetch('omit')], ['fetch+cookies', () => viaFetch('include')], ['canvas', viaCanvas]];
  const errors = [];
  for (const [method, run] of tries) {
    try {
      const blob = await run();
      const b64 = await toB64(blob);
      store[key] = b64;
      return {ok: true, size: blob.size, b64len: b64.length, contentType: blob.type || '', method};
    } catch (e) { errors.push(method + ': ' + String(e && e.message || e)); }
  }
  return {ok: false, error: errors.join('; ')};
}
"""

JS_READ_SLOT = """
((key, start, count) => {
  const s = (window.__arenaDl || {})[key];
  return typeof s === 'string' ? s.slice(start, start + count) : null;
})
"""

JS_FREE_SLOT = """
((key) => { if (window.__arenaDl) delete window.__arenaDl[key]; return true; })
"""

_SECURITY_DIALOG = security_dialog_check()

JS_PAGE_READY = _inject("""
;(() => {
  const reasons=[];
  const checks=__READINESS_CHECKS__;
  for(const c of checks){
    const el=document.querySelector(c.sel);
    if(!el) reasons.push(c.name+' not found');
    else if(el.offsetParent===null) reasons.push(c.name+' not visible');
  }
  const dialogs=document.querySelectorAll(__SECURITY_DIALOG_SEL__);
  for(const d of dialogs){ if(d.innerText&&d.innerText.includes(__SECURITY_DIALOG_TEXT__)) reasons.push('Security dialog'); }
  return {ready:reasons.length===0,reasons};
})()
""",
    READINESS_CHECKS=json.dumps(readiness_checks()),
    SECURITY_DIALOG_SEL=json.dumps(_SECURITY_DIALOG["sel"]),
    SECURITY_DIALOG_TEXT=json.dumps(_SECURITY_DIALOG["text"]),
)

JS_SECURITY_DIALOG = build_visible_js()

JS_IS_GENERATING = _inject("""
;(() => {
  let spinning=false; let count=0; let details=[];
  try{
    const spinners=document.querySelectorAll(__SPINNER_SELECTOR__);
    for(const s of spinners){ if(s.offsetParent!==null){spinning=true;count++;details.push({label:'generating'});} }
  }catch(e){}
  return {spinning:spinning,spinCount:count,details:details,isGenerating:spinning};
})()
""", SPINNER_SELECTOR=json.dumps(spinner_selector()))
