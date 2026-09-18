/* Captcha completion probe tests — the getResponse patch in inject.js and
   the step-based close_dialog.js (2026-09-18 captcha-completion).
   Regression: the token was injected but the dialog's closure-callback
   never fired, so the dialog was stuck and the flow never resumed.
   Docs: docs/archive/2026-09-18-captcha-completion/design.md */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const probe = (name) => readFileSync(join(ROOT, 'app', 'browser', 'captcha_js', name), 'utf8').trim();

/* ——— minimal DOM stub (same surface as test_captcha.mjs + removeChild) ——— */

class El {
  constructor(tag, attrs = {}) {
    this.tagName = String(tag).toUpperCase();
    this.nodeType = 1;
    this.attrs = { ...attrs };
    this.children = [];
    this.parent = null;
    this._text = attrs._text || '';
    this._value = '';
    this.events = [];
    this.clicked = false;
  }
  get parentElement() { return this.parent; }
  get parentNode() { return this.parent; }
  getBoundingClientRect() { return { top: 0, left: 0, right: 100, bottom: 100, width: 100, height: 100 }; }
  append(...els) { els.forEach(e => { e.parent = this; this.children.push(e); }); return this; }
  removeChild(c) {
    const i = this.children.indexOf(c);
    if (i >= 0) this.children.splice(i, 1);
    c.parent = null;
    return c;
  }
  getAttribute(n) { return this.attrs[n] !== undefined ? String(this.attrs[n]) : null; }
  get offsetParent() { return {}; }
  get innerText() { return this._text; }
  get textContent() { return this._text || this.children.map(c => c.textContent).join(''); }
  get value() { return this._value; }
  set value(v) { this._value = String(v); }
  dispatchEvent(ev) { this.events.push(ev); }
  click() { this.clicked = true; }
  closest(sel) {
    let n = this;
    while (n) {
      if (n.nodeType === 1 && matchCompound(n, sel)) return n;
      n = n.parent;
    }
    return null;
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  querySelectorAll(sel) { return qsa(this, sel); }
}

function* walk(root) {
  for (const c of root.children) { yield c; yield* walk(c); }
}

function matchCompound(el, s) {
  const parts = [];
  const re = /([a-zA-Z][\w-]*)|\.([\w-]+)|\[([\w-]+)(?:\s*(\*?)=\s*"([^"]*)")?\]|#([\w-]+)/g;
  let m;
  while ((m = re.exec(s))) {
    if (m[1]) parts.push({ tag: m[1].toUpperCase() });
    else if (m[2]) parts.push({ cls: m[2] });
    else if (m[3]) parts.push({ attr: m[3], sub: m[4] || '', val: m[5] });
    else if (m[6]) parts.push({ id: m[6] });
  }
  if (!parts.length) return false;
  return parts.every(p => {
    if (p.tag && el.tagName !== p.tag) return false;
    if (p.id && el.attrs.id !== p.id) return false;
    if (p.cls && !String(el.attrs.class || '').split(/\s+/).includes(p.cls)) return false;
    if (p.attr) {
      const v = el.attrs[p.attr];
      if (v === undefined || v === null) return false;
      if (p.val === undefined) return true;
      return p.sub ? String(v).includes(p.val) : String(v) === p.val;
    }
    return true;
  });
}

function qsa(root, sel) {
  const sels = sel.split(',').map(s => s.trim()).filter(Boolean);
  const out = [];
  for (const el of walk(root)) {
    if (el.nodeType !== 1) continue;
    if (sels.some(s => matchCompound(el, s))) out.push(el);
  }
  return out;
}

const makeDoc = (body) => {
  const document = {
    body,
    children: body.children,
    querySelector: (sel) => qsa(document, sel)[0] || null,
    querySelectorAll: (sel) => qsa(document, sel),
    dispatchEvent() {},
  };
  return document;
};

function openDialog(extra = []) {
  const d = new El('div', { role: 'dialog', 'data-state': 'open', _text: 'Security Verification' });
  d.append(new El('textarea', { name: 'g-recaptcha-response' }));
  extra.forEach(e => d.append(e));
  return d;
}

/* ——— inject.js: the getResponse patch ——— */

const runInject = (token, body, win = {}) => {
  const document = makeDoc(body);
  const proto = {};
  Object.defineProperty(proto, 'value', {
    configurable: true,
    get() { return this._value; },
    set(v) { this._value = String(v); },
  });
  const HTMLTextAreaElement = { prototype: proto };
  const HTMLInputElement = { prototype: proto };
  class Event { constructor(type, init) { this.type = type; } }
  const fn = new Function('document', 'HTMLTextAreaElement', 'HTMLInputElement', 'Event', 'window',
                          'return (' + probe('inject.js') + ')');
  return fn(document, HTMLTextAreaElement, HTMLInputElement, Event, win)(token);
};

test('inject: patches grecaptcha.getResponse to return the solved token', () => {
  const win = { grecaptcha: { getResponse: () => 'stale' } };
  const body = new El('body').append(openDialog());
  const r = runInject('TOK_P', body, win);
  assert.equal(r.ok, true);
  assert.equal(r.getResponsePatched, true);
  assert.equal(win.grecaptcha.getResponse(), 'TOK_P');  // the read path now yields our token
});

test('inject: no grecaptcha on window → not patched, still ok', () => {
  const body = new El('body').append(openDialog());
  const r = runInject('TOK_X', body, {});
  assert.equal(r.ok, true);
  assert.equal(r.getResponsePatched, false);
});

test('inject: grecaptcha without getResponse → not patched, no crash', () => {
  const win = { grecaptcha: { render: () => 1 } };
  const body = new El('body').append(openDialog());
  const r = runInject('TOK_Y', body, win);
  assert.equal(r.ok, true);
  assert.equal(r.getResponsePatched, false);
});

/* ——— close_dialog.js: one step per call ——— */

const runClose = (step, body) => {
  const document = makeDoc(body);
  class KeyboardEvent { constructor(type, init) { this.type = type; this.key = init && init.key; } }
  const fn = new Function('document', 'KeyboardEvent',
                          'return (' + probe('close_dialog.js') + ')');
  return fn(document, KeyboardEvent)(step);
};

test('close: no open dialog → used none (idempotent)', () => {
  const r = runClose('esc', new El('body').append(new El('div')));
  assert.equal(r.ok, true);
  assert.equal(r.used, 'none');
});

test('close: esc step dispatches on an open dialog', () => {
  const body = new El('body').append(openDialog());
  const r = runClose('esc', body);
  assert.equal(r.ok, true);
  assert.equal(r.used, 'esc');
});

test('close: close step clicks the Radix close control', () => {
  const btn = new El('button', { 'aria-label': 'Close' });
  const body = new El('body').append(openDialog([btn]));
  const r = runClose('close', body);
  assert.equal(r.ok, true);
  assert.equal(r.used, 'close-btn');
  assert.equal(btn.clicked, true);
});

test('close: close step with no control → ok:false reason', () => {
  const body = new El('body').append(openDialog());
  const r = runClose('close', body);
  assert.equal(r.ok, false);
  assert.match(r.reason, /no close control/);
});

test('close: nuclear removes dialog + overlay sibling + focus guards', () => {
  const guard = new El('div', { 'data-radix-focus-guard': '' });
  const overlay = new El('div', { 'data-state': 'open', class: 'fixed inset-0 z-50 bg-black/80' });
  const dialog = openDialog();
  const portal = new El('div');
  portal.append(guard, overlay, dialog);
  const body = new El('body').append(portal);
  const r = runClose('nuclear', body);
  assert.equal(r.ok, true);
  assert.equal(r.used, 'nuclear');
  assert.ok(r.removed >= 3);
  assert.equal(qsa(body, 'div[role="dialog"]').length, 0);
  assert.equal(qsa(body, 'div[data-state="open"]').length, 0);
  assert.equal(qsa(body, 'div[data-radix-focus-guard]').length, 0);
});

test('close: unknown step → ok:false', () => {
  const r = runClose('warp', new El('body').append(openDialog()));
  assert.equal(r.ok, false);
  assert.match(r.reason, /unknown step/);
});
