"""CDP DOM helpers — extracted from cdp_client.py (C2).

RULE18: file 150-300, func ≤20, CC≤10, params≤4.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger("arena")


@dataclass
class HighlightSpec:
    """Param object for highlight (C6) — reduces param count."""
    color: str = "#FF0000"
    duration_ms: int = 2000
    caption: str = ""


async def get_document(transport) -> Optional[dict]:
    try:
        r = await transport.send("DOM.getDocument", {"depth": 0})
        return r.get("result", {}).get("root")
    except Exception as e:
        log.warning(f"DOM.getDocument failed: {e}")
        return None


async def query_selector(transport, node_id: int, selector: str) -> Optional[int]:
    try:
        r = await transport.send("DOM.querySelector", {"nodeId": node_id, "selector": selector})
        return r.get("result", {}).get("nodeId") or None
    except Exception as e:
        log.debug(f"querySelector {selector} failed: {e}")
        return None


async def query_selector_all(transport, node_id: int, selector: str) -> List[int]:
    try:
        r = await transport.send("DOM.querySelectorAll", {"nodeId": node_id, "selector": selector})
        return r.get("result", {}).get("nodeIds") or []
    except Exception as e:
        log.debug(f"querySelectorAll {selector} failed: {e}")
        return []


async def set_file_input_files(transport, node_id: int, files: List[str]) -> bool:
    try:
        r = await transport.send("DOM.setFileInputFiles", {"nodeId": node_id, "files": files})
        if r.get("result") is not None:
            return True
        return True
    except Exception as e:
        log.warning(f"setFileInputFiles failed node {node_id} files {files}: {e}")
        return False


async def _find_file_input(transport, root_id: int, selectors: List[str]) -> Tuple[Optional[int], str]:
    for sel in selectors:
        nid = await query_selector(transport, root_id, sel)
        if nid:
            return nid, sel
    return None, ""


async def _resolve_image_path(image_path: str) -> str:
    return str(Path(image_path).resolve())


async def attach_image_cdp(transport, image_path: str, selectors: List[str] = None) -> Tuple[bool, str]:
    if selectors is None:
        selectors = [
            'form input[type="file"][accept*="image"]',
            'input[type="file"][accept*="image"]',
            'input[type="file"]',
        ]
    try:
        doc = await get_document(transport)
        if not doc:
            return False, "Failed to get document root"
        root_id = doc.get("nodeId")
        if not root_id:
            return False, "No root nodeId"
        node_id, used_sel = await _find_file_input(transport, root_id, selectors)
        if not node_id:
            return False, f"File input not found for selectors {selectors}"
        abs_path = await _resolve_image_path(image_path)
        ok = await set_file_input_files(transport, node_id, [abs_path])
        if ok:
            return True, f"Attached {abs_path} via {used_sel} node {node_id}"
        return False, f"setFileInputFiles failed for {abs_path}"
    except Exception as e:
        return False, f"Exception attach_image_cdp: {e}"


_HIGHLIGHT_JS_TEMPLATE = """
(function(){
  try {
    var sel = __SEL__;
    var el = document.querySelector(sel);
    if (!el) return {found:false};
    var r = el.getBoundingClientRect();
    if (!r || (!r.width && !r.height)) return {found:false};
    var box = document.createElement('div');
    box.setAttribute('data-arena-highlight','1');
    box.style.cssText = [
      'position:fixed',
      'left:'+Math.max(0,r.left)+'px',
      'top:'+Math.max(0,r.top)+'px',
      'width:'+Math.max(0,r.width)+'px',
      'height:'+Math.max(0,r.height)+'px',
      'outline:2px solid __COLOR__',
      'outline-offset:-1px',
      'background:rgba(255,0,0,0.08)',
      'pointer-events:none',
      'z-index:2147483647'
    ].join(';');
    var tag = document.createElement('div');
    tag.textContent = __CAPTION__;
    tag.style.cssText = [
      'position:absolute','left:0','top:-18px',
      'font:700 11px/14px sans-serif','padding:2px 6px',
      'color:#fff','background:__COLOR__','white-space:nowrap',
      'border-radius:3px'
    ].join(';');
    box.appendChild(tag);
    (document.body||document.documentElement).appendChild(box);
    setTimeout(function(){ if(box.parentNode) box.parentNode.removeChild(box); }, __DUR__);
    return {found:true, rect:{x:r.left,y:r.top,width:r.width,height:r.height}};
  } catch(e) { return {found:false, error:String(e)}; }
})()
"""


def _build_highlight_js(selector: str, spec: HighlightSpec) -> str:
    caption = spec.caption or selector
    js = _HIGHLIGHT_JS_TEMPLATE
    js = js.replace("__SEL__", json.dumps(selector))
    js = js.replace("__COLOR__", spec.color)
    js = js.replace("__CAPTION__", json.dumps(caption))
    js = js.replace("__DUR__", str(spec.duration_ms))
    return js


async def highlight_element(transport, selector: str, spec: HighlightSpec = None):
    """Highlight with spec param object — 3 params (C6)."""
    if spec is None:
        spec = HighlightSpec()
    js = _build_highlight_js(selector, spec)
    return await transport.evaluate(js)


async def highlight_element_legacy(transport, selector: str, color: str = "#FF0000",
                                   duration_ms: int = 2000, caption: str = ""):
    """Backward compat wrapper — old signature."""
    spec = HighlightSpec(color=color, duration_ms=duration_ms, caption=caption)
    return await highlight_element(transport, selector, spec)


async def clear_highlights(transport):
    js = """
(function(){
  try {
    var old = document.querySelectorAll('[data-arena-highlight]');
    var n = old.length;
    for(var i=0;i<old.length;i++){ if(old[i].parentNode) old[i].parentNode.removeChild(old[i]); }
    return {cleared:n};
  } catch(e){ return {cleared:0}; }
})()
"""
    return await transport.evaluate(js)
