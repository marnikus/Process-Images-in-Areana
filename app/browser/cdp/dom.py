"""CDP DOM helpers: evaluate, queries, file input attach, highlight (W2 split)."""
from __future__ import annotations

import json
from typing import List, Optional

log = __import__("logging").getLogger("arena")

# JS overlay for highlight_element — data, not code (W2: template constant so
# the builder stays small; placeholders are unique tokens, replaced verbatim).
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
    tag.textContent = __CAP__;
    tag.style.cssText = [
      'position:absolute','left:0','top:-18px',
      'font:700 11px/14px sans-serif','padding:2px 6px',
      'color:#fff','background:__COLOR__','white-space:nowrap',
      'border-radius:3px'
    ].join(';');
    box.appendChild(tag);
    (document.body||document.documentElement).appendChild(box);
    setTimeout(function(){ if(box.parentNode) box.parentNode.removeChild(box); }, __MS__);
    return {found:true, rect:{x:r.left,y:r.top,width:r.width,height:r.height}};
  } catch(e) { return {found:false, error:String(e)}; }
})()
"""

DEFAULT_FILE_INPUT_SELECTORS = [
    'form input[type="file"][accept*="image"]',
    'input[type="file"][accept*="image"]',
    'input[type="file"]',
]


def highlight_js(selector: str, color: str, duration_ms: int, caption: str) -> str:
    """Build the highlight-overlay evaluate() expression."""
    return (_HIGHLIGHT_JS_TEMPLATE
            .replace("__SEL__", json.dumps(selector))
            .replace("__CAP__", json.dumps(caption or selector))
            .replace("__COLOR__", color)
            .replace("__MS__", str(duration_ms)))


class CdpDomMixin:
    """evaluate + DOM queries + file input attach + element highlight."""

    async def evaluate(self, expression: str, await_promise: bool = True):
        """Runtime.evaluate with exception handling -> value or None."""
        try:
            r = await self.send("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": await_promise})
            res = r.get("result", {})
            if res.get("exceptionDetails"):
                log.warning(f"evaluate exception: {res.get('exceptionDetails')}")
                return None
            return res.get("result", {}).get("value")
        except Exception as e:
            log.warning(f"evaluate failed: {e}")
            return None

    async def get_document(self) -> Optional[dict]:
        """DOM.getDocument root node."""
        try:
            r = await self.send("DOM.getDocument", {"depth": 0})
            return r.get("result", {}).get("root")
        except Exception as e:
            log.warning(f"DOM.getDocument failed: {e}")
            return None

    async def query_selector(self, node_id: int, selector: str) -> Optional[int]:
        """Return nodeId of element matching selector under node_id, or None."""
        try:
            r = await self.send("DOM.querySelector", {"nodeId": node_id, "selector": selector})
            return r.get("result", {}).get("nodeId") or None
        except Exception as e:
            log.debug(f"querySelector {selector} failed: {e}")
            return None

    async def query_selector_all(self, node_id: int, selector: str) -> List[int]:
        """All nodeIds matching selector under node_id."""
        try:
            r = await self.send("DOM.querySelectorAll", {"nodeId": node_id, "selector": selector})
            return r.get("result", {}).get("nodeIds") or []
        except Exception as e:
            log.debug(f"querySelectorAll {selector} failed: {e}")
            return []

    async def set_file_input_files(self, node_id: int, files: List[str]) -> bool:
        """Set files for <input type=file> via CDP DOM.setFileInputFiles."""
        try:
            # files must be absolute paths accessible to Chrome
            await self.send("DOM.setFileInputFiles", {"nodeId": node_id, "files": files})
            # Some Chrome versions return empty result on success — treat as ok
            return True
        except Exception as e:
            log.warning(f"setFileInputFiles failed for node {node_id} files {files}: {e}")
            return False

    async def attach_image_cdp(self, image_path: str, selectors: List[str] = None) -> tuple[bool, str]:
        """Attach image via CDP: find file input and set files."""
        if selectors is None:
            selectors = DEFAULT_FILE_INPUT_SELECTORS
        try:
            doc = await self.get_document()
            if not doc:
                return False, "Failed to get document root"
            root_id = doc.get("nodeId")
            if not root_id:
                return False, "No root nodeId"
            target_node_id, used_selector = await self._find_file_input(root_id, selectors)
            if not target_node_id:
                return False, f"File input not found for selectors {selectors}"
            return await self._set_attached_file(target_node_id, used_selector, image_path)
        except Exception as e:
            return False, f"Exception attach_image_cdp: {e}"

    async def _find_file_input(self, root_id: int, selectors: List[str]) -> tuple:
        """(nodeId, selector) of the first matching file input, else ('', '')."""
        for sel in selectors:
            nid = await self.query_selector(root_id, sel)
            if nid:
                return nid, sel
        return None, ""

    async def _set_attached_file(self, node_id: int, used_selector: str, image_path: str) -> tuple[bool, str]:
        """Resolve to an absolute path and push it into the file input."""
        from pathlib import Path
        abs_path = str(Path(image_path).resolve())
        ok = await self.set_file_input_files(node_id, [abs_path])
        if ok:
            return True, f"Attached {abs_path} via {used_selector} node {node_id}"
        return False, f"setFileInputFiles failed for {abs_path}"

    async def highlight_element(self, selector: str, color: str = "#FF0000",
                                duration_ms: int = 2000, caption: str = ""):
        """Draw a temporary outline overlay over the first selector match."""
        return await self.evaluate(highlight_js(selector, color, duration_ms, caption))
