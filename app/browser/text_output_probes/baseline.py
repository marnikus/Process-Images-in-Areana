# ideal-size: 200 lines reason=single JS payload for baseline text probe; splitting string literal would break in-page contract
from __future__ import annotations
import json
from .shared import SELECTORS_TEXT, _GEN_SPINNERS, _MODEL_LABEL

JS_BASELINE_TEXT = """
(() => {
  try {
    const selectors = __SELECTORS__;
    const outputs = [];
    for (const sel of selectors) {
      try {
        const els = document.querySelectorAll(sel);
        for (const el of els) {
          if (!el.textContent) continue;
          const txt = el.textContent.trim();
          if (txt.length < 10) continue;
          if (txt.length > 5000) continue;
          const rect = el.getBoundingClientRect();
          outputs.push({
            text: txt.slice(0,500),
            full_len: txt.length,
            top: rect.top,
            visible: el.offsetParent !== null,
            selector: sel
          });
        }
      } catch(e) {}
    }
    let spinning = false;
    try { spinning = (__GEN_SPINNERS__)().length > 0; } catch(e) {}
    return {
      text_count: outputs.length,
      text_outputs: outputs,
      spinning: spinning,
      timestamp: Date.now()
    };
  } catch(e) {
    return {text_count:0, text_outputs:[], error:String(e), timestamp:Date.now(), spinning:false};
  }
})
""".replace("__SELECTORS__", json.dumps(SELECTORS_TEXT)).replace("__GEN_SPINNERS__", _GEN_SPINNERS)

def build_baseline_text_js() -> str:
    return JS_BASELINE_TEXT
