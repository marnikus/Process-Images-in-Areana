"""DOM highlight — C6 refactor with HighlightSpec param objects and small helpers."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from app.browser.probe_requests import (
    COLOR_CLICK,
    ClickProbeSpec,
    FindProbeSpec,
    HighlightSpec,
    MATCH_EXACT,
)

HIGHLIGHT_ATTR = "data-arena-highlight"
STASH_KEY = "__arenaStash"
WATCHER_ATTR = "data-arena-watcher-overlay"

_HELPERS_JS = """
  function probeVisible(el) {
    var st = null;
    try { st = window.getComputedStyle(el); } catch(e) {}
    if (st && (st.display === 'none' || st.visibility === 'hidden')) {
      return {visible: false, disabled: !!el.disabled || st.pointerEvents === 'none'};
    }
    var metrics = !!(el.offsetWidth || el.offsetHeight || (el.getClientRects && el.getClientRects().length));
    return {visible: metrics, disabled: !!el.disabled || (st && st.pointerEvents === 'none')};
  }
  function describe(el) {
    if (!el || !el.tagName) return null;
    var cls = '';
    try { cls = el.className && String(el.className).trim() ? '.' + String(el.className).trim().split(/\\s+/).join('.') : ''; } catch(e) {}
    return el.tagName.toLowerCase() + cls;
  }
  function clearHighlights() {
    try { var old = document.querySelectorAll('[__ATTR__]'); for (var k=0;k<old.length;k++) if (old[k].parentNode) old[k].parentNode.removeChild(old[k]); } catch(e) {}
  }
  function highlight(el, color, ms, caption) {
    try {
      if (!el || !el.getBoundingClientRect) return null;
      var r = el.getBoundingClientRect();
      if (!r || (!r.width && !r.height)) return null;
      var box = document.createElement('div');
      box.setAttribute('__ATTR__', '1');
      box.style.cssText = ['position:fixed','left:'+Math.max(0,r.left)+'px','top:'+Math.max(0,r.top)+'px','width:'+Math.max(0,r.width)+'px','height:'+Math.max(0,r.height)+'px','outline:2px solid '+color,'outline-offset:-1px','background:transparent','pointer-events:none','z-index:2147483647'].join(';');
      if (caption) { var tag=document.createElement('div'); tag.textContent=caption; tag.style.cssText=['position:absolute','left:0','top:-16px','font:700 10px/14px sans-serif','letter-spacing:.5px','padding:0 4px','color:#fff','white-space:nowrap','background:'+color,'pointer-events:none'].join(';'); box.appendChild(tag); }
      (document.body||document.documentElement).appendChild(box);
      var life=ms>0?ms:2000; setTimeout(function(){ if(box.parentNode) box.parentNode.removeChild(box); }, life);
      return {x:r.left,y:r.top,width:r.width,height:r.height};
    } catch(e) { return null; }
  }
""".replace("__ATTR__", HIGHLIGHT_ATTR)


def _js_str(value: str) -> str:
    return json.dumps(str(value or ""))


def _base_out_js() -> str:
    return """
  var out = {phase:null,query:null,total:0,found:false,index:-1,text:'',visible:false,disabled:false,clickable:false,clicked:false,clicked_target:null,target_desc:null,highlighted:false,rect:null,candidates:[],note:null,error:null};
"""


_PROBE_JS = """
;(function(){
%(out)s
%(helpers)s
  try {
%(body)s
  } catch (err) { out.error = String(err && err.message || err); }
  return JSON.stringify(out);
})()
"""


def _probe(body: str, **fields) -> str:
    script = body % fields
    return _PROBE_JS % {"out": _base_out_js(), "helpers": _HELPERS_JS, "body": script.strip("\n")}


def _splice(body: str, **fragments) -> str:
    for name, fragment in fragments.items():
        body = body.replace(f"__{name.upper()}__", fragment.strip("\n"))
    return body


_QUERY_VARS = """
    var sel = %(selector)s;
    var childSel = %(label_selector)s;
    var matchText = %(match_text)s;
    var exact = %(exact)s;
"""

_LABEL_JS = """
      var node = nodes[i];
      var el = node;
      var label = (node.textContent || '').trim().replace(/\\s+/g, ' ');
      if (childSel) { var c = node.querySelector(childSel); if (c) { el = c; label = (c.textContent || '').trim().replace(/\\s+/g, ' '); }"""

_MATCH_JS = """
      if (matchText !== null && matchText !== undefined && matchText !== '') {
        if (exact) { if (label !== matchText) { continue; } }
        else { if (label.indexOf(matchText) < 0) { continue; } }
      }
"""

_FIND_BODY = _splice("""
    out.phase = 'find';
__QUERY__
    var doHighlight = %(highlight)s;
    out.query = sel;
    clearHighlights();
    try { window.%(stash)s = null; } catch(e) {}
    var nodes = Array.prototype.slice.call(document.querySelectorAll(sel));
    out.total = nodes.length;
    var cands = [];
    for (var i = 0; i < nodes.length; i++) {
__LABEL__
      if (label.length > 120) label = label.slice(0, 120) + '\\u2026';
__MATCH__
      var vi = probeVisible(node);
      if (!out.found) {
        out.found = true; out.index = i; out.text = label;
        out.visible = vi.visible; out.disabled = vi.disabled;
        out.clickable = vi.visible && !vi.disabled;
        out.target_desc = describe(node);
        try { window.%(stash)s = node; } catch(e) {}
        if (doHighlight) { var rect = highlight(node, %(color)s, %(hms)s, %(caption)s); out.rect = rect; out.highlighted = !!rect; }
      }
      cands.push({index: i, text: label, visible: vi.visible, clickable: vi.visible && !vi.disabled});
    }
    out.candidates = cands.slice(0, %(maxcand)s);
""", query=_QUERY_VARS, label=_LABEL_JS, match=_MATCH_JS)

_HIGHLIGHT_BODY = _splice("""
    out.phase = 'highlight';
__QUERY__
    out.query = sel;
    if (%(clear)s) clearHighlights();
    var nodes = Array.prototype.slice.call(document.querySelectorAll(sel));
    out.total = nodes.length;
    for (var i = 0; i < nodes.length; i++) {
__LABEL__
__MATCH__
      var vi = probeVisible(node);
      out.found = true; out.index = i; out.text = label;
      out.visible = vi.visible; out.disabled = vi.disabled;
      out.clickable = vi.visible && !vi.disabled;
      out.target_desc = describe(node);
      var rect = highlight(node, %(color)s, %(hms)s, %(caption)s);
      out.rect = rect; out.highlighted = !!rect; break;
    }
""", query=_QUERY_VARS, label=_LABEL_JS, match=_MATCH_JS)

_CLICK_BODY = """
    out.phase = 'click';
    var doHighlight = %(highlight)s;
    var doClick = %(do_click)s;
    var clickSel = %(click_selector)s;
    var root = null;
    try { root = window.%(stash)s; } catch(e) {}
    if (!root) { out.error = 'no element stashed from the find phase'; return JSON.stringify(out); }
    if (!root.isConnected) { out.error = 'the found element is no longer attached to the page'; return JSON.stringify(out); }
    var target = root;
    if (clickSel) {
      var inner = root.querySelector(clickSel);
      if (!inner) { var selfMatch=false; try{ selfMatch=!!(root.matches && root.matches(clickSel)); }catch(e){} if(selfMatch){ inner=root; out.note='click selector matches the found element itself'; } }
      if (!inner) { out.error='click target '+clickSel+' not found inside the element'; return JSON.stringify(out); }
      target = inner;
    }
    out.found = true; out.text = (target.textContent||'').trim().replace(/\\s+/g,' ').slice(0,120);
    out.target_desc = describe(target); out.clicked_target = out.target_desc;
    var vi = probeVisible(target); out.visible=vi.visible; out.disabled=vi.disabled; out.clickable=vi.visible && !vi.disabled;
    if (doHighlight) { var rect=highlight(target,%(color)s,%(hms)s,%(caption)s); out.rect=rect; out.highlighted=!!rect; }
    if (doClick && out.clickable) { try{ if(target.scrollIntoView) target.scrollIntoView({block:'center',inline:'center'}); }catch(e){} try{ target.click(); out.clicked=true; }catch(err){ out.error=String(err && err.message || err); } }
"""


def build_find_probe(selector: str, spec: Optional[FindProbeSpec] = None) -> str:
    spec = spec or FindProbeSpec()
    return _probe(_FIND_BODY,
                  selector=_js_str(selector),
                  label_selector=(_js_str(spec.label_selector) if spec.label_selector else "null"),
                  match_text=(_js_str(spec.match_text) if spec.match_text else "null"),
                  exact="true" if spec.match_mode == MATCH_EXACT else "false",
                  highlight="true" if spec.highlight else "false",
                  color=_js_str(spec.color),
                  caption=_js_str(spec.caption),
                  hms=int(spec.highlight_ms),
                  stash=STASH_KEY,
                  maxcand=int(spec.max_candidates))


def build_click_probe(click_selector: Optional[str] = None, spec: Optional[ClickProbeSpec] = None) -> str:
    spec = spec or ClickProbeSpec()
    return _probe(_CLICK_BODY,
                  click_selector=(_js_str(click_selector) if click_selector else "null"),
                  highlight="true" if spec.highlight else "false",
                  do_click="true" if spec.do_click else "false",
                  color=_js_str(spec.color),
                  caption=_js_str(spec.caption),
                  hms=int(spec.highlight_ms),
                  stash=STASH_KEY)


def build_highlight_probe(selector: str, spec: Optional[HighlightSpec] = None) -> str:
    spec = spec or HighlightSpec()
    return _probe(_HIGHLIGHT_BODY,
                  selector=_js_str(selector),
                  label_selector=(_js_str(spec.label_selector) if spec.label_selector else "null"),
                  match_text=(_js_str(spec.match_text) if spec.match_text else "null"),
                  exact="true" if spec.match_mode == MATCH_EXACT else "false",
                  clear="true" if spec.clear_first else "false",
                  color=_js_str(spec.color),
                  caption=_js_str(spec.caption),
                  hms=int(spec.highlight_ms))


def build_clear_probe() -> str:
    return """
;(function(){
  try { var old=document.querySelectorAll('[%(attr)s]'); for(var k=0;k<old.length;k++) if(old[k].parentNode) old[k].parentNode.removeChild(old[k]); return JSON.stringify({cleared: old.length}); } catch(err){ return JSON.stringify({cleared:0}); }
})()
""" % {"attr": HIGHLIGHT_ATTR}


# ---- interpretation helpers (C6 small funcs) ----

def _candidate_lines(result: dict) -> str:
    cands = result.get("candidates") or []
    if not cands:
        return ""
    parts = []
    for c in cands[:4]:
        parts.append(f"[{c.get('index')}] \"{str(c.get('text',''))[:40]}\" "
                     f"({'visible' if c.get('visible') else 'hidden'}, "
                     f"{'clickable' if c.get('clickable') else 'not clickable'})")
    return " Candidates: " + "; ".join(parts) + "."


def interpret_find(result, label: str = "element") -> tuple[str, str]:
    if not result:
        return f"❌ FIND failed: no data returned for {label} (page context unavailable?)", "error"
    if result.get("error"):
        return f"❌ FIND error while searching {label}: {result['error']}", "error"
    total = int(result.get("total", 0) or 0)
    if not result.get("found"):
        return (f"❌ FIND failed: {label} — selector matched {total} node(s), none with the required text/properties."
                + _candidate_lines(result)), "error"
    text = str(result.get("text", ""))[:60]
    idx = result.get("index", -1)
    msg = f"✅ FIND success: {label} — matched node #{idx} \"{text}\" ({_found_state(result)})" + _outline_suffix(result)
    return msg, ("success" if result.get("visible") else "warn")


def _found_state(result: dict) -> str:
    state = "visible" if result.get("visible") else "⚠ NOT visible (hidden/zero-size)"
    if result.get("disabled"):
        state += ", ⚠ disabled (or pointer-events:none)"
    return state


def _outline_suffix(result: dict) -> str:
    if result.get("highlighted"):
        rect = result.get("rect") or {}
        if not rect:
            return " — 🟥 red outline drawn"
        return f" — 🟥 red outline drawn at {int(rect.get('x',0))},{int(rect.get('y',0))} {int(rect.get('width',0))}×{int(rect.get('height',0))}px"
    return " — (highlight off)" if result.get("visible") else ""


def interpret_click(result, label: str = "element") -> tuple[str, str]:
    if not result:
        return f"❌ CLICK failed: no data returned for {label}", "error"
    if result.get("error") and not result.get("clicked"):
        return f"❌ CLICK failed: {label} — {result['error']}", "error"
    target = result.get("target_desc") or "the found element"
    if not result.get("clickable"):
        why = []
        if not result.get("visible"):
            why.append("not visible (hidden/zero-size)")
        if result.get("disabled"):
            why.append("disabled or pointer-events:none")
        reason = ", ".join(why) or "not interactive"
        return f"❌ CLICK failed: {target} is NOT clickable — {reason}", "error"
    if result.get("clicked"):
        return f"✅ CLICK success: clicked {target} \"{str(result.get('text',''))[:40]}\"", "success"
    return f"⚠ CLICK not dispatched: {target} is clickable but no click was performed", "warn"


def interpret_click_target(result) -> tuple[str, str]:
    if not isinstance(result, dict):
        return "⚠ CLICK target unknown — no data returned", "warn"
    target = result.get("target_desc") or "the found element"
    if result.get("clickable"):
        msg = f"✅ CLICK target is clickable: {target}"
        if result.get("highlighted"):
            msg += " — 🟧 orange outline drawn"
        return msg, "success"
    return f"⚠ CLICK target {target} is not clickable", "warn"


# ---- C6 param objects for highlight wrappers ----

@dataclass
class HighlightJsSpec:
    selector: str
    color: str = "#FF0000"
    duration_ms: int = 2000
    caption: str = ""
    clear_first: bool = True


@dataclass
class HighlightRectSpec:
    x: float
    y: float
    w: float
    h: float
    color: str = "#FF0000"
    duration_ms: int = 2000
    caption: str = ""


@dataclass
class WatcherOverlaySpec:
    message: str = "wait for finish generation"
    kind: str = "generation"
    timeout_sec: int = 600
    sub: str = ""


def build_highlight_js_from_spec(spec: HighlightJsSpec) -> str:
    hs = HighlightSpec(color=spec.color, caption=spec.caption or spec.selector[:40],
                       highlight_ms=spec.duration_ms, clear_first=spec.clear_first)
    return ";" + build_highlight_probe(spec.selector, hs).lstrip()


def build_highlight_js(selector: str, color: str = "#FF0000", duration_ms: int = 2000, caption: str = "", clear_first: bool = True) -> str:
    spec = HighlightJsSpec(selector=selector, color=color, duration_ms=duration_ms, caption=caption, clear_first=clear_first)
    return build_highlight_js_from_spec(spec)


def build_clear_js() -> str:
    return build_clear_probe()


def build_highlight_rect_js_from_spec(spec: HighlightRectSpec) -> str:
    color_json = json.dumps(spec.color)
    caption_json = json.dumps(spec.caption or f"{int(spec.w)}x{int(spec.h)}")
    return f"""
;(function(){{
{_HELPERS_JS}
  try {{
    var r = {{left:{spec.x}, top:{spec.y}, width:{spec.w}, height:{spec.h}}};
    var fake = {{getBoundingClientRect:function(){{return r;}}}};
    var rect = highlight(fake, {color_json}, {spec.duration_ms}, {caption_json});
    return JSON.stringify({{found: !!rect, rect: r}});
  }} catch(e) {{ return JSON.stringify({{found:false}}); }}
}})()
"""


def build_highlight_rect_js(x: float, y: float, w: float, h: float, color: str = "#FF0000", duration_ms: int = 2000, caption: str = "") -> str:
    spec = HighlightRectSpec(x=x, y=y, w=w, h=h, color=color, duration_ms=duration_ms, caption=caption)
    return build_highlight_rect_js_from_spec(spec)


# ---- watcher overlay split into small helpers (C6) ----

def _watcher_style_js() -> str:
    return """
    if (!document.getElementById('arena-watcher-style-v2')) {
      var st = document.createElement('style');
      st.id = 'arena-watcher-style-v2';
      st.textContent = `
        @keyframes arenaWatcherPulse2 { 0%,100% { box-shadow:0 8px 24px rgba(0,0,0,0.6); opacity:0.97; } 50% { box-shadow:0 8px 32px rgba(0,0,0,0.75); opacity:1; } }
        @keyframes arenaWatcherSpin { 0% { transform:rotate(0deg); } 100% { transform:rotate(360deg); } }
        @keyframes arenaWatcherGlow { 0%,100% { opacity:0.8; } 50% { opacity:1; } }
      `;
      document.head.appendChild(st);
    }
"""


def _watcher_overlay_css(bg: str, border_color: str) -> str:
    return f"""
      'position:fixed','left:50%','top:12px','transform:translateX(-50%)','max-width:380px','min-width:220px',
      'background:'+{json.dumps(bg)},'border:2px solid '+{json.dumps(border_color)},'border-radius:10px',
      'box-shadow:0 8px 24px rgba(0,0,0,0.6)','z-index:2147483646','display:flex','flex-direction:column',
      'align-items:center','justify-content:center','padding:12px 16px',
      'font-family:system-ui, -apple-system, Segoe UI, sans-serif','color:#fff','pointer-events:auto',
      'cursor:grab','user-select:none','animation:arenaWatcherPulse2 1.5s ease-in-out infinite'
    """


def _watcher_drag_js() -> str:
    return """
    var drag=null;
    overlay.addEventListener('mousedown', function(e){ try{ var r=overlay.getBoundingClientRect(); drag={x:e.clientX-r.left,y:e.clientY-r.top}; overlay.style.cursor='grabbing'; e.preventDefault(); }catch(err){} });
    document.addEventListener('mousemove', function(e){ if(!drag||!overlay.isConnected){ drag=null; return; } try{ var nx=Math.max(0,Math.min(window.innerWidth-overlay.offsetWidth,e.clientX-drag.x)); var ny=Math.max(0,Math.min(window.innerHeight-overlay.offsetHeight,e.clientY-drag.y)); overlay.style.transform='none'; overlay.style.left=nx+'px'; overlay.style.top=ny+'px'; window.__arenaWatcherPos={left:nx,top:ny}; }catch(err){} });
    document.addEventListener('mouseup', function(){ drag=null; try{ overlay.style.cursor='grab'; }catch(err){} });
"""


def build_watcher_overlay_js_from_spec(spec: WatcherOverlaySpec) -> str:
    msg_json = json.dumps(spec.message or "wait")
    kind_json = json.dumps(spec.kind or "generation")
    timeout_json = json.dumps(int(spec.timeout_sec or 600))
    sub_json = json.dumps(spec.sub or "")
    return f"""
;(function(){{
  try {{
    var ATTR = "{WATCHER_ATTR}";
    var msg = {msg_json};
    var kind = {kind_json};
    var timeoutSec = {timeout_json};
    var subText = {sub_json};
    var startTime = Date.now();
    var olds = document.querySelectorAll('['+ATTR+']');
    for (var i=0;i<olds.length;i++) if (olds[i].parentNode) olds[i].parentNode.removeChild(olds[i]);
    var isCaptcha = (kind === 'captcha' || msg.toLowerCase().indexOf('captcha') >=0);
    var bg = isCaptcha ? 'rgba(180, 20, 20, 0.96)' : 'rgba(20, 80, 180, 0.96)';
    var borderColor = isCaptcha ? '#ff4444' : '#44aaff';
    var icon = isCaptcha ? '🛡️' : '⏳';
    var overlay = document.createElement('div');
    overlay.setAttribute(ATTR, kind);
    overlay.style.cssText = [{_watcher_overlay_css('rgba(20,80,180,0.96)', '#44aaff')}].join(';');
    overlay.style.background = bg; overlay.style.borderColor = borderColor;
    try {{ var sp=window.__arenaWatcherPos; if(sp && typeof sp.left==='number' && typeof sp.top==='number'){{ overlay.style.left=sp.left+'px'; overlay.style.top=sp.top+'px'; overlay.style.transform='none'; }} }}catch(e){{}}
    {_watcher_style_js()}
    var headRow=document.createElement('div'); headRow.style.cssText='display:flex; align-items:center; gap:8px;';
    var iconEl=document.createElement('div'); iconEl.textContent=icon; iconEl.style.cssText='font-size:26px; line-height:1;';
    var titleEl=document.createElement('div'); titleEl.textContent=msg.toUpperCase(); titleEl.style.cssText='font-size:14px; font-weight:800; line-height:1.25; letter-spacing:0.3px; text-shadow:0 1px 2px rgba(0,0,0,0.5);';
    headRow.appendChild(iconEl); headRow.appendChild(titleEl);
    var subEl=document.createElement('div'); subEl.textContent=isCaptcha ? 'Solve captcha manually — watcher is waiting (drag me)' : 'Generation in progress — watcher is waiting (drag me)'; subEl.style.cssText='font-size:11px; opacity:0.9; margin-top:6px; text-align:center; font-weight:500;';
    var spinnerWrap=document.createElement('div'); spinnerWrap.style.cssText='display:flex; align-items:center; gap:8px; margin-top:8px;';
    var spinner=document.createElement('div'); spinner.style.cssText='width:18px; height:18px; border:2px solid rgba(255,255,255,0.3); border-top-color:#fff; border-radius:50%; animation: arenaWatcherSpin 0.9s linear infinite;';
    var spinnerText=document.createElement('div'); spinnerText.textContent='Waiting...'; spinnerText.style.cssText='font-size:11px; font-weight:600; opacity:0.9; animation: arenaWatcherGlow 1.5s ease-in-out infinite;';
    spinnerWrap.appendChild(spinner); spinnerWrap.appendChild(spinnerText);
    var timeEl=document.createElement('div'); timeEl.id='arena-watcher-time'; timeEl.style.cssText='font-size:10px; opacity:0.85; margin-top:8px; font-family:monospace; background:rgba(0,0,0,0.25); padding:3px 8px; border-radius:6px;';
    var timeoutEl=document.createElement('div'); timeoutEl.id='arena-watcher-timeout'; timeoutEl.style.cssText='font-size:10px; opacity:0.75; margin-top:4px; font-family:monospace;';
    function updateTime(){{ var elapsed=Math.floor((Date.now()-startTime)/1000); var remaining=Math.max(0,timeoutSec-elapsed); var te=document.getElementById('arena-watcher-time'); var to=document.getElementById('arena-watcher-timeout'); if(te) te.textContent='\\u23f1 '+elapsed+'s elapsed — '+new Date().toLocaleTimeString(); if(to) to.textContent='Timeout: '+timeoutSec+'s (win setting) — '+remaining+'s left'; }}
    overlay.appendChild(headRow); overlay.appendChild(subEl);
    if (subText) {{ var reasonEl=document.createElement('div'); reasonEl.textContent=subText; reasonEl.style.cssText='font-size:11px; font-weight:700; color:#ffd28a; margin-top:5px; text-align:center;'; overlay.appendChild(reasonEl); }}
    overlay.appendChild(spinnerWrap); overlay.appendChild(timeEl); overlay.appendChild(timeoutEl);
    {_watcher_drag_js()}
    (document.body||document.documentElement).appendChild(overlay);
    updateTime();
    var interval=setInterval(function(){{ var te=document.getElementById('arena-watcher-time'); if(!te){{ clearInterval(interval); return; }} updateTime(); }}, 1000);
    try{{ overlay.setAttribute('data-interval', interval); }}catch(e){{}}
    return JSON.stringify({{shown:true,kind:kind,message:msg,timeout:timeoutSec}});
  }} catch(e){{ return JSON.stringify({{shown:false,error:String(e && e.message || e)}}); }}
}})()
"""


def build_watcher_overlay_js(message: str = "wait for finish generation", kind: str = "generation", timeout_sec: int = 600, sub: str = "") -> str:
    spec = WatcherOverlaySpec(message=message, kind=kind, timeout_sec=timeout_sec, sub=sub)
    return build_watcher_overlay_js_from_spec(spec)


def build_watcher_clear_js() -> str:
    return f"""
;(function(){{
  try {{
    var ATTR = "{WATCHER_ATTR}";
    var olds = document.querySelectorAll('['+ATTR+']');
    var count = olds.length;
    for (var i=0;i<olds.length;i++) if (olds[i].parentNode) olds[i].parentNode.removeChild(olds[i]);
    return JSON.stringify({{cleared: count}});
  }} catch(e){{ return JSON.stringify({{cleared:0,error:String(e && e.message || e)}}); }}
}})()
"""
