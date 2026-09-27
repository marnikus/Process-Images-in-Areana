/* Activity Log: "Copy all" + follow-the-bottom only while the user is there (I-69, 2026-09-27).
 *
 * Owner: "add button copy all to log win to copy full log stack to clipboard. In Logs terminal
 * win add feature not stick new content to the bottom and push down if user scroll the logs up
 * and return it back if user scrolls the win back to the bottom."
 * The REAL log-console.js + log-tools.js run as classic <script>s in jsdom (they share the
 * global scope exactly as on the page); jsdom has no layout, so each test sets the console's
 * scroll metrics.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';

const JS = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../app/ui/web/js');
const src = (f) => fs.readFileSync(path.join(JS, f), 'utf-8');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function page({ execOk = true, asyncOk = null } = {}) {
  const html = '<button id="copyLogBtn">Copy all</button><button id="clearLogBtn">Clear</button><div id="logConsole"></div>'
    + `<script>${src('log-console.js')}</script><script>${src('log-tools.js')}</script>`;
  const w = new JSDOM(`<body>${html}</body>`, { runScripts: 'dangerously' }).window;
  const el = w.document.getElementById('logConsole');
  const box = { height: 1000, client: 200, top: 800 };            // starts scrolled to the bottom
  Object.defineProperty(el, 'scrollHeight', { get: () => box.height });
  Object.defineProperty(el, 'clientHeight', { get: () => box.client });
  Object.defineProperty(el, 'scrollTop', { get: () => box.top, set: (v) => { box.top = v; } });
  const copied = [];
  w.document.execCommand = (cmd) => {
    copied.push({ cmd, text: w.document.querySelector('textarea')?.value });
    return execOk;
  };
  if (asyncOk !== null) {
    Object.defineProperty(w.navigator, 'clipboard', { configurable: true, value: {
      writeText: async (t) => { copied.push({ cmd: 'async', text: t }); if (!asyncOk) throw new Error('NotAllowed'); },
    } });
  }
  const run = (code) => w.eval(code);
  return { w, el, box, copied, run, lines: () => [...el.children].map((c) => c.textContent) };
}

describe('follow the bottom only while the user is there', () => {
  test('at the bottom: a new line scrolls the view down', async () => {
    const p = page();
    p.run('LogConsole.log("one")');
    p.box.height = 1040;                    // the new line grew the content…
    await sleep(150);
    assert.equal(p.box.top, 1040, '…and the view follows it');
  });

  test('scrolled up: new lines never move the view', async () => {
    const p = page();
    p.box.top = 100;                         // the user is reading older lines
    p.run('LogConsole.log("one"); LogConsole.log("two")');
    await sleep(150);
    assert.equal(p.box.top, 100);
    assert.equal(p.lines().length, 2, 'the lines are still added');
  });

  test('back at the bottom: following resumes', async () => {
    const p = page();
    p.box.top = 100;
    p.run('LogConsole.log("while up")');
    await sleep(150);
    p.box.top = p.box.height - p.box.client - 10;   // within the slack = "at the bottom"
    p.run('LogConsole.log("after return")');
    p.box.height = 1100;
    await sleep(150);
    assert.equal(p.box.top, 1100);
  });

  test('atBottom: a few pixels of slack count as the bottom; no element = follow', () => {
    const p = page();
    assert.equal(p.run('LogTools.atBottom(document.getElementById("logConsole"))'), true);
    p.box.top = 700;
    assert.equal(p.run('LogTools.atBottom(document.getElementById("logConsole"))'), false);
    assert.equal(p.run('LogTools.atBottom(null)'), true);
  });
});

describe('the full history behind "Copy all"', () => {
  test('keeps every line past the 500-row display trim', () => {
    const p = page();
    p.run('for (let i = 0; i < 600; i++) LogConsole.log("msg " + i)');
    assert.equal(p.lines().length, 500, 'the display still trims');
    assert.equal(p.run('LogTools.count()'), 600);
    const text = p.run('LogTools.text()').split('\n');
    assert.match(text[0], /^\[\d\d:\d\d:\d\d\] msg 0$/);
    assert.match(text[599], /msg 599$/);
  });

  test('a folded repeat updates the last history line; Clear empties both', () => {
    const p = page();
    p.run('LogConsole.log("same"); LogConsole.log("same")');
    assert.equal(p.run('LogTools.count()'), 1);
    assert.match(p.run('LogTools.text()'), /same \(x2\)$/);
    p.run('LogConsole.clear()');
    assert.equal(p.lines().length, 0);
    assert.equal(p.run('LogTools.count()'), 0);
  });

  test('history is bounded (MAX_LINES) — the oldest lines go first', () => {
    const p = page();
    p.run('LogTools.MAX_LINES = 3; ["a","b","c","d"].forEach((m) => LogTools.record(m))');
    assert.equal(p.run('LogTools.text()'), 'b\nc\nd');
  });
});

describe('Copy all', () => {
  test('the button copies every line inside the click and says so', async () => {
    const p = page();
    await sleep(20);                          // DOMContentLoaded → LogTools.init() wires the button
    p.run('LogConsole.log("first"); LogConsole.log("second", "error")');
    p.w.document.getElementById('copyLogBtn').click();
    await sleep(10);
    assert.equal(p.copied.length, 1);
    assert.equal(p.copied[0].cmd, 'copy');
    assert.match(p.copied[0].text, /first\n.*second$/);
    assert.equal(p.w.document.querySelector('textarea'), null, 'the helper textarea is removed');
    assert.match(p.lines().at(-1), /📋 Copied 2 log line\(s\) to the clipboard$/);
  });

  test('execCommand refused → navigator.clipboard takes over', async () => {
    const p = page({ execOk: false, asyncOk: true });
    p.run('LogConsole.log("x")');
    assert.equal(await p.run('LogTools.copyAll()'), true);
    assert.deepEqual(p.copied.map((c) => c.cmd), ['copy', 'async']);
  });

  test('both refused → an honest error line, never a silent success', async () => {
    const p = page({ execOk: false, asyncOk: false });
    p.run('LogConsole.log("x")');
    assert.equal(await p.run('LogTools.copyAll()'), false);
    assert.match(p.lines().at(-1), /Copy failed — select the log text and press Ctrl\+C$/);
    assert.ok(p.el.lastChild.className.includes('error'));
  });

  test('an empty log copies nothing and says so', async () => {
    const p = page();
    assert.equal(await p.run('LogTools.copyAll()'), false);
    assert.equal(p.copied.length, 0);
    assert.match(p.lines().at(-1), /Log is empty/);
  });
});
