"""Output probes v3 — JS for baseline and new output detection.

Fixes 4 root causes:
1. Early-break stopping scan before newer images
2. Inner text container <p> only JOB-ID excluding reference thumbnail
3. flex-col-reverse misdetect
4. No fallback + truncated src

Per RULE 21 selector priority, RULE 22 correlation token.
"""

import json
from typing import List

# Normalized selector keys, no early-break, full src returned
SELECTORS_V3: List[str] = [
    'div.no-scrollbar img[src*=".r2.cloudflarestorage.com/"]',
    'div.no-scrollbar img[src*="messages-prod."]',
    'div.no-scrollbar img[loading="lazy"].aspect-square',
    'img.aspect-square.cursor-pointer',
    'img.cursor-pointer',
    'div.flex img[src*=".r2.cloudflarestorage.com/"]',
    'main img[src*=".r2.cloudflarestorage.com/"]',
    'div.no-scrollbar img[src^="https://"]',
    'img.aspect-square.w-full',
    'img[src*=".r2.cloudflarestorage.com/"]',
    'img[src*="messages-prod"]',
    'img.h-\\[50vh\\]',
    'img.w-\\[50vh\\]',
    'ol img[src^="https://"]',
    'main img',
]

# Baseline probe — full src + rect, skips blob and tiny icons
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
      const spinners = document.querySelectorAll('div.animate-spin');
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
""".replace("__SELECTORS__", json.dumps(SELECTORS_V3))

# Check new output probe v3 — layout-aware, no early-break, full src, below-prompt preference
JS_CHECK_NEW_OUTPUT_V3 = """
((oldSrcs, correlationId, oldOutputs) => {
  try {
    let spinning = false;
    let spinCount = 0;
    let spinDetails = [];
    try {
      const spinners = document.querySelectorAll('div.animate-spin');
      for (const s of spinners) {
        if (s.offsetParent !== null) {
          spinning = true;
          spinCount++;
          let parent = s.closest('div.flex.min-w-0.flex-1.items-center.gap-2');
          let label = '';
          if (parent) {
            const trunc = parent.querySelector('span.truncate');
            if (trunc) label = trunc.textContent.trim();
          }
          spinDetails.push({label: label || 'unknown', visible: true});
        }
      }
    } catch(e) {}

    // Layout-aware: detect flex-col-reverse
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

    // Collect all JOB-ID prompts with improved container logic
    let allJobs = [];
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
          // Improved: smallest container requires hasJob && (hasImg || hasFlex || hasGroup)
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
            allJobs.push({
              jobId: jobId,
              el: el,
              container: container,
              top: rect.top,
              left: rect.left,
              width: rect.width,
              height: rect.height,
              text: txt.slice(0,200),
              isUserBubble: (container.className||'').includes('items-end')
            });
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
                allJobs.push({
                  jobId: correlationId,
                  el: parent,
                  container: parent.closest('div.flex.min-w-0.flex-1.flex-col.items-end, div.group, div.flex.flex-col') || parent,
                  top: r.top,
                  left: r.left,
                  width: r.width,
                  height: r.height,
                  text: val.slice(0,200),
                  isUserBubble: true
                });
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

    // No early-break: scan all selectors, deduplicate later
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
                const wasNotReady = !old.complete || old.naturalWidth===0 || old.opacity==='0' || (old.className&&old.className.includes('opacity-0')) || !old.visible;
                if (!wasNotReady) {
                  debugFiltered.push({reason:'in_oldSrcs_ready', src:el.src.slice(-80), sel, oldLen:oldSrcs.length});
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

          // Check for assistant bubble class justify-start (correct) vs items-end (user)
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
            isUserBubble: isUserBubble
          };
          allNew.push(info);

          if (jobFound && jobEl) {
            const beforeCurrent = isBeforeInDOM(el, jobEl);
            const afterCurrent = isBeforeInDOM(jobEl, el);
            const afterPrev = prevJobEl ? isBeforeInDOM(prevJobEl, el) : true;
            const beforePrev = prevJobEl ? isBeforeInDOM(el, prevJobEl) : false;
            const aboveVisual = rect.top < jobTop - 5;
            const belowVisual = rect.top > jobTop + 5;

            // Correct image is BELOW prompt block per user: top > jobTop and justify-start
            // For flex-col-reverse, DOM before = visual below, so handle both
            if (isAssistantBubble && belowVisual) {
              validBelow.push(info);
            } else if (beforeCurrent && afterPrev) {
              // File above = visual below if reverse, could be valid
              if (layoutReverse) {
                // In reverse, file above = visual below → validBelow
                validBelow.push(info);
              } else {
                validAbove.push(info);
              }
            } else if (afterCurrent && afterPrev) {
              // File below = visual above if reverse, but user says correct is below prompt block
              // In normal layout, file below = visual below → validBelow
              if (!layoutReverse) {
                validBelow.push(info);
              } else {
                aboveCandidates.push(info);
              }
            } else if (beforeCurrent && beforePrev) {
              invalidAbove.push(info);
            } else if (!beforeCurrent && !afterCurrent) {
              // fallback visual
              if (belowVisual) validBelow.push(info);
              else if (aboveVisual) validAbove.push(info);
              else belowCandidates.push(info);
            } else {
              if (belowVisual) belowCandidates.push(info);
              else if (aboveVisual) aboveCandidates.push(info);
            }
          } else {
            // No job anchor, use below as valid (newest)
            validBelow.push(info);
          }
        }
      } catch(e) {}
    }

    // Deduplicate by src
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

    // Fallback: scan ALL img tags if still empty
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
                const wasNotReady = !old.complete || old.naturalWidth===0 || old.opacity==='0' || (old.className&&old.className.includes('opacity-0')) || !old.visible;
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
            isAssistantBubble: parentClass.includes('justify-start')
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

    // Prefer validBelow (correct image BELOW prompt per user) over validAbove
    let pool = [];
    if (validBelow.length > 0) {
      validBelow.sort((a,b)=>{
        // Prefer assistant bubble, then closest below (smallest top > jobTop), then largest width
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

    for (const cand of pool) {
      const el = cand.el;
      if (!el.complete) {
        return {ready:false, reason:'not_complete', src: cand.src, spinning: spinning, spinCount: spinCount, spinDetails: spinDetails, candidates: pool.length, validBelow: validBelow.length, validAbove: validAbove.length, belowCount: belowCandidates.length, aboveCount: aboveCandidates.length, jobFound: jobFound, jobTop: jobTop, prevJobTop: prevJobTop, nextJobTop: nextJobTop, jobIndex: jobIndex, allJobs: allJobs.length, isLarge: cand.isLarge, top: cand.top, jobId: correlationId, layoutReverse: layoutReverse, orderCheck: `Below prompt: jobTop ${jobTop} img top ${cand.top} isAssistant ${cand.isAssistantBubble} (DOM order)`};
      }
      if (el.naturalWidth === 0) {
        return {ready:false, reason:'zero_width', src: cand.src, spinning: spinning, spinCount: spinCount, spinDetails: spinDetails, candidates: pool.length, jobFound: jobFound, jobTop: jobTop, isLarge: cand.isLarge};
      }
      if (!cand.visible) continue;
      if (spinning) {
        return {ready:false, reason:'generating_spinner_visible', src: cand.src, spinning: true, spinCount: spinCount, spinDetails: spinDetails, width: cand.width, height: cand.height, rect: cand.rect, jobFound: jobFound, jobTop: jobTop, prevJobTop: prevJobTop, nextJobTop: nextJobTop, jobIndex: jobIndex, allJobs: allJobs.length, validBelow: validBelow.length, validAbove: validAbove.length, isLarge: cand.isLarge, top: cand.top, layoutReverse: layoutReverse, orderCheck: `Below prompt but spinning, await`};
      }
      return {ready:true, src: cand.src, width: cand.width, height: cand.height, spinning: false, rect: cand.rect, selector: cand.selector, jobFound: jobFound, jobTop: jobTop, prevJobTop: prevJobTop, nextJobTop: nextJobTop, jobIndex: jobIndex, allJobs: allJobs.length, validBelow: validBelow.length, validAbove: validAbove.length, belowCount: belowCandidates.length, aboveCount: aboveCandidates.length, isLarge: cand.isLarge, top: cand.top, layoutReverse: layoutReverse, orderCheck: `Below prompt verified: jobTop ${jobTop} < img top ${cand.top} isAssistant ${cand.isAssistantBubble} (correct image BELOW prompt block)`};
    }

    if (pool.length > 0) {
      const first = pool[0];
      const reason = !first.visible ? 'hidden' : (!first.complete ? 'not_complete' : 'loading');
      return {ready:false, reason: reason, src: first.src, spinning: spinning, spinCount: spinCount, spinDetails: spinDetails, candidates: pool.length, validBelow: validBelow.length, validAbove: validAbove.length, jobFound: jobFound, jobTop: jobTop};
    }

    if (allNew.length > 0) {
      let allNewDetails = [];
      try {
        for (const n of allNew.slice(0,10)) {
          allNewDetails.push({src: n.src.slice(0,120), top: n.top, isLarge: n.isLarge, width: n.width, selector: n.selector, isAssistant: n.isAssistantBubble});
        }
      } catch(e) {}
      return {ready:false, reason:'no_exact_below_found_wait_next', spinning: spinning, spinCount: spinCount, spinDetails: spinDetails, jobFound: jobFound, jobTop: jobTop, prevJobTop: prevJobTop, nextJobTop: nextJobTop, jobIndex: jobIndex, allJobs: allJobs.map(j=>({id:j.jobId, top:j.top, isUser:j.isUserBubble})), allNew: allNew.length, allNewDetails: allNewDetails, validBelow: validBelow.length, validAbove: validAbove.length, belowCount: belowCandidates.length, aboveCount: aboveCandidates.length, jobId: correlationId, layoutReverse: layoutReverse, orderCheck: `No exact below: jobTop ${jobTop} prevTop ${prevJobTop} nextTop ${nextJobTop} allNew ${allNew.length} validBelow ${validBelow.length} validAbove ${validAbove.length}`, debugAllImgs: debugAllImgs.slice(0,10), debugFiltered: debugFiltered.slice(0,15), oldSrcsSample: oldSrcs.slice(0,3).map(s=>s.slice(0,120))};
    }

    if (spinning) {
      return {ready:false, reason:'generating_no_new_yet', spinning: true, spinCount: spinCount, spinDetails: spinDetails, jobFound: jobFound, jobTop: jobTop, prevJobTop: prevJobTop, jobIndex: jobIndex, allJobs: allJobs.length, layoutReverse: layoutReverse};
    }
    return {ready:false, reason:'no_new', spinning: false, spinCount: 0, jobFound: jobFound, jobTop: jobTop, prevJobTop: prevJobTop, nextJobTop: nextJobTop, jobIndex: jobIndex, allJobs: allJobs.map(j=>({id:j.jobId, top:j.top})), validBelow: validBelow.length, validAbove: validAbove.length, allNew: allNew.length, jobId: correlationId, layoutReverse: layoutReverse, orderCheck: `No new images at all, oldSrcs ${oldSrcs.length}`, debugAllImgs: debugAllImgs.slice(0,10), debugFiltered: debugFiltered.slice(0,10), oldSrcsSample: oldSrcs.slice(0,3).map(s=>s.slice(0,120))};
  } catch(e) { return {ready:false, reason:String(e), spinning: false}; }
})
""".replace("__SELECTORS__", json.dumps(SELECTORS_V3))


def build_baseline_js() -> str:
    # ideal-size: 3 lines reason=returns baseline JS
    return f";({JS_BASELINE_V3})()"


def build_check_js(old_srcs, correlation_id, old_outputs) -> str:
    # ideal-size: 4 lines reason=builds check JS with full src
    return f";({JS_CHECK_NEW_OUTPUT_V3})({json.dumps(old_srcs)}, {json.dumps(correlation_id) if correlation_id else 'null'}, {json.dumps(old_outputs)})"


def is_layout_reverse_js() -> str:
    # ideal-size: 3 lines reason=layout reverse detection snippet
    return "!!document.querySelector('ol.flex-col-reverse')"


def get_selectors() -> list:
    # ideal-size: 2 lines reason=returns normalized selectors
    return SELECTORS_V3.copy()
