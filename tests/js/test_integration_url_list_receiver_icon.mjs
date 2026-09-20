// Integration lane: actual DOM, boot/bridge or cross-file contracts.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { execFileSync } from 'node:child_process';
import { controls } from './live_controls_harness.mjs';

const row = (id, enabled, receiver) => ({id, url:'https://arena.ai/' + id, enabled, receiver, status:'valid', tab_id:'t1'});

test('the real status cell uses receiver only, not enabled or connection state', async t => {
  const {w} = await controls(t);
  w.UrlListRender.render([row('a', true, false), row('b', false, true), row('c', false, false)]);
  const rows = [...w.document.querySelectorAll('#urlTableBody tr')];
  assert.equal(rows.length, 3);
  assert.equal(rows[0].cells.length, 8);
  assert.equal(rows[0].cells[2].querySelector('.url-not-receiver').textContent, '⊘');
  assert.equal(rows[1].querySelector('.url-not-receiver'), null);
  assert.equal(rows[2].cells[2].querySelector('.url-not-receiver').textContent, '⊘');
  assert.match(rows[0].cells[2].querySelector('.url-not-receiver').title, /unchecked\/offline/);
});

test('a pushed receiver transition removes the icon without moving table actions', async t => {
  const {w} = await controls(t);
  w.UrlListRender.render([row('a', true, false)]);
  assert.ok(w.document.querySelector('#urlTableBody .url-not-receiver'));
  w.UrlListRender.render([row('a', true, true)]);
  assert.equal(w.document.querySelector('#urlTableBody .url-not-receiver'), null);
  assert.equal(w.document.querySelectorAll('#urlTableBody tr').length, 1);
  assert.ok(w.document.querySelector('#urlTableBody button[data-action="connect"]'));
});

test('render js did not grow in lines or function count', () => {
  const file = 'app/ui/web/js/panels/url-list/render.js';
  const base = execFileSync('git', ['show', `2bbf9ab:${file}`], {encoding:'utf8'});
  const current = fs.readFileSync(file,'utf8');
  assert.equal(current.split('\n').length, base.split('\n').length);
  const methods = s => [...s.matchAll(/^  \w+\([^\n]*\) \{/gm)].map(m => m[0]);
  assert.deepEqual(methods(current), methods(base));
});
