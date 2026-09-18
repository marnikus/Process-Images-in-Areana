import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import {JSDOM} from 'jsdom';

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname),
  '../../app/browser/composer_js');
const probe = (name) => fs.readFileSync(path.join(ROOT, name), 'utf8');
const rect = (node) => { node.getBoundingClientRect = () => ({width: 300, height: 80}); };

test('prompt insertion targets visible composer and not stale hidden textarea', () => {
  const dom = new JSDOM(`<!doctype html><body>
    <form aria-hidden="true"><textarea name="message">stale</textarea></form>
    <form><textarea id="active" placeholder="Describe the image you want to generate…"></textarea></form>`,
    {url: 'https://arena.ai', runScripts: 'outside-only'});
  const active = dom.window.document.getElementById('active'); rect(active);
  const text = 'Use this reference image and keep its proportions';

  const inserted = dom.window.eval(`${probe('insert_prompt.js')}(${JSON.stringify(text)})`);
  const verified = dom.window.eval(`${probe('verify_prompt.js')}(${JSON.stringify(text)})`);

  assert.equal(inserted.ok, true);
  assert.equal(verified.ok, true);
  assert.equal(active.value, text);
  assert.equal(dom.window.document.querySelector('[aria-hidden="true"] textarea').value, 'stale');
});

test('contenteditable prompt is supported when textarea is absent', () => {
  const dom = new JSDOM('<form><div id="active" role="textbox" contenteditable="true"></div></form>',
    {url: 'https://arena.ai', runScripts: 'outside-only'});
  const active = dom.window.document.getElementById('active'); rect(active);

  const result = dom.window.eval(`${probe('insert_prompt.js')}('hello')`);

  assert.equal(result.ok, true);
  assert.equal(active.textContent, 'hello');
});
