import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import {JSDOM} from 'jsdom';

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname),
  '../../app/browser/attachment_js');
const probe = (name) => fs.readFileSync(path.join(ROOT, name), 'utf8');
const rect = (node) => { node.getBoundingClientRect = () => ({width: 200, height: 60}); };

function composerPage() {
  const html = `<!doctype html><body>
    <form aria-hidden="true"><textarea name="message"></textarea><input id="stale" type="file" accept="image/png"><img src="blob:old"></form>
    <img id="unrelated" src="blob:page-image">
    <form id="active"><textarea placeholder="Describe the image you want to generate…"></textarea><input id="wanted" type="file" accept="image/png"><div id="previews"></div></form>
  </body>`;
  const dom = new JSDOM(html, {url: 'https://arena.ai', runScripts: 'outside-only'});
  rect(dom.window.document.querySelector('#active textarea'));
  return dom;
}

test('image paste dispatches a real File to the active prompt', () => {
  const dom = composerPage();
  class Transfer {
    constructor() {
      this.files = [];
      this.items = {add: (file) => this.files.push(file)};
    }
  }
  dom.window.DataTransfer = Transfer;
  let pasted = null;
  dom.window.document.querySelector('#active textarea').addEventListener('paste',
    (event) => { pasted = event.clipboardData.files[0]; });

  const result = dom.window.eval(`${probe('paste.js')}('reference.png', 'image/png', 'cG5n')`);

  assert.equal(result.ok, true);
  assert.equal(pasted.name, 'reference.png');
  assert.equal(pasted.type, 'image/png');
});

test('attachment target belongs to the visible active prompt form', () => {
  const dom = composerPage();
  const result = dom.window.eval(`${probe('target.js')}('mark-1', [])`);

  assert.equal(result.ok, true);
  assert.equal(dom.window.document.getElementById('wanted').dataset.arenaUploadTarget, 'mark-1');
  assert.equal(dom.window.document.getElementById('stale').dataset.arenaUploadTarget, undefined);
  assert.deepEqual(Array.from(result.previews), []);
});

test('attachment verification requires active input file or fresh active preview', () => {
  const dom = composerPage();
  const input = dom.window.document.getElementById('wanted');
  Object.defineProperty(input, 'files', {value: [{name: 'reference.png'}], configurable: true});
  let result = dom.window.eval(`${probe('verify.js')}('reference.png', [])`);
  assert.equal(result.found, true);
  assert.equal(result.matched, 'active-input-file');

  Object.defineProperty(input, 'files', {value: [], configurable: true});
  const image = dom.window.document.createElement('img');
  image.src = 'blob:fresh'; rect(image);
  dom.window.document.getElementById('previews').appendChild(image);
  result = dom.window.eval(`${probe('verify.js')}('reference.png', [])`);
  assert.equal(result.found, true);
  assert.equal(result.matched, 'new-active-preview');
});

test('old or unrelated images cannot prove attachment', () => {
  const dom = composerPage();
  const image = dom.window.document.createElement('img');
  image.src = 'blob:already-there'; rect(image);
  dom.window.document.getElementById('previews').appendChild(image);
  const baseline = [`${image.src}|`];

  const result = dom.window.eval(`${probe('verify.js')}('reference.png', ${JSON.stringify(baseline)})`);

  assert.equal(result.found, false);
});

test('attachment target fails without a visible prompt composer', () => {
  const dom = new JSDOM('<form><textarea name="message"></textarea><input type="file"></form>',
    {url: 'https://arena.ai', runScripts: 'outside-only'});
  const result = dom.window.eval(`${probe('target.js')}('mark-1', [])`);
  assert.equal(result.ok, false);
  assert.match(result.error, /visible prompt/);
});
