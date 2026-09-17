/* Minimal DOM + CSS-flexbox layout engine to run the real sash-grid JS in Node. */

export class ClassList {
  constructor(el) { this.el = el; this.set = new Set(); }
  add(...cs) { cs.forEach((c) => this.set.add(c)); this._sync(); }
  remove(...cs) { cs.forEach((c) => this.set.delete(c)); this._sync(); }
  toggle(c, force) {
    const want = force === undefined ? !this.set.has(c) : !!force;
    if (want) this.set.add(c); else this.set.delete(c);
    this._sync();
    return want;
  }
  contains(c) { return this.set.has(c); }
  _sync() { this.el.className = [...this.set].join(' '); }
}

export class El {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.parent = null;
    this.dataset = {};
    this.style = {};
    this._listeners = {};
    this._rect = { left: 0, top: 0, width: 0, height: 0 };
    this._className = '';
    this.classList = new ClassList(this);
    this.id = '';
    this.textContent = '';
    this.title = '';
    this._innerHTML = '';
    this.isConnected = true;
  }
  get className() { return this._className; }
  set className(v) {
    this._className = String(v);
    this.classList.set = new Set(this._className.split(/\s+/).filter(Boolean));
  }
  get firstChild() { return this.children[0] || null; }
  get parentNode() { return this.parent; }
  get parentElement() { return this.parent; }
  get nextSibling() {
    if (!this.parent) return null;
    const i = this.parent.children.indexOf(this);
    return this.parent.children[i + 1] || null;
  }
  get offsetWidth() { return Math.round(this._rect.width); }
  get offsetHeight() { return Math.round(this._rect.height); }
  get innerHTML() { return this._innerHTML; }
  set innerHTML(v) { this._innerHTML = String(v); this.children = []; }
  appendChild(c) {
    if (c.parent) c.parent.children.splice(c.parent.children.indexOf(c), 1);
    c.parent = this; c.isConnected = true;
    this.children.push(c);
    return c;
  }
  insertBefore(c, ref) {
    if (c.parent) c.parent.children.splice(c.parent.children.indexOf(c), 1);
    c.parent = this; c.isConnected = true;
    const i = ref ? this.children.indexOf(ref) : -1;
    if (i < 0) this.children.push(c); else this.children.splice(i, 0, c);
    return c;
  }
  replaceChildren(...nodes) {
    this.children.forEach((c) => { c.parent = null; c.isConnected = false; });
    this.children = [];
    nodes.forEach((n) => this.appendChild(n));
  }
  remove() {
    if (this.parent) this.parent.children.splice(this.parent.children.indexOf(this), 1);
    this.parent = null; this.isConnected = false;
  }
  getBoundingClientRect() {
    const r = this._rect;
    return { left: r.left, top: r.top, width: r.width, height: r.height,
             right: r.left + r.width, bottom: r.top + r.height };
  }
  addEventListener(t, fn) { (this._listeners[t] = this._listeners[t] || []).push(fn); }
  removeEventListener(t, fn) {
    this._listeners[t] = (this._listeners[t] || []).filter((f) => f !== fn);
  }
  setPointerCapture() {}
  releasePointerCapture() {}
  dispatch(type, ev) {
    (this._listeners[type] || []).slice().forEach((fn) => fn(ev));
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  querySelectorAll(sel) { return queryAll(this, sel); }
  closest(sel) {
    let n = this;
    while (n) { if (matches(n, compile(sel), n)) return n; n = n.parent; }
    return null;
  }
}

/* ——— tiny selector engine (covers the subset the sash grid uses) ——— */

function parseCompound(comp) {
  const parts = [];
  const re = /:not\(([^)]*)\)|\.([\w-]+)|#([\w-]+)|\[([\w-]+)\s*=\s*"([^"]*)"\]|\*|([a-zA-Z][\w-]*)/g;
  let m;
  while ((m = re.exec(comp))) {
    if (m[1] !== undefined) parts.push({ not: m[1] });
    else if (m[2] !== undefined) parts.push({ cls: m[2] });
    else if (m[3] !== undefined) parts.push({ id: m[3] });
    else if (m[4] !== undefined) parts.push({ attr: m[4], val: m[5] });
    else if (m[6] !== undefined) parts.push({ star: true });
    else parts.push({ tag: m[7].toUpperCase() });
  }
  return parts;
}

function partMatch(el, part, scope) {
  if (!el) return false;
  if (part.tag && el.tagName !== part.tag) return false;
  if (part.cls && !el.classList.contains(part.cls)) return false;
  if (part.id && el.id !== part.id) return false;
  if (part.attr !== undefined) {
    const key = part.attr.startsWith('data-') ? part.attr.slice(5) : part.attr;
    const v = (el.dataset && el.dataset[key] !== undefined) ? el.dataset[key] : el[key];
    if (v !== part.val) return false;
  }
  if (part.not) {
    const inner = parseCompound(part.not);
    if (inner.every((p) => partMatch(el, p, scope))) return false;
  }
  if (part.scope && el !== scope) return false;
  return true;
}

function compile(sel) {
  // returns array of {parts, comb} — comb = combinator BEFORE this part
  const tokens = [];
  const re = /:scope|>|\S+/g;
  let m;
  const raw = [];
  while ((m = re.exec(sel))) raw.push(m[0]);
  // merge ">" tokens with the following compound
  const out = [];
  for (let i = 0; i < raw.length; i++) {
    const t = raw[i];
    if (t === '>') continue;
    const child = (raw[i - 1] === '>');
    if (t === ':scope') out.push({ parts: [{ scope: true }], comb: child ? '>' : ' ' });
    else out.push({ parts: parseCompound(t), comb: child ? '>' : ' ' });
  }
  return out;
}

function matches(el, parsed, scope) {
  let cur = el;
  for (let i = parsed.length - 1; i >= 0; i--) {
    const seg = parsed[i];
    const ok = seg.parts.every((p) => partMatch(cur, p, scope));
    if (!ok) return false;
    if (i === 0) break;
    if (seg.comb === '>') { cur = cur.parent; if (!cur) return false; }
    else {
      let a = cur.parent, found = false;
      while (a) {
        if (parsed[i - 1].parts.every((p) => partMatch(a, p, scope))) { cur = a; found = true; break; }
        a = a.parent;
      }
      if (!found) return false;
    }
  }
  return true;
}

export function queryAll(root, sel) {
  const parsed = compile(sel);
  const scope = root;
  const out = [];
  const walk = (n) => {
    for (const c of n.children) {
      if (matches(c, parsed, scope)) out.push(c);
      walk(c);
    }
  };
  walk(root);
  return out;
}

/* ——— CSS flexbox (column/row, grow+basis0 or 0 0 px, min floors) ——— */

const MIN_PX = 96;
const SASH_PX = 6;

function parseFlex(f) {
  if (!f) return { grow: 0, basisPx: null };
  const m = String(f).trim().split(/\s+/);
  const grow = parseFloat(m[0]) || 0;
  const b = m[2] || '0%';
  const pm = /^([\d.]+)px$/.exec(b);
  return { grow, basisPx: pm ? parseFloat(pm[1]) : 0 };
}

function itemHidden(el) {
  if (el.classList.contains('sash-window'))
    return el.classList.contains('sash-win-hidden') || el.classList.contains('sash-win-closed');
  if (el.classList.contains('sash')) return el.classList.contains('sash-hidden');
  if (el.classList.contains('sash-split')) return el.classList.contains('sash-split-hidden');
  return false;
}

function layoutSplit(el, W, H) {
  const row = el.classList.contains('sash-row');
  el._rect.width = W; el._rect.height = H;
  const items = [];
  for (const c of el.children) {
    if (itemHidden(c)) { items.push({ el: c, kind: 'zero' }); continue; }
    if (c.classList.contains('sash')) { items.push({ el: c, kind: 'fixed', size: SASH_PX }); continue; }
    const { grow, basisPx } = parseFlex(c.style.flex);
    items.push(basisPx !== null && grow === 0
      ? { el: c, kind: 'px', size: Math.max(MIN_PX, basisPx), min: MIN_PX }
      : { el: c, kind: 'grow', grow: grow || 1, min: MIN_PX });
  }
  const M = row ? W : H;
  const fixed = items.reduce((a, it) => a + (it.kind === 'fixed' ? it.size : 0), 0);
  const pxSum = items.reduce((a, it) => a + (it.kind === 'px' ? it.size : 0), 0);
  const growItems = items.filter((it) => it.kind === 'grow');
  const free = M - fixed - pxSum;
  // iterative flexbox: hypothetical sizes, clamp at min, redistribute
  const clamped = new Map();
  let active = growItems.slice();
  let K = 0;
  for (let pass = 0; pass < 8 && active.length; pass++) {
    const sg = active.reduce((a, it) => a + it.grow, 0);
    const clampedSum = [...clamped.values()].reduce((a, b) => a + b, 0);
    const ka = sg > 0 ? Math.max(0, free - clampedSum) / sg : 0;
    const still = [];
    let changed = false;
    for (const it of active) {
      if (it.grow * ka < it.min) { clamped.set(it, it.min); changed = true; }
      else still.push(it);
    }
    K = ka;
    if (!changed) break;
    active = still;
  }
  let off = 0;
  for (const it of items) {
    let size;
    if (it.kind === 'zero') size = 0;
    else if (it.kind === 'fixed') size = it.size;
    else if (it.kind === 'px') size = it.size;
    else size = clamped.has(it) ? it.min : it.grow * K;
    const baseLeft = el._rect.left, baseTop = el._rect.top;
    const cross = row ? H : W;
    it.el._rect.left = row ? baseLeft + off : baseLeft;
    it.el._rect.top = row ? baseTop : baseTop + off;
    it.el._rect.width = row ? size : cross;
    it.el._rect.height = row ? cross : size;
    off += size;
  }
  for (const it of items) {
    if (it.el.classList.contains('sash-split')) {
      const r = it.el._rect;
      layoutSplit(it.el, r.width, r.height);
    }
  }
}

export function layoutGrid(gridEl, W, H) {
  gridEl._rect = { left: 0, top: 0, width: W, height: H };
  for (const c of gridEl.children) {
    c._rect.left = 0; c._rect.top = 0;
    if (c.classList.contains('sash-split')) layoutSplit(c, W, H);
    else { c._rect.width = W; c._rect.height = H; }
  }
}
