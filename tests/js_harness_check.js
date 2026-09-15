/* JS harness for output check v4 — runs real probe against DOM stub.
 * Usage: node tests/js_harness_check.js <probe_file> (probe exports raw JS fn)
 * Probe file contains JS expression ((oldKeys, correlationId) => {...}).
 * Defines minimal document/window/Node/NodeFilter, then 7 cases.
 * Exits 0 when all pass, 1 otherwise. Prints JSON summary.
 *
 * v4: the live page IS ol.flex-col-reverse (message list) and the output is
 * DOM-after its prompt; the reference (DOM-before, same turn) must never win.
 */
const fs = require('fs');

const FOLLOWING = 4;
const PRECEDING = 2;
global.Node = { DOCUMENT_POSITION_FOLLOWING: FOLLOWING, DOCUMENT_POSITION_PRECEDING: PRECEDING };
global.NodeFilter = { SHOW_TEXT: 4 };
global.window = { innerHeight: 1000, innerWidth: 1400 };

let orderCounter = 0;
function makeNode(tag, opts = {}) {
  const n = {
    tagName: (tag || 'div').toUpperCase(),
    children: [],
    parentElement: null,
    textContent: opts.text || '',
    nodeValue: opts.text || '',
    src: opts.src || '',
    className: opts.cls || '',
    complete: opts.complete !== undefined ? opts.complete : true,
    naturalWidth: opts.naturalWidth !== undefined ? opts.naturalWidth : 800,
    naturalHeight: opts.naturalHeight || 800,
    offsetParent: opts.visible === false ? null : {},
    _rect: opts.rect || { top: 0, left: 0, width: 400, height: 400 },
    _order: orderCounter++,
    classList: null,
    querySelector(sel) { const all = this.querySelectorAll(sel); return all[0] || null; },
    querySelectorAll(sel) { return queryAll(this, sel); },
    getBoundingClientRect() { return this._rect; },
    contains(other) {
      let cur = other;
      while (cur) { if (cur === this) return true; cur = cur.parentElement; }
      return false;
    },
    compareDocumentPosition(other) {
      if (other === this) return 0;
      if (this.contains(other)) return 20; // contains + following-ish, not pure
      if (other.contains(this)) return 10;
      return this._order < other._order ? FOLLOWING : PRECEDING;
    },
    closest(sel) {
      const parts = sel.split(',').map(s => s.trim());
      let cur = this;
      while (cur) {
        for (const p of parts) {
          if (matchSimple(cur, p)) return cur;
        }
        cur = cur.parentElement;
      }
      return null;
    },
    scrollIntoView() { this._scrolled = true; },
  };
  n.classList = {
    contains(c) { return (' ' + n.className + ' ').includes(' ' + c + ' '); },
  };
  (opts.children || []).forEach(c => appendChild(n, c));
  return n;
}
function appendChild(parent, child) {
  child.parentElement = parent;
  parent.children.push(child);
  // propagate textContent upward for container checks
  let cur = parent;
  while (cur) {
    if (child.textContent && !cur.textContent.includes(child.textContent.slice(0, 30))) {
      cur.textContent = (cur.textContent + ' ' + child.textContent).slice(0, 5000);
    }
    cur = cur.parentElement;
  }
}
function matchSimple(node, sel) {
  // minimal: check tag, class fragments, attr fragments used by probe
  const s = sel.toLowerCase();
  const cls = (node.className || '').toLowerCase();
  const tag = (node.tagName || '').toLowerCase();
  if (s.includes('animate-spin') && !cls.includes('animate-spin')) return false;
  if (s.includes('no-scrollbar') && !cls.includes('no-scrollbar')) return false;
  if (s.includes('flex-col-reverse') && !cls.includes('flex-col-reverse')) return false;
  if (s.includes('.flex') && !s.includes('flex-col-reverse') && !cls.includes('flex')) return false;
  if (s.includes('.group') && !cls.includes('group')) return false;
  if (s.includes('truncate') && !cls.includes('truncate')) return false;
  if (s.includes('aspect-square') && !cls.includes('aspect-square')) return false;
  if (s.includes('img') && tag !== 'img') {
    // selector like 'div.no-scrollbar img...' — leaf must be img
    if (!s.trim().endsWith('img') && !s.includes(' img')) { /* container */ } else return false;
  }
  if (s.includes('r2.cloudflarestorage') && !(node.src || '').includes('r2.cloudflarestorage')) return false;
  if (s.includes('messages-prod') && !(node.src || '').includes('messages-prod')) return false;
  if (s.startsWith('img') && tag !== 'img') return false;
  if (s === 'img' && tag !== 'img') return false;
  return true;
}
function queryAll(root, sel) {
  const out = [];
  // split comma selectors
  const parts = sel.split(',').map(s => s.trim()).filter(Boolean);
  function walk(n) {
    for (const p of parts) {
      // for descendant selectors, check leaf match + ancestor match
      if (p.includes(' ')) {
        const toks = p.split(/\s+/);
        const leaf = toks[toks.length - 1];
        if (!matchSimple(n, leaf)) continue;
        // check ancestor chain contains each prior token
        let ok = true;
        let cur = n.parentElement;
        for (let i = toks.length - 2; i >= 0; i--) {
          let found = false;
          while (cur) {
            if (matchSimple(cur, toks[i])) { found = true; cur = cur.parentElement; break; }
            cur = cur.parentElement;
          }
          if (!found) { ok = false; break; }
        }
        if (ok) { out.push(n); break; }
      } else {
        if (matchSimple(n, p)) { out.push(n); break; }
      }
    }
    (n.children || []).forEach(walk);
  }
  walk(root);
  return out;
}
function collectTextNodes(root) {
  const out = [];
  function walk(n) {
    if (n.nodeValue && n.tagName !== 'TEXTAREA') {
      // treat leaf text holders as text nodes with parentElement
      if (n.children.length === 0 && n.textContent) {
        out.push({ nodeValue: n.nodeValue, parentElement: n.parentElement || n });
      }
    }
    (n.children || []).forEach(walk);
  }
  // also push explicit text wrappers
  walk(root);
  return out;
}

function buildDoc(structure) {
  orderCounter = 0;
  const body = makeNode('body', { rect: { top: 0, left: 0, width: 1400, height: 2000 } });
  structure(body);
  const doc = {
    body,
    querySelector(sel) { return queryAll(body, sel)[0] || null; },
    querySelectorAll(sel) { return queryAll(body, sel); },
    createTreeWalker(root, what) {
      const nodes = collectTextNodes(root);
      // also include direct text nodes from structure (p nodes with text)
      let idx = 0;
      return { nextNode() { return idx < nodes.length ? nodes[idx++] : null; } };
    },
  };
  global.document = doc;
  return doc;
}

function r2(key) { return 'https://messages-prod.r2.cloudflarestorage.com/' + key; }
function normKey(src) { return String(src).split('?')[0].split('#')[0].slice(-120); }

function runCase(name, fn) {
  try {
    const res = fn();
    return { name, pass: !!res.pass, detail: res.detail || '' };
  } catch (e) {
    return { name, pass: false, detail: String(e).slice(0, 300) };
  }
}

// Mirrors the saved live page: user turn (ref + prompt) then assistant turn.
// ref: w-32, naturalWidth 1200 (big photo), shares turn container with prompt.
// gen: 50vh in no-scrollbar grid, DOM-after the prompt.
function buildLiveBattle(body, jobId) {
  const ol = makeNode('ol', { cls: 'mt-8 flex w-full max-w-screen-xl grow flex-col-reverse justify-end gap-4', rect: { top: 0, left: 0, width: 1300, height: 2000 } });
  appendChild(body, ol);
  const h0 = makeNode('div', { cls: 'h-0', rect: { top: 0, left: 0, width: 10, height: 0 } });
  appendChild(ol, h0);
  const vote = makeNode('div', { cls: 'w-full', text: 'Which response do you prefer?', rect: { top: 10, left: 100, width: 600, height: 80 } });
  appendChild(ol, vote);
  const userTurn = makeNode('div', { cls: 'mx-auto max-w-[800px] flex w-full justify-end', rect: { top: 100, left: 100, width: 800, height: 600 } });
  appendChild(ol, userTurn);
  const group = makeNode('div', { cls: 'group flex max-w-[min(768px,100%)] flex-col gap-1 self-end', rect: { top: 110, left: 150, width: 700, height: 550 } });
  appendChild(userTurn, group);
  const turn = makeNode('div', { cls: 'flex flex-col gap-4', rect: { top: 120, left: 160, width: 650, height: 470 } });
  appendChild(group, turn);
  const refRow = makeNode('div', { cls: 'flex w-full flex-row items-center gap-2 ml-auto max-w-2xl flex-wrap justify-end', rect: { top: 120, left: 200, width: 600, height: 150 } });
  appendChild(turn, refRow);
  const wfit = makeNode('div', { cls: 'w-fit', rect: { top: 125, left: 550, width: 140, height: 140 } });
  appendChild(refRow, wfit);
  const rel = makeNode('div', { cls: 'relative', rect: { top: 125, left: 550, width: 130, height: 130 } });
  appendChild(wfit, rel);
  const ref = makeNode('img', { src: r2('ref/03-a.jpeg'), cls: 'aspect-square w-32 cursor-pointer overflow-hidden rounded-lg object-cover object-center opacity-100 transition', rect: { top: 125, left: 550, width: 128, height: 128 }, naturalWidth: 1200, naturalHeight: 900 });
  appendChild(rel, ref);
  const bubRow = makeNode('div', { cls: 'flex min-w-0 flex-1 flex-col items-end gap-1', rect: { top: 280, left: 200, width: 600, height: 300 } });
  appendChild(turn, bubRow);
  const bubble = makeNode('div', { cls: 'bg-surface-raised w-fit min-w-0 max-w-prose rounded-lg px-3 py-2', rect: { top: 285, left: 250, width: 550, height: 280 } });
  appendChild(bubRow, bubble);
  const prose = makeNode('div', { cls: 'prose text-wrap break-words prose-base body-base', rect: { top: 290, left: 260, width: 520, height: 260 } });
  appendChild(bubble, prose);
  const p = makeNode('p', { text: `[JOB-ID: ${jobId}] Transform test prompt`, rect: { top: 295, left: 270, width: 500, height: 200 } });
  appendChild(prose, p);
  const t1 = makeNode('span', { text: `[JOB-ID: ${jobId}] Transform test prompt`, rect: { top: 295, left: 270, width: 500, height: 50 } });
  appendChild(p, t1);
  const asstTurn = makeNode('div', { cls: 'mx-auto max-w-[800px] w-full', rect: { top: 720, left: 100, width: 800, height: 700 } });
  appendChild(ol, asstTurn);
  const card = makeNode('div', { cls: 'bg-surface-primary relative flex w-full min-w-0 flex-1 flex-col overflow-hidden gap-2', rect: { top: 730, left: 120, width: 780, height: 650 } });
  appendChild(asstTurn, card);
  const grid = makeNode('div', { cls: 'no-scrollbar relative flex w-full flex-1 flex-col overflow-x-auto', rect: { top: 740, left: 130, width: 760, height: 600 } });
  appendChild(card, grid);
  const minw = makeNode('div', { cls: 'min-w-0', rect: { top: 745, left: 135, width: 740, height: 580 } });
  appendChild(grid, minw);
  const gap3 = makeNode('div', { cls: 'flex flex-col gap-3', rect: { top: 750, left: 140, width: 720, height: 560 } });
  appendChild(minw, gap3);
  const outRow = makeNode('div', { cls: 'flex w-full flex-row items-center gap-2 justify-start', rect: { top: 755, left: 145, width: 700, height: 540 } });
  appendChild(gap3, outRow);
  const wfit2 = makeNode('div', { cls: 'w-fit', rect: { top: 760, left: 150, width: 420, height: 420 } });
  appendChild(outRow, wfit2);
  const rel2 = makeNode('div', { cls: 'relative', rect: { top: 760, left: 150, width: 410, height: 410 } });
  appendChild(wfit2, rel2);
  const gen = makeNode('img', { src: r2('new/1789508403662-genA.png'), cls: 'transition-opacity duration-500 opacity-100 aspect-square h-[50vh] w-[50vh] max-w-full cursor-pointer overflow-hidden rounded-lg object-cover object-center', rect: { top: 760, left: 150, width: 400, height: 400 }, naturalWidth: 1024, naturalHeight: 1024 });
  appendChild(rel2, gen);
  return { ol, ref, gen };
}

function main() {
  const probeFile = process.argv[2];
  if (!probeFile) { console.log(JSON.stringify({ ok: false, error: 'no probe file' })); process.exit(1); }
  const code = fs.readFileSync(probeFile, 'utf8');
  const probe = eval(code);
  const results = [];

  // Case 1: LIVE battle layout — ol.flex-col-reverse present (message list!),
  // ref DOM-before prompt (same turn), gen DOM-after prompt in grid.
  // Must pick gen with poolKind 'below' — never the ref (v4 regression).
  results.push(runCase('live_battle_below', () => {
    const oldKey = normKey(r2('old/111-old.png'));
    buildDoc((body) => { buildLiveBattle(body, 'QJ9K'); });
    const r = probe([oldKey], 'QJ9K');
    const pass = r.ready === true && (r.src || '').includes('genA') && r.poolKind === 'below';
    return { pass, detail: JSON.stringify({ ready: r.ready, src: (r.src || '').slice(-30), pool: r.poolKind, reason: r.reason, jobFound: r.jobFound, validBelow: r.validBelow, order: (r.orderCheck || '').slice(0, 80) }).slice(0, 400) };
  }));

  // Case 2: spinner visible, gen not yet, should be generating (not ready, spinning true)
  results.push(runCase('spinner_generating', () => {
    buildDoc((body) => {
      const wrap = makeNode('div', { cls: 'flex min-w-0 flex-1 items-center gap-2', rect: { top: 100, left: 100, width: 400, height: 50 } });
      appendChild(body, wrap);
      const spin = makeNode('div', { cls: 'h-5 w-5 flex-shrink-0 animate-spin', rect: { top: 100, left: 100, width: 20, height: 20 } });
      appendChild(wrap, spin);
      const label = makeNode('span', { cls: 'truncate', text: 'Response A', rect: { top: 100, left: 130, width: 100, height: 20 } });
      appendChild(wrap, label);
      const userWrap = makeNode('div', { cls: 'group flex', rect: { top: 500, left: 100, width: 600, height: 200 }, text: '[JOB-ID: SPIN1] hello world test' });
      appendChild(body, userWrap);
      const p = makeNode('p', { text: '[JOB-ID: SPIN1] hello', rect: { top: 520, left: 120, width: 400, height: 80 } });
      appendChild(userWrap, p);
      const t1 = makeNode('span', { text: '[JOB-ID: SPIN1] hello', rect: { top: 520, left: 120, width: 400, height: 40 } });
      appendChild(p, t1);
    });
    const r = probe([], 'SPIN1');
    const pass = r.ready === false && r.spinning === true;
    return { pass, detail: JSON.stringify({ ready: r.ready, spinning: r.spinning, reason: r.reason }).slice(0, 300) };
  }));

  // Case 3: multi-turn pairing is DOM-after. DOM: genNew, NEW1, MID1, genOld.
  // NEW1 has no output yet (genNew is DOM-before it) -> await next.
  // MID1 pairs with genOld (DOM-after it) -> ready.
  results.push(runCase('pairing_dom_after', () => {
    buildDoc((body) => {
      const ol = makeNode('div', { cls: 'flex-col-reverse', rect: { top: 0, left: 0, width: 1300, height: 2000 } });
      appendChild(body, ol);
      const genNew = makeNode('img', { src: r2('new/999-newest.png'), cls: 'aspect-square object-cover', rect: { top: 1500, left: 100, width: 400, height: 400 } });
      const genWrap1 = makeNode('div', { cls: 'no-scrollbar', rect: { top: 1500, left: 100, width: 500, height: 500 } });
      appendChild(ol, genWrap1); appendChild(genWrap1, genNew);
      const userNew = makeNode('div', { cls: 'group flex', rect: { top: 1300, left: 100, width: 600, height: 150 }, text: '[JOB-ID: NEW1] newest prompt here testing' });
      appendChild(ol, userNew);
      const pn = makeNode('p', { text: '[JOB-ID: NEW1] newest', rect: { top: 1310, left: 120, width: 400, height: 60 } });
      appendChild(userNew, pn);
      const tn = makeNode('span', { text: '[JOB-ID: NEW1] newest', rect: { top: 1310, left: 120, width: 400, height: 30 } });
      appendChild(pn, tn);
      const userMid = makeNode('div', { cls: 'group flex', rect: { top: 900, left: 100, width: 600, height: 150 }, text: '[JOB-ID: MID1] middle prompt testing here' });
      appendChild(ol, userMid);
      const pm = makeNode('p', { text: '[JOB-ID: MID1] middle', rect: { top: 910, left: 120, width: 400, height: 60 } });
      appendChild(userMid, pm);
      const tm = makeNode('span', { text: '[JOB-ID: MID1] middle', rect: { top: 910, left: 120, width: 400, height: 30 } });
      appendChild(pm, tm);
      const genWrapOld = makeNode('div', { cls: 'no-scrollbar', rect: { top: 500, left: 100, width: 500, height: 500 } });
      appendChild(ol, genWrapOld);
      const genOld = makeNode('img', { src: r2('new/111-midgen.png'), cls: 'aspect-square object-cover', rect: { top: 500, left: 100, width: 400, height: 400 } });
      appendChild(genWrapOld, genOld);
    });
    const rNew = probe([], 'NEW1');
    const newOk = rNew.ready === false && rNew.invalidAbove >= 1
      && rNew.reason === 'image_above_belongs_to_previous_prompt_await_next';
    const rMid = probe([], 'MID1');
    const midOk = rMid.ready === true && (rMid.src || '').includes('midgen')
      && rMid.poolKind === 'below';
    const pass = newOk && midOk;
    return { pass, detail: JSON.stringify({ newOk, midOk, rNew: { ready: rNew.ready, reason: rNew.reason, invalid: rNew.invalidAbove }, rMid: { ready: rMid.ready, src: (rMid.src || '').slice(-30), pool: rMid.poolKind } }).slice(0, 500) };
  }));

  // Case 4: plain below layout, gen after user -> validBelow ready
  results.push(runCase('below_exact', () => {
    buildDoc((body) => {
      const col = makeNode('div', { cls: 'flex flex-col', rect: { top: 0, left: 0, width: 1300, height: 1500 } });
      appendChild(body, col);
      const userWrap = makeNode('div', { cls: 'group flex', rect: { top: 300, left: 100, width: 600, height: 150 }, text: '[JOB-ID: BELOW1] below layout test prompt' });
      appendChild(col, userWrap);
      const p = makeNode('p', { text: '[JOB-ID: BELOW1] below', rect: { top: 310, left: 120, width: 400, height: 60 } });
      appendChild(userWrap, p);
      const t1 = makeNode('span', { text: '[JOB-ID: BELOW1] below', rect: { top: 310, left: 120, width: 400, height: 30 } });
      appendChild(p, t1);
      const genWrap = makeNode('div', { cls: 'no-scrollbar', rect: { top: 500, left: 100, width: 500, height: 500 } });
      appendChild(col, genWrap);
      const gen = makeNode('img', { src: r2('new/222-belowgen.png'), cls: 'aspect-square object-cover', rect: { top: 500, left: 100, width: 400, height: 400 } });
      appendChild(genWrap, gen);
    });
    const r = probe([], 'BELOW1');
    const pass = r.ready === true && (r.src || '').includes('belowgen') && r.poolKind === 'below';
    return { pass, detail: JSON.stringify({ ready: r.ready, src: (r.src || '').slice(-30), pool: r.poolKind, reason: r.reason }).slice(0, 400) };
  }));

  // Case 5: query rotation, same key with query should be old
  results.push(runCase('query_rotation_old', () => {
    const key = normKey(r2('k/1789508403662-02-c.jpeg'));
    buildDoc((body) => {
      const genWrap = makeNode('div', { cls: 'no-scrollbar', rect: { top: 600, left: 100, width: 500, height: 500 } });
      appendChild(body, genWrap);
      const gen = makeNode('img', { src: r2('k/1789508403662-02-c.jpeg') + '?X-Amz-NewSig', cls: 'aspect-square object-cover', rect: { top: 600, left: 100, width: 400, height: 400 } });
      appendChild(genWrap, gen);
    });
    const r = probe([key], null);
    const pass = r.ready === false && r.reason === 'no_new';
    return { pass, detail: JSON.stringify({ ready: r.ready, reason: r.reason, allNew: r.allNew }).slice(0, 300) };
  }));

  // Case 6: reference only (generation not finished) -> NEVER ready with ref.
  // allNewDetails must mark it isReference; fallbackDetails must be empty.
  results.push(runCase('reference_never_selected', () => {
    buildDoc((body) => {
      const ol = makeNode('ol', { cls: 'flex flex-col-reverse', rect: { top: 0, left: 0, width: 1300, height: 1200 } });
      appendChild(body, ol);
      const turn = makeNode('div', { cls: 'flex flex-col gap-4', rect: { top: 100, left: 100, width: 650, height: 470 } });
      appendChild(ol, turn);
      const ref = makeNode('img', { src: r2('ref/09-input.jpeg'), cls: 'aspect-square w-32 object-cover', rect: { top: 120, left: 120, width: 128, height: 128 }, naturalWidth: 1600, naturalHeight: 1200 });
      appendChild(turn, ref);
      const p = makeNode('p', { text: '[JOB-ID: REF1] waiting for output', rect: { top: 300, left: 120, width: 500, height: 100 } });
      appendChild(turn, p);
      const t1 = makeNode('span', { text: '[JOB-ID: REF1] waiting for output', rect: { top: 300, left: 120, width: 500, height: 40 } });
      appendChild(p, t1);
    });
    const r = probe([], 'REF1');
    const marked = (r.allNewDetails || []).length === 1 && r.allNewDetails[0].isReference === true;
    const noFb = ((r.fallbackDetails || []).length === 0);
    const pass = r.ready === false && r.jobFound === true && marked && noFb;
    return { pass, detail: JSON.stringify({ ready: r.ready, reason: r.reason, allNew: r.allNew, marked, noFb, src: (r.src || '').slice(-20) }).slice(0, 400) };
  }));

  // Case 7: fallback payload excludes refs. JB1A current, JB2A next (DOM-after),
  // gen DOM-after J2 (unpaired -> belowCands) + ref in J1 turn.
  // fallbackDetails must be [gen] only; ref marked isReference in allNewDetails.
  results.push(runCase('fallback_excludes_reference', () => {
    buildDoc((body) => {
      const turn = makeNode('div', { cls: 'flex flex-col gap-4', rect: { top: 100, left: 100, width: 650, height: 470 } });
      appendChild(body, turn);
      const ref = makeNode('img', { src: r2('ref/07-in.jpeg'), cls: 'aspect-square w-32 object-cover', rect: { top: 120, left: 120, width: 128, height: 128 }, naturalWidth: 2000, naturalHeight: 1500 });
      appendChild(turn, ref);
      const p1 = makeNode('p', { text: '[JOB-ID: JB1A] first prompt here', rect: { top: 300, left: 120, width: 500, height: 100 } });
      appendChild(turn, p1);
      const t1 = makeNode('span', { text: '[JOB-ID: JB1A] first prompt here', rect: { top: 300, left: 120, width: 500, height: 40 } });
      appendChild(p1, t1);
      const p2 = makeNode('p', { text: '[JOB-ID: JB2A] second prompt here', rect: { top: 600, left: 120, width: 500, height: 100 } });
      appendChild(body, p2);
      const t2 = makeNode('span', { text: '[JOB-ID: JB2A] second prompt here', rect: { top: 600, left: 120, width: 500, height: 40 } });
      appendChild(p2, t2);
      const genWrap = makeNode('div', { cls: 'no-scrollbar', rect: { top: 750, left: 100, width: 500, height: 500 } });
      appendChild(body, genWrap);
      const gen = makeNode('img', { src: r2('new/333-fbgen.png'), cls: 'aspect-square h-[50vh] object-cover', rect: { top: 750, left: 100, width: 400, height: 400 } });
      appendChild(genWrap, gen);
    });
    const r = probe([], 'JB1A');
    const fb = r.fallbackDetails || [];
    const fbOk = fb.length === 1 && (fb[0].src || '').includes('fbgen') && fb[0].isReference === false;
    const refMarked = (r.allNewDetails || []).some(n => (n.src || '').includes('07-in') && n.isReference === true);
    const pass = r.ready === false && r.jobFound === true && fbOk && refMarked;
    return { pass, detail: JSON.stringify({ ready: r.ready, reason: r.reason, fbLen: fb.length, fbOk, refMarked }).slice(0, 400) };
  }));

  const failed = results.filter(r => !r.pass);
  console.log(JSON.stringify({ ok: failed.length === 0, results }, null, 1));
  process.exit(failed.length === 0 ? 0 : 1);
}
main();
