"""DOM highlight JS builder — visual confirmation overlays (from Old App backend/dom_highlight.py, simplified for Arena)."""

import json

HIGHLIGHT_ATTR = "data-arena-highlight"

_HELPERS_JS = """
  function clearArenaHighlights() {
    try {
      var old = document.querySelectorAll('[__ATTR__]');
      for (var k = 0; k < old.length; k++) {
        if (old[k].parentNode) old[k].parentNode.removeChild(old[k]);
      }
    } catch(e) {}
  }
  function arenaHighlight(el, color, ms, caption) {
    try {
      if (!el || !el.getBoundingClientRect) return null;
      var r = el.getBoundingClientRect();
      if (!r || (!r.width && !r.height)) return null;
      var box = document.createElement('div');
      box.setAttribute('__ATTR__', '1');
      box.style.cssText = [
        'position:fixed',
        'left:' + Math.max(0, r.left) + 'px',
        'top:' + Math.max(0, r.top) + 'px',
        'width:' + Math.max(0, r.width) + 'px',
        'height:' + Math.max(0, r.height) + 'px',
        'outline:2px solid ' + color,
        'outline-offset:-1px',
        'background:rgba(255,0,0,0.08)',
        'pointer-events:none',
        'z-index:2147483647'
      ].join(';');
      if (caption) {
        var tag = document.createElement('div');
        tag.textContent = caption;
        tag.style.cssText = [
          'position:absolute', 'left:0', 'top:-18px',
          'font:700 11px/14px sans-serif', 'letter-spacing:.5px',
          'padding:2px 6px', 'color:#fff', 'white-space:nowrap',
          'background:' + color, 'border-radius:3px', 'pointer-events:none'
        ].join(';');
        box.appendChild(tag);
      }
      (document.body || document.documentElement).appendChild(box);
      var life = ms > 0 ? ms : 2000;
      setTimeout(function(){
        if (box.parentNode) box.parentNode.removeChild(box);
      }, life);
      return {x: r.left, y: r.top, width: r.width, height: r.height};
    } catch(e) { return null; }
  }
""".replace("__ATTR__", HIGHLIGHT_ATTR)

def build_highlight_js(selector: str, color: str = "#FF0000", duration_ms: int = 2000, caption: str = "", clear_first: bool = True) -> str:
    """Build JS that highlights selector and returns rect."""
    sel_json = json.dumps(selector)
    color_json = json.dumps(color)
    caption_json = json.dumps(caption or selector)
    clear_js = "clearArenaHighlights();" if clear_first else ""
    return f"""
(function(){{
{_HELPERS_JS}
  try {{
    {clear_js}
    var sel = {sel_json};
    var el = document.querySelector(sel);
    if (!el) return JSON.stringify({{found:false, error:'not found: '+sel}});
    var rect = arenaHighlight(el, {color_json}, {duration_ms}, {caption_json});
    return JSON.stringify({{found: !!rect, rect: rect, selector: sel}});
  }} catch(e) {{
    return JSON.stringify({{found:false, error:String(e)}});
  }}
}})()
"""

def build_clear_js() -> str:
    return f"""
(function(){{
  try {{
    var old = document.querySelectorAll('[{HIGHLIGHT_ATTR}]');
    var n = old.length;
    for(var i=0;i<old.length;i++){{ if(old[i].parentNode) old[i].parentNode.removeChild(old[i]); }}
    return JSON.stringify({{cleared:n}});
  }} catch(e){{ return JSON.stringify({{cleared:0}}); }}
}})()
"""

def build_highlight_rect_js(x: float, y: float, w: float, h: float, color: str = "#FF0000", duration_ms: int = 2000, caption: str = "") -> str:
    """Highlight arbitrary rect (for demo)."""
    return f"""
(function(){{
{_HELPERS_JS}
  try {{
    var r = {{left:{x}, top:{y}, width:{w}, height:{h}}};
    var fake = {{getBoundingClientRect:function(){{return r;}}}};
    var rect = arenaHighlight(fake, {json.dumps(color)}, {duration_ms}, {json.dumps(caption)});
    return JSON.stringify({{found: !!rect, rect: r}});
  }} catch(e) {{ return JSON.stringify({{found:false}}); }}
}})()
"""
