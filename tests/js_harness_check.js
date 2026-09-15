/* JS harness for output check v3 — runs real probe against DOM stub.
 * Usage: node tests/js_harness_check.js <probe_file> (probe exports raw JS fn)
 * Probe file contains JS expression ((oldKeys, correlationId) => {...}).
 * Defines minimal document/window/Node/NodeFilter, then 5 cases.
 * Exits 0 when all pass, 1 otherwise. Prints JSON summary.
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

function main() {
  const probeFile = process.argv[2];
  if (!probeFile) { console.log(JSON.stringify({ ok: false, error: 'no probe file' })); process.exit(1); }
  const code = fs.readFileSync(probeFile, 'utf8');
  const probe = eval(code);
  const results = [];

  // Case 1: reverse layout, gen_A before user QJ9K, should be ready above
  results.push(runCase('reverse_exact_above', () => {
    const oldKey = normKey(r2('old/111-old.png'));
    buildDoc((body) => {
      const ol = makeNode('div', { cls: 'flex-col-reverse', rect: { top: 0, left: 0, width: 1300, height: 1800 } });
      appendChild(body, ol);
      const h0 = makeNode('div', { cls: 'h-0', rect: { top: 0, left: 0, width: 10, height: 0 } });
      appendChild(ol, h0);
      const genWrap = makeNode('div', { cls: 'no-scrollbar', rect: { top: 900, left: 100, width: 500, height: 500 } });
      appendChild(ol, genWrap);
      const genA = makeNode('img', { src: r2('new/1789508403662-genA.png'), cls: 'aspect-square object-cover cursor-pointer', rect: { top: 900, left: 100, width: 400, height: 400 } });
      appendChild(genWrap, genA);
      const userWrap = makeNode('div', { cls: 'group flex flex-col', rect: { top: 500, left: 100, width: 600, height: 300 }, text: '[JOB-ID: QJ9K] Transform test prompt for case one with enough text' });
      appendChild(ol, userWrap);
      const refImg = makeNode('img', { src: r2('ref/03-a.jpeg'), cls: 'aspect-square w-32 object-cover', rect: { top: 520, left: 120, width: 128, height: 128 }, naturalWidth: 1200 });
      appendChild(userWrap, refImg);
      const p = makeNode('p', { text: '[JOB-ID: QJ9K] Transform test prompt for case one', rect: { top: 600, left: 120, width: 500, height: 100 } });
      appendChild(userWrap, p);
      // text node wrappers for TreeWalker
      const t1 = makeNode('span', { text: '[JOB-ID: QJ9K] Transform test prompt', rect: { top: 600, left: 120, width: 500, height: 50 } });
      appendChild(p, t1);
    });
    const r = probe([oldKey], 'QJ9K');
    const pass = r.ready === true && (r.src || '').includes('genA') && r.poolKind === 'above';
    return { pass, detail: JSON.stringify({ ready: r.ready, src: (r.src || '').slice(-30), pool: r.poolKind, reason: r.reason, jobFound: r.jobFound, valid: r.validAbove }).slice(0, 400) };
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

  // Case 3: middle job, only older gen before prev -> belongs to previous
  results.push(runCase('belongs_to_previous', () => {
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
      // middle user MID1 with NO gen (missing), older gen below in DOM (after)
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
    // For MID1: prev is NEW1 (DOM before), valid range (NEW1, MID1) is empty (no img between).
    // genNew (idx1) is before prev -> invalidAbove. genOld (idx after MID1) is below -> belowCands.
    // Expect not ready, with invalidAbove>=1 or allNew>0 and reason indicates await next.
    const r = probe([], 'MID1');
    const pass = r.ready === false && (r.invalidAbove >= 1 || r.allNew >= 1) && r.jobFound === true;
    return { pass, detail: JSON.stringify({ ready: r.ready, reason: r.reason, invalid: r.invalidAbove, allNew: r.allNew, jobFound: r.jobFound }).slice(0, 400) };
  }));

  // Case 4: normal layout fallback, gen after user -> validBelow ready
  results.push(runCase('normal_below_fallback', () => {
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

  const failed = results.filter(r => !r.pass);
  console.log(JSON.stringify({ ok: failed.length === 0, results }, null, 1));
  process.exit(failed.length === 0 ? 0 : 1);
}
main();
