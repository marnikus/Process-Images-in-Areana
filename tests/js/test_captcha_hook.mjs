/* Render-hook tests — execute the REAL recaptcha_hook.js + inject.js
   (RULE 8: run, don't string-assert). The hook captures the dialog
   widget's sitecallback closure so the solver can resolve arena's own
   token promise (docs/archive/2026-09-18-captcha-escalation-path). */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const probe = (name) => readFileSync(join(ROOT, 'app', 'browser', 'captcha_js', name), 'utf8').trim();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const runHook = (win) => {
  const fn = new Function('window', `return (${probe('recaptcha_hook.js')});`);
  return fn(win);
};

const makeWin = (render) => {
  const calls = [];
  const orig = (container, opts) => { calls.push({ container, opts }); return 'widget-1'; };
  const ent = { ready: (f) => {}, __renderCalls: calls };
  if (render !== null) ent.render = orig;
  return { grecaptcha: { enterprise: ent }, calls };
};

test('hook: install wraps render and captures the sitecallback closure', () => {
  const win = makeWin(true);
  const r = runHook(win);
  assert.deepEqual(r, {installed: true, fresh: true, ready: true});
  const ent = win.grecaptcha.enterprise;
  assert.equal(ent.__hooked, true);
  const cb = (t) => { win.__resolved = t; };
  const id = ent.render('container', {sitekey: 'DIALOGKEY', callback: cb});
  assert.equal(id, 'widget-1');                    // original render still runs
  assert.equal(win.calls.length, 1);
  const ch = win.__arenaV2Challenge;
  assert.ok(ch && ch.sitekey === 'DIALOGKEY');
  assert.equal(typeof ch.ts, 'number');
  assert.equal(ch.solve('TOK'), true);
  assert.equal(win.__resolved, 'TOK');             // the closure fired with our token
});

test('hook: solve returns false when the callback throws', () => {
  const win = makeWin(true);
  runHook(win);
  win.grecaptcha.enterprise.render('c', {
    sitekey: 'K', callback: () => { throw new Error('boom'); },
  });
  assert.equal(win.__arenaV2Challenge.solve('TOK'), false);
});

test('hook: idempotent — second eval is a no-op, no double wrap', () => {
  const win = makeWin(true);
  const first = runHook(win);
  const second = runHook(win);
  assert.equal(first.fresh, true);
  assert.deepEqual(second, {installed: true, fresh: false, ready: true});
  const cb = () => {};
  win.grecaptcha.enterprise.render('c', {sitekey: 'K', callback: cb});
  assert.equal(win.calls.length, 1);               // wrapped exactly once
});

test('hook: library still loading — installs once render appears (200 ms poll)', async () => {
  const win = makeWin(null);                       // loader stub: ready() only
  const r = runHook(win);
  assert.deepEqual(r, {installed: true, fresh: true, ready: false});
  assert.equal(win.grecaptcha.enterprise.__hooked, undefined);
  await sleep(100);
  win.grecaptcha.enterprise.render = (c, o) => { win.calls.push({c, o}); return 'w'; };
  await sleep(450);                                // next poll tick wraps it
  const ent = win.grecaptcha.enterprise;
  assert.equal(ent.__hooked, true);
  const cb = (t) => { win.__resolved = t; };
  ent.render('c', {sitekey: 'K2', callback: cb});
  assert.equal(win.__arenaV2Challenge.sitekey, 'K2');
  assert.equal(win.__arenaV2Challenge.solve('T2'), true);
  assert.equal(win.__resolved, 'T2');
});

test('hook: second challenge overwrites the capture (one widget at a time)', () => {
  const win = makeWin(true);
  runHook(win);
  const ent = win.grecaptcha.enterprise;
  let first, second;
  ent.render('c1', {sitekey: 'K1', callback: (t) => { first = t; }});
  ent.render('c2', {sitekey: 'K2', callback: (t) => { second = t; }});
  assert.equal(win.__arenaV2Challenge.sitekey, 'K2');
  win.__arenaV2Challenge.solve('TOK');
  assert.equal(first, undefined);                  // stale closure not used
  assert.equal(second, 'TOK');
});

/* ——— inject.js: canonical path first, field path as fallback ——— */

const runInject = (token, win = {}) => {
  const body = { children: [] };
  const document = { querySelector: () => null, querySelectorAll: () => [], body, children: [] };
  const fn = new Function('document', 'HTMLTextAreaElement', 'HTMLInputElement', 'Event', 'window',
                          `return (${probe('inject.js')})`);
  const inject = fn(document, {}, {}, class Event {}, win);
  return inject(token);
};

test('inject: captured challenge → canonical path, no DOM touched', () => {
  const win = {};
  let got = null;
  win.__arenaV2Challenge = {sitekey: 'K', ts: Date.now(), solve: (t) => { got = t; return true; }};
  const r = runInject('TOK_HOOK', win);
  assert.deepEqual(r, {ok: true, path: 'hook', cb: 'hook', cbCalled: true});
  assert.equal(got, 'TOK_HOOK');
});

test('inject: challenge solve rejected → falls back to the field path', () => {
  const win = {__arenaV2Challenge: {sitekey: 'K', ts: Date.now(), solve: () => false}};
  const r = runInject('TOK', win);
  assert.equal(r.ok, false);                       // no field in this bare DOM → field path fails
  assert.equal(r.path, undefined);
});

test('detect: hook evidence — captured challenge reported with age', () => {
  const body = { children: [] };
  const document = { querySelector: () => null, querySelectorAll: () => [], body, children: [] };
  const location = {href: 'https://arena.ai/c/xyz'};
  const win = {__arenaV2Challenge: {sitekey: 'DIALOGKEY', ts: Date.now() - 5000}};
  const fn = new Function('document', 'location', 'window', `return (${probe('detect.js')});`);
  const r = fn(document, location, win);
  assert.equal(r.hook.captured, true);
  assert.equal(r.hook.sitekey, 'DIALOGKEY');
  assert.ok(r.hook.ageSec >= 4.5 && r.hook.ageSec < 6);
});

test('detect: hook evidence — ready but not captured / absent window', () => {
  const body = { children: [] };
  const document = { querySelector: () => null, querySelectorAll: () => [], body, children: [] };
  const location = {href: 'https://arena.ai/c/xyz'};
  const fn = new Function('document', 'location', 'window', `return (${probe('detect.js')});`);
  const r1 = fn(document, location, {grecaptcha: {enterprise: {render: () => 1}}});
  assert.equal(r1.hook.ready, true);
  assert.equal(r1.hook.captured, false);
  assert.equal(r1.hook.sitekey, '');
  assert.equal(r1.hook.ageSec, -1);
  const r2 = fn(document, location, {});
  assert.equal(r2.hook.ready, false);
  assert.equal(r2.hook.captured, false);
});
