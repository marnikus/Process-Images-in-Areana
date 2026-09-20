import test from 'node:test';
import assert from 'node:assert/strict';
import { functions, cases } from './function_harness.mjs';

test('LiveDebugActions.read', async t => {
  await cases(t, ['ok','throws','missing'], mode => {
    const {w}=functions(t); const replies=[], errors=[];
    if (mode==='throws') w.App.bridge.get_page_pool_status=() => {throw Error('unavailable');};
    if (mode==='missing') {delete w.App.bridge.get_page_pool_status; w.console.warn=()=>{};}
    w.LiveDebugActions.read('get_page_pool_status', raw => replies.push(raw), error => errors.push(error));
    assert.equal(replies.length,mode==='ok'?1:0); assert.equal(errors.length,mode==='ok'?0:1);
  });
});

test('LiveDebugActions.refresh', async t => {
  await cases(t, [false,true], stale => {
    const {w,calls}=functions(t); let reply;
    w.App.bridge.get_page_pool_status=cb => {calls.push('read'); reply=cb;};
    w.LiveDebugActions.refresh();
    if (stale) w.LiveDebugStore.onPool({pages:[]});
    reply(JSON.stringify({pages:[{tab_id:'t1'}]}));
    assert.deepEqual(calls,['read']); assert.equal(w.LiveDebugStore.pool.pages.length,stale?0:1);
  });
});

test('LiveDebugActions.loadQueue', async t => {
  await cases(t, ['ok','stale','broken'], mode => {
    const {w}=functions(t); let reply; w.App.bridge.get_arena_state=cb => {reply=cb;};
    w.LiveDebugActions.loadQueue();
    if (mode==='stale') w.LiveDebugStore.onLive({live:{queued:7}});
    reply(mode==='broken'?'bad':JSON.stringify({progress:{live:{queued:3}}}));
    if (mode==='broken') assert.match(w.LiveDebugStore.errors.live,/unavailable/);
    else assert.equal(w.LiveDebugStore.live.queued,mode==='stale'?7:3);
  });
});

test('LiveDebugActions.connect', t => {
  const {w,calls,handlers}=functions(t); w.LiveDebugActions.connect(null); assert.equal(calls.length,0);
  w.LiveDebugActions.connect(w.App.bridge);
  assert.deepEqual(calls.map(c=>c[0]),['get_arena_state','get_page_pool_status']);
  assert.equal(handlers.pool.length,1); assert.equal(handlers.live.length,1);
  handlers.live[0]('{"live":{"queued":8}}'); assert.equal(w.LiveDebugStore.live.queued,8);
});

test('LiveDebugPanel.init', t => {
  const {w,calls,timers,handlers}=functions(t); w.LiveDebugPanel.init(); w.LiveDebugPanel.init();
  assert.equal(timers.length,1); assert.equal(timers[0].ms,1000); assert.equal(handlers.live.length,1);
  calls.length=0; timers[0].fn(); assert.equal(calls.length,0);
  w.document.getElementById('liveDebugRefreshBtn').click();
  assert.deepEqual(calls.map(c=>c[0]),['get_page_pool_status']);
});

test('LiveDebugPanel.refresh', t => {
  const {w,calls}=functions(t); w.LiveDebugPanel.refresh();
  assert.deepEqual(calls.map(c=>c[0]),['get_page_pool_status']);
  assert.equal(w.LiveDebugStore.pool.pages.length,0);
});
