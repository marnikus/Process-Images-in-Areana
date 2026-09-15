"""Output probes — JS builders for baseline and new-output check.

Owns: JS payloads for output detection v4 (turn-container reference
exclusion, no direction flip, below-pairing, fallback details). Python
wrappers stay tiny; JS length is exempt per RULE 16.1.5. No Qt imports.

v4 (2026-09-16): v3's document-wide flex-col-reverse flip always fired
(the message list itself is ol.flex-col-reverse) and the above-pool
downloaded the reference preview. v4 pairs DOM-after-prompt and excludes
references structurally. See docs/archive/2026-09-16-wrong-image-downloaded/.
"""

# ideal-size: 360 lines reason=single JS payload for output check v4;
# splitting the in-page probe literal would break CDP evaluate contract.

from __future__ import annotations

import json

JS_BASELINE_V3 = r"""
(() => {
  try {
    const outputs = [];
    const selectors = [
      'div.no-scrollbar img[src*=".r2.cloudflarestorage.com/"]',
      'div.no-scrollbar img[src*="messages-prod."]',
      'div.no-scrollbar img[loading="lazy"].aspect-square',
      'img.aspect-square.cursor-pointer',
      'main img[src*=".r2.cloudflarestorage.com/"]',
      'img[src*=".r2.cloudflarestorage.com/"]'
    ];
    for (const sel of selectors) {
      try {
        const els = document.querySelectorAll(sel);
        for (const el of els) {
          if (!el.src) continue;
          if (el.src.startsWith('blob:')) continue;
          if (el.src.startsWith('data:')) continue;
          if (el.naturalWidth && el.naturalWidth < 50
              && el.naturalHeight && el.naturalHeight < 50) continue;
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
    return {output_count:0, output_srcs:[],
      error:String(e), timestamp:Date.now(), spinning:false};
  }
})
"""

JS_CHECK_NEW_OUTPUT_V4 = r"""
((oldKeys, correlationId) => {
  try {
    function normKey(src) {
      try {
        const base = String(src).split('?')[0].split('#')[0];
        return base.slice(-120);
      } catch(e) { return String(src).slice(-120); }
    }
    function isBefore(a, b) {
      try {
        if (!a || !b || a === b) return false;
        if (a.contains(b) || b.contains(a)) return false;
        return !!(a.compareDocumentPosition(b)
          & Node.DOCUMENT_POSITION_FOLLOWING);
      } catch(e) { return false; }
    }
    function findJobContainer(el, jobId) {
      let cur = el;
      for (let i = 0; i < 8 && cur; i++) {
        const tag = cur.tagName || '';
        if (tag === 'BODY' || tag === 'HTML') break;
        if (cur.classList && cur.classList.contains('no-scrollbar')) break;
        try {
          const r = cur.getBoundingClientRect();
          const hOk = r.height > 30
            && r.height < window.innerHeight * 0.9;
          const wOk = r.width < window.innerWidth * 0.95;
          const hasImg = !!cur.querySelector('img');
          const hasFlex = cur.classList
            && (cur.classList.contains('flex')
              || cur.classList.contains('group'));
          const hasJob = (cur.textContent || '').includes(jobId);
          if (hOk && wOk && hasJob && (hasImg || hasFlex)) return cur;
        } catch(e) {}
        cur = cur.parentElement;
      }
      try {
        return el.closest('div.group, div.flex.flex-col, div[data-message-id]')
          || el;
      } catch(e) { return el; }
    }
    function isLarge(rect, naturalW, cls) {
      const w = naturalW || rect.width || 0;
      if (w >= 200 || rect.width >= 200) return true;
      if ((cls || '').includes('50vh')) return true;
      if ((cls || '').includes('object-cover') && rect.width >= 100)
        return true;
      return (cls || '').includes('aspect-square') && rect.width >= 150;
    }
    function isSmallThumb(rect, cls) {
      if (rect.width && rect.width <= 140) return true;
      const c = cls || '';
      return c.includes('w-32') || c.includes('h-16')
        || c.includes('w-16');
    }
    function smallBox(r) {
      try {
        return r.height < window.innerHeight * 0.9
          && r.width < window.innerWidth * 0.95;
      } catch(e) { return false; }
    }
    function sharesTurnWithJob(img, jobs) {
      // Reference previews live in the same turn container as their
      // prompt (div.flex.flex-col.gap-4 holding BOTH the w-32 img AND
      // the JOB-ID bubble). Generated output lives in its own
      // assistant turn, so no small ancestor is ever shared with the
      // prompt. Direction-independent (v4, 2026-09-16).
      let cur = null;
      try { cur = img.parentElement; } catch(e) { return false; }
      for (let i = 0; i < 8 && cur; i++) {
        const tag = cur.tagName || '';
        if (tag === 'BODY' || tag === 'HTML') break;
        try {
          if (smallBox(cur.getBoundingClientRect())) {
            for (const j of jobs) {
              if (j.el && cur.contains(j.el)) return true;
            }
          }
        } catch(e) {}
        cur = cur.parentElement;
      }
      return false;
    }

    let spinning = false;
    let spinCount = 0;
    let spinDetails = [];
    try {
      const spinners = document.querySelectorAll('div.animate-spin');
      for (const s of spinners) {
        if (s.offsetParent !== null) {
          spinning = true;
          spinCount++;
          let label = 'unknown';
          try {
            const p = s.closest('div.flex.min-w-0.flex-1.items-center.gap-2');
            const t = p ? p.querySelector('span.truncate') : null;
            if (t) label = t.textContent.trim() || 'unknown';
          } catch(e) {}
          spinDetails.push({label: label, visible: true});
        }
      }
    } catch(e) {}

    let allJobs = [];
    try {
      const re = /\[JOB-ID:\s*([^\]\s]+)\]/g;
      const walker = document.createTreeWalker(
        document.body, NodeFilter.SHOW_TEXT);
      const seen = new Set();
      let node;
      while ((node = walker.nextNode())) {
        const val = node.nodeValue || '';
        if (!val.includes('JOB-ID')) continue;
        re.lastIndex = 0;
        let m;
        while ((m = re.exec(val)) !== null) {
          const jobId = m[1];
          if (!jobId || jobId.length < 3 || seen.has(jobId)) continue;
          const parent = node.parentElement;
          if (!parent) continue;
          if (parent.tagName === 'TEXTAREA'
            || parent.tagName === 'SCRIPT'
            || parent.tagName === 'STYLE') continue;
          const container = findJobContainer(parent, jobId);
          seen.add(jobId);
          try {
            const r = (container || parent).getBoundingClientRect();
            allJobs.push({jobId: jobId, el: parent,
              container: container || parent,
              top: r.top, left: r.left,
              width: r.width, height: r.height});
          } catch(e) {}
        }
      }
      allJobs.sort((a, b) => {
        try {
          const pos = a.el.compareDocumentPosition(b.el);
          if (pos & Node.DOCUMENT_POSITION_FOLLOWING) return -1;
          if (pos & Node.DOCUMENT_POSITION_PRECEDING) return 1;
        } catch(e) {}
        return a.top - b.top;
      });
    } catch(e) {}

    let jobEl = null;
    let jobContainer = null;
    let jobTop = null;
    let jobFound = false;
    let jobIndex = -1;
    let prevEl = null;
    let nextEl = null;
    let prevTop = null;
    let nextTop = null;
    let prevId = null;
    let nextId = null;
    if (correlationId) {
      for (let i = 0; i < allJobs.length; i++) {
        if (allJobs[i].jobId === correlationId) {
          jobEl = allJobs[i].el;
          jobContainer = allJobs[i].container;
          jobTop = allJobs[i].top;
          jobFound = true;
          jobIndex = i;
          if (i > 0) {
            prevEl = allJobs[i-1].el;
            prevTop = allJobs[i-1].top;
            prevId = allJobs[i-1].jobId;
          }
          if (i < allJobs.length - 1) {
            nextEl = allJobs[i+1].el;
            nextTop = allJobs[i+1].top;
            nextId = allJobs[i+1].jobId;
          }
          break;
        }
      }
    }

    const oldSet = new Set((oldKeys || []).map(k => String(k).slice(-120)));
    let allNew = [];
    let validAbove = [];
    let validBelow = [];
    let invalidAbove = [];
    let belowCands = [];
    let debugAll = [];
    let debugFilt = [];

    function insideAnyJob(img) {
      for (const j of allJobs) {
        try {
          if (j.container && j.container.contains(img)) return true;
        } catch(e) {}
      }
      return false;
    }
    function hasIntervBefore(img) {
      for (const j of allJobs) {
        if (j.jobId === correlationId) continue;
        if (isBefore(img, j.el) && isBefore(j.el, jobEl)) return true;
      }
      return false;
    }
    function hasIntervAfter(img) {
      for (const j of allJobs) {
        if (j.jobId === correlationId) continue;
        if (isBefore(jobEl, j.el) && isBefore(j.el, img)) return true;
      }
      return false;
    }

    try {
      const imgs = document.querySelectorAll('img');
      for (const im of imgs) {
        if (!im.src) continue;
        try {
          const r0 = im.getBoundingClientRect();
          debugAll.push({
            src: im.src.slice(-80),
            cls: (im.className || '').slice(0, 80),
            w: im.naturalWidth || Math.round(r0.width),
            h: im.naturalHeight || Math.round(r0.height),
            visible: im.offsetParent !== null,
            complete: im.complete,
            inOld: oldSet.has(normKey(im.src)),
            top: Math.round(r0.top),
            isBlob: im.src.startsWith('blob:')
          });
        } catch(e) {}
      }
    } catch(e) {}

    const outSels = [
      'div.no-scrollbar img[src*=".r2.cloudflarestorage.com/"]',
      'div.no-scrollbar img[src*="messages-prod."]',
      'main img[src*=".r2.cloudflarestorage.com/"]',
      'img[src*=".r2.cloudflarestorage.com/"]',
      'div.no-scrollbar img.aspect-square',
      'main img.aspect-square',
      'img.aspect-square.cursor-pointer'
    ];
    const seenSrc = new Set();
    for (const sel of outSels) {
      let els = [];
      try { els = document.querySelectorAll(sel); } catch(e) { continue; }
      for (const el of els) {
        if (!el.src || seenSrc.has(el.src)) continue;
        seenSrc.add(el.src);
        if (el.src.startsWith('blob:')) {
          debugFilt.push({reason: 'blob', src: el.src.slice(-40)});
          continue;
        }
        if (el.src.startsWith('data:')) {
          debugFilt.push({reason: 'data', src: el.src.slice(-40)});
          continue;
        }
        if (el.src.indexOf('r2.cloudflarestorage.com') < 0
            && el.src.indexOf('messages-prod.') < 0) {
          debugFilt.push({reason: 'non_r2', src: el.src.slice(-40)});
          continue;
        }
        if (oldSet.has(normKey(el.src))) {
          debugFilt.push({reason: 'in_old', src: el.src.slice(-40)});
          continue;
        }
        if (el.naturalWidth && el.naturalWidth < 50
          && el.naturalHeight && el.naturalHeight < 50) {
          debugFilt.push({reason: 'tiny', src: el.src.slice(-40)});
          continue;
        }
        const rect = el.getBoundingClientRect();
        const cls = el.className || '';
        const large = isLarge(rect, el.naturalWidth, cls);
        const inside = insideAnyJob(el);
        let inGrid = false;
        try { inGrid = !!el.closest('div.no-scrollbar'); } catch(e) {}
        const isRef = sharesTurnWithJob(el, allJobs)
          || isSmallThumb(rect, cls);
        if (isRef) {
          debugFilt.push({reason: 'reference',
            src: el.src.slice(-40), cls: cls.slice(0, 40)});
        }
        const info = {
          el: el, src: el.src, key: normKey(el.src),
          rect: {x: rect.left, y: rect.top,
            width: rect.width, height: rect.height},
          width: el.naturalWidth || rect.width || 0,
          height: el.naturalHeight || rect.height || 0,
          visible: el.offsetParent !== null,
          complete: el.complete,
          naturalWidth: el.naturalWidth,
          selector: sel, isLarge: large,
          insideJob: inside, isRef: isRef, inGrid: inGrid,
          top: rect.top, left: rect.left
        };
        allNew.push(info);
        if (info.isRef) continue;
        if (jobFound && jobEl) {
          const beforeCurr = isBefore(el, jobEl);
          const afterCurr = isBefore(jobEl, el);
          const afterPrev = prevEl ? isBefore(prevEl, el) : true;
          const beforePrev = prevEl ? isBefore(el, prevEl) : false;
          const beforeNext = nextEl ? isBefore(el, nextEl) : true;
          if (beforeCurr && afterPrev && !hasIntervBefore(el)) {
            validAbove.push(info);
          } else if (afterCurr && beforeNext && !hasIntervAfter(el)) {
            validBelow.push(info);
          } else if (beforeCurr && beforePrev) {
            invalidAbove.push(info);
          } else if (!beforeCurr) {
            belowCands.push(info);
          } else {
            invalidAbove.push(info);
          }
        } else {
          validAbove.push(info);
        }
      }
    }

    // v4: NO direction flip. The message list itself is
    // ol.flex-col-reverse, so a document-wide "is reversed?" check is
    // always true — v3's above-pool then downloaded the reference
    // preview (2026-09-16). DOM order pairs each prompt with its
    // output (output is DOM-after its prompt); references are excluded
    // structurally, never by direction.
    let pool = [];
    let poolKind = 'none';
    if (!jobFound) {
      const cands = validAbove.filter(n => !n.isRef);
      if (cands.length > 0) {
        cands.sort((a, b) => {
          if (Math.abs(a.top - b.top) > 5) return b.top - a.top;
          const aw = (a.rect && a.rect.width) || 0;
          const bw = (b.rect && b.rect.width) || 0;
          return bw - aw;
        });
        pool = cands;
        poolKind = 'nofilter';
      }
    } else {
      for (const a of validAbove) invalidAbove.push(a);
      validAbove = [];
      const below = validBelow.filter(n => !n.isRef);
      if (below.length > 0) {
        below.sort((a, b) => {
          const ag = a.inGrid ? 1 : 0;
          const bg = b.inGrid ? 1 : 0;
          if (bg !== ag) return bg - ag;
          try {
            const pos = a.el.compareDocumentPosition(b.el);
            if (pos & Node.DOCUMENT_POSITION_FOLLOWING) return -1;
            if (pos & Node.DOCUMENT_POSITION_PRECEDING) return 1;
          } catch(e) {}
          return a.top - b.top;
        });
        pool = below;
        poolKind = 'below';
      }
    }
    const largePool = pool.filter(c => c.isLarge);
    if (largePool.length > 0) pool = largePool;

    function orderText() {
      if (poolKind === 'below') {
        return 'below verified: curr ' + correlationId
          + ' < img < next ' + (nextId || 'none') + ' (DOM order)';
      }
      return poolKind + ' verified: prev ' + (prevId || 'none')
        + ' < img < curr ' + correlationId + ' (DOM order)';
    }

    for (const cand of pool) {
      const el = cand.el;
      if (!el.complete) {
        try { el.scrollIntoView({block: 'nearest'}); } catch(e) {}
        return {ready: false, reason: 'not_complete',
          src: cand.src, spinning: spinning, spinCount: spinCount,
          spinDetails: spinDetails, candidates: pool.length,
          validAbove: validAbove.length, validBelow: validBelow.length,
          invalidAbove: invalidAbove.length,
          belowCount: belowCands.length,
          jobFound: jobFound, jobTop: jobTop,
          prevJobTop: prevTop, nextJobTop: nextTop,
          jobIndex: jobIndex, allJobs: allJobs.length,
          isLarge: cand.isLarge, top: cand.top,
          poolKind: poolKind, jobId: correlationId,
          orderCheck: poolKind + ' candidate loading, scrolled'};
      }
      if (el.naturalWidth === 0) {
        try { el.scrollIntoView({block: 'nearest'}); } catch(e) {}
        return {ready: false, reason: 'zero_width',
          src: cand.src, spinning: spinning,
          spinCount: spinCount, spinDetails: spinDetails,
          candidates: pool.length, jobFound: jobFound,
          jobTop: jobTop, prevJobTop: prevTop,
          poolKind: poolKind};
      }
      if (!cand.visible) continue;
      if (spinning) {
        return {ready: false, reason: 'generating_spinner_visible',
          src: cand.src, spinning: true,
          spinCount: spinCount, spinDetails: spinDetails,
          width: cand.width, height: cand.height,
          rect: cand.rect, jobFound: jobFound,
          jobTop: jobTop, prevJobTop: prevTop,
          nextJobTop: nextTop, jobIndex: jobIndex,
          allJobs: allJobs.length,
          validAbove: validAbove.length,
          validBelow: validBelow.length,
          isLarge: cand.isLarge, top: cand.top,
          poolKind: poolKind,
          orderCheck: poolKind + ' verified but spinning, await'};
      }
      return {ready: true, src: cand.src,
        width: cand.width, height: cand.height,
        spinning: false, rect: cand.rect,
        selector: cand.selector, jobFound: jobFound,
        jobTop: jobTop, prevJobTop: prevTop,
        nextJobTop: nextTop, jobIndex: jobIndex,
        allJobs: allJobs.length,
        validAbove: validAbove.length,
        validBelow: validBelow.length,
        invalidAbove: invalidAbove.length,
        belowCount: belowCands.length,
        isLarge: cand.isLarge, top: cand.top,
        poolKind: poolKind,
        orderCheck: orderText()};
    }

    if (pool.length > 0) {
      const first = pool[0];
      const reason = !first.visible ? 'hidden'
        : (!first.complete ? 'not_complete' : 'loading');
      return {ready: false, reason: reason,
        src: first.src, spinning: spinning,
        spinCount: spinCount, spinDetails: spinDetails,
        candidates: pool.length,
        validAbove: validAbove.length,
        validBelow: validBelow.length,
        jobFound: jobFound, jobTop: jobTop,
        prevJobTop: prevTop, poolKind: poolKind};
    }
    if (invalidAbove.length > 0) {
      return {ready: false,
        reason: 'image_above_belongs_to_previous_prompt_await_next',
        spinning: spinning, spinCount: spinCount,
        spinDetails: spinDetails, jobFound: jobFound,
        jobTop: jobTop, prevJobTop: prevTop,
        nextJobTop: nextTop, jobIndex: jobIndex,
        invalidAbove: invalidAbove.length,
        validAbove: 0, validBelow: validBelow.length,
        allJobs: allJobs.map(j => ({id: j.jobId, top: j.top})),
        allNew: allNew.length, jobId: correlationId,
        poolKind: poolKind,
        orderCheck: 'no exact ' + poolKind
          + ', found ' + invalidAbove.length
          + ' before prev ' + prevId};
    }
    if (allNew.length > 0) {
      const fbPool = jobFound ? belowCands : allNew;
      return {ready: false, reason: 'no_exact_above_found_wait_next',
        spinning: spinning, spinCount: spinCount,
        spinDetails: spinDetails, jobFound: jobFound,
        jobTop: jobTop, prevJobTop: prevTop,
        nextJobTop: nextTop, jobIndex: jobIndex,
        allJobs: allJobs.map(j => ({id: j.jobId, top: j.top})),
        allNew: allNew.length,
        allNewDetails: allNew.slice(0, 10).map(n => ({
          src: n.src, top: n.top,
          isLarge: n.isLarge, width: n.width,
          selector: n.selector, rect: n.rect,
          isReference: !!n.isRef, inGrid: !!n.inGrid})),
        fallbackDetails: fbPool.filter(n => !n.isRef)
          .slice(0, 10).map(n => ({
            src: n.src, top: n.top,
            isLarge: n.isLarge, width: n.width,
            selector: n.selector, rect: n.rect,
            isReference: false, inGrid: !!n.inGrid})),
        validAbove: 0, validBelow: validBelow.length,
        invalidAbove: invalidAbove.length,
        belowCount: belowCands.length,
        belowDetails: belowCands.slice(0, 5).map(b => ({
          src: b.src.slice(-60), top: b.top})),
        jobId: correlationId, poolKind: poolKind,
        orderCheck: 'no exact: jobTop ' + jobTop
          + ' prevTop ' + prevTop + ' allNew ' + allNew.length,
        debugAllImgs: debugAll.slice(0, 15),
        debugFiltered: debugFilt.slice(0, 15),
        oldKeysSample: (oldKeys || []).slice(0, 3)};
    }
    if (spinning) {
      return {ready: false, reason: 'generating_no_new_yet',
        spinning: true, spinCount: spinCount,
        spinDetails: spinDetails, jobFound: jobFound,
        jobTop: jobTop, prevJobTop: prevTop,
        jobIndex: jobIndex, allJobs: allJobs.length,
        poolKind: poolKind};
    }
    return {ready: false, reason: 'no_new', spinning: false,
      spinCount: 0, jobFound: jobFound, jobTop: jobTop,
      prevJobTop: prevTop, nextJobTop: nextTop,
      jobIndex: jobIndex,
      allJobs: allJobs.map(j => ({id: j.jobId, top: j.top})),
      validAbove: validAbove.length,
      validBelow: validBelow.length,
      invalidAbove: invalidAbove.length,
      allNew: allNew.length, jobId: correlationId,
      poolKind: poolKind,
      orderCheck: 'no new images, oldKeys ' + (oldKeys || []).length,
      debugAllImgs: debugAll.slice(0, 20),
      debugFiltered: debugFilt.slice(0, 20),
      oldKeysSample: (oldKeys || []).slice(0, 3)};
  } catch(e) {
    return {ready: false, reason: String(e), spinning: false};
  }
})
"""

JS_SCROLL_BOTTOM = r"""
(() => {
  try {
    const sc = document.querySelector('div.no-scrollbar')
      || document.querySelector('main');
    if (sc) sc.scrollTop = sc.scrollHeight;
    return {ok: true};
  } catch(e) { return {ok: false, error: String(e)}; }
})
"""


def build_baseline_js() -> str:
    """Return baseline capture expression for CDP evaluate."""
    return f";({JS_BASELINE_V3})()"


def build_check_js(old_keys: list, correlation_id: str | None) -> str:
    """Return new-output check expression with normalized keys."""
    keys_json = json.dumps(list(old_keys or []))
    corr_json = json.dumps(correlation_id) if correlation_id else "null"
    return f";({JS_CHECK_NEW_OUTPUT_V4})({keys_json}, {corr_json})"


def build_scroll_bottom_js() -> str:
    """Return scroll-to-bottom expression to trigger lazy load."""
    return f";({JS_SCROLL_BOTTOM})()"
