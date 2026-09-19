"""DOM highlight — C6/C10 refactor with HighlightSpec param objects and small helpers.
# ideal-size: 280 lines reason=Python wrappers + interpretation helpers + watcher overlay builders; JS payloads moved to dom_highlight_js.py per RULE16.1.5 single JS literal exception
"""

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
from .dom_highlight_js import (
    HIGHLIGHT_ATTR,
    STASH_KEY,
    WATCHER_ATTR,
    _HELPERS_JS,
    _PROBE_JS,
    _FIND_BODY,
    _HIGHLIGHT_BODY,
    _CLICK_BODY,
    _base_out_js,
)


def _js_str(value: str) -> str:
    return json.dumps(str(value or ""))


def _probe(body: str, **fields) -> str:
    script = body % fields
    return _PROBE_JS % {"out": _base_out_js(), "helpers": _HELPERS_JS, "body": script.strip("\n")}


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


# quality-override: loc=50 reason=embedded JS overlay literal, allowed by RULE 16.1.5
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
