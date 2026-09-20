import test from 'node:test';
import assert from 'node:assert/strict';
import { functions, cases } from './function_harness.mjs';

test('UrlInterval.clamp', async t => {
  const {w}=functions(t);
  await cases(t, [[1,500],[70000,60000],['bad',5000],['2500',2500]], ([input,expected]) => {
    assert.equal(w.UrlInterval.clamp(input),expected);
  });
});

test('UrlInterval.applyValue', async t => {
  const {w}=functions(t);
  await cases(t, [500,9000], value => {
    w.UrlInterval.applyValue(value);
    assert.equal(w.document.getElementById('urlIntervalMs').value,String(value));
  });
  w.document.getElementById('urlIntervalMs').remove();
  assert.doesNotThrow(() => w.UrlInterval.applyValue(1000));
});

test('UrlInterval.load', async t => {
  const {w}=functions(t), el=w.document.getElementById('urlIntervalMs');
  await cases(t, [[null,'1234'],[{},'1234'],[{url_interval_ms:9},'500'],[{url_interval_ms:60001},'60000']], ([input,expected]) => {
    el.value='1234'; w.UrlInterval.load(input); assert.equal(el.value,expected);
  });
});

test('UrlInterval.save', async t => {
  await cases(t, [['2500',2500],['',5000]], ([input,expected]) => {
    const {w,calls}=functions(t); w.document.getElementById('urlIntervalMs').value=input;
    w.UrlInterval.save(); assert.deepEqual(calls,[['save_settings',{url_reconcile_interval_ms:expected}]]);
  });
});

test('UrlInterval._bindLive', t => {
  const {w,handlers,calls}=functions(t); w.UrlInterval._bindLive();
  assert.equal(handlers.live.length,1);
  handlers.live[0]('{"live":{"url_interval_ms":9000}}');
  assert.equal(w.document.getElementById('urlIntervalMs').value,'9000');
  handlers.live[0]('broken'); assert.equal(calls.length,0);
});

test('UrlInterval.init', t => {
  const {w,calls}=functions(t); w.App.state={progress:{live:{url_interval_ms:2200}}};
  w.UrlInterval.init(); w.UrlInterval.init();
  assert.equal(w.document.getElementById('urlIntervalMs').value,'2200');
  w.document.getElementById('urlIntervalSaveBtn').click();
  assert.deepEqual(calls,[['save_settings',{url_reconcile_interval_ms:2200}]]);
});

test('UrlListRender.rowHtml', async t => {
  const {w}=functions(t);
  await cases(t, [[true,false,1],[false,true,0],[false,false,1]], ([enabled,receiver,count]) => {
    const tr=w.document.createElement('tr');
    tr.innerHTML=w.UrlListRender.rowHtml({id:'one',url:'<script>x</script>',status:'valid',enabled,receiver});
    assert.equal(tr.cells.length,8);
    assert.equal(tr.cells[2].querySelectorAll('.url-not-receiver').length,count);
    assert.equal(tr.querySelector('script'),null);
  });
});
