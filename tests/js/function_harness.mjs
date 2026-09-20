// Test boundary only: real markup/modules, controllable bridge and clock.
import fs from 'node:fs';
import vm from 'node:vm';
import { JSDOM } from 'jsdom';

export function functions(t) {
  const dom = new JSDOM(fs.readFileSync('app/ui/web/index.html','utf8'), {runScripts:'outside-only',url:'https://ui.test/'});
  t.after(() => dom.window.close());
  const w=dom.window, calls=[], handlers={}, timers=[];
  w.Date.now=() => 2000000;
  w.setInterval=(fn,ms) => {timers.push({fn,ms}); return timers.length;};
  w.App={state:{},bridge:{
    save_settings:(raw,cb) => {calls.push(['save_settings',JSON.parse(raw)]); cb('{}');},
    get_page_pool_status:cb => {calls.push(['get_page_pool_status']); cb(JSON.stringify({pages:[],waits_in_scope:false}));},
    get_arena_state:cb => {calls.push(['get_arena_state']); cb(JSON.stringify({progress:{live:{queued:3,next_image:'a.png'}}}));},
    page_pool_updated:{connect:fn => (handlers.pool ||= []).push(fn)},
    progress_updated:{connect:fn => (handlers.live ||= []).push(fn)}
  }};
  w.BridgeReady={ready:fn => fn(w.App.bridge)}; // WebChannel readiness boundary
  for (const name of ['core/boot.js','core/ui-helpers.js','panels/url-list/store.js','panels/url-list/render.js',
    'panels/url-list/interval.js','panels/live-debug/store.js','panels/live-debug/render.js',
    'panels/live-debug/actions.js','panels/live-debug.js']) {
    vm.runInContext(fs.readFileSync('app/ui/web/js/'+name,'utf8'),dom.getInternalVMContext(),{filename:name});
  }
  return {w,calls,handlers,timers};
}

// Parameterized data, not a dispatch table of old test bodies.
export async function cases(t, values, run) {
  for (let i=0; i<values.length; i++) await t.test(`case ${i+1}`, () => run(values[i]));
}
