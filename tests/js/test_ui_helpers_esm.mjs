/** test_ui_helpers_esm.mjs — ESM direct import for c8 coverage C14 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { JSDOM } from 'jsdom';
import { UIHelpers } from '../../app/ui/web/js/core/ui-helpers.esm.mjs';

// setup DOM for el/chip
const dom = new JSDOM('<!DOCTYPE html><html><body></body></html>');
global.document = dom.window.document;
global.window = dom.window;

describe('ui-helpers-esm', () => {
  test('esc', () => {
    assert.equal(UIHelpers.esc('<script>'), '&lt;script&gt;');
    assert.equal(UIHelpers.esc('a & b'), 'a &amp; b');
    assert.equal(UIHelpers.esc(null), '');
  });
  test('el', () => {
    const el = UIHelpers.el('div', 'cls', 'hello');
    assert.equal(el.tagName, 'DIV');
    assert.equal(el.className, 'cls');
    assert.equal(el.textContent, 'hello');
  });
  test('chip', () => {
    const chip = UIHelpers.chip({ title: 'test', meta: 'meta' });
    assert.ok(chip);
    assert.ok(chip.className.includes('chip'));
  });
  test('sortArrow', () => {
    assert.equal(UIHelpers.sortArrow(false, 0), '▲▼');
    assert.equal(UIHelpers.sortArrow(true, 1), '▲');
    assert.equal(UIHelpers.sortArrow(true, -1), '▼');
  });
  test('mergeParts', () => {
    const host = { a: 1 };
    const part = { b: 2, fn() { return this.a + this.b; } };
    UIHelpers.mergeParts(host, part);
    assert.equal(host.b, 2);
    assert.equal(host.fn(), 3);
  });
  test('actionChip', () => {
    const chip = UIHelpers.actionChip('<b>', () => {}, () => {});
    assert.ok(chip.innerHTML.includes('&lt;b&gt;'));
  });
  test('bookmarkChip truncates', () => {
    const longUrl = 'https://example.com/' + 'a'.repeat(100);
    const chip = UIHelpers.bookmarkChip(longUrl, () => {}, () => {});
    assert.ok(chip.textContent.includes('…'));
  });
});
