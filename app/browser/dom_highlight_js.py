"""DOM highlight JS payloads — C10 split from dom_highlight.py for RULE18 file 150-300.

This file owns only JS string literals and helpers to build them.
Python control flow around literals stays in dom_highlight.py with CC≤10.
# ideal-size: 180 lines reason=single JS payload for probe + watcher overlay CSS/JS literals per RULE16.1.5; splitting string literal would break in-page agent contract
"""

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
