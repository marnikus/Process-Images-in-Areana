/* Captcha probe tests — execute the REAL probe files (app/browser/captcha_js/*)
   against a purpose-built stub DOM (RULE 8: run, don't string-assert).
   Tier A, no browser, node --test. */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const probe = (name) => readFileSync(join(ROOT, 'app', 'browser', 'captcha_js', name), 'utf8').trim();

/* ——— minimal DOM stub (just enough surface for the three probes) ——— */

class El {
  constructor(tag, attrs = {}) {
    this.tagName = String(tag).toUpperCase();
    this.nodeType = 1;
    this.attrs = { ...attrs };
    this.children = [];
    this.parent = null;
    this._value = '';
    this.events = [];
    this.clicked = false;
    this.disabled = !!attrs.disabled;
    this._hidden = false;
    this._text = attrs._text || '';
    this._style = attrs._style || null;
    this._rect = null;
  }
  get parentElement() { return this.parent; }
  getBoundingClientRect() {
    return this._rect || { top: 0, left: 0, right: 100, bottom: 100, width: 100, height: 100 };
  }
  append(...els) { els.forEach(e => { e.parent = this; this.children.push(e); }); return this; }
  getAttribute(n) { return this.attrs[n] !== undefined ? String(this.attrs[n]) : null; }
  get type() { return this.attrs.type || ''; }
  get offsetParent() { return this._hidden ? null : {}; }
  get innerText() { return this._text; }
  get textContent() { return this._text || this.children.map(c => c.textContent).join(''); }
  get value() { return this._value; }
  set value(v) { this._value = String(v); }
  contains(el) { let n = el; while (n) { if (n === this) return true; n = n.parent; } return false; }
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
      if (p.val === undefined) return true;  // presence selector
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

function makeDoc(body) {
  const document = {
    body,
    children: body.children,  // walk() surface: body's top-level elements
    querySelector: (sel) => qsa(document, sel)[0] || null,
    querySelectorAll: (sel) => qsa(document, sel),
  };
  return document;
}

const location = { href: 'https://arena.ai/image/direct' };

function securityDialog({ iframeSrc = '', dataSitekey, withImageCaptcha = false, button = null }) {
  const d = new El('div', { role: 'dialog', 'data-state': 'open', _text: 'Security Verification' });
  if (iframeSrc) d.append(new El('iframe', { title: 'reCAPTCHA', src: iframeSrc }));
  if (dataSitekey) d.append(new El('div', { 'data-sitekey': dataSitekey }));
  if (withImageCaptcha) d.append(new El('img', { src: 'https://x/captcha/123.png' }));
  if (button) d.append(button);
  return d;
}

/* ——— detect probe ——— */

const runDetect = (body) => {
  const document = makeDoc(body);
  const fn = new Function('document', 'location', `return (${probe('detect.js')});`);
  return fn(document, location);
};

test('detect: visible enterprise widget with sitekey in anchor src', () => {
  const body = new El('body').append(
    securityDialog({ iframeSrc: 'https://www.google.com/recaptcha/enterprise/anchor?ar=1&k=6LEnterpkey0000000000000000000' }),
  );
  const r = runDetect(body);
  assert.equal(r.visible, true);
  assert.equal(r.kind, 'recaptcha_enterprise');
  assert.equal(r.sitekey, '6LEnterpkey0000000000000000000');
  assert.equal(r.url, 'https://arena.ai/image/direct');
});

test('detect: v2 anchor src classifies as recaptcha_v2', () => {
  const body = new El('body').append(
    securityDialog({ iframeSrc: 'https://www.google.com/recaptcha/api2/anchor?k=6LV2key000000000000000000000' }),
  );
  const r = runDetect(body);
  assert.equal(r.visible, true);
  assert.equal(r.kind, 'recaptcha_v2');
  assert.equal(r.sitekey, '6LV2key000000000000000000000');
});

test('detect: sitekey from data-sitekey when src has none', () => {
  const body = new El('body').append(
    securityDialog({ iframeSrc: 'https://www.google.com/recaptcha/enterprise/anchor', dataSitekey: '6LDataSitekey0000000000000000000' }),
  );
  const r = runDetect(body);
  assert.equal(r.sitekey, '6LDataSitekey0000000000000000000');
});

test('detect: no dialog and no iframe → not visible', () => {
  const r = runDetect(new El('body').append(new El('div')));
  assert.equal(r.visible, false);
  assert.equal(r.kind, 'none');
  assert.equal(r.sitekey, '');
});

test('detect: anchor diagnostics — cb present, size, anchor-ms, execute-ms', () => {
  const src = 'https://www.google.com/recaptcha/enterprise/anchor?ar=1&k=6LEnterpkey0000000000000000000&size=normal&anchor-ms=20000&execute-ms=30000&cb=cf1ox98i3rhg';
  const r = runDetect(new El('body').append(securityDialog({ iframeSrc: src })));
  assert.equal(r.anchor.cb, true);
  assert.equal(r.anchor.size, 'normal');
  assert.equal(r.anchor.ams, '20000');
  assert.equal(r.anchor.ems, '30000');
});

test('detect: anchor diagnostics — cb absent → false, empty params → empty', () => {
  const r = runDetect(new El('body').append(
    securityDialog({ iframeSrc: 'https://www.google.com/recaptcha/enterprise/anchor?k=6LEnterpkey0000000000000000000' }),
  ));
  assert.equal(r.anchor.cb, false);
  assert.equal(r.anchor.size, '');
  assert.equal(r.anchor.ams, '');
  assert.equal(r.anchor.ems, '');
});

test('detect: closed dialog with unmounted (hidden) iframe does not count', () => {
  const iframe = new El('iframe', { title: 'reCAPTCHA', src: 'https://www.google.com/recaptcha/enterprise/anchor?k=6Lx' });
  const d = securityDialog({});
  d.append(iframe);
  d.attrs['data-state'] = 'closed';  // closed Radix dialog unmounts → iframe gone/hidden
  iframe._hidden = true;
  const r = runDetect(new El('body').append(d));
  assert.equal(r.visible, false);
});

test('detect: image captcha without widget classified as image', () => {
  const r = runDetect(new El('body').append(securityDialog({ withImageCaptcha: true })));
  assert.equal(r.visible, true);
  assert.equal(r.kind, 'image');
});

test('detect: script-scan fallback finds embedded sitekey', () => {
  const script = new El('script');
  script._text = 'window.x = { siteKey: "6LFromScript00000000000000000000" };';
  const body = new El('body').append(
    securityDialog({ iframeSrc: 'https://www.google.com/recaptcha/enterprise/anchor' }),
    script,
  );
  const r = runDetect(body);
  assert.equal(r.sitekey, '6LFromScript00000000000000000000');
});

/* ——— detect: real arena.ai states (2026-09-18 research) ———
   Dialog state: user-pasted live markup. Badge state: saved page
   'arena webpages/state/' — anchor.html saved-from URL proves size=invisible
   and the badge's DIFFERENT sitekey. */

const DIALOG_SRC = 'https://www.google.com/recaptcha/enterprise/anchor?ar=1&k=6Le3_cYsAAAAAGwWOK2RLDgNI15Bh8C0yLBOL1yL&co=aHR0cHM6Ly9hcmVuYS5haTo0NDM.&hl=en&v=zqB-6Xpbd3lCIvi7Tr2D0pob&theme=light&size=normal&anchor-ms=20000&execute-ms=30000&cb=cf1ox98i3rhg';
const BADGE_SRC = 'https://www.google.com/recaptcha/enterprise/anchor?ar=1&k=6LeTGMcsAAAAALuIlkVwIxaAuZA8VledA6d3Nnb0&co=aHR0cHM6Ly9hcmVuYS5haTo0NDM.&hl=en&v=BnqMGSY_YP4cCmbNINHpJPkd&size=invisible&anchor-ms=20000&execute-ms=30000&cb=t3pnrgbyrriv';

function realDialog() {
  const d = new El('div', { role: 'dialog', 'data-state': 'open', _text: 'Security Verification' });
  const container = new El('div', { class: 'recaptcha-v2-container', id: 'recaptcha-v2-container' });
  container.append(new El('iframe', { title: 'reCAPTCHA', src: DIALOG_SRC }));
  container.append(new El('textarea', { id: 'g-recaptcha-response', name: 'g-recaptcha-response', class: 'g-recaptcha-response' }));
  d.append(container);
  d.append(new El('span', { _text: 'Protected by reCAPTCHA' }));
  return d;
}

function realBadge() {
  const badge = new El('div', { class: 'grecaptcha-badge' });
  badge.append(new El('iframe', { title: 'reCAPTCHA', src: BADGE_SRC }));
  const field = new El('textarea', { id: 'g-recaptcha-response-100000', name: 'g-recaptcha-response', style: 'display: none' });
  return [badge, field];
}

test('detect: REAL challenge dialog — enterprise kind + DIALOG sitekey, not invisible', () => {
  const r = runDetect(new El('body').append(realDialog()));
  assert.equal(r.visible, true);
  assert.equal(r.kind, 'recaptcha_enterprise');
  assert.equal(r.sitekey, '6Le3_cYsAAAAAGwWOK2RLDgNI15Bh8C0yLBOL1yL');  // dialog key, not badge key
  assert.equal(r.invisible, false);  // size=normal → visible checkbox widget
});

test('detect: badge state (visible invisible-badge iframe) is NOT a challenge', () => {
  const r = runDetect(new El('body').append(...realBadge()));
  assert.equal(r.visible, false);  // badge iframe excluded from the page-level fallback
  assert.equal(r.kind, 'none');
  assert.equal(r.sitekey, '');
});

test('detect: badge + open dialog coexist → dialog wins with its own sitekey', () => {
  const body = new El('body').append(...realBadge(), realDialog());
  const r = runDetect(body);
  assert.equal(r.visible, true);
  assert.equal(r.sitekey, '6Le3_cYsAAAAAGwWOK2RLDgNI15Bh8C0yLBOL1yL');
});

test('detect: invisible enterprise widget inside a dialog → invisible flag', () => {
  const d = new El('div', { role: 'dialog', 'data-state': 'open', _text: 'Security Verification' });
  d.append(new El('iframe', { title: 'reCAPTCHA', src: 'https://www.google.com/recaptcha/enterprise/anchor?ar=1&k=6LInvisible0000000000000000000&size=invisible' }));
  const r = runDetect(new El('body').append(d));
  assert.equal(r.visible, true);
  assert.equal(r.invisible, true);
  assert.equal(r.sitekey, '6LInvisible0000000000000000000');
});

test('detect: dialog with container only (no standard iframe) + footer text is visible', () => {
  const d = new El('div', { role: 'dialog', 'data-state': 'open', _text: 'Protected by reCAPTCHA' });
  d.append(new El('div', { class: 'recaptcha-v2-container' }));
  d.append(new El('div', { 'data-sitekey': '6LDialogScoped00000000000000000000' }));
  const r = runDetect(new El('body').append(d));
  assert.equal(r.visible, true);
  assert.equal(r.kind, 'recaptcha_enterprise');
  assert.equal(r.sitekey, '6LDialogScoped00000000000000000000');  // dialog-scoped data-sitekey
  assert.equal(r.invisible, false);
});

/* ——— visible.js — the gate predicate (is_security_dialog_visible) ———
   The 2026-09-18 user report: the reCAPTCHA widget on screen (badge
   state) made the app start the captcha flow. The badge must never
   count; a real challenge dialog still must. */

const runVisible = (body) => {
  const document = makeDoc(body);
  const window = {
    innerWidth: 1600,
    innerHeight: 900,
    getComputedStyle: (el) => (el && el._style) || { display: 'block', visibility: 'visible' },
  };
  const fn = new Function('document', 'window', `return (${probe('visible.js')});`);
  return fn(document, window);
};

test('visible: badge widget on screen (normal state) is NOT a challenge', () => {
  const r = runVisible(new El('body').append(...realBadge()));
  assert.equal(r, false);  // ← the user report: do not start the captcha flow
});

test('visible: open challenge dialog is a challenge', () => {
  assert.equal(runVisible(new El('body').append(realDialog())), true);
});

test('visible: badge + open dialog coexist → challenge (dialog wins)', () => {
  assert.equal(runVisible(new El('body').append(...realBadge(), realDialog())), true);
});

test('visible: closed dialog + badge → not a challenge', () => {
  const iframe = new El('iframe', { title: 'reCAPTCHA', src: DIALOG_SRC });
  const d = new El('div', { role: 'dialog', 'data-state': 'closed', _text: 'Security Verification' });
  d.append(iframe);
  iframe._hidden = true;  // closed Radix dialog unmounts its children
  assert.equal(runVisible(new El('body').append(...realBadge(), d)), false);
});

test('visible: classic standalone visible reCAPTCHA iframe (no badge) still counts', () => {
  const r = runVisible(new El('body').append(
    new El('iframe', { title: 'reCAPTCHA', src: 'https://www.google.com/recaptcha/api2/anchor?k=6Lx' }),
  ));
  assert.equal(r, true);
});

test('visible: hidden badge iframe (never rendered) is not a challenge either', () => {
  const f = new El('iframe', { title: 'reCAPTCHA', src: BADGE_SRC });
  f._hidden = true;
  const badge = new El('div', { class: 'grecaptcha-badge' });
  badge.append(f);
  assert.equal(runVisible(new El('body').append(badge)), false);
});

test('visible: off-screen widget (right:-186px past viewport) is NOT on screen', () => {
  // saved-state badge geometry: laid out (offsetParent set) but off-screen
  const f = new El('iframe', { title: 'reCAPTCHA', src: 'https://www.google.com/recaptcha/enterprise/anchor?ar=1&k=6Lx&size=invisible' });
  f._rect = { top: 0, left: 2000, right: 2256, bottom: 60, width: 256, height: 60 };
  assert.equal(runVisible(new El('body').append(f)), false);
});

test('visible: visibility:hidden ancestor (saved-state badge style) is NOT on screen', () => {
  // no badge class here — the geometry/visibility walk must catch it alone
  const wrap = new El('div', { _style: { display: 'block', visibility: 'hidden' } });
  const f = new El('iframe', { title: 'reCAPTCHA', src: 'https://www.google.com/recaptcha/enterprise/anchor?k=6Lx' });
  wrap.append(f);
  assert.equal(runVisible(new El('body').append(wrap)), false);
});

test('visible: display:none ancestor is NOT on screen', () => {
  const wrap = new El('div', { _style: { display: 'none', visibility: 'visible' } });
  const f = new El('iframe', { title: 'reCAPTCHA', src: 'https://www.google.com/recaptcha/enterprise/anchor?k=6Lx' });
  wrap.append(f);
  assert.equal(runVisible(new El('body').append(wrap)), false);
});

/* ——— inject probe ——— */

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
  class Event { constructor(type, init) { this.type = type; this.bubbles = !!(init && init.bubbles); } }
  const fn = new Function('document', 'HTMLTextAreaElement', 'HTMLInputElement', 'Event', 'window',
                          'return (' + probe('inject.js') + ')');
  return fn(document, HTMLTextAreaElement, HTMLInputElement, Event, win)(token);
};

test('inject: sets dialog-scoped hidden field with events', () => {
  const field = new El('textarea', { name: 'g-recaptcha-response' });
  const d = securityDialog({});
  d.append(field);  // field inside the dialog → dialog-scope path
  const document = makeDoc(new El('body').append(d));
  const proto = {};
  Object.defineProperty(proto, 'value', { configurable: true, get() { return this._value; }, set(v) { this._value = String(v); } });
  class Event { constructor(type, init) { this.type = type; this.bubbles = !!(init && init.bubbles); } }
  const fn = new Function('document', 'HTMLTextAreaElement', 'HTMLInputElement', 'Event',
                          'return (' + probe('inject.js') + ')');
  const r = fn(document, { prototype: proto }, { prototype: proto }, Event)('TOKEN123');
  assert.equal(r.ok, true);
  assert.equal(r.scope, 'dialog');
  assert.equal(field._value, 'TOKEN123');
  assert.deepEqual(field.events.map(e => e.type), ['input', 'change']);  // React-safe events fired
});

test('inject: falls back to document-level field', () => {
  const d = securityDialog({});
  const field = new El('input', { name: 'g-recaptcha-response' });
  const body = new El('body').append(d, field);
  const r = runInject('TOK9', body);
  assert.equal(r.ok, true);
  assert.equal(r.scope, 'document');
  assert.equal(field._value, 'TOK9');
});

test('inject: no field on page → ok:false with error', () => {
  const r = runInject('TOK', new El('body').append(securityDialog({})));
  assert.equal(r.ok, false);
  assert.match(r.error, /response field not found/);
});

test('inject: invokes the dialog anchor callback with the token (the real solve path)', () => {
  let got = null;
  const d = securityDialog({ iframeSrc: 'https://www.google.com/recaptcha/enterprise/anchor?ar=1&k=6LEnterpkey0000000000000000000&size=normal&cb=abc123' });
  d.append(new El('textarea', { name: 'g-recaptcha-response' }));
  const win = { abc123: (tok) => { got = tok; } };
  const r = runInject('TOK_CB', new El('body').append(d), win);
  assert.equal(r.ok, true);
  assert.equal(r.scope, 'dialog');
  assert.equal(r.cb, 'abc123');
  assert.equal(r.cbCalled, true);
  assert.equal(r.cbError, null);
  assert.equal(got, 'TOK_CB');
});

test('inject: no cb in anchor → ok, cb null, no window call', () => {
  const d = securityDialog({ iframeSrc: 'https://www.google.com/recaptcha/enterprise/anchor?ar=1&k=6LEnterpkey0000000000000000000&size=normal' });
  d.append(new El('textarea', { name: 'g-recaptcha-response' }));
  const r = runInject('TOK2', new El('body').append(d), {});
  assert.equal(r.ok, true);
  assert.equal(r.cb, null);
  assert.equal(r.cbCalled, false);
});

test('inject: cb throwing → ok, cbError captured, injection still counts', () => {
  const d = securityDialog({ iframeSrc: 'https://www.google.com/recaptcha/enterprise/anchor?k=6LEnterpkey0000000000000000000&cb=boom9' });
  d.append(new El('textarea', { name: 'g-recaptcha-response' }));
  const win = { boom9: () => { throw new Error('handler down'); } };
  const r = runInject('TOK3', new El('body').append(d), win);
  assert.equal(r.ok, true);
  assert.equal(r.cb, 'boom9');
  assert.equal(r.cbCalled, false);
  assert.match(r.cbError, /handler down/);
});

/* ——— continue-click probe ——— */

const runContinue = (body) => {
  const document = makeDoc(body);
  const fn = new Function('document', `return (${probe('continue_click.js')});`);
  return fn(document);
};

test('continue: clicks the dialog submit button', () => {
  const btn = new El('button', { type: 'submit' });
  const r = runContinue(new El('body').append(securityDialog({ button: btn })));
  assert.equal(r.ok, true);
  assert.equal(btn.clicked, true);
});

test('continue: matches aria-label verify', () => {
  const btn = new El('button', { 'aria-label': 'Verify and continue' });
  const r = runContinue(new El('body').append(securityDialog({ button: btn })));
  assert.equal(r.ok, true);
  assert.equal(btn.clicked, true);
});

test('continue: matches exact button text', () => {
  const btn = new El('button', { _text: 'Continue' });
  const r = runContinue(new El('body').append(securityDialog({ button: btn })));
  assert.equal(r.ok, true);
  assert.equal(btn.clicked, true);
});

test('continue: no action button → ok:false (site auto-submits instead)', () => {
  const r = runContinue(new El('body').append(securityDialog({})));
  assert.equal(r.ok, false);
});

test('continue: disabled buttons are skipped', () => {
  const btn = new El('button', { type: 'submit', disabled: 'disabled' });
  btn.disabled = true;
  const r = runContinue(new El('body').append(securityDialog({ button: btn })));
  assert.equal(r.ok, false);
  assert.equal(btn.clicked, false);
});
