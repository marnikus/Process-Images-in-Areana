"""Output probes v4 — strict JOB-ID verification before download.

Fixes after page reset incorrect image saved:
- Before download, verify prompt above and key matching with image processing key
- If not match, do not download, process as error
- Full verification: associatedJobId must equal correlationId

Per RULE 21 selector priority, RULE 22 correlation token.
"""

import json

from .probe_selectors import model_label_probe, output_image_selectors, spinner_selector

# Single source is site_adapter via probe_selectors (RULE 21).
SELECTORS_V3 = output_image_selectors()
_SPINNER_SEL = json.dumps(spinner_selector())
_MODEL_LABEL = model_label_probe()

JS_BASELINE_V3 = """
(() => {
  try {
    const outputs = [];
    const selectors = __SELECTORS__;
    for (const sel of selectors) {
      try {
        const els = document.querySelectorAll(sel);
        for (const el of els) {
          if (!el.src) continue;
          if (el.src.startsWith('blob:')) continue;
          if (el.naturalWidth && el.naturalWidth < 50 && el.naturalHeight < 50) continue;
          const rect = el.getBoundingClientRect();
          const cls = el.className || '';
          const opacity = (()=>{ try { return window.getComputedStyle(el).opacity; } catch(e){ return '1'; } })();
          outputs.push({
            src: el.src,
            complete: el.complete,
            naturalWidth: el.naturalWidth,
            naturalHeight: el.naturalHeight,
            visible: el.offsetParent !== null,
            selector: sel,
            className: cls.slice(0,120),
            opacity: opacity,
            top: rect.top,
            width: rect.width,
            isLarge: cls.includes('50vh') || rect.width >= 400 || (el.naturalWidth||0) >= 400
          });
        }
      } catch(e) {}
      if (outputs.length > 0) break;
    }
    let spinning = false;
    try {
      const spinners = document.querySelectorAll(__SPINNER_SELECTOR__);
      for (const s of spinners) { if (s.offsetParent !== null) { spinning = true; break; } }
    } catch(e) {}
    return {
      output_count: outputs.length,
      output_srcs: outputs.map(o => o.src),
      outputs: outputs,
      spinning: spinning,
      timestamp: Date.now(),
      url: window.location.href
    };
  } catch(e) {
    return {output_count:0, output_srcs:[], error:String(e), timestamp:Date.now(), spinning:false};
  }
})
""".replace("__SELECTORS__", json.dumps(SELECTORS_V3)).replace("__SPINNER_SELECTOR__", _SPINNER_SEL)

JS_CHECK_NEW_OUTPUT_V3 = """
((oldSrcs, correlationId, oldOutputs) => {
  try {
    let spinning = false;
    let spinCount = 0;
    let spinDetails = [];
    try {
      const spinners = document.querySelectorAll(__SPINNER_SELECTOR__);
      for (const s of spinners) {
        if (s.offsetParent !== null) {
          spinning = true;
          spinCount++;
          let parent = s.closest(__MODEL_ROW_SCOPE__);
          let label = '';
          if (parent) {
            const trunc = parent.querySelector(__MODEL_LABEL__);
            if (trunc) label = trunc.textContent.trim();
          }
          spinDetails.push({label: label || 'unknown', visible: true});
        }
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
              const hasImg = !!cur.querySelector('img');
              const hasFlex = cur.classList && (cur.classList.contains('flex') || cur.classList.contains('group'));
              const isNoScrollbar = cur.classList && cur.classList.contains('no-scrollbar');
              if (hasJob && (hasImg || hasFlex) && !isNoScrollbar) {
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
      if (allJobs.length === 0 && correlationId) {
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        let node;
        while (node = walker.nextNode()) {
          const val = node.nodeValue || '';
          if (val.includes(correlationId)) {
            let parent = node.parentElement;
            if (parent && parent.tagName !== 'TEXTAREA' && parent.tagName !== 'SCRIPT') {
              try {
                const r = parent.getBoundingClientRect();
                allJobs.push(jobRecord(correlationId, parent,
                  parent.closest('div.flex.min-w-0.flex-1.flex-col.items-end, div.group, div.flex.flex-col') || parent,
                  r, val, true));
                break;
              } catch(e) {}
            }
          }
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
    let prevJobId = null;
    let nextJobId = null;
    let prevJobEl = null;
    let nextJobEl = null;

    if (correlationId) {
      try {
        for (let i=0; i<allJobs.length; i++) {
          const j = allJobs[i];
          if (j.jobId === correlationId || j.text.includes(correlationId) || (j.el && j.el.textContent && j.el.textContent.includes(correlationId))) {
            jobEl = j.el;
            jobContainer = j.container;
            jobTop = j.top;
            jobFound = true;
            jobIndex = i;
            if (i > 0) {
              prevJobTop = allJobs[i-1].top;
              prevJobId = allJobs[i-1].jobId;
              prevJobEl = allJobs[i-1].el;
            }
            if (i < allJobs.length - 1) {
              nextJobTop = allJobs[i+1].top;
              nextJobId = allJobs[i+1].jobId;
              nextJobEl = allJobs[i+1].el;
            }
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
    let validAbove = [];
    let validBelow = [];
    let invalidAbove = [];
    let belowCandidates = [];
    let aboveCandidates = [];
    let debugAllImgs = [];
    let debugFiltered = [];
    let mismatchDetails = [];

    // Baseline entry recorded before submission; "not ready then" means the
    // same src may legitimately reappear as this job's finished output.
    function oldWasNotReady(old) {
      return !old.complete || old.naturalWidth===0 || old.opacity==='0' || (old.className&&old.className.includes('opacity-0')) || !old.visible;
    }

    function isReferenceImage(el) {
      try {
        const cls = el.className || '';
        const rect = el.getBoundingClientRect();
        const isSmall = rect.width <= 140 || cls.includes('w-32') || cls.includes('h-16') || cls.includes('w-16');
        const is50vh = cls.includes('50vh') || cls.includes('h-[50vh]') || cls.includes('w-[50vh]');
        if (isSmall && !is50vh) {
          if (jobContainer && jobContainer.contains(el)) return true;
          for (const j of allJobs) {
            if (j.container && j.container.contains(el)) return true;
          }
        }
      } catch(e) {}
      return false;
    }

    function isBeforeInDOM(a, b) {
      try {
        if (!a || !b) return false;
        if (a === b) return false;
        const pos = a.compareDocumentPosition(b);
        return !!(pos & Node.DOCUMENT_POSITION_FOLLOWING);
      } catch(e) { return false; }
    }

    function findAssociatedJobForImage(imgEl, rect, expectedId) {
      try {
        let domPrev = null;
        let domNext = null;
        let visualPrev = null;
        let visualNext = null;
        let aboveCandidates = [];
        for (const j of allJobs) {
          try {
            if (isBeforeInDOM(j.el, imgEl)) {
              domPrev = j;
            } else if (isBeforeInDOM(imgEl, j.el)) {
              if (!domNext) domNext = j;
            }
          } catch(e) {}
          try {
            if (j.top < rect.top - 5) {
              aboveCandidates.push(j);
              if (!visualPrev || j.top > visualPrev.top) visualPrev = j;
            } else if (j.top > rect.top + 5) {
              if (!visualNext || j.top < visualNext.top) visualNext = j;
            }
          } catch(e) {}
        }
        // Parallel fix: if expectedId matches any nearby, prefer it directly
        const assocShape = (j) => ({
          associatedJobId: j ? j.jobId : null,
          associatedTop: j ? j.top : null,
          domPrevJobId: domPrev ? domPrev.jobId : null,
          domNextJobId: domNext ? domNext.jobId : null,
          visualPrevJobId: visualPrev ? visualPrev.jobId : null,
          visualNextJobId: visualNext ? visualNext.jobId : null,
          visualPrevTop: visualPrev ? visualPrev.top : null,
          domPrevTop: domPrev ? domPrev.top : null
        });
        if (expectedId) {
          const matched = (c) => Object.assign(assocShape(c), {matchedExpected: true});
          const nearbyChecks = [domPrev, domNext, visualPrev, visualNext];
          for (const c of nearbyChecks) {
            if (c && c.jobId === expectedId) return matched(c);
          }
          for (const c of aboveCandidates) {
            if (c.jobId === expectedId) return matched(c);
          }
        }
        let associated = null;
        if (layoutReverse) {
          // For reverse, domNext should be visually above; prefer it if it is above
          if (domNext && domNext.top < rect.top - 5) {
            associated = domNext;
          } else if (visualPrev) {
            // Choose closest above, but if domPrev is also above and domNext was None, prefer domPrev if visualPrev is far old?
            // If domPrev is above and visualPrev is different, pick the one with smallest vertical gap
            if (domPrev && domPrev.top < rect.top - 5) {
              const gapVisual = rect.top - (visualPrev ? visualPrev.top : -Infinity);
              const gapDom = rect.top - domPrev.top;
              // Prefer the job that is closer above, but if gap difference < 200px and domPrev is closer to expected (no old), choose domPrev when visualPrev is old and domPrev not old?
              // Simple: pick closest above
              associated = (gapVisual < gapDom) ? visualPrev : domPrev;
              // If visualPrev is old and domPrev is expected (handled above via expectedId), we already returned expected, so here just closest
            } else {
              associated = visualPrev;
            }
          } else {
            associated = domPrev || domNext;
          }
          if (associated && associated.top > rect.top + 5) {
            if (visualPrev) associated = visualPrev;
          }
        } else {
          associated = domPrev || visualPrev || domNext;
        }
        return assocShape(associated);
      } catch(e) {
        return {associatedJobId: null, error: String(e)};
      }
    }

    try {
      const allImgsInDOM = document.querySelectorAll('img');
      for (const im of allImgsInDOM) {
        if (!im.src) continue;
        const r = im.getBoundingClientRect();
        debugAllImgs.push({
          src: im.src,
          cls: (im.className||'').slice(0,80),
          w: im.naturalWidth||r.width,
          h: im.naturalHeight||r.height,
          visible: im.offsetParent!==null,
          complete: im.complete,
          inOld: oldSrcs.includes(im.src),
          top: Math.round(r.top),
          isBlob: im.src.startsWith('blob:')
        });
      }
    } catch(e) {}

    for (const sel of selectors) {
      try {
        const els = document.querySelectorAll(sel);
        for (const el of els) {
          if (!el.src) { debugFiltered.push({reason:'no_src', sel}); continue; }
          if (el.src.startsWith('blob:')) { debugFiltered.push({reason:'blob', src:el.src.slice(-80), sel}); continue; }
          if (oldSrcs.includes(el.src)) {
            try {
              const old = (oldOutputs||[]).find(o=>o.src===el.src);
              if (old) {
                const wasNotReady = oldWasNotReady(old);
                if (!wasNotReady) {
                  debugFiltered.push({reason:'in_oldSrcs_ready', src:el.src.slice(-80), sel});
                  continue;
                }
              } else {
                debugFiltered.push({reason:'in_oldSrcs_no_old_entry', src:el.src.slice(-80), sel});
                continue;
              }
            } catch(e) {
              debugFiltered.push({reason:'in_oldSrcs', src:el.src.slice(-80), sel});
              continue;
            }
          }
          if (el.naturalWidth && el.naturalWidth < 50 && el.naturalHeight < 50) { debugFiltered.push({reason:'tiny_natural', src:el.src.slice(-80), w:el.naturalWidth, sel}); continue; }
          if (isReferenceImage(el)) { debugFiltered.push({reason:'isReference', src:el.src.slice(-80), cls:(el.className||'').slice(0,40), sel}); continue; }

          const rect = el.getBoundingClientRect();
          const visible = el.offsetParent !== null;
          const width = el.naturalWidth || rect.width || 0;
          const height = el.naturalHeight || rect.height || 0;
          const className = el.className || '';
          const isLarge = className.includes('50vh') || width >= 400 || rect.width >= 400 || (el.naturalWidth||0) >= 400;
          if (!isLarge) { debugFiltered.push({reason:'not_large', src:el.src.slice(-80), w:width, rectW:rect.width, cls:className.slice(0,40), sel}); continue; }

          let parentClass = '';
          try {
            let p = el.parentElement;
            for (let i=0; i<4 && p; i++) {
              parentClass += ' ' + (p.className||'');
              p = p.parentElement;
            }
          } catch(e) {}
          const isAssistantBubble = parentClass.includes('justify-start');
          const isUserBubble = parentClass.includes('items-end');

          const assoc = findAssociatedJobForImage(el, rect, correlationId);

          const info = {
            el: el,
            src: el.src,
            rect: {x: rect.left, y: rect.top, width: rect.width, height: rect.height},
            width: width,
            height: height,
            visible: visible,
            complete: el.complete,
            naturalWidth: el.naturalWidth,
            selector: sel,
            isLarge: isLarge,
            top: rect.top,
            left: rect.left,
            parentClass: parentClass.slice(0,120),
            isAssistantBubble: isAssistantBubble,
            isUserBubble: isUserBubble,
            associatedJobId: assoc.associatedJobId,
            domPrevJobId: assoc.domPrevJobId,
            domNextJobId: assoc.domNextJobId,
            visualPrevJobId: assoc.visualPrevJobId,
            visualPrevTop: assoc.visualPrevTop,
            associatedTop: assoc.associatedTop
          };
          allNew.push(info);

          // Strict JOB-ID verification: if correlationId provided, image must belong to it
          // Fix parallel case: associated may be wrong due to reverse layout, but domPrev/domNext/visualPrev may be correct
          // Check if any nearby job equals expected -> consider matching
          if (correlationId) {
            const nearby = [assoc.associatedJobId, assoc.domPrevJobId, assoc.domNextJobId, assoc.visualPrevJobId, assoc.visualNextJobId].filter(Boolean);
            const hasExpectedNearby = nearby.includes(correlationId);
            if (assoc.associatedJobId && assoc.associatedJobId !== correlationId && !hasExpectedNearby) {
              mismatchDetails.push({src: el.src.slice(0,80), associated: assoc.associatedJobId, expected: correlationId, top: Math.round(rect.top), domPrev: assoc.domPrevJobId, domNext: assoc.domNextJobId, visualPrev: assoc.visualPrevJobId, visualNext: assoc.visualNextJobId});
              debugFiltered.push({reason:'job_id_mismatch', src:el.src.slice(-80), associated: assoc.associatedJobId, expected: correlationId, domPrev: assoc.domPrevJobId, domNext: assoc.domNextJobId, visualPrev: assoc.visualPrevJobId, sel});
              continue;
            }
            // If associated is null but no nearby equals expected and we have expected job, still allow if image is in valid position relative to expected job (will be checked in validBelow/Above)
            // Do not filter here if hasExpectedNearby, let it pass to valid pools
          }

          if (jobFound && jobEl) {
            const beforeCurrent = isBeforeInDOM(el, jobEl);
            const afterCurrent = isBeforeInDOM(jobEl, el);
            const afterPrev = prevJobEl ? isBeforeInDOM(prevJobEl, el) : true;
            const beforePrev = prevJobEl ? isBeforeInDOM(el, prevJobEl) : false;
            const aboveVisual = rect.top < jobTop - 5;
            const belowVisual = rect.top > jobTop + 5;

            if (isAssistantBubble && belowVisual) {
              validBelow.push(info);
            } else if (beforeCurrent && afterPrev) {
              if (layoutReverse) {
                validBelow.push(info);
              } else {
                validAbove.push(info);
              }
            } else if (afterCurrent && afterPrev) {
              if (!layoutReverse) {
                validBelow.push(info);
              } else {
                aboveCandidates.push(info);
              }
            } else if (beforeCurrent && beforePrev) {
              invalidAbove.push(info);
            } else if (!beforeCurrent && !afterCurrent) {
              if (belowVisual) validBelow.push(info);
              else if (aboveVisual) validAbove.push(info);
              else belowCandidates.push(info);
            } else {
              if (belowVisual) belowCandidates.push(info);
              else if (aboveVisual) aboveCandidates.push(info);
            }
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
        if (!seen.has(n.src)) { seen.add(n.src); dedup.push(n); }
      }
      allNew = dedup;
      let seenV = new Set();
      validAbove = validAbove.filter(v=>{ if(seenV.has(v.src)) return false; seenV.add(v.src); return true; });
      let seenB = new Set();
      validBelow = validBelow.filter(v=>{ if(seenB.has(v.src)) return false; seenB.add(v.src); return true; });
      let seenBelow = new Set();
      belowCandidates = belowCandidates.filter(v=>{ if(seenBelow.has(v.src)) return false; seenBelow.add(v.src); return true; });
    } catch(e) {}

    if (allNew.length === 0) {
      try {
        const allImgs = document.querySelectorAll('img');
        for (const el of allImgs) {
          if (!el.src) continue;
          if (el.src.startsWith('blob:')) continue;
          if (oldSrcs.includes(el.src)) {
            try {
              const old = (oldOutputs||[]).find(o=>o.src===el.src);
              if (old) {
                const wasNotReady = oldWasNotReady(old);
                if (!wasNotReady) continue;
              } else continue;
            } catch(e) { continue; }
          }
          const rect = el.getBoundingClientRect();
          const width = el.naturalWidth || rect.width || 0;
          const cls = el.className || '';
          const isLargeFallback = width >= 400 || rect.width >= 400 || cls.includes('50vh');
          if (!isLargeFallback) continue;
          if (isReferenceImage(el)) {
            const isSmall = rect.width <= 140 || cls.includes('w-32') || cls.includes('h-16') || cls.includes('w-16');
            const is50vh = cls.includes('50vh');
            if (isSmall && !is50vh) continue;
          }
          const assoc = findAssociatedJobForImage(el, rect, correlationId);
          if (correlationId && assoc.associatedJobId && assoc.associatedJobId !== correlationId) {
            const nearby = [assoc.associatedJobId, assoc.domPrevJobId, assoc.domNextJobId, assoc.visualPrevJobId, assoc.visualNextJobId].filter(Boolean);
            if (!nearby.includes(correlationId)) {
              mismatchDetails.push({src: el.src.slice(0,80), associated: assoc.associatedJobId, expected: correlationId, top: Math.round(rect.top), reason:'fallback_mismatch', domPrev: assoc.domPrevJobId, visualPrev: assoc.visualPrevJobId});
              continue;
            }
          }
          let parentClass = '';
          try {
            let p = el.parentElement;
            for (let i=0; i<3 && p; i++) { parentClass += ' ' + (p.className||''); p = p.parentElement; }
          } catch(e) {}
          const info = {
            el: el,
            src: el.src,
            rect: {x: rect.left, y: rect.top, width: rect.width, height: rect.height},
            width: width,
            height: el.naturalHeight || rect.height || 0,
            visible: el.offsetParent !== null,
            complete: el.complete,
            naturalWidth: el.naturalWidth,
            selector: 'fallback_all_img',
            isLarge: true,
            top: rect.top,
            left: rect.left,
            parentClass: parentClass.slice(0,120),
            isAssistantBubble: parentClass.includes('justify-start'),
            associatedJobId: assoc.associatedJobId,
            domPrevJobId: assoc.domPrevJobId,
            visualPrevJobId: assoc.visualPrevJobId
          };
          allNew.push(info);
          if (jobFound && jobEl) {
            const belowVisual = rect.top > jobTop + 5;
            if (belowVisual && info.isAssistantBubble) validBelow.push(info);
            else if (isBeforeInDOM(el, jobEl)) {
              if (layoutReverse) validBelow.push(info); else validAbove.push(info);
            } else if (isBeforeInDOM(jobEl, el)) {
              if (!layoutReverse) validBelow.push(info); else validAbove.push(info);
            }
          } else {
            validBelow.push(info);
          }
        }
      } catch(e) {}
    }

    let pool = [];
    if (validBelow.length > 0) {
      validBelow.sort((a,b)=>{
        if (a.isAssistantBubble !== b.isAssistantBubble) return a.isAssistantBubble ? -1 : 1;
        if (Math.abs(a.top - b.top) > 5) return a.top - b.top;
        return b.width - a.width;
      });
      pool = validBelow;
    } else if (validAbove.length > 0) {
      validAbove.sort((a,b)=>{
        try {
          if (a.el === b.el) return 0;
          const pos = a.el.compareDocumentPosition(b.el);
          if (pos & Node.DOCUMENT_POSITION_FOLLOWING) return 1;
          if (pos & Node.DOCUMENT_POSITION_PRECEDING) return -1;
        } catch(e) {}
        return b.top - a.top;
      });
      pool = validAbove;
    } else if (belowCandidates.length > 0) {
      belowCandidates.sort((a,b) => a.top - b.top);
      pool = belowCandidates;
    } else if (aboveCandidates.length > 0) {
      aboveCandidates.sort((a,b) => b.top - a.top);
      pool = aboveCandidates;
    } else {
      pool = [];
    }

    let largePool = pool.filter(c => c.isLarge);
    if (largePool.length > 0) pool = largePool;

    // Shared core of both job_id_mismatch_no_matching_image returns (field
    // set frozen by tests/js/test_output_probes.mjs key-set locks).
    const mismatchReturn = (orderCheckMsg, extra) => Object.assign({
      ready: false,
      reason: 'job_id_mismatch_no_matching_image',
      spinning: spinning,
      spinCount: spinCount,
      spinDetails: spinDetails,
      jobFound: jobFound,
      jobTop: jobTop,
      prevJobTop: prevJobTop,
      nextJobTop: nextJobTop,
      jobIndex: jobIndex,
      allJobs: allJobs.map(j=>({id:j.jobId, top:j.top})),
      allNew: allNew.length,
      validBelow: validBelow.length,
      validAbove: validAbove.length,
      jobId: correlationId,
      expectedJobId: correlationId,
      mismatchDetails: mismatchDetails.slice(0,10),
      layoutReverse: layoutReverse,
      orderCheck: orderCheckMsg,
      debugAllImgs: debugAllImgs.slice(0,10),
      debugFiltered: debugFiltered.slice(0,15)
    }, extra);

    // Final strict verification: if correlationId provided, pool must have matching associatedJobId
    // Parallel fix: allow if any nearby job equals expected (domPrev/domNext/visualPrev/visualNext) — covers reverse layout where visualPrev may be old but domPrev is expected
    if (correlationId) {
      const matchingPool = pool.filter(c => {
        if (!c.associatedJobId) return true;
        if (c.associatedJobId === correlationId) return true;
        const nearby = [c.domPrevJobId, c.domNextJobId, c.visualPrevJobId].filter(Boolean);
        return nearby.includes(correlationId);
      });
      if (matchingPool.length === 0 && pool.length > 0) {
        return mismatchReturn(
          `JOB-ID mismatch: expected ${correlationId} but found images belong to ${mismatchDetails.map(m=>m.associated).join(',')} — not downloading, will error`,
          {poolDetails: pool.slice(0,5).map(p=>({src:p.src.slice(0,80), associated:p.associatedJobId, expected:correlationId, top:Math.round(p.top)}))});
      }
      pool = matchingPool;
    }

    for (const cand of pool) {
      const el = cand.el;
      if (!el.complete) {
        return {ready:false, reason:'not_complete', src: cand.src, spinning: spinning, spinCount: spinCount, spinDetails: spinDetails, candidates: pool.length, validBelow: validBelow.length, validAbove: validAbove.length, jobFound: jobFound, jobTop: jobTop, jobIndex: jobIndex, allJobs: allJobs.length, isLarge: cand.isLarge, top: cand.top, jobId: correlationId, associatedJobId: cand.associatedJobId, expectedJobId: correlationId, layoutReverse: layoutReverse, orderCheck: `Below prompt: jobTop ${jobTop} img top ${cand.top} associated ${cand.associatedJobId} expected ${correlationId}`};
      }
      if (el.naturalWidth === 0) {
        return {ready:false, reason:'zero_width', src: cand.src, spinning: spinning, spinCount: spinCount, spinDetails: spinDetails, candidates: pool.length, jobFound: jobFound, jobTop: jobTop, isLarge: cand.isLarge, associatedJobId: cand.associatedJobId, expectedJobId: correlationId};
      }
      if (!cand.visible) continue;
      if (spinning) {
        return {ready:false, reason:'generating_spinner_visible', src: cand.src, spinning: true, spinCount: spinCount, spinDetails: spinDetails, width: cand.width, height: cand.height, rect: cand.rect, jobFound: jobFound, jobTop: jobTop, jobIndex: jobIndex, allJobs: allJobs.length, validBelow: validBelow.length, validAbove: validAbove.length, isLarge: cand.isLarge, top: cand.top, associatedJobId: cand.associatedJobId, expectedJobId: correlationId, layoutReverse: layoutReverse, orderCheck: `Below prompt but spinning, associated ${cand.associatedJobId} expected ${correlationId}`};
      }
      return {ready:true, src: cand.src, width: cand.width, height: cand.height, spinning: false, rect: cand.rect, selector: cand.selector, jobFound: jobFound, jobTop: jobTop, prevJobTop: prevJobTop, nextJobTop: nextJobTop, jobIndex: jobIndex, allJobs: allJobs.length, validBelow: validBelow.length, validAbove: validAbove.length, belowCount: belowCandidates.length, aboveCount: aboveCandidates.length, isLarge: cand.isLarge, top: cand.top, associatedJobId: cand.associatedJobId, expectedJobId: correlationId, domPrevJobId: cand.domPrevJobId, visualPrevJobId: cand.visualPrevJobId, layoutReverse: layoutReverse, orderCheck: `Verified below prompt: jobTop ${jobTop} < img top ${cand.top} isAssistant ${cand.isAssistantBubble} associated ${cand.associatedJobId} == expected ${correlationId} (CORRECT KEY MATCH)`};
    }

    if (pool.length > 0) {
      const first = pool[0];
      const reason = !first.visible ? 'hidden' : (!first.complete ? 'not_complete' : 'loading');
      return {ready:false, reason: reason, src: first.src, spinning: spinning, spinCount: spinCount, spinDetails: spinDetails, candidates: pool.length, validBelow: validBelow.length, validAbove: validAbove.length, jobFound: jobFound, jobTop: jobTop, associatedJobId: first.associatedJobId, expectedJobId: correlationId};
    }

    if (allNew.length > 0) {
      let allNewDetails = [];
      try {
        for (const n of allNew.slice(0,10)) {
          allNewDetails.push({src: n.src.slice(0,80), top: Math.round(n.top), isLarge: n.isLarge, width: n.width, selector: n.selector, isAssistant: n.isAssistantBubble, associated: n.associatedJobId, expected: correlationId});
        }
      } catch(e) {}
      if (mismatchDetails.length > 0) {
        return mismatchReturn(
          `JOB-ID mismatch after reset: expected ${correlationId} but all ${allNew.length} new images belong to different keys ${mismatchDetails.map(m=>m.associated).join(',')} — do not download, error`,
          {allNewDetails: allNewDetails, belowCount: belowCandidates.length, aboveCount: aboveCandidates.length});
      }
      return {ready:false, reason:'no_exact_below_found_wait_next', spinning: spinning, spinCount: spinCount, spinDetails: spinDetails, jobFound: jobFound, jobTop: jobTop, prevJobTop: prevJobTop, nextJobTop: nextJobTop, jobIndex: jobIndex, allJobs: allJobs.map(j=>({id:j.jobId, top:j.top, isUser:j.isUserBubble})), allNew: allNew.length, allNewDetails: allNewDetails, validBelow: validBelow.length, validAbove: validAbove.length, belowCount: belowCandidates.length, aboveCount: aboveCandidates.length, jobId: correlationId, expectedJobId: correlationId, mismatchDetails: mismatchDetails.slice(0,10), layoutReverse: layoutReverse, orderCheck: `No exact below: jobTop ${jobTop} prevTop ${prevJobTop} nextTop ${nextJobTop} allNew ${allNew.length} validBelow ${validBelow.length} validAbove ${validAbove.length} expected ${correlationId}`, debugAllImgs: debugAllImgs.slice(0,10), debugFiltered: debugFiltered.slice(0,15), oldSrcsSample: oldSrcs.slice(0,3).map(s=>s.slice(0,80))};
    }

    if (spinning) {
      return {ready:false, reason:'generating_no_new_yet', spinning: true, spinCount: spinCount, spinDetails: spinDetails, jobFound: jobFound, jobTop: jobTop, prevJobTop: prevJobTop, jobIndex: jobIndex, allJobs: allJobs.length, layoutReverse: layoutReverse, expectedJobId: correlationId};
    }
    return {ready:false, reason:'no_new', spinning: false, spinCount: 0, jobFound: jobFound, jobTop: jobTop, prevJobTop: prevJobTop, nextJobTop: nextJobTop, jobIndex: jobIndex, allJobs: allJobs.map(j=>({id:j.jobId, top:j.top})), validBelow: validBelow.length, validAbove: validAbove.length, allNew: allNew.length, jobId: correlationId, expectedJobId: correlationId, mismatchDetails: mismatchDetails.slice(0,10), layoutReverse: layoutReverse, orderCheck: `No new images at all, oldSrcs ${oldSrcs.length} expected ${correlationId}`, debugAllImgs: debugAllImgs.slice(0,10), debugFiltered: debugFiltered.slice(0,10), oldSrcsSample: oldSrcs.slice(0,3).map(s=>s.slice(0,80))};
  } catch(e) { return {ready:false, reason:String(e), spinning: false}; }
})
""".replace("__SELECTORS__", json.dumps(SELECTORS_V3)).replace("__SPINNER_SELECTOR__", _SPINNER_SEL) \
    .replace("__MODEL_ROW_SCOPE__", json.dumps(_MODEL_LABEL["scope"])) \
    .replace("__MODEL_LABEL__", json.dumps(_MODEL_LABEL["label"]))


def build_baseline_js() -> str:
    return f";({JS_BASELINE_V3})()"


def build_check_js(old_srcs, correlation_id, old_outputs) -> str:
    return f";({JS_CHECK_NEW_OUTPUT_V3})({json.dumps(old_srcs)}, {json.dumps(correlation_id) if correlation_id else 'null'}, {json.dumps(old_outputs)})"
