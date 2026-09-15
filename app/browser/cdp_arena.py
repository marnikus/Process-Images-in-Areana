"""CDP Arena Controller — automation for arena.ai via CDPClient (already opened Chrome).

Implements:
- attach image as reference (via DOM.setFileInputFiles)
- insert prompt with JOB-ID token
- submit once
- baseline capture / new output detection
- download validation
- highlight rectangle with configurable duration (saved in preset)

Uses semantic selectors from site_adapter, with fallbacks.
"""

import json
import time
import asyncio
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple, Callable

from .cdp_client import CDPClient
from .site_adapter import SELECTORS, get_selector

log = logging.getLogger("arena")

# JS snippets for operations
JS_FIND_TEXTAREA = """
(() => {
  const sels = [
    'textarea[name="message"]',
    'textarea[name="message"][autocomplete="off"]',
    'textarea[placeholder^="Describe how you want to edit"]',
    'textarea[placeholder^="Describe the image you want to generate"]',
    'textarea[placeholder^="Describe"]',
    'textarea[rows="1"]'
  ];
  for (const sel of sels) {
    const el = document.querySelector(sel);
    if (el && el.offsetParent !== null) return sel;
  }
  return null;
})
"""

JS_INSERT_PROMPT = """
((promptText) => {
  try {
    const sels = [
      'textarea[name="message"]',
      'textarea[name="message"][autocomplete="off"]',
      'textarea[placeholder^="Describe how you want to edit"]',
      'textarea[placeholder^="Describe the image you want to generate"]',
      'textarea[placeholder^="Describe"]',
      'textarea[rows="1"]'
    ];
    let ta = null;
    for (const sel of sels) {
      const el = document.querySelector(sel);
      if (el && el.offsetParent !== null) { ta = el; break; }
    }
    if (!ta) return {ok:false, error:'textarea not found'};
    ta.focus();
    // Use native setter to trigger React
    const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
    nativeSetter.call(ta, promptText);
    ta.dispatchEvent(new Event('input', {bubbles:true}));
    ta.dispatchEvent(new Event('change', {bubbles:true}));
    // Also set value directly as fallback
    ta.value = promptText;
    return {ok:true, value: ta.value, len: ta.value.length};
  } catch(e) { return {ok:false, error:String(e)}; }
})
"""

JS_VERIFY_PROMPT = """
((expected) => {
  try {
    const el = document.querySelector('textarea[name="message"]');
    if (!el) return {ok:false, error:'not found'};
    return {ok: el.value === expected, actual: el.value, expected: expected, actualLen: el.value.length, expectedLen: expected.length};
  } catch(e) { return {ok:false, error:String(e)}; }
})
"""

JS_FIND_SEND_BUTTON = """
(() => {
  const sels = [
    'button[aria-label="Send message"]:not([disabled])',
    'form button[aria-label="Send message"]:not([disabled])',
    'form:has(textarea[name="message"]) button[aria-label="Send message"]:not([disabled])',
    'div.flex.items-center.gap-2 button[aria-label="Send message"]:not([disabled])',
    'button[type="button"][aria-label="Send message"]:not([disabled])',
    'button[aria-label="Send message"]',
    'button[type="submit"][aria-label="Send message"]',
    'form div.flex.items-center.gap-2 button:last-child:not([disabled])',
    'form button:has(svg):not([disabled])',
    'form button[type="submit"]',
    'button.inline-flex.h-8.w-8[aria-label="Send message"]'
  ];
  for (const sel of sels) {
    try {
      const els = document.querySelectorAll(sel);
      for (const el of els) {
        // Check visible and not disabled, and not opacity-50 pointer-events-none
        const style = window.getComputedStyle(el);
        const isDisabled = el.disabled || el.getAttribute('aria-disabled') === 'true' || el.hasAttribute('disabled');
        const hasPointerNone = style.pointerEvents === 'none';
        const isVisible = el.offsetParent !== null || (el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0);
        if (isVisible && !isDisabled && !hasPointerNone) return sel;
      }
    } catch(e) {}
  }
  // Fallback: return first enabled button if any
  try {
    const all = document.querySelectorAll('button[aria-label="Send message"]');
    for (const el of all) {
      if (el.offsetParent !== null) return 'button[aria-label="Send message"]';
    }
  } catch(e) {}
  return null;
})
"""

JS_CLICK_SEND = """
(() => {
  try {
    const sels = [
      'button[aria-label="Send message"]:not([disabled])',
      'form button[aria-label="Send message"]:not([disabled])',
      'form:has(textarea[name="message"]) button[aria-label="Send message"]:not([disabled])',
      'div.flex.items-center.gap-2 button[aria-label="Send message"]:not([disabled])',
      'button[type="button"][aria-label="Send message"]:not([disabled])',
      'button[aria-label="Send message"]',
      'button[type="submit"][aria-label="Send message"]',
      'form div.flex.items-center.gap-2 button:last-child',
      'form button[type="submit"]',
      'button.inline-flex.h-8.w-8[aria-label="Send message"]'
    ];
    let btn = null;
    let usedSel = null;
    for (const sel of sels) {
      try {
        const els = document.querySelectorAll(sel);
        for (const el of els) {
          const style = window.getComputedStyle(el);
          const isDisabled = el.disabled || el.getAttribute('aria-disabled') === 'true' || el.hasAttribute('disabled');
          const hasPointerNone = style.pointerEvents === 'none';
          const isVisible = el.offsetParent !== null || (el.getBoundingClientRect().width > 0);
          if (isVisible && !isDisabled) { btn = el; usedSel = sel; break; }
          // Even if disabled check fails, keep last visible as fallback
          if (isVisible && !btn) { btn = el; usedSel = sel; }
        }
      } catch(e) {}
      if (btn && !btn.disabled) break;
    }
    if (!btn) return {ok:false, error:'send button not found or disabled', tried: sels};
    // Try multiple click methods for React
    try { btn.focus(); } catch(e) {}
    try {
      btn.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true}));
      btn.dispatchEvent(new MouseEvent('mouseup', {bubbles:true, cancelable:true}));
      btn.click();
    } catch(e) {
      try { btn.click(); } catch(e2) { return {ok:false, error:String(e2), sel: usedSel}; }
    }
    return {ok:true, sel: usedSel};
  } catch(e) { return {ok:false, error:String(e)}; }
})
"""

JS_BASELINE = """
(() => {
  try {
    const outputs = [];
    const selectors = [
      'div.no-scrollbar img[src*=".r2.cloudflarestorage.com/"]',
      'div.no-scrollbar img[src*="messages-prod."]',
      'div.no-scrollbar img[loading="lazy"].aspect-square',
      'img.aspect-square.cursor-pointer',
      'img.cursor-pointer',
      'div.flex.flex-wrap img[src^="blob:"]',
      'div.flex img[src*=".r2.cloudflarestorage.com/"]',
      'div.flex img.aspect-square',
      'main img[src*=".r2.cloudflarestorage.com/"]',
      'main img.aspect-square',
      'div.no-scrollbar img[src^="https://"]',
      'img.aspect-square.w-full',
      'img[src*=".r2.cloudflarestorage.com/"]'
    ];
    for (const sel of selectors) {
      try {
        const els = document.querySelectorAll(sel);
        for (const el of els) {
          if (!el.src) continue;
          // Skip blob preview (attachment) - only want generated
          if (el.src.startsWith('blob:')) continue;
          // Skip tiny icons
          if (el.naturalWidth && el.naturalWidth < 50 && el.naturalHeight < 50) continue;
          outputs.push({
            src: el.src,
            complete: el.complete,
            naturalWidth: el.naturalWidth,
            naturalHeight: el.naturalHeight,
            visible: el.offsetParent !== null,
            selector: sel
          });
        }
      } catch(e) {}
      if (outputs.length > 0) break;
    }
    // Also check spinner state for baseline
    let spinning = false;
    try {
      const spinners = document.querySelectorAll('div.animate-spin');
      for (const s of spinners) {
        if (s.offsetParent !== null) { spinning = true; break; }
      }
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
"""

JS_CHECK_NEW_OUTPUT = """
((oldSrcs, correlationId) => {
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

    // --- Collect all JOB-ID prompts with their DOM order and visual top ---
    let allJobs = [];
    try {
      const jobRegex = /\[JOB-ID:\s*([^\]\s]+)\]/g;
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
          let container = el;
          let cur = el;
          for (let i=0; i<10 && cur; i++) {
            if (cur.getBoundingClientRect) {
              const r = cur.getBoundingClientRect();
              if (r.height > 20 && r.height < window.innerHeight * 0.95 && r.width < window.innerWidth * 0.98) {
                if (cur.querySelector('img') || cur.classList.contains('flex') || cur.classList.contains('group') || cur.textContent.includes(jobId)) {
                  if (!cur.classList.contains('no-scrollbar')) {
                    container = cur;
                  }
                }
              }
            }
            if (cur.classList && cur.classList.contains('no-scrollbar')) break;
            cur = cur.parentElement;
          }
          if (!container) container = el.closest('div.group, div.flex.flex-col, div[data-message-id], div.min-w-0.flex-1, div.flex.w-full') || el.closest('div') || el;
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
              text: txt.slice(0,200)
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
                  container: parent.closest('div.group, div.flex.flex-col') || parent,
                  top: r.top,
                  left: r.left,
                  width: r.width,
                  height: r.height,
                  text: val.slice(0,200)
                });
                break;
              } catch(e) {}
            }
          }
        }
      }
      // Deduplicate by jobId
      let deduped = [];
      let seenIds = new Set();
      for (const j of allJobs) {
        if (!seenIds.has(j.jobId)) {
          seenIds.add(j.jobId);
          deduped.push(j);
        }
      }
      allJobs = deduped;
      // Sort by DOM order (document order) — primary for exact above logic
      // Use compareDocumentPosition to sort
      allJobs.sort((a,b)=>{
        try {
          if (a.el === b.el) return 0;
          const pos = a.el.compareDocumentPosition(b.el);
          if (pos & Node.DOCUMENT_POSITION_FOLLOWING) return -1; // a before b
          if (pos & Node.DOCUMENT_POSITION_PRECEDING) return 1;  // a after b
        } catch(e) {}
        // Fallback to visual top
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
              jobContainer = el.closest('div.group, div.flex.flex-col, div[data-message-id], div.min-w-0.flex-1, div.flex.w-full') || el.closest('div') || el;
              try { jobTop = jobContainer.getBoundingClientRect().top; } catch(e) {}
              jobFound = true;
              break;
            }
          }
        }
      } catch(e) {}
    }

    const selectors = [
      'div.no-scrollbar img[src*=".r2.cloudflarestorage.com/"]',
      'div.no-scrollbar img[src*="messages-prod."]',
      'div.no-scrollbar img[loading="lazy"].aspect-square',
      'img.aspect-square.cursor-pointer',
      'img.cursor-pointer',
      'div.flex img[src*=".r2.cloudflarestorage.com/"]',
      'main img[src*=".r2.cloudflarestorage.com/"]',
      'div.no-scrollbar img[src^="https://"]',
      'img.aspect-square.w-full',
      'img[src*=".r2.cloudflarestorage.com/"]'
    ];

    let allNew = [];
    let validAbove = [];
    let invalidAbove = [];
    let belowCandidates = [];

    function isReferenceImage(el) {
      try {
        if (jobContainer && jobContainer.contains(el)) return true;
        for (const j of allJobs) {
          if (j.container && j.container.contains(el)) {
            const cls = el.className || '';
            const rect = el.getBoundingClientRect();
            const isSmall = rect.width <= 140 || cls.includes('w-32') || cls.includes('h-16') || cls.includes('w-16');
            if (isSmall) return true;
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
    function isAfterInDOM(a, b) {
      try {
        if (!a || !b) return false;
        if (a === b) return false;
        const pos = a.compareDocumentPosition(b);
        return !!(pos & Node.DOCUMENT_POSITION_PRECEDING);
      } catch(e) { return false; }
    }

    for (const sel of selectors) {
      try {
        const els = document.querySelectorAll(sel);
        for (const el of els) {
          if (!el.src) continue;
          if (el.src.startsWith('blob:')) continue;
          if (oldSrcs.includes(el.src)) continue;
          if (el.naturalWidth && el.naturalWidth < 50 && el.naturalHeight < 50) continue;
          if (isReferenceImage(el)) continue;

          const rect = el.getBoundingClientRect();
          const visible = el.offsetParent !== null;
          const width = el.naturalWidth || rect.width || 0;
          const height = el.naturalHeight || rect.height || 0;
          const className = el.className || '';
          const isLarge = width >= 200 || rect.width >= 200 || className.includes('50vh') || className.includes('object-cover') || (el.classList && el.classList.contains('aspect-square') && rect.width >= 200);
          if (!isLarge) continue;

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
            left: rect.left
          };
          allNew.push(info);

          if (jobFound && jobEl) {
            // DOM-order exact above logic (primary):
            // Image must be before current job in DOM (file above)
            // And after previous job in DOM (if exists) — so between prev and current
            // This matches <ol flex-col-reverse> where gen directly above user in file belongs to that user
            const beforeCurrent = isBeforeInDOM(el, jobEl);
            const afterPrev = prevJobEl ? isBeforeInDOM(prevJobEl, el) : true;
            const beforePrev = prevJobEl ? isBeforeInDOM(el, prevJobEl) : false;

            // Also check visual top as secondary, but DOM order is primary
            const aboveVisual = rect.top < jobTop - 5;
            const belowVisual = rect.top > jobTop + 5;

            // For flex-col-reverse, DOM before = visual after (larger top), so we cannot rely only on visual
            // Valid if DOM between prev and current, regardless of visual top
            if (beforeCurrent && afterPrev) {
              // Ensure no intervening job between image and current in DOM order
              let hasInterveningJob = false;
              for (const j of allJobs) {
                if (j.jobId === correlationId) continue;
                if (isBeforeInDOM(el, j.el) && isBeforeInDOM(j.el, jobEl)) {
                  hasInterveningJob = true;
                  break;
                }
              }
              if (!hasInterveningJob) {
                validAbove.push(info);
              } else {
                invalidAbove.push(info);
              }
            } else if (beforeCurrent && beforePrev) {
              // Image before previous job — belongs to previous prompt
              invalidAbove.push(info);
            } else if (!beforeCurrent) {
              // Image after current in DOM (below in file, above visually due to flex-col-reverse)
              // Could be below candidate — but for flex-col-reverse, image after current in DOM is actually older, not relevant
              belowCandidates.push(info);
            } else {
              // Fallback: use visual check
              if (aboveVisual) {
                let between = true;
                if (prevJobTop !== null) {
                  if (rect.top <= prevJobTop + 5) between = false;
                }
                if (between) {
                  let hasIntervening = false;
                  for (const j of allJobs) {
                    if (j.jobId === correlationId) continue;
                    if (j.top > rect.top + 5 && j.top < jobTop - 5) { hasIntervening = true; break; }
                  }
                  if (!hasIntervening) validAbove.push(info);
                  else invalidAbove.push(info);
                } else {
                  invalidAbove.push(info);
                }
              } else if (belowVisual) {
                belowCandidates.push(info);
              }
            }
          } else {
            validAbove.push(info);
          }
        }
      } catch(e) {}
      if (validAbove.length > 0) break;
    }

    // If we have validAbove (exact above current prompt in DOM order), pick closest above (nearest before current in DOM)
    let pool = [];
    if (validAbove.length > 0) {
      // Sort by DOM order: closest before current = last in DOM order before current
      validAbove.sort((a,b)=>{
        try {
          if (a.el === b.el) return 0;
          const pos = a.el.compareDocumentPosition(b.el);
          if (pos & Node.DOCUMENT_POSITION_FOLLOWING) return 1; // a before b, so b closer to job
          if (pos & Node.DOCUMENT_POSITION_PRECEDING) return -1;
        } catch(e) {}
        return b.top - a.top;
      });
      pool = validAbove;
    } else if (belowCandidates.length > 0 && !jobFound) {
      belowCandidates.sort((a,b) => b.top - a.top);
      pool = belowCandidates;
    } else {
      pool = [];
    }

    let largePool = pool.filter(c => c.isLarge);
    if (largePool.length > 0) pool = largePool;

    if (jobFound && pool.length > 0) {
      pool.sort((a,b)=>{
        try {
          const pos = a.el.compareDocumentPosition(b.el);
          if (pos & Node.DOCUMENT_POSITION_FOLLOWING) return 1;
          if (pos & Node.DOCUMENT_POSITION_PRECEDING) return -1;
        } catch(e) {}
        return b.top - a.top;
      });
    } else {
      pool.sort((a,b)=>{
        if (a.visible !== b.visible) return a.visible ? -1 : 1;
        return b.top - a.top;
      });
    }

    for (const cand of pool) {
      const el = cand.el;
      if (!el.complete) {
        return {ready:false, reason:'not_complete', src: cand.src, spinning: spinning, spinCount: spinCount, spinDetails: spinDetails, candidates: pool.length, validAbove: validAbove.length, invalidAbove: invalidAbove.length, belowCount: belowCandidates.length, jobFound: jobFound, jobTop: jobTop, prevJobTop: prevJobTop, nextJobTop: nextJobTop, jobIndex: jobIndex, allJobs: allJobs.length, isLarge: cand.isLarge, top: cand.top, jobId: correlationId, orderCheck: `DOM exact above: prev ${prevJobId||'none'} < img < curr ${correlationId} (DOM order), top ${cand.top}`};
      }
      if (el.naturalWidth === 0) {
        return {ready:false, reason:'zero_width', src: cand.src, spinning: spinning, spinCount: spinCount, spinDetails: spinDetails, candidates: pool.length, jobFound: jobFound, jobTop: jobTop, prevJobTop: prevJobTop, isLarge: cand.isLarge};
      }
      if (!cand.visible) continue;
      if (spinning) {
        return {ready:false, reason:'generating_spinner_visible', src: cand.src, spinning: true, spinCount: spinCount, spinDetails: spinDetails, width: cand.width, height: cand.height, rect: cand.rect, jobFound: jobFound, jobTop: jobTop, prevJobTop: prevJobTop, nextJobTop: nextJobTop, jobIndex: jobIndex, allJobs: allJobs.length, validAbove: validAbove.length, invalidAbove: invalidAbove.length, isLarge: cand.isLarge, top: cand.top, orderCheck: `DOM exact above but spinning, await next above if still generating`};
      }
      return {ready:true, src: cand.src, width: cand.width, height: cand.height, spinning: false, rect: cand.rect, selector: cand.selector, jobFound: jobFound, jobTop: jobTop, prevJobTop: prevJobTop, nextJobTop: nextJobTop, jobIndex: jobIndex, allJobs: allJobs.length, validAbove: validAbove.length, invalidAbove: invalidAbove.length, belowCount: belowCandidates.length, isLarge: cand.isLarge, top: cand.top, orderCheck: `DOM exact above verified: prev ${prevJobId||'none'} < img < curr ${correlationId} (DOM order)`};
    }

    if (pool.length > 0) {
      const first = pool[0];
      const reason = !first.visible ? 'hidden' : (!first.complete ? 'not_complete' : 'loading');
      return {ready:false, reason: reason, src: first.src, spinning: spinning, spinCount: spinCount, spinDetails: spinDetails, candidates: pool.length, validAbove: validAbove.length, invalidAbove: invalidAbove.length, jobFound: jobFound, jobTop: jobTop, prevJobTop: prevJobTop};
    }

    if (invalidAbove.length > 0) {
      let invalidDetails = [];
      try { for (const inv of invalidAbove.slice(0,5)) invalidDetails.push({src: inv.src.slice(-60), top: inv.top}); } catch(e) {}
      return {ready:false, reason:'image_above_belongs_to_previous_prompt_await_next', spinning: spinning, spinCount: spinCount, spinDetails: spinDetails, jobFound: jobFound, jobTop: jobTop, prevJobTop: prevJobTop, nextJobTop: nextJobTop, jobIndex: jobIndex, invalidAbove: invalidAbove.length, invalidAboveDetails: invalidDetails, validAbove: 0, allJobs: allJobs.map(j=>({id:j.jobId, top:j.top})), allNew: allNew.length, jobId: correlationId, orderCheck: `DOM no exact above, found ${invalidAbove.length} images before prev ${prevJobId} ${prevJobTop}, awaiting next above current ${correlationId} ${jobTop}`};
    }

    if (allNew.length > 0) {
      let allNewDetails = [];
      try {
        for (const n of allNew.slice(0,10)) {
          allNewDetails.push({src: n.src.slice(-60), top: n.top, isLarge: n.isLarge, width: n.width, selector: n.selector});
        }
      } catch(e) {}
      return {ready:false, reason:'no_exact_above_found_wait_next', spinning: spinning, spinCount: spinCount, spinDetails: spinDetails, jobFound: jobFound, jobTop: jobTop, prevJobTop: prevJobTop, nextJobTop: nextJobTop, jobIndex: jobIndex, allJobs: allJobs.map(j=>({id:j.jobId, top:j.top})), allNew: allNew.length, allNewDetails: allNewDetails, validAbove: 0, invalidAbove: invalidAbove.length, invalidAboveDetails: invalidAbove.slice(0,5).map(i=>({src:i.src.slice(-60), top:i.top})), belowCount: belowCandidates.length, belowDetails: belowCandidates.slice(0,5).map(b=>({src:b.src.slice(-60), top:b.top})), jobId: correlationId, orderCheck: `DOM no exact above: jobTop ${jobTop} prevTop ${prevJobTop} nextTop ${nextJobTop} allNew ${allNew.length} valid 0 invalid ${invalidAbove.length}`};
    }

    if (spinning) {
      return {ready:false, reason:'generating_no_new_yet', spinning: true, spinCount: spinCount, spinDetails: spinDetails, jobFound: jobFound, jobTop: jobTop, prevJobTop: prevJobTop, jobIndex: jobIndex, allJobs: allJobs.length};
    }
    return {ready:false, reason:'no_new', spinning: false, spinCount: 0, jobFound: jobFound, jobTop: jobTop, prevJobTop: prevJobTop, nextJobTop: nextJobTop, jobIndex: jobIndex, allJobs: allJobs.map(j=>({id:j.jobId, top:j.top})), validAbove: validAbove.length, invalidAbove: invalidAbove.length, allNew: allNew.length, jobId: correlationId, orderCheck: `DOM no new images at all, oldSrcs ${oldSrcs.length}`};
  } catch(e) { return {ready:false, reason:String(e), spinning: false}; }
})
"""


JS_VERIFY_ATTACHMENT = """
((expectedFilename) => {
  try {
    const selectors = [
      'div.flex.flex-wrap.gap-2 img[alt]',
      'div.flex.flex-wrap.gap-2 img[src^="blob:"]',
      'div.group.relative.overflow-hidden.rounded-lg.h-16.w-16 img',
      'form img[src^="blob:"]',
      'form img[alt]'
    ];
    for (const sel of selectors) {
      const els = document.querySelectorAll(sel);
      for (const el of els) {
        if (el.offsetParent === null) continue;
        const alt = el.getAttribute('alt') || '';
        const src = el.getAttribute('src') || '';
        if (src.startsWith('blob:')) {
          return {found:true, alt: alt, src: src, matched:'blob'};
        }
        if (expectedFilename && alt && alt.toLowerCase().includes(expectedFilename.toLowerCase())) {
          return {found:true, alt: alt, src: src, matched:'filename'};
        }
        if (alt) {
          return {found:true, alt: alt, src: src, matched:'alt_exists'};
        }
      }
    }
    return {found:false};
  } catch(e) { return {found:false, error:String(e)}; }
})
"""

JS_DOWNLOAD_IMAGE = """
async (src) => {
  // Try multiple strategies: fetch, then canvas toDataURL fallback
  const tryFetch = async (url) => {
    try {
      const res = await fetch(url, {credentials: 'include', mode: 'cors'});
      if (!res.ok) return {ok:false, status:res.status, statusText:res.statusText, method:'fetch'};
      const buf = await res.arrayBuffer();
      const contentType = res.headers.get('content-type') || '';
      // Check if HTML
      const firstBytes = new Uint8Array(buf.slice(0,100));
      const text = new TextDecoder().decode(firstBytes).toLowerCase();
      if (text.includes('<html') || text.includes('<!doctype')) {
        return {ok:false, error:'HTML not image', method:'fetch', contentType: contentType};
      }
      return {ok:true, bytes: Array.from(new Uint8Array(buf)), contentType: contentType, method:'fetch'};
    } catch(e) {
      return {ok:false, error:e.toString(), method:'fetch'};
    }
  };

  const tryCanvas = async (url) => {
    try {
      // Find img element with this src
      let imgEl = null;
      const allImgs = document.querySelectorAll('img');
      for (const im of allImgs) {
        if (im.src === url || im.src.includes(url) || url.includes(im.src)) { imgEl = im; break; }
      }
      if (!imgEl) {
        // Try selector for output
        imgEl = document.querySelector(`img[src="${url}"]`) || document.querySelector(`img[src*="${url.slice(-30)}"]`);
      }
      if (!imgEl) return {ok:false, error:'img element not found for canvas', method:'canvas'};
      // Ensure loaded
      if (!imgEl.complete || imgEl.naturalWidth === 0) {
        await new Promise((resolve, reject) => {
          const timeout = setTimeout(() => reject('timeout waiting for img load'), 5000);
          imgEl.onload = () => { clearTimeout(timeout); resolve(); };
          imgEl.onerror = () => { clearTimeout(timeout); reject('img load error'); };
          if (imgEl.complete) { clearTimeout(timeout); resolve(); }
        });
      }
      const canvas = document.createElement('canvas');
      canvas.width = imgEl.naturalWidth || imgEl.width;
      canvas.height = imgEl.naturalHeight || imgEl.height;
      if (canvas.width === 0 || canvas.height === 0) return {ok:false, error:'zero dimension for canvas', method:'canvas'};
      const ctx = canvas.getContext('2d');
      try {
        ctx.drawImage(imgEl, 0, 0);
      } catch(e) {
        return {ok:false, error:'canvas drawImage failed (CORS tainted?): ' + e.toString(), method:'canvas'};
      }
      // Try to get data
      let dataUrl;
      try {
        dataUrl = canvas.toDataURL('image/png');
      } catch(e) {
        return {ok:false, error:'toDataURL failed (CORS): ' + e.toString(), method:'canvas'};
      }
      // Convert dataUrl to bytes
      const base64 = dataUrl.split(',')[1];
      const binary = atob(base64);
      const bytes = new Uint8Array(binary.length);
      for (let i=0;i<binary.length;i++) bytes[i] = binary.charCodeAt(i);
      return {ok:true, bytes: Array.from(bytes), contentType: 'image/png', method:'canvas', width: canvas.width, height: canvas.height};
    } catch(e) {
      return {ok:false, error:e.toString(), method:'canvas'};
    }
  };

  // Strategy 1: fetch
  let result = await tryFetch(src);
  if (result.ok) return result;

  // Strategy 2: try fetch with no-cors? (will be opaque, can't read, skip)

  // Strategy 3: canvas
  let canvasResult = await tryCanvas(src);
  if (canvasResult.ok) return canvasResult;

  // Return combined error
  return {ok:false, error: `Fetch failed ${JSON.stringify(result)}; Canvas failed ${JSON.stringify(canvasResult)}`, src: src};
}
"""

class CDPArenaController:
    def __init__(self, cdp_client: CDPClient, log_callback: Optional[Callable[[str], None]] = None):
        self.cdp = cdp_client
        self._log_callback = log_callback

    def set_log_callback(self, cb: Callable[[str], None]):
        self._log_callback = cb

    def _log(self, msg: str, level: str = "info"):
        log.info(msg)
        if self._log_callback:
            try:
                self._log_callback(msg)
            except Exception:
                pass

    async def ensure_connected(self) -> bool:
        if self.cdp.is_connected:
            return True
        self._log("CDP not connected — cannot automate", "warn")
        return False

    async def capture_baseline(self) -> Dict[str, Any]:
        js = f";({JS_BASELINE})()"
        result = await self.cdp.evaluate(js)
        if not result:
            return {"output_count": 0, "output_srcs": [], "timestamp": int(time.time()*1000)}
        return result

    async def attach_image(self, image_path: str) -> Tuple[bool, str]:
        if not await self.ensure_connected():
            return False, "Not connected"
        # Use CDP DOM.setFileInputFiles
        ok, reason = await self.cdp.attach_image_cdp(image_path)
        if not ok:
            self._log(f"Attach via CDP failed: {reason}", "warn")
            return False, reason
        self._log(f"Attached {image_path}: {reason}")
        # Wait a bit for preview to appear
        await asyncio.sleep(1)
        # Verify
        verified, vreason = await self.verify_attachment(Path(image_path).name)
        if verified:
            self._log(f"Attachment verified: {vreason}")
            return True, vreason
        else:
            self._log(f"Attachment not yet visible: {vreason}, waiting 2s", "warn")
            await asyncio.sleep(2)
            verified2, vreason2 = await self.verify_attachment(Path(image_path).name)
            return verified2, vreason2

    async def verify_attachment(self, expected_filename: str) -> Tuple[bool, str]:
        js = f";({JS_VERIFY_ATTACHMENT})({json.dumps(expected_filename)})"
        result = await self.cdp.evaluate(js)
        if not result:
            return False, "No result from verify"
        if result.get("found"):
            return True, f"Found via {result.get('matched')} alt={result.get('alt')}"
        return False, f"Preview not found: {result}"

    async def insert_prompt(self, prompt_text: str) -> Tuple[bool, str]:
        if not await self.ensure_connected():
            return False, "Not connected"
        # Highlight textarea before insert if possible
        try:
            await self.highlight_selector('textarea[name="message"]', color="#00AAFF", duration_ms=1000, caption="Prompt input")
        except Exception:
            pass
        # Build JS that calls the function with arg
        js = f";({JS_INSERT_PROMPT})({json.dumps(prompt_text)})"
        result = await self.cdp.evaluate(js)
        if not result:
            return False, "No result"
        if result.get("ok"):
            return True, f"Inserted len {result.get('len')}"
        return False, result.get("error", "Unknown")

    async def verify_prompt(self, expected: str) -> Tuple[bool, str]:
        js = f";({JS_VERIFY_PROMPT})({json.dumps(expected)})"
        result = await self.cdp.evaluate(js)
        if not result:
            return False, "No result"
        if result.get("ok"):
            return True, "Exact match"
        # Provide diff
        actual = result.get("actual", "")
        return False, f"Mismatch actual len {len(actual)} expected len {len(expected)}: {result}"

    async def submit(self) -> Tuple[bool, str]:
        if not await self.ensure_connected():
            return False, "Not connected"
        try:
            await self.highlight_selector('button[aria-label="Send message"]', color="#FFAA00", duration_ms=1000, caption="Send")
        except Exception:
            pass
        js = f";({JS_CLICK_SEND})()"
        result = await self.cdp.evaluate(js)
        if not result:
            return False, "No result"
        if result.get("ok"):
            return True, "Clicked"
        return False, result.get("error", "Failed")

    async def wait_for_new_output(self, baseline: Dict[str, Any], timeout_ms: int = 180000, correlation_id: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
        """Poll for new output, return status. Understands spinner (Response A/B) as generating indicator.
        correlation_id: JOB-ID token to anchor detection — ensures we pick image AFTER user message containing this ID,
        not the reference image above prompt inside same user bubble."""
        old_srcs = baseline.get("output_srcs", []) or []
        start = time.time()
        poll = 2
        seen_spinning = False
        last_log_time = 0
        while (time.time() - start) * 1000 < timeout_ms:
            # Pass correlation_id to JS so it can find user message and pick image after it (fix for matching image above prompt)
            js_check = f";({JS_CHECK_NEW_OUTPUT})({json.dumps(old_srcs)}, {json.dumps(correlation_id) if correlation_id else 'null'})"
            result = await self.cdp.evaluate(js_check)
            if not result:
                await asyncio.sleep(poll)
                continue

            # If spinner visible, we are generating
            if result.get("spinning"):
                if not seen_spinning:
                    self._log(f"⏳ Generation started — spinner visible {result.get('spinDetails')} (Response A/B processing)", "info")
                    seen_spinning = True
                # Log every 10s while generating
                now = time.time()
                if now - last_log_time > 10:
                    self._log(f"⏳ Still generating... spinner {result.get('spinCount')} visible, reason={result.get('reason')} src={result.get('src','')[:60]}", "info")
                    last_log_time = now
                await asyncio.sleep(poll)
                continue

            if result.get("ready"):
                self._log(f"✅ New output ready: {result.get('src','')[:80]} {result.get('width')}x{result.get('height')}", "success")
                return "completed", {"new_src": result.get("src"), "check": result, "baseline": baseline, "rect": result.get("rect")}

            # If we saw spinning before and now no spinning but still no new image, maybe just finished but image not yet in DOM — wait a bit more
            # Enhanced to handle DOM-order exact above cases: no_exact_above_found_wait_next, image_above_belongs_to_previous_prompt_await_next, etc.
            if seen_spinning and not result.get("spinning"):
                reason = result.get("reason") or ""
                if reason in ("no_new", "no_exact_above_found_wait_next", "image_above_belongs_to_previous_prompt_await_next", "not_complete", "zero_width", "hidden", "loading", "generating_no_new_yet"):
                    self._log(f"Spinner disappeared but no new image yet — reason={reason} waiting... orderCheck={result.get('orderCheck','')[:200]} allNew={result.get('allNew')} validAbove={result.get('validAbove')} jobFound={result.get('jobFound')}", "info")
                    await asyncio.sleep(poll)
                    continue
                # Also if ready false but allNew exists, keep waiting a bit
                if result.get("allNew") and result.get("allNew") > 0 and not result.get("ready"):
                    self._log(f"Spinner gone but allNew={result.get('allNew')} not ready reason={reason} — waiting for exact above image to appear... {result.get('orderCheck','')[:200]}", "info")
                    await asyncio.sleep(poll)
                    continue

            # Log orderCheck periodically even when not spinning, to help debug exact above
            now = time.time()
            if now - last_log_time > 10:
                self._log(f"⏳ Waiting... reason={result.get('reason')} spinning={result.get('spinning')} allNew={result.get('allNew')} validAbove={result.get('validAbove')} invalidAbove={result.get('invalidAbove')} jobFound={result.get('jobFound')} orderCheck={result.get('orderCheck','')[:250]}", "info")
                last_log_time = now

            await asyncio.sleep(poll)

        final_baseline = await self.capture_baseline()
        return "failed", {"error": f"Timeout after {timeout_ms}ms, last spinning seen={seen_spinning}", "last_baseline": final_baseline, "last_check": result if 'result' in locals() else None}

    async def _python_download(self, src: str) -> Tuple[bool, bytes, str]:
        """Fallback: download directly via Python (bypasses CORS/fetch canvas taint).
        R2 presigned URLs are accessible anonymously — fetch from page context fails due to CORS,
        but Python urllib succeeds. Runs blocking IO in executor to avoid blocking event loop."""
        def sync_fetch(url: str):
            import urllib.request
            import ssl
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
            req = urllib.request.Request(url, headers=headers)
            ctx = ssl.create_default_context()
            try:
                with urllib.request.urlopen(req, timeout=45, context=ctx) as resp:
                    data = resp.read()
                    raw_ctype = resp.headers.get("Content-Type", "") or ""
                    return data, raw_ctype, getattr(resp, 'status', 200)
            except Exception:
                with urllib.request.urlopen(req, timeout=45) as resp2:
                    data = resp2.read()
                    ctype = resp2.headers.get("Content-Type", "") if hasattr(resp2.headers, 'get') else ""
                    return data, ctype, 200

        loop = asyncio.get_event_loop()
        try:
            data, ctype, status = await loop.run_in_executor(None, lambda: sync_fetch(src))
            if not data or len(data) < 100:
                return False, b"", f"Python download too small {len(data)} status {status} ctype {ctype}"
            low = data[:200].lower()
            if b"<html" in low or b"<!doctype" in low:
                txt = data[:500].decode(errors="ignore")
                if "NoSuchKey" in txt or "AccessDenied" in txt or "ExpiredToken" in txt:
                    return False, b"", f"Python download got error page: {txt[:200]}"
                return False, b"", f"Python download returned HTML not image (len {len(data)})"
            self._log(f"Python direct download succeeded: {len(data)} bytes {ctype} from {src[:80]}...", "success")
            return True, data, ctype
        except Exception as e:
            self._log(f"Python download failed for {src[:80]}: {e}", "warn")
            return False, b"", f"Python download failed: {e}"

    async def download_image(self, src: str) -> Tuple[bool, bytes, str]:
        # Strategy 1: JS fetch + canvas (fast, works for blob: and same-origin)
        js = f";({JS_DOWNLOAD_IMAGE})({json.dumps(src)})"
        try:
            result = await self.cdp.evaluate(js)
            if result and result.get("ok"):
                byte_list = result.get("bytes", [])
                data = bytes(byte_list)
                if b"<html" not in data[:100].lower() and len(data) > 100:
                    return True, data, result.get("contentType", "") or ""
                else:
                    self._log(f"JS download returned HTML or small ({len(data)}), trying Python fallback", "warn")
            else:
                err = result.get("error") if result else "No result"
                err_str = err[:200] if isinstance(err, str) else str(err)[:200]
                self._log(f"JS download failed: {err_str} — trying Python direct", "warn")
        except Exception as e:
            self._log(f"JS download exception: {e} — trying Python direct", "warn")

        # Strategy 2: Python direct download (bypasses CORS, canvas taint) — essential for R2 presigned URLs
        ok, data, ctype = await self._python_download(src)
        if ok:
            return True, data, ctype

        # Strategy 3: canvas retry with crossOrigin anonymous (last resort)
        try:
            js_retry = (
                "(async (src) => {"
                " try {"
                " const img = new Image();"
                " img.crossOrigin = 'anonymous';"
                " img.src = src;"
                " await new Promise((res, rej) => {"
                " img.onload = res;"
                " img.onerror = () => rej('load error');"
                " setTimeout(() => rej('timeout'), 10000);"
                " });"
                " const c = document.createElement('canvas');"
                " c.width = img.naturalWidth; c.height = img.naturalHeight;"
                " const ctx = c.getContext('2d');"
                " ctx.drawImage(img, 0, 0);"
                " const dataUrl = c.toDataURL('image/png');"
                " const base64 = dataUrl.split(',')[1];"
                " const bin = atob(base64);"
                " const bytes = new Uint8Array(bin.length);"
                " for(let i=0;i<bin.length;i++) bytes[i]=bin.charCodeAt(i);"
                " return {ok:true, bytes: Array.from(bytes), contentType:'image/png', method:'canvas_retry'};"
                " } catch(e) { return {ok:false, error:String(e), method:'canvas_retry'}; }"
                "})(" + json.dumps(src) + ")"
            )
            result2 = await self.cdp.evaluate(f";{js_retry}")
            if result2 and result2.get("ok"):
                byte_list = result2.get("bytes", [])
                data = bytes(byte_list)
                if len(data) > 100:
                    return True, data, result2.get("contentType", "")
        except Exception as e:
            self._log(f"Canvas retry failed: {e}", "warn")

        return False, b"", f"All download methods failed: JS fetch/canvas failed (CORS tainted), Python direct failed, canvas retry failed for src={src[:120]}"

    def report(self, message: str, level: str = "info"):
        # For visual_click engine compatibility (engine.report)
        self._log(message, level)

    async def highlight_selector(self, selector: str, color: str = "#FF0000", duration_ms: int = 2000, caption: str = "") -> dict | None:
        try:
            from .dom_highlight import build_highlight_js, build_highlight_probe
            from .probe_requests import HighlightSpec
            import json as _json
            # Use new probe that returns rect
            spec = HighlightSpec(color=color, caption=caption or selector[:40], highlight_ms=duration_ms, clear_first=True)
            # Prefer build_highlight_probe for rect
            from .dom_highlight import build_highlight_probe
            js = build_highlight_probe(selector, spec)
            raw = await self.cdp.evaluate(js)
            if raw:
                try:
                    data = _json.loads(raw) if isinstance(raw, str) else raw
                    if isinstance(data, dict) and data.get("rect"):
                        return data.get("rect")
                    if isinstance(data, dict) and data.get("found"):
                        return data.get("rect") or {"x":0,"y":0,"width":100,"height":100}
                except Exception:
                    pass
            # fallback to old build_highlight_js
            js2 = build_highlight_js(selector, color, duration_ms, caption, clear_first=True)
            raw2 = await self.cdp.evaluate(js2)
            if raw2:
                try:
                    data2 = _json.loads(raw2) if isinstance(raw2, str) else raw2
                    if isinstance(data2, dict) and data2.get("rect"):
                        return data2.get("rect")
                except Exception:
                    pass
            return {"x":100,"y":100,"width":200,"height":100}
        except Exception as e:
            log.debug(f"highlight_selector failed: {e}")
            return None

    async def clear_highlights(self):
        try:
            from .dom_highlight import build_clear_js
            js = build_clear_js()
            await self.cdp.evaluate(js)
        except Exception as e:
            log.debug(f"clear_highlights failed: {e}")

    async def show_watcher_overlay(self, message: str = "wait for finish generation", kind: str = "generation") -> bool:
        """Show watcher overlay rectangle on left center page with message.
        kind: 'generation' or 'captcha' — different colors.
        Used by watcher window that passively rechecks every x ms.
        """
        try:
            from .dom_highlight import build_watcher_overlay_js
            js = build_watcher_overlay_js(message=message, kind=kind)
            raw = await self.cdp.evaluate(js)
            if raw:
                try:
                    import json as _json
                    data = _json.loads(raw) if isinstance(raw, str) else raw
                    return bool(data.get("shown")) if isinstance(data, dict) else True
                except Exception:
                    return True
            return False
        except Exception as e:
            log.debug(f"show_watcher_overlay failed: {e}")
            return False

    async def hide_watcher_overlay(self) -> bool:
        """Hide watcher overlay rectangle."""
        try:
            from .dom_highlight import build_watcher_clear_js
            js = build_watcher_clear_js()
            await self.cdp.evaluate(js)
            return True
        except Exception as e:
            log.debug(f"hide_watcher_overlay failed: {e}")
            return False

    async def is_page_ready(self) -> Tuple[bool, List[str]]:
        """Check readiness via JS."""
        js = """
        ;(() => {
          const reasons = [];
          const checks = [
            {sel: 'textarea[name="message"]', name: 'prompt_textarea'},
            {sel: 'button[aria-label="Send message"]', name: 'send_button'},
            {sel: 'input[type="file"]', name: 'file_input'},
            {sel: 'div.no-scrollbar', name: 'output_region'}
          ];
          for (const c of checks) {
            const el = document.querySelector(c.sel);
            if (!el) reasons.push(c.name + ' not found');
            else if (el.offsetParent === null) reasons.push(c.name + ' not visible');
          }
          // security dialog
          const dialogs = document.querySelectorAll('div[role="dialog"][data-state="open"]');
          for (const d of dialogs) {
            if (d.innerText && d.innerText.includes('Security Verification')) reasons.push('Security dialog visible');
          }
          return {ready: reasons.length===0, reasons: reasons};
        })()
        """
        result = await self.cdp.evaluate(js)
        if not result:
            return False, ["No result from readiness check"]
        return bool(result.get("ready")), result.get("reasons", [])

    async def is_security_dialog_visible(self) -> bool:
        js = """
        ;(() => {
          const dialogs = document.querySelectorAll('div[role="dialog"][data-state="open"]');
          for (const d of dialogs) {
            if (d.innerText && d.innerText.includes('Security Verification')) return true;
            if (d.querySelector('iframe[title="reCAPTCHA"]')) return true;
          }
          const iframes = document.querySelectorAll('iframe[title="reCAPTCHA"]');
          for (const f of iframes) {
            const style = window.getComputedStyle(f);
            if (style.display !== 'none' && f.offsetParent !== null) return true;
          }
          return false;
        })()
        """
        result = await self.cdp.evaluate(js)
        return bool(result)

    async def is_generating(self) -> Tuple[bool, Dict[str, Any]]:
        """Check if generation is still in progress — spinner visible means job running.
        Returns (is_generating, details). Used to decide if download should return to waiting state."""
        js = """
        ;(() => {
          let spinning = false;
          let spinCount = 0;
          let details = [];
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
                details.push({label: label || 'unknown'});
              }
            }
          } catch(e) {}
          // Also check for Processing/Generating text visible
          let processingText = false;
          try {
            const all = document.body.innerText || '';
            if (all.includes('Processing') || all.includes('Generating')) {
              // Check if near spinner region
              const procEls = document.querySelectorAll('div, span');
              for (const el of procEls) {
                const txt = (el.textContent || '').trim();
                if ((txt === 'Processing' || txt === 'Generating' || txt.includes('Processing') || txt.includes('Generating')) && el.offsetParent !== null) {
                  // Small element, likely indicator
                  if (txt.length < 30) { processingText = true; break; }
                }
              }
            }
          } catch(e) {}
          return {spinning: spinning, spinCount: spinCount, processingText: processingText, details: details, isGenerating: spinning || processingText};
        })()
        """
        try:
            result = await self.cdp.evaluate(js)
            if not result:
                return False, {}
            is_gen = bool(result.get("isGenerating") or result.get("spinning"))
            return is_gen, result
        except Exception as e:
            log.debug(f"is_generating check failed: {e}")
            return False, {"error": str(e)}

    async def get_generation_state(self, correlation_id: Optional[str] = None) -> Dict[str, Any]:
        """Detailed generation state: spinning, ready, output count."""
        old_srcs = []  # we want current state regardless
        js_check = f";({JS_CHECK_NEW_OUTPUT})({json.dumps(old_srcs)}, {json.dumps(correlation_id) if correlation_id else 'null'})"
        try:
            result = await self.cdp.evaluate(js_check)
            return result or {}
        except Exception as e:
            return {"error": str(e), "spinning": False}

    async def reload_page(self) -> Tuple[bool, str]:
        """Reload page via CDP Page.reload — used after 2 min wait timeout as retry, not failure.
        User requested: after 2 min try to reload page first but not failed yet as unsuccess, because chance bad cache."""
        try:
            self._log("🔄 Reloading page after wait timeout (cache may be bad) — will retry waiting", "warn")
            # Try CDP Page.reload
            try:
                await self.cdp.send("Page.reload", {}, timeout=15)
            except Exception as e:
                # Fallback to location.reload via JS
                self._log(f"Page.reload via CDP failed {e}, trying location.reload()", "warn")
                try:
                    await self.cdp.evaluate("window.location.reload(); true")
                except Exception as e2:
                    return False, f"Both reload methods failed: {e} / {e2}"
            # Wait for page to load
            await asyncio.sleep(4)
            # Wait up to 10s for ready
            for i in range(10):
                ready, reasons = await self.is_page_ready()
                if ready:
                    self._log(f"✅ Page reloaded and ready after {i+1}s", "success")
                    return True, "Reloaded and ready"
                await asyncio.sleep(1)
            # Even if not fully ready, return true — let waiting logic handle
            self._log("⚠ Page reloaded but not fully ready yet, continuing anyway", "warn")
            return True, "Reloaded but not fully ready"
        except Exception as e:
            self._log(f"Reload page failed: {e}", "error")
            return False, str(e)
