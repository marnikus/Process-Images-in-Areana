/* Is this tab on a NEW chat? — the probe a job asks before it starts (I-74, 2026-09-27).
 *
 * Owner request: "the app does not check if the new job goes on a new chat page or not —
 * verify it; if not, start a new chat first." A job runs on whatever the tab shows, so a
 * failed post-job reset (or a chat the user opened) sent the next image into an old
 * conversation. The saved Arena page (docs/research/Directly Chat…html, saved from
 * arena.ai/c/01a0a4f3-…) is the real "started chat": its path and its user message must
 * each be enough. A fresh New Chat page keeps JOB-ID titles in the sidebar and a promo
 * image — neither is a conversation.
 */
import { test, describe, before } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const SAVED = path.join(ROOT, 'docs/research/Directly Chat with Frontier Image Generation AI Models.html');
const NEW_CHAT = 'https://arena.ai/image/direct?model_a=max';

function findPython() {
  const cands = [process.env.PYTHON, path.join(ROOT, '.venv/bin/python'), path.join(ROOT, '.venv/Scripts/python.exe'),
    'python3', 'python'].filter(Boolean);
  for (const c of cands) {
    try { execFileSync(c, ['-c', 'import sys'], { stdio: 'ignore' }); return c; } catch { /* next */ }
  }
  return assert.fail('no Python interpreter found — set PYTHON=<path>');
}

let PROBE;
before(() => {
  const py = 'import json\nfrom app.browser.chat_page import build_chat_page_js\nprint(json.dumps(build_chat_page_js()))';
  PROBE = JSON.parse(execFileSync(findPython(), ['-c', py], { cwd: ROOT, encoding: 'utf-8' }));
});

function run(html, url) {
  const w = new JSDOM(html, { url, runScripts: 'outside-only' }).window;
  return JSON.parse(JSON.stringify(w.eval(PROBE)));
}

const SIDEBAR = '<nav data-sidebar="sidebar"><a href="/image/direct"><span>New Chat</span></a>'
  + '<a data-sidebar="menu-button"><span class="truncate">[JOB-ID: 20260927-223815-YGM5] Keep aspect</span></a>'
  + '<div class="flex"><img class="cursor-pointer" src="https://img.youtube.com/vi/x/promo.jpg"></div></nav>';
const composer = (value = '', attach = '') => '<main><form class="flex w-full flex-col">'
  + `<div class="flex flex-wrap gap-2">${attach}</div><textarea name="message">${value}</textarea></form></main>`;

describe('the chat-page probe', () => {
  test('a fresh New Chat page: nothing of a conversation (sidebar JOB-IDs and the promo image do not count)', () => {
    assert.deepEqual(run(`<body>${SIDEBAR}${composer()}</body>`, NEW_CHAT),
      { path: '/image/direct', messages: 0, outputs: 0, attachments: 0, composer: 0 });
  });

  test('the saved Arena chat at its own address: path /c/… and one user message', () => {
    const state = run(fs.readFileSync(SAVED, 'utf-8'), 'https://arena.ai/c/01a0a4f3-b60a-7169-8e15-aa3f099d8e4e');
    assert.equal(state.path, '/c/01a0a4f3-b60a-7169-8e15-aa3f099d8e4e');
    assert.equal(state.messages, 1);
    assert.equal(state.composer, 0);
  });

  test('the same saved chat shown under /image/direct is still caught by its message', () => {
    assert.equal(run(fs.readFileSync(SAVED, 'utf-8'), NEW_CHAT).messages, 1);
  });

  test('a finished image from Arena storage is counted (owner HTML 22:40)', () => {
    const out = '<ol><div class="flex w-full flex-row"><div class="relative"><img loading="lazy" '
      + 'src="https://messages-prod.x.r2.cloudflarestorage.com/a/1.png?X-Amz-Date=1"></div></div></ol>';
    assert.equal(run(`<body>${SIDEBAR}${out}${composer()}</body>`, NEW_CHAT).outputs, 1);
  });

  test('leftovers in the prompt box: text and an attached file inside the composer form', () => {
    const state = run(`<body>${SIDEBAR}${composer('old prompt', '<img alt="a.png" src="blob:x">')}</body>`, NEW_CHAT);
    assert.equal(state.composer, 10);
    assert.equal(state.attachments, 1);
  });

  test('no prompt box at all is reported as -1', () => {
    assert.equal(run(`<body>${SIDEBAR}</body>`, NEW_CHAT).composer, -1);
  });
});
