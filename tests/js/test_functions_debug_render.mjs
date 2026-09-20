import test from 'node:test';
import assert from 'node:assert/strict';
import { functions, cases } from './function_harness.mjs';

const page=() => ({tab_id:'t1',title:'Arena',url:'https://arena.ai/',is_connected:true,status:'busy',current_job_id:'job',current_image:'a.png',busy_since:new Date(1910000).toISOString()});

test('LiveDebugRender.text', t => {
  const {w}=functions(t); w.LiveDebugRender.text('liveDebugQueue','<b>safe</b>');
  assert.equal(w.document.getElementById('liveDebugQueue').textContent,'<b>safe</b>');
  assert.equal(w.document.querySelector('#liveDebugQueue b'),null);
  assert.doesNotThrow(() => w.LiveDebugRender.text('missing','ignored'));
});

test('LiveDebugRender.queueHead', async t => {
  const {w}=functions(t);
  await cases(t, [[null,/Waiting/],[{queued:0},/0 pending.*queue empty/],
    [{queued:3,next_image:'a.png',receivers:{receivers:2,not_receivers:1},run_state:'running'},/3 pending.*first: a.png.*2 receiving.*1 not receiving.*running/]],
  ([raw,want]) => assert.match(w.LiveDebugRender.queueHead(raw),want));
});

test('LiveDebugRender.cadence', async t => {
  const {w}=functions(t), store=w.LiveDebugStore;
  await cases(t, [[null,/Waiting/],[{url_interval_ms:5000,last_pass_at:0,passes:0},/every 5.0 s.*not yet run/],
    [{url_interval_ms:5000,last_pass_at:1998,passes:4},/last pass 2s ago.*4 passes.*read-only/]], ([live,want]) => {
    store.live=live; assert.match(w.LiveDebugRender.cadence(store),want);
  });
});

test('LiveDebugRender.status', async t => {
  const {w}=functions(t);
  await cases(t, [[false,'busy',true,'disconnected'],[true,'waiting_captcha',false,'waiting'],
    [true,'waiting_captcha',true,'waiting captcha'],[true,null,true,'unknown']], ([connected,status,scope,want]) => {
    assert.equal(w.LiveDebugRender.status({is_connected:connected,status},scope),want);
  });
});

test('LiveDebugRender.pause', async t => {
  const {w}=functions(t);
  await cases(t, [[false,null,/^$/],[true,null,/timing unavailable/],
    [true,{absorbed_s:12,cap_s:300,remaining_s:288},/12s absorbed.*300s cap.*288s remaining.*last settled/],
    [true,{absorbed_s:300,cap_s:300,remaining_s:0},/cap exhausted/],
    [true,{absorbed_s:12,cap_s:0,remaining_s:null},/uncapped/]], ([scope,pause,want]) => {
    assert.match(w.LiveDebugRender.pause({status:'waiting_captcha',pause},scope),want);
  });
  assert.equal(w.LiveDebugRender.pause({status:'steady'},true),'');
});

test('LiveDebugRender.timing', async t => {
  const {w}=functions(t); w.LiveDebugStore.poolAt=2000000;
  await cases(t, [[page(),/elapsed 90s/],[{status:'cooldown',cooldown_remaining:30},/elapsed unknown.*cooldown 30s/]],
    ([p,want]) => assert.match(w.LiveDebugRender.timing(p,w.LiveDebugStore),want));
});

test('LiveDebugRender.detail', async t => {
  const {w}=functions(t);
  await cases(t, [[{error:'captcha'},false,''],[{error:'solver unavailable'},true,'solver unavailable'],
    [{cooldown_reason:'job cycle'},false,'job cycle'],[{},true,'']], ([p,scope,want]) => {
    assert.equal(w.LiveDebugRender.detail(p,scope),want);
  });
});

test('LiveDebugRender.worker', t => {
  const {w}=functions(t), s=w.LiveDebugStore; s.pool={waits_in_scope:false};
  const el=w.document.createElement('div');
  el.innerHTML=w.LiveDebugRender.worker({...page(),title:'<script>x</script>'},s);
  assert.equal(el.querySelector('script'),null); assert.equal(el.querySelectorAll('article').length,1);
  assert.match(el.textContent,/job.*a.png.*elapsed 90s/);
});

test('LiveDebugRender.workers', async t => {
  const {w}=functions(t), s=w.LiveDebugStore;
  await cases(t, [[null,/Waiting/],[{pages:[]},/No workers connected/],[{pages:[page()]},/Arena/]], ([pool,want]) => {
    s.pool=pool; assert.match(w.LiveDebugRender.workers(s),want);
  });
});

test('LiveDebugRender.summary', async t => {
  const {w}=functions(t);
  await cases(t, [[null,/awaiting snapshot/],[{pages:[],busy:0,cooling:0,free:0},/0 workers/],
    [{total:3,pages:[],busy:1,cooling:1,free:1},/3 workers.*1 busy.*1 cooling.*1 free/]], ([pool,want]) => assert.match(w.LiveDebugRender.summary(pool),want));
});

test('LiveDebugRender.render', t => {
  const {w}=functions(t), s=w.LiveDebugStore;
  s.pool={pages:[page()]}; s.live={queued:2,next_image:'first.png'}; s.errors={pool:'last snapshot'};
  w.LiveDebugRender.render(s);
  assert.match(w.document.getElementById('liveDebugQueue').textContent,/2 pending.*first.png/);
  assert.equal(w.document.querySelectorAll('#liveDebugWorkers article').length,1);
  assert.equal(w.document.getElementById('liveDebugStatus').textContent,'last snapshot');
  s.pool={pages:[]}; s.errors={}; w.LiveDebugRender.render(s);
  assert.equal(w.document.querySelectorAll('#liveDebugWorkers article').length,0);
});
