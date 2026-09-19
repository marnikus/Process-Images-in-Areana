/**
 * test_ui_helpers.mjs — tests for ui-helpers.js dedup (C8)
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';
import vm from 'node:vm';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const uiHelpersPath = path.resolve(__dirname, '../../app/ui/web/js/core/ui-helpers.js');
const code = fs.readFileSync(uiHelpersPath, 'utf-8');

function loadHelpers() {
  const dom = new JSDOM('<!DOCTYPE html><html><body></body></html>');
  const window = dom.window;
  const sandbox = {
    window,
    document: window.document,
    console,
    String, Array, Object, JSON, Math,
  };
  sandbox.window = window;
  sandbox.document = window.document;
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  return sandbox.window.UIHelpers;
}

const UIHelpers = loadHelpers();

describe('ui-helpers', () => {
  test('esc escapes html', () => {
    assert.equal(UIHelpers.esc('<script>'), '&lt;script&gt;');
    assert.equal(UIHelpers.esc('a & b'), 'a &amp; b');
    assert.equal(UIHelpers.esc('"x"'), '&quot;x&quot;');
    assert.equal(UIHelpers.esc("'y'"), '&#39;y&#39;');
    assert.equal(UIHelpers.esc(null), '');
  });

  test('el creates element', () => {
    const el = UIHelpers.el('div', 'cls', 'hello');
    assert.equal(el.tagName, 'DIV');
    assert.equal(el.className, 'cls');
    assert.equal(el.textContent, 'hello');
  });

  test('chip creates chip node', () => {
    const chip = UIHelpers.chip({ title: 'test', meta: 'meta' });
    assert.ok(chip);
    assert.ok(chip.className.includes('chip'));
    assert.ok(chip.textContent.includes('test'));
  });

  test('sortArrow', () => {
    assert.equal(UIHelpers.sortArrow(false, 0), '▲▼');
    assert.equal(UIHelpers.sortArrow(true, 1), '▲');
    assert.equal(UIHelpers.sortArrow(true, -1), '▼');
  });

  test('mergeParts binds functions', () => {
    const host = { a: 1 };
    const part = { b: 2, fn() { return this.a + this.b; } };
    UIHelpers.mergeParts(host, part);
    assert.equal(host.b, 2);
    assert.equal(host.fn(), 3);
  });

  test('actionChip and customChip use esc', () => {
    const chip = UIHelpers.actionChip('<b>', () => {}, () => {});
    assert.ok(chip.innerHTML.includes('&lt;b&gt;'));
  });

  test('bookmarkChip truncates', () => {
    const longUrl = 'https://example.com/' + 'a'.repeat(100);
    const chip = UIHelpers.bookmarkChip(longUrl, () => {}, () => {});
    assert.ok(chip.textContent.includes('…'));
  });
});
