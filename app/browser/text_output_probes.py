# ideal-size: 475 lines reason=single JS payload for text output probes; splitting string literal would break in-page contract per RULE 16.1.5
"""Text output probes — detect new assistant text for description generation.

Similar to output_probes.py but for text output instead of images.
Used by GENERATE_IMAGE_DESCRIPTION workflow: image + prompt -> text description saved as JSON.

RULE 21: selectors come from probe_selectors (single source = site_adapter).
"""

import json

from .probe_selectors import (
    assistant_message_selectors,
    assistant_text_selectors,
    generating_spinners_js,
    model_label_probe,
    user_message_selector,
)

SELECTORS_TEXT = assistant_text_selectors()
SELECTORS_ASSISTANT = assistant_message_selectors()
_GEN_SPINNERS = generating_spinners_js()
_MODEL_LABEL = model_label_probe()

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
""".replace("__SELECTORS__", json.dumps(SELECTORS_TEXT)).replace(
    "__GEN_SPINNERS__", _GEN_SPINNERS
)

JS_CHECK_NEW_TEXT = """
((oldTexts, correlationId, oldOutputs) => {
  try {
    let spinning = false;
    let spinCount = 0;
    let spinDetails = [];
    try {
      for (const s of (__GEN_SPINNERS__)()) {
        spinning = true;
        spinCount++;
        const trunc = s.closest(__MODEL_ROW_SCOPE__).querySelector(__MODEL_LABEL__);
        spinDetails.push({label: (trunc && trunc.textContent.trim()) || 'unknown', visible: true});
      }
    } catch(e) {}

    let layoutReverse = false;
    try {
      layoutReverse = !!document.querySelector('ol.flex-col-reverse');
      if (!layoutReverse) {
        const ol = document.querySelector('ol');
        if (ol) {
          const style = window.getComputedStyle(ol);
          if (style.flexDirection === 'column-reverse') layoutReverse = true;
        }
      }
    } catch(e) {}

    let allJobs = [];
    const jobRecord = (jobId, el, container, rect, text, isUserBubble) => ({
      jobId: jobId,
      el: el,
      container: container,
      top: rect.top,
      left: rect.left,
      width: rect.width,
      height: rect.height,
      text: text.slice(0,200),
      isUserBubble: isUserBubble
    });
    try {
      const jobRegex = /\\[JOB-ID:\\s*([^\\]\\s]+)\\]/g;
      const allEls = document.querySelectorAll('div, span, p, pre');
      let seenContainers = new Set();
      for (const el of allEls) {
        if (!el.textContent) continue;
        if (el.tagName === 'TEXTAREA' || el.tagName === 'SCRIPT' || el.tagName === 'STYLE') continue;
        const txt = el.textContent;
        if (txt.length > 2000) continue;
        let match;
        jobRegex.lastIndex = 0;
        while ((match = jobRegex.exec(txt)) !== null) {
          const jobId = match[1];
          if (!jobId || jobId.length < 3) continue;
          let container = null;
          let cur = el;
          for (let i=0; i<12 && cur; i++) {
            try {
              if (!cur.getBoundingClientRect) { cur = cur.parentElement; continue; }
              const r = cur.getBoundingClientRect();
              if (r.height < 20 || r.height > window.innerHeight * 0.95) { cur = cur.parentElement; continue; }
              if (r.width > window.innerWidth * 0.98) { cur = cur.parentElement; continue; }
              const hasJob = cur.textContent && cur.textContent.includes(jobId);
              const hasFlex = cur.classList && (cur.classList.contains('flex') || cur.classList.contains('group'));
              const isNoScrollbar = cur.classList && cur.classList.contains('no-scrollbar');
              if (hasJob && hasFlex && !isNoScrollbar) {
                container = cur;
                break;
              }
              if (isNoScrollbar) break;
            } catch(e) {}
            cur = cur.parentElement;
          }
          if (!container) {
            container = el.closest('div.flex.min-w-0.flex-1.flex-col.items-end, div.group, div.flex.flex-col, div[data-message-id]') || el.closest('div') || el;
          }
          let key = jobId + '|' + (container ? (container.getBoundingClientRect().top + '|' + container.getBoundingClientRect().left) : el.getBoundingClientRect().top);
          if (seenContainers.has(key)) continue;
          seenContainers.add(key);
          try {
            const rect = container.getBoundingClientRect();
            allJobs.push(jobRecord(jobId, el, container, rect, txt, (container.className||'').includes('items-end')));
          } catch(e) {}
        }
      }
      let deduped = [];
      let seenIds = new Set();
      for (const j of allJobs) {
        if (!seenIds.has(j.jobId)) {
          seenIds.add(j.jobId);
          deduped.push(j);
        }
      }
      allJobs = deduped;
      allJobs.sort((a,b)=>{
        try {
          if (a.el === b.el) return 0;
          const pos = a.el.compareDocumentPosition(b.el);
          if (pos & Node.DOCUMENT_POSITION_FOLLOWING) return -1;
          if (pos & Node.DOCUMENT_POSITION_PRECEDING) return 1;
        } catch(e) {}
        if (Math.abs(a.top - b.top) > 5) return a.top - b.top;
        return a.left - b.left;
      });
    } catch(e) {}

    let jobEl = null;
    let jobContainer = null;
    let jobTop = null;
    let jobFound = false;
    let jobIndex = -1;
    let prevJobTop = null;
    let nextJobTop = null;

    if (correlationId) {
      try {
        for (let i=0; i<allJobs.length; i++) {
          const j = allJobs[i];
          if (j.jobId === correlationId || j.text.includes(correlationId)) {
            jobEl = j.el;
            jobContainer = j.container;
            jobTop = j.top;
            jobFound = true;
            jobIndex = i;
            if (i > 0) prevJobTop = allJobs[i-1].top;
            if (i < allJobs.length - 1) nextJobTop = allJobs[i+1].top;
            break;
          }
        }
        if (!jobFound) {
          const allEls = document.querySelectorAll('div, span, p, pre');
          for (const el of allEls) {
            if (!el.textContent) continue;
            if (el.textContent.includes(correlationId)) {
              jobEl = el;
              jobContainer = el.closest('div.flex.min-w-0.flex-1.flex-col.items-end, div.group, div.flex.flex-col') || el.closest('div') || el;
              try { jobTop = jobContainer.getBoundingClientRect().top; } catch(e) {}
              jobFound = true;
              break;
            }
          }
        }
      } catch(e) {}
    }

    const selectors = __SELECTORS__;
    let allNew = [];
    let validBelow = [];
    let validAbove = [];
    let belowCandidates = [];
    let debugAll = [];

    function inUserMessage(el) {
      try { return !!el.closest(__USER_MESSAGE__); } catch(e) { return false; }
    }

    function isBeforeInDOM(a, b) {
      try {
        if (!a || !b) return false;
        if (a === b) return false;
        const pos = a.compareDocumentPosition(b);
        return !!(pos & Node.DOCUMENT_POSITION_FOLLOWING);
      } catch(e) { return false; }
    }

    function findAssociatedJobForText(textEl, rect, expectedId) {
      try {
        let domPrev = null;
        let domNext = null;
        let visualPrev = null;
        let visualNext = null;
        for (const j of allJobs) {
          try {
            if (isBeforeInDOM(j.el, textEl)) {
              domPrev = j;
            } else if (isBeforeInDOM(textEl, j.el)) {
              if (!domNext) domNext = j;
            }
          } catch(e) {}
          try {
            if (j.top < rect.top - 5) {
              if (!visualPrev || j.top > visualPrev.top) visualPrev = j;
            } else if (j.top > rect.top + 5) {
              if (!visualNext || j.top < visualNext.top) visualNext = j;
            }
          } catch(e) {}
        }
        const assocShape = (j) => ({
          associatedJobId: j ? j.jobId : null,
          domPrevJobId: domPrev ? domPrev.jobId : null,
          domNextJobId: domNext ? domNext.jobId : null,
          visualPrevJobId: visualPrev ? visualPrev.jobId : null,
          visualNextJobId: visualNext ? visualNext.jobId : null
        });
        if (expectedId) {
          const matched = (c) => Object.assign(assocShape(c), {matchedExpected: true});
          const nearbyChecks = [domPrev, domNext, visualPrev, visualNext];
          for (const c of nearbyChecks) {
            if (c && c.jobId === expectedId) return matched(c);
          }
        }
        let associated = null;
        if (layoutReverse) {
          if (domNext && domNext.top < rect.top - 5) associated = domNext;
          else if (visualPrev) associated = visualPrev;
          else associated = domPrev || domNext;
        } else {
          associated = domPrev || visualPrev || domNext;
        }
        return assocShape(associated);
      } catch(e) {
        return {associatedJobId: null, error: String(e)};
      }
    }

    try {
      const allAssistant = document.querySelectorAll(__SELECTORS__.join(','));
      for (const el of allAssistant) {
        if (!el.textContent) continue;
        const txt = el.textContent.trim();
        if (txt.length < 10) continue;
        if (txt.length > 10000) continue;
        const rect = el.getBoundingClientRect();
        debugAll.push({
          text: txt.slice(0,80),
          len: txt.length,
          top: Math.round(rect.top),
          visible: el.offsetParent !== null,
          inUser: inUserMessage(el)
        });
      }
    } catch(e) {}

    for (const sel of selectors) {
      try {
        const els = document.querySelectorAll(sel);
        for (const el of els) {
          if (!el.textContent) continue;
          const fullText = el.textContent.trim();
          if (fullText.length < 20) continue;
          if (fullText.length > 20000) continue;
          if (inUserMessage(el)) continue;

          const oldMatch = (oldTexts||[]).some(t => fullText.includes(t) || t.includes(fullText.slice(0,100)));
          if (oldMatch) continue;

          const rect = el.getBoundingClientRect();
          const visible = el.offsetParent !== null;
          if (!visible) continue;

          const assoc = findAssociatedJobForText(el, rect, correlationId);

          if (correlationId && assoc.associatedJobId && assoc.associatedJobId !== correlationId) {
            const nearby = [assoc.associatedJobId, assoc.domPrevJobId, assoc.domNextJobId, assoc.visualPrevJobId].filter(Boolean);
            if (!nearby.includes(correlationId)) continue;
          }

          const info = {
            el: el,
            text: fullText,
            rect: {x: rect.left, y: rect.top, width: rect.width, height: rect.height},
            top: rect.top,
            left: rect.left,
            visible: visible,
            selector: sel,
            associatedJobId: assoc.associatedJobId,
            domPrevJobId: assoc.domPrevJobId,
            visualPrevJobId: assoc.visualPrevJobId
          };
          allNew.push(info);

          if (jobFound && jobEl) {
            const aboveVisual = rect.top < jobTop - 5;
            const belowVisual = rect.top > jobTop + 5;
            if (belowVisual) validBelow.push(info);
            else if (aboveVisual) validAbove.push(info);
            else belowCandidates.push(info);
          } else {
            validBelow.push(info);
          }
        }
      } catch(e) {}
    }

    try {
      let seen = new Set();
      let dedup = [];
      for (const n of allNew) {
        const key = n.text.slice(0,100);
        if (!seen.has(key)) { seen.add(key); dedup.push(n); }
      }
      allNew = dedup;
    } catch(e) {}

    let pool = [];
    if (validBelow.length > 0) {
      validBelow.sort((a,b)=> a.top - b.top);
      pool = validBelow;
    } else if (belowCandidates.length > 0) {
      belowCandidates.sort((a,b) => a.top - b.top);
      pool = belowCandidates;
    } else if (validAbove.length > 0) {
      validAbove.sort((a,b)=> b.top - a.top);
      pool = validAbove;
    }

    if (correlationId) {
      const matchingPool = pool.filter(c => {
        if (!c.associatedJobId) return true;
        if (c.associatedJobId === correlationId) return true;
        const nearby = [c.domPrevJobId, c.visualPrevJobId].filter(Boolean);
        return nearby.includes(correlationId);
      });
      if (matchingPool.length === 0 && pool.length > 0) {
        return {
          ready: false,
          reason: 'job_id_mismatch_no_matching_text',
          spinning: spinning,
          spinCount: spinCount,
          spinDetails: spinDetails,
          jobFound: jobFound,
          jobTop: jobTop,
          jobId: correlationId,
          expectedJobId: correlationId,
          allNew: allNew.length,
          validBelow: validBelow.length,
          debugAll: debugAll.slice(0,5)
        };
      }
      pool = matchingPool;
    }

    let cand = pool[0];
    if (cand) {
      if (spinning) {
        return {
          ready: false,
          reason: 'generating_spinner_visible',
          text: cand.text.slice(0,200),
          spinning: true,
          spinCount: spinCount,
          spinDetails: spinDetails,
          jobFound: jobFound,
          jobTop: jobTop,
          jobId: correlationId,
          associatedJobId: cand.associatedJobId,
          expectedJobId: correlationId
        };
      }
      return {
        ready: true,
        text: cand.text,
        full_text: cand.text,
        spinning: false,
        rect: cand.rect,
        selector: cand.selector,
        jobFound: jobFound,
        jobTop: jobTop,
        jobIndex: jobIndex,
        allNew: allNew.length,
        validBelow: validBelow.length,
        associatedJobId: cand.associatedJobId,
        expectedJobId: correlationId,
        orderCheck: `Verified below prompt: jobTop ${jobTop} text top ${cand.top} associated ${cand.associatedJobId} == expected ${correlationId}`
      };
    }

    if (spinning) {
      return {
        ready: false,
        reason: 'generating_no_new_yet',
        spinning: true,
        spinCount: spinCount,
        spinDetails: spinDetails,
        jobFound: jobFound,
        jobTop: jobTop,
        jobId: correlationId,
        expectedJobId: correlationId
      };
    }

    return {
      ready: false,
      reason: 'no_new_text',
      spinning: false,
      spinCount: 0,
      jobFound: jobFound,
      jobTop: jobTop,
      jobId: correlationId,
      expectedJobId: correlationId,
      allNew: allNew.length,
      validBelow: validBelow.length,
      debugAll: debugAll.slice(0,5)
    };
  } catch(e) { return {ready:false, reason:String(e), spinning: false}; }
})
""".replace("__SELECTORS__", json.dumps(SELECTORS_TEXT)).replace(
    "__GEN_SPINNERS__", _GEN_SPINNERS
).replace(
    "__MODEL_ROW_SCOPE__", json.dumps(_MODEL_LABEL["scope"])
).replace(
    "__MODEL_LABEL__", json.dumps(_MODEL_LABEL["label"])
).replace(
    "__USER_MESSAGE__", json.dumps(user_message_selector())
)


def build_baseline_text_js() -> str:
    return f";({JS_BASELINE_TEXT})()"


def build_check_text_js(old_texts, correlation_id, old_outputs) -> str:
    return f";({JS_CHECK_NEW_TEXT})({json.dumps(old_texts)}, {json.dumps(correlation_id) if correlation_id else 'null'}, {json.dumps(old_outputs)})"
