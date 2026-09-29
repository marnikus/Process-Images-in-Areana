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
    owner_key: str = "legacy"


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


# quality-override: loc=50 reason=embedded JavaScript lease renderer is one atomic page payload
# ideal-size: 50 lines reason=one generated browser payload; JS string splitting breaks atomic overlay owner updates
def build_watcher_overlay_js_from_spec(spec: WatcherOverlaySpec) -> str:
    owner_json = json.dumps(str(spec.owner_key or "legacy"))
    msg_json = json.dumps(spec.message or "wait")
    kind_json = json.dumps(spec.kind or "generation")
    timeout_json = json.dumps(int(spec.timeout_sec or 600))
    sub_json = json.dumps(spec.sub or "")
    return f"""
;(function(){{
  try {{
    var ATTR = "{WATCHER_ATTR}", key = {owner_json};
    var state = window.__arenaWatcherOverlayState || {{leases:Object.create(null), interval:0, drag:null, pos:window.__arenaWatcherPos || null}}; window.__arenaWatcherOverlayState = state;
    var prior = state.leases[key];
    state.leases[key] = {{message:{msg_json},kind:{kind_json},timeout:{timeout_json},sub:{sub_json},started:prior ? prior.started : Date.now(),updated:Date.now()}};
    function removeVisible() {{
      var old = document.querySelectorAll('['+ATTR+']');
      for (var i=0;i<old.length;i++) if (old[i].parentNode) old[i].parentNode.removeChild(old[i]);
    }}
    function render() {{
      removeVisible();
      var keys = Object.keys(state.leases).sort(function(a,b) {{ return state.leases[b].updated-state.leases[a].updated; }});
      if (!keys.length) {{ if(state.interval) clearInterval(state.interval); state.interval=0; return; }}
      var activeKey = keys[0], item = state.leases[activeKey];
      var isCaptcha = item.kind === 'captcha' || item.message.toLowerCase().indexOf('captcha') >= 0;
      var overlay = document.createElement('div');
      overlay.setAttribute(ATTR, item.kind); overlay.setAttribute('data-overlay-owner', activeKey);
      overlay.style.cssText = [{_watcher_overlay_css('rgba(20,80,180,0.96)', '#44aaff')}].join(';');
      overlay.style.background = isCaptcha ? 'rgba(180,20,20,0.96)' : 'rgba(20,80,180,0.96)';
      overlay.style.borderColor = isCaptcha ? '#ff4444' : '#44aaff';
      if(state.pos) {{ overlay.style.left=state.pos.left+'px'; overlay.style.top=state.pos.top+'px'; overlay.style.transform='none'; }}
      {_watcher_style_js()}
      var head=document.createElement('div'); head.style.cssText='display:flex;align-items:center;gap:8px;';
      var icon=document.createElement('div'); icon.textContent=isCaptcha?'🛡️':'⏳'; icon.style.cssText='font-size:26px;line-height:1;';
      var title=document.createElement('div'); title.textContent=item.message.toUpperCase(); title.style.cssText='font-size:14px;font-weight:800;line-height:1.25;letter-spacing:.3px;text-shadow:0 1px 2px rgba(0,0,0,.5);';
      head.appendChild(icon); head.appendChild(title);
      var sub=document.createElement('div'); sub.textContent=item.sub || (isCaptcha?'Solve captcha manually — watcher is waiting (drag me)':'Generation in progress — watcher is waiting (drag me)'); sub.style.cssText='font-size:11px;opacity:.9;margin-top:6px;text-align:center;font-weight:500;';
      var time=document.createElement('div'); time.id='arena-watcher-time'; time.style.cssText='font-size:10px;opacity:.85;margin-top:8px;font-family:monospace;background:rgba(0,0,0,.25);padding:3px 8px;border-radius:6px;';
      var limit=document.createElement('div'); limit.id='arena-watcher-timeout'; limit.style.cssText='font-size:10px;opacity:.75;margin-top:4px;font-family:monospace;';
      overlay.appendChild(head); overlay.appendChild(sub); overlay.appendChild(time); overlay.appendChild(limit);
      if(item.sub){{var reason=document.createElement('div');reason.textContent=item.sub;reason.style.cssText='font-size:11px;font-weight:700;color:#ffd28a;margin-top:5px;text-align:center;';overlay.insertBefore(reason,time);}}
      overlay.addEventListener('mousedown',function(e){{try{{var r=overlay.getBoundingClientRect();state.drag={{x:e.clientX-r.left,y:e.clientY-r.top}};overlay.style.cursor='grabbing';e.preventDefault();}}catch(err){{}}}});
      (document.body||document.documentElement).appendChild(overlay);
      function update(){{var elapsed=Math.floor((Date.now()-item.started)/1000),remaining=Math.max(0,item.timeout-elapsed);var t=document.getElementById('arena-watcher-time'),l=document.getElementById('arena-watcher-timeout');if(t)t.textContent='⏱ '+elapsed+'s elapsed — '+new Date().toLocaleTimeString();if(l)l.textContent='Timeout: '+item.timeout+'s — '+remaining+'s left';}}
      update(); if(state.interval)clearInterval(state.interval); state.interval=setInterval(update,1000);
      if(!state.dragBound){{state.dragBound=true;document.addEventListener('mousemove',function(e){{if(!state.drag)return;var el=document.querySelector('['+ATTR+']');if(!el)return;var x=Math.max(0,Math.min(window.innerWidth-el.offsetWidth,e.clientX-state.drag.x)),y=Math.max(0,Math.min(window.innerHeight-el.offsetHeight,e.clientY-state.drag.y));state.pos={{left:x,top:y}};window.__arenaWatcherPos=state.pos;el.style.transform='none';el.style.left=x+'px';el.style.top=y+'px';}});document.addEventListener('mouseup',function(){{state.drag=null;var el=document.querySelector('['+ATTR+']');if(el)el.style.cursor='grab';}});}}
    }}
    state.leases[key].refresh=render; render();
    return JSON.stringify({{shown:true,kind:{kind_json},message:{msg_json},owner:key,timeout:{timeout_json}}});
  }} catch(e){{ return JSON.stringify({{shown:false,error:String(e && e.message || e)}}); }}
}})()
"""


def build_watcher_overlay_js(message: str = "wait for finish generation", kind: str = "generation", timeout_sec: int = 600, sub: str = "") -> str:
    spec = WatcherOverlaySpec(message=message, kind=kind, timeout_sec=timeout_sec, sub=sub)
    return build_watcher_overlay_js_from_spec(spec)


def build_watcher_clear_js(owner_key: str = "") -> str:
    owner_json = json.dumps(str(owner_key or ""))
    return f"""
;(function(){{
  try {{
    var ATTR = "{WATCHER_ATTR}", key = {owner_json};
    var state = window.__arenaWatcherOverlayState, cleared = 0;
    if (!state) return JSON.stringify({{cleared:0}});
    if (key) {{ if (Object.prototype.hasOwnProperty.call(state.leases,key)) {{ delete state.leases[key]; cleared=1; }} }}
    else {{ cleared=Object.keys(state.leases).length; state.leases=Object.create(null); }}
    var old=document.querySelectorAll('['+ATTR+']');
    for(var i=0;i<old.length;i++) if(old[i].parentNode) old[i].parentNode.removeChild(old[i]);
    var keys=Object.keys(state.leases).sort(function(a,b){{return state.leases[b].updated-state.leases[a].updated;}});
    if(!keys.length) {{ if(state.interval)clearInterval(state.interval);state.interval=0; }}
    else {{ var next=state.leases[keys[0]]; if(next.refresh) next.refresh(); }}
    return JSON.stringify({{cleared:cleared,remaining:Object.keys(state.leases).length}});
  }} catch(e){{ return JSON.stringify({{cleared:0,error:String(e && e.message || e)}}); }}
}})()
"""
