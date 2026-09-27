/* Log console (2026-09-27 D-5): follow-the-end scrolling + Copy all.
   RULE 8: runs the REAL app/ui/web/js/log-console.js in a vm with a
   small scroll model: every line is 20 px, scrollTop is clamped like a
   browser, and changing it fires `scroll`. The same file was driven in real
   Chromium with the real CSS (design §5). */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = fs.readFileSync(path.resolve(__dirname, '../../app/ui/web/js/log-console.js'), 'utf-8');
const LINE = 20;

function makeConsole() {
  const el = {
    children: [], _top: 0, clientHeight: 200, _listeners: {},
    get firstChild() { return this.children[0] || null; },
    get lastChild() { return this.children[this.children.length - 1] || null; },
    get scrollHeight() { return Math.max(this.clientHeight, this.children.length * LINE); },
    get scrollTop() { return this._top; },
    set scrollTop(v) {
      const next = Math.max(0, Math.min(v, this.scrollHeight - this.clientHeight));
      if (next === this._top) return;
      this._top = next;
      (this._listeners.scroll || []).forEach((f) => f());
    },
    appendChild(c) { this.children.push(c); return c; },
    removeChild(c) { this.children.splice(this.children.indexOf(c), 1); return c; },
    addEventListener(t, f) { (this._listeners[t] ||= []).push(f); },
    set innerHTML(_v) { this.children = []; this._top = 0; },
  };
  return el;
}

function button() {
  return { hidden: false, textContent: '', _click: [], addEventListener(t, f) { if (t === 'click') this._click.push(f); },
    click() { this._click.forEach((f) => f()); } };
}

function boot({ clipboard = null, execOk = true } = {}) {
  const timers = [];
  const els = { logConsole: makeConsole(), copyLogBtn: button(), logFollowBtn: button() };
  const body = { children: [], appendChild(c) { this.children.push(c); }, removeChild(c) { this.children.splice(this.children.indexOf(c), 1); } };
  const copied = [];
  const document = {
    body,
    getElementById: (id) => els[id] || null,
    createElement: (tag) => ({ tagName: tag, style: {}, offsetHeight: LINE, textContent: '', value: '',
      setAttribute() {}, select() { copied.push(this.value); } }),
    execCommand: (cmd) => (cmd === 'copy' ? execOk : false),
    addEventListener: () => {},
  };
  const sb = { document, window: {}, setTimeout: (fn) => { timers.push(fn); return timers.length; }, Date, Math, String };
  if (clipboard) sb.navigator = { clipboard };
  vm.createContext(sb);
  vm.runInContext(SRC + '\n;globalThis.LogConsole = LogConsole;', sb);
  const LC = sb.LogConsole;
  LC.init();
  const flush = () => timers.splice(0).forEach((f) => f());
  const add = (n, from = 0) => { for (let i = from; i < from + n; i++) LC.log('line ' + i); flush(); };
  return { LC, el: els.logConsole, chip: els.logFollowBtn, copyBtn: els.copyLogBtn, flush, add, copied };
}

const firstLine = (el) => el.children[0].textContent.slice(11);
const atEnd = (el) => el.scrollTop === el.scrollHeight - el.clientHeight;

describe('log console — follow mode', () => {
  test('follows the end while the view is at the end; the chip stays hidden', () => {
    const { el, chip, add } = boot();
    add(50);
    assert.ok(atEnd(el));
    assert.equal(chip.hidden, true);
  });

  test('scrolling up pauses: new lines do not move the view, the chip counts them', () => {
    const { el, chip, add } = boot();
    add(50);
    el.scrollTop = 100;
    add(30, 50);
    assert.equal(el.scrollTop, 100, 'view stayed where the user is reading');
    assert.equal(chip.hidden, false);
    assert.equal(chip.textContent, '⬇ 30 new');
  });

  test('scrolling back to the end resumes following', () => {
    const { el, chip, add } = boot();
    add(50);
    el.scrollTop = 0;
    add(5, 50);
    el.scrollTop = el.scrollHeight;          // user drags to the bottom
    assert.equal(chip.hidden, true);
    add(5, 55);
    assert.ok(atEnd(el));
  });

  test('the chip jumps to the end and follows again', () => {
    const { el, chip, add } = boot();
    add(50);
    el.scrollTop = 0;
    add(3, 50);
    chip.click();
    assert.ok(atEnd(el));
    assert.equal(chip.hidden, true);
    add(3, 53);
    assert.ok(atEnd(el));
  });

  test('while paused the lines being read are not trimmed away; following trims back to 500', () => {
    const { LC, el, add } = boot();
    add(500);
    el.scrollTop = 40;                       // reading line 2
    add(300, 500);
    assert.equal(el.children.length, 800);
    assert.equal(el.scrollTop, 40);
    assert.equal(firstLine(el), 'line 0');
    el.scrollTop = el.scrollHeight;
    add(1, 800);
    assert.equal(el.children.length, LC._maxEntries);
    assert.ok(atEnd(el));
  });

  test('paused beyond the history cap: the top trim keeps the same line in view', () => {
    const { LC, el, add } = boot();
    LC._maxHistory = 100;
    add(100);
    el.scrollTop = 400;                      // line 20 at the top of the view
    add(10, 100);
    assert.equal(el.children.length, 100);
    assert.equal(firstLine(el), 'line 10');
    assert.equal(el.scrollTop, 200, 'shifted up by the 10 removed lines → still line 20');
  });

  test('a follow-scroll already scheduled does not jump if the user scrolled up meanwhile', () => {
    const { el, LC, flush, add } = boot();
    add(50);
    LC.log('pending');                       // schedules the follow-scroll
    el.scrollTop = 0;                        // user scrolls up before it runs
    flush();
    assert.equal(el.scrollTop, 0);
  });

  test('clear empties the view and the history and follows again', () => {
    const { LC, el, chip, add } = boot();
    add(50);
    el.scrollTop = 0;
    add(2, 50);
    LC.clear();
    assert.equal(el.children.length, 0);
    assert.equal(LC.allText(), '');
    assert.equal(chip.hidden, true);
  });
});

describe('log console — Copy all', () => {
  test('copies the whole history, including lines trimmed from the screen, through navigator.clipboard', async () => {
    const written = [];
    const { LC, copyBtn, add } = boot({ clipboard: { writeText: async (t) => { written.push(t); } } });
    add(600);
    assert.equal(LC._el.children.length, 500);
    copyBtn.click();
    await new Promise((r) => setImmediate(r));
    const lines = written[0].split('\n');
    assert.equal(lines.length, 600);
    assert.match(lines[0], /^\[\d\d:\d\d:\d\d\] line 0$/);
    assert.equal(copyBtn.textContent, 'Copied ✓');
    assert.match(LC.allText().split('\n').pop(), /📋 Copied 600 log line\(s\) to the clipboard$/);
  });

  test('a refused clipboard falls back to execCommand("copy") with the same text', async () => {
    const { LC, copyBtn, add, copied } = boot({ clipboard: { writeText: async () => { throw new Error('denied'); } } });
    add(3);
    const ok = await LC.copyAll();
    assert.equal(ok, true);
    assert.equal(copied[0].split('\n').length, 3);
    assert.equal(copyBtn.textContent, 'Copied ✓');
  });

  test('no clipboard API: fallback; both failing is reported honestly', () => {
    const { LC, copyBtn, add } = boot({ execOk: false });
    add(2);
    assert.equal(LC.copyAll(), false);
    assert.equal(copyBtn.textContent, 'Copy failed');
    assert.match(LC.allText(), /⚠ Could not copy the log to the clipboard$/);
  });

  test('a repeated line updates its (xN) count in the history too', () => {
    const { LC } = boot();
    LC.log('same');
    LC.log('same');
    LC.log('same');
    assert.match(LC.allText(), /\] same \(x3\)$/);
    assert.equal(LC._history.length, 1);
  });
});
