/**
 * Tier A — S7 receiver icon: the ⊘ span in the status cell (Node.js, no browser).
 * rowHtml shows ⊘ after the status chip exactly when u.receiver === false,
 * with a "Not receiving: <reason>" title; the span reads u.receiver/u.reason only.
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const RENDER = path.resolve(__dirname, '../../app/ui/web/js/panels/url-list/render.js');
const STORE = path.resolve(__dirname, '../../app/ui/web/js/panels/url-list/store.js');

function loadRender() {
  const sandbox = { console, JSON, Math, Object, Array, Map, Set, Error,
    document: undefined, PagePoolPanel: undefined, CDPPanel: undefined };
  sandbox.self = sandbox;
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(STORE, 'utf-8'), sandbox, { filename: 'store.js' });
  vm.runInContext(fs.readFileSync(RENDER, 'utf-8'), sandbox, { filename: 'render.js' });
  return sandbox.UrlListRender;
}

const Render = loadRender();

describe('receiver icon', () => {
  test('minimal row with receiver:false shows the icon', () => {
    const html = Render.rowHtml({ id: 'u1', url: 'https://arena.ai/c/x', receiver: false });
    assert.ok(html.includes('⊘'), 'icon shown');
    assert.ok(html.includes('url-recv-off'), 'icon class present');
  });

  test('icon sits in the 3rd cell, after the status chip, nowhere else', () => {
    const html = Render.rowHtml({ id: 'u1', url: 'https://arena.ai/c/x',
      status: 'ok', receiver: false, reason: 'offline' });
    const cells = html.split('<td');
    assert.equal(cells.length, 9);  // 8 cells + the pre-first-cell head
    const status = cells[3];
    assert.ok(status.indexOf('url-status-') !== -1, 'status chip in 3rd cell');
    assert.ok(status.indexOf('⊘') > status.indexOf('url-status-'), 'icon after the chip');
    for (const i of [1, 2, 4, 5, 6, 7, 8]) {
      assert.ok(!cells[i].includes('⊘'), `no icon in cell ${i}`);
    }
  });

  test('receiving rows show no icon', () => {
    for (const u of [{ id: 'u1', url: 'https://x', receiver: true },
                     { id: 'u2', url: 'https://x' }]) {
      assert.ok(!Render.rowHtml(u).includes('⊘'), `no icon for ${u.id}`);
    }
  });

  test('title carries each reason wording', () => {
    for (const reason of ['no tab assigned', 'not running', 'offline']) {
      const html = Render.rowHtml({ id: 'u1', url: 'https://x', receiver: false, reason });
      assert.ok(html.includes(`Not receiving: ${reason}`), `title for "${reason}"`);
    }
  });

  test('source lock: 73 lines, 12 funcs, span reads receiver+reason only', () => {
    const src = fs.readFileSync(RENDER, 'utf-8');
    assert.equal(src.trimEnd().split('\n').length, 73);
    const methods = (src.match(/^  (?!if|for|while|switch|catch|return|const|let|var)[A-Za-z_$][\w$]*\s*\(/gm) || []).length;
    const arrows = (src.match(/=>/g) || []).length;
    assert.equal(methods + arrows, 12);
    const at = src.indexOf('url-recv-off');
    assert.ok(at !== -1, 'icon span present');
    const span = src.slice(src.lastIndexOf('${', at), src.indexOf('</span>', at));
    assert.ok(span.includes('u.receiver') && span.includes('u.reason'), 'reads receiver+reason');
    assert.ok(!span.includes('u.enabled') && !span.includes('u.tab_id'), 'reads nothing else');
  });
});
