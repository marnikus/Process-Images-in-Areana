/* diagnose.js probe tests — verdict + evidence for the observable security
   gate (cdp_arena._security_gate) and the on-demand "Scan now" report.
   Regression: the per-poll gate was a silent no-op (no settler armed in the
   bridge block runner) and the boolean verdict gave no "what was on screen".
   Verdict logic must stay IDENTICAL to visible.js (the canonical gate).
   Docs: docs/archive/2026-09-18-captcha-wait-visibility/design.md */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const probe = (name) => readFileSync(join(ROOT, 'app', 'browser', 'captcha_js', name), 'utf8').trim();

/* ——— minimal DOM stub (same surface as test_captcha.mjs) ——— */

class El {
  constructor(tag, attrs = {}) {
    this.tagName = String(tag).toUpperCase();
    this.nodeType = 1;
    this.attrs = { ...attrs };
    this.children = [];
    this.parent = null;
    this._text = attrs._text || '';
    this._style = attrs._style || null;
    this._rect = null;
    this._hidden = false;
  }
  get parentElement() { return this.parent; }
  getBoundingClientRect() {
    return this._rect || { top: 0, left: 0, right: 100, bottom: 100, width: 100, height: 100 };
  }
  append(...els) { els.forEach(e => { e.parent = this; this.children.push(e); }); return this; }
  getAttribute(n) { return this.attrs[n] !== undefined ? String(this.attrs[n]) : null; }
  get offsetParent() { return this._hidden ? null : {}; }
  get innerText() { return this._text; }
  get textContent() { return this._text || this.children.map(c => c.textContent).join(''); }
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

const makeDoc = (body) => ({
  body,
  children: body.children,
  querySelector: (sel) => qsa(makeDoc(body), sel)[0] || null,
  querySelectorAll: (sel) => qsa(makeDoc(body), sel),
});

const location = { href: 'https://arena.ai/image/direct' };

function runDiagnose(body) {
  const document = makeDoc(body);
  const window = {
    innerWidth: 1600,
    innerHeight: 900,
    getComputedStyle: (el) => (el && el._style) || { display: 'block', visibility: 'visible' },
  };
  const fn = new Function('document', 'window', 'location', `return (${probe('diagnose.js')});`);
  return fn(document, window, location);
}

const DIALOG_SRC = 'https://www.google.com/recaptcha/enterprise/anchor?ar=1&k=6Le3_cYsAAAAAGwWOK2RLDgNI15Bh8C0yLBOL1yL&co=aHR0cHM6Ly9hcmVuYS5haTo0NDM.&hl=en&v=zqB-6Xpbd3lCIvi7Tr2D0pob&theme=light&size=normal&anchor-ms=20000&execute-ms=30000&cb=cf1ox98i3rhg';
const BADGE_SRC = 'https://www.google.com/recaptcha/enterprise/anchor?ar=1&k=6LeTGMcsAAAAALuIlkVwIxaAuZA8VledA6d3Nnb0&size=invisible&anchor-ms=20000&execute-ms=30000&cb=t3pnrgbyrriv';

function realDialog() {
  const d = new El('div', { role: 'dialog', 'data-state': 'open', _text: 'Security Verification' });
  const container = new El('div', { class: 'recaptcha-v2-container', id: 'recaptcha-v2-container' });
  const f = new El('iframe', { title: 'reCAPTCHA', src: DIALOG_SRC });
  f._rect = { top: 387, left: 1128, right: 1432, bottom: 465, width: 304, height: 78 };
  container.append(f);
  d.append(container);
  d.append(new El('span', { _text: 'Protected by reCAPTCHA' }));
  return d;
}

function realBadge() {
  const badge = new El('div', { class: 'grecaptcha-badge' });
  badge.append(new El('iframe', { title: 'reCAPTCHA', src: BADGE_SRC }));
  return [badge, new El('textarea', { id: 'g-recaptcha-response-100000' })];
}

test('diagnose: badge-only (normal state) → clear, badge reason in evidence', () => {
  const r = runDiagnose(new El('body').append(...realBadge()));
  assert.equal(r.visible, false);
  assert.equal(r.kind, 'none');
  assert.equal(r.sitekey, '');
  assert.equal(r.evidence.dialogs_open, 0);
  assert.equal(r.evidence.iframes.length, 1);
  assert.equal(r.evidence.iframes[0].in_badge, true);
  assert.match(r.evidence.reason, /no open dialog/);
  assert.match(r.evidence.reason, /1 in badge/);
});

test('diagnose: real challenge dialog → challenge + DIALOG sitekey + geometry evidence', () => {
  const r = runDiagnose(new El('body').append(realDialog()));
  assert.equal(r.visible, true);
  assert.equal(r.kind, 'recaptcha_enterprise');
  assert.equal(r.sitekey, '6Le3_cYsAAAAAGwWOK2RLDgNI15Bh8C0yLBOL1yL');
  assert.equal(r.invisible, false);
  assert.equal(r.anchor.cb, true);
  assert.equal(r.anchor.size, 'normal');
  assert.equal(r.evidence.dialogs_open, 1);
  assert.match(r.evidence.dialog_hits[0].hits.join(','), /Security Verification/);
  assert.equal(r.evidence.iframes[0].in_dialog, true);
  assert.equal(r.evidence.iframes[0].on_screen, true);
  assert.equal(r.evidence.iframes[0].w, 304);
  assert.equal(r.evidence.iframes[0].h, 78);
  assert.equal(r.evidence.iframes[0].x, 1128);
  assert.match(r.evidence.reason, /open dialog/);
});

test('diagnose: badge + open dialog coexist → dialog wins with its own sitekey', () => {
  const body = new El('body').append(...realBadge(), realDialog());
  const r = runDiagnose(body);
  assert.equal(r.visible, true);
  assert.equal(r.sitekey, '6Le3_cYsAAAAAGwWOK2RLDgNI15Bh8C0yLBOL1yL');  // dialog key, not badge key
  assert.equal(r.evidence.iframes.length, 2);
});

test('diagnose: standalone on-screen iframe (no dialog, no badge) → challenge via iframe branch', () => {
  const f = new El('iframe', { title: 'reCAPTCHA', src: 'https://www.google.com/recaptcha/api2/anchor?k=6LV2key000000000000000000000' });
  const r = runDiagnose(new El('body').append(f));
  assert.equal(r.visible, true);
  assert.equal(r.kind, 'recaptcha_v2');
  assert.equal(r.sitekey, '6LV2key000000000000000000000');
  assert.match(r.evidence.reason, /iframe on screen/);
});

test('diagnose: closed dialog + hidden badge iframe → clear (parity with visible.js)', () => {
  const f = new El('iframe', { title: 'reCAPTCHA', src: DIALOG_SRC });
  const d = new El('div', { role: 'dialog', 'data-state': 'closed', _text: 'Security Verification' });
  d.append(f);
  f._hidden = true;
  const r = runDiagnose(new El('body').append(...realBadge(), d));
  assert.equal(r.visible, false);
  assert.match(r.evidence.reason, /no open dialog/);
});

test('diagnose: dialog with container + footer only (no iframe) → challenge, sitekey from data-sitekey', () => {
  const d = new El('div', { role: 'dialog', 'data-state': 'open', _text: 'Protected by reCAPTCHA' });
  d.append(new El('div', { class: 'recaptcha-v2-container' }));
  d.append(new El('div', { 'data-sitekey': '6LDialogScoped00000000000000000000' }));
  const r = runDiagnose(new El('body').append(d));
  assert.equal(r.visible, true);
  assert.equal(r.kind, 'recaptcha_enterprise');
  assert.equal(r.sitekey, '6LDialogScoped00000000000000000000');
  assert.match(r.evidence.reason, /open dialog/);
});

test('diagnose: nothing on page → clear with full counts in reason', () => {
  const r = runDiagnose(new El('body').append(new El('div')));
  assert.equal(r.visible, false);
  assert.equal(r.url, 'https://arena.ai/image/direct');
  assert.equal(r.evidence.dialogs_open, 0);
  assert.equal(r.evidence.iframes.length, 0);
  assert.match(r.evidence.reason, /0 recaptcha iframe\(s\)/);
});

/* verdict parity with the canonical gate — same verdicts on all of the
   visible.js regression states (badge never counts, dialog always does). */

test('diagnose: verdict matches visible.js on badge / dialog / coexist / hidden states', () => {
  const runVisible = (body) => {
    const document = makeDoc(body);
    const window = {
      innerWidth: 1600,
      innerHeight: 900,
      getComputedStyle: (el) => (el && el._style) || { display: 'block', visibility: 'visible' },
    };
    return new Function('document', 'window', `return (${probe('visible.js')});`)(document, window);
  };
  const f = new El('iframe', { title: 'reCAPTCHA', src: DIALOG_SRC });
  const closed = new El('div', { role: 'dialog', 'data-state': 'closed', _text: 'Security Verification' });
  closed.append(f);
  f._hidden = true;
  const states = [
    new El('body').append(...realBadge()),
    new El('body').append(realDialog()),
    new El('body').append(...realBadge(), realDialog()),
    new El('body').append(...realBadge(), closed),
  ];
  for (const body of states) {
    assert.equal(runDiagnose(body).visible, runVisible(body), 'verdict parity');
  }
});
