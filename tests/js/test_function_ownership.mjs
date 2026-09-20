// Structural contract (not a production unit): one registration per scoped method.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { execFileSync } from 'node:child_process';
import { parse } from 'acorn';
import { simple } from 'acorn-walk';

const parseFile=file => parse(fs.readFileSync(file,'utf8'),{ecmaVersion:'latest',sourceType:'module'});

test('S0–S10 JS units own every scoped method exactly once', () => {
  const manifest=JSON.parse(fs.readFileSync('tests/live_chain_manifest.json','utf8'));
  const wanted=[];
  for (const file of ['panels/url-list/interval.js','panels/live-debug.js','panels/live-debug/store.js','panels/live-debug/render.js','panels/live-debug/actions.js']) {
    simple(parseFile('app/ui/web/js/'+file),{AssignmentExpression(node) {
      if (node.left.type!=='MemberExpression' || node.left.object.name!=='window' || node.right.type!=='ObjectExpression') return;
      for (const prop of node.right.properties) {
        if (prop.value?.type==='FunctionExpression') wanted.push(`${node.left.property.name}.${prop.key.name}`);
      }
    }});
  }
  wanted.push('UrlListRender.rowHtml');
  const actual=[];
  for (const file of manifest.js_units) {
    simple(parseFile(file), {CallExpression(node) {
      if (node.callee.name!=='test') return;
      assert.equal(node.arguments[0].type,'Literal');
      actual.push(node.arguments[0].value);
    }});
  }
  assert.equal(new Set(actual).size,actual.length,'duplicate method owners');
  assert.deepEqual(actual.sort(),wanted.sort());
});


test('all original chain JS integration bodies survive the move unchanged', () => {
  const manifest=JSON.parse(fs.readFileSync('tests/live_chain_manifest.json','utf8'));
  const normalize=tree => JSON.stringify(tree, (key,value) => ['start','end'].includes(key)?undefined:value);
  for (const [source,destination] of Object.entries(manifest.js_legacy_files)) {
    const old=execFileSync('git',['show',`19a96c9:${source}`],{encoding:'utf8'});
    assert.equal(normalize(parseFile(destination)),normalize(parse(old,{ecmaVersion:'latest',sourceType:'module'})),source);
  }
});
