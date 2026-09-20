import test from 'node:test';
import assert from 'node:assert/strict';
import { functions, cases } from './function_harness.mjs';

test('LiveDebugStore.decode', async t => {
  const {w}=functions(t), s=w.LiveDebugStore;
  await cases(t, ['{}',{queued:3}], raw => {assert.equal(typeof s.decode(raw),'object');});
  await cases(t, [null,[], 'bad', {error:'CDP down'}], raw => {assert.throws(() => s.decode(raw));});
});

test('LiveDebugStore.onPool', async t => {
  await cases(t, [{pages:[]},{pages:[{tab_id:'t1'}]},{pages:'bad'},{pages:[null]}], data => {
    const {w}=functions(t), s=w.LiveDebugStore;
    s.onPool({pages:[{tab_id:'old'}]}); const previous=s.pool;
    s.onPool(JSON.stringify(data));
    if (Array.isArray(data.pages) && data.pages.every(p => p)) {
      assert.equal(s.pool.pages.length,data.pages.length); assert.equal(s.poolVersion,2);
      assert.equal(s.poolAt,2000000); assert.equal(s.errors.pool,undefined);
    } else {assert.equal(s.pool,previous); assert.match(s.errors.pool,/invalid/);}
  });
});

test('LiveDebugStore.onLive', async t => {
  await cases(t, [{live:{queued:3}}, {live:{}}, {error:'offline'}], data => {
    const {w}=functions(t), s=w.LiveDebugStore;
    s.onLive({live:{queued:1}}); const previous=s.live; s.onLive(data);
    if (data.live?.queued === 3) {
      assert.equal(s.live.queued,3); assert.equal(s.liveVersion,2); assert.equal(s.liveAt,2000000);
    } else {assert.equal(s.live,previous); assert.match(s.errors.live,/unavailable/);}
  });
});

test('LiveDebugStore.seconds', async t => {
  const {w}=functions(t);
  await cases(t, [[12,12],[-1,0],['4',4],[Infinity,0],['bad',0]], ([raw,want]) => assert.equal(w.LiveDebugStore.seconds(raw),want));
});

test('LiveDebugStore.age', async t => {
  const {w}=functions(t);
  await cases(t, [[1998000,2],[new Date(1998000).toISOString(),2],[2001000,0],[0,null],['bad',null]], ([raw,want]) => assert.equal(w.LiveDebugStore.age(raw),want));
});

test('LiveDebugStore.elapsed', async t => {
  const {w}=functions(t);
  await cases(t, [['job',new Date(1910000).toISOString(),90],['',new Date(1910000).toISOString(),null],['job','bad',null]], ([id,start,want]) => {
    assert.equal(w.LiveDebugStore.elapsed({current_job_id:id,busy_since:start}),want);
  });
});

test('LiveDebugStore.cooldown', async t => {
  const {w}=functions(t); w.LiveDebugStore.poolAt=1995000;
  await cases(t, [[30,25],[2,0],[null,0]], ([left,want]) => assert.equal(w.LiveDebugStore.cooldown({cooldown_remaining:left}),want));
});

test('LiveDebugStore.tick', t => {
  const {w,calls}=functions(t); w.LiveDebugStore.live={queued:3,next_image:'x.png'};
  w.LiveDebugStore.tick();
  assert.match(w.document.getElementById('liveDebugQueue').textContent,/3 pending.*x.png/);
  assert.equal(calls.length,0);
});
