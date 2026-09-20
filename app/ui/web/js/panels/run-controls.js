/* run-controls.js */
'use strict';

const RunControls = {
  init() {
    document.getElementById('runStartBtn')?.addEventListener('click', ()=>this.start());
    document.getElementById('runPauseBtn')?.addEventListener('click', ()=>this.pause());
    document.getElementById('runResumeBtn')?.addEventListener('click', ()=>this.resume());
    document.getElementById('runStopAfterBtn')?.addEventListener('click', ()=>this.stopAfter());
    document.getElementById('runCancelBtn')?.addEventListener('click', ()=>this.cancel());
    document.getElementById('runRetryBtn')?.addEventListener('click', ()=>this.retry());
    document.getElementById('cdpAttachTestBtn')?.addEventListener('click', ()=>this.testAttach());
    document.getElementById('cdpPromptTestBtn')?.addEventListener('click', ()=>this.testPrompt());
    document.getElementById('cdpFullFlowTestBtn')?.addEventListener('click', ()=>this.testFullFlow());
  },

  start() {
    if (App.bridge && App.bridge.start_run) {
      App.bridge.start_run((res)=>{
        try{ const r=JSON.parse(res); LogConsole.log(r.ok?'Run started':'Start failed: '+r.error, r.ok?'success':'error'); }catch(e){}
      });
    }
  },
  pause() {
    if (App.bridge && App.bridge.pause_run) App.bridge.pause_run(()=>LogConsole.log('Paused','warn'));
  },
  resume() {
    if (App.bridge && App.bridge.resume_run) App.bridge.resume_run(()=>LogConsole.log('Resumed','info'));
  },
  stopAfter() {
    if (App.bridge && App.bridge.stop_after_current) App.bridge.stop_after_current(()=>LogConsole.log('Will stop after current','warn'));
  },
  cancel() {
    if (App.bridge && App.bridge.cancel_current) App.bridge.cancel_current(()=>LogConsole.log('Cancel current','warn'));
  },
  retry() {
    if (App.bridge && App.bridge.retry_failed) App.bridge.retry_failed(()=>LogConsole.log('Retrying failed','info'));
  },

  testAttach() {
    if (App.bridge && App.bridge.cdp_attach_image_test) {
      const firstSel = App.state && App.state.images ? (App.state.images.find(i=>i.selected) || {}).id || '' : '';
      App.bridge.cdp_attach_image_test(firstSel, (res)=>{
        try{ const r=JSON.parse(res); LogConsole.log(r.ok?'Attach test queued: '+r.path:'Attach test failed: '+r.error, r.ok?'info':'error'); }catch(e){}
      });
    } else {
      LogConsole.log('cdp_attach_image_test not available', 'warn');
    }
  },

  testPrompt() {
    if (App.bridge && App.bridge.cdp_insert_prompt_test) {
      const prompt = document.getElementById('promptTextarea')?.value || '';
      App.bridge.cdp_insert_prompt_test(prompt, (res)=>{
        try{ const r=JSON.parse(res); LogConsole.log(r.ok?'Prompt test queued':'Prompt test failed: '+r.error, r.ok?'info':'error'); }catch(e){}
      });
    }
  },

  testFullFlow() {
    if (App.bridge && App.bridge.cdp_test_full_flow) {
      App.bridge.cdp_test_full_flow((res)=>{
        try{ const r=JSON.parse(res); LogConsole.log(r.ok?'Full flow test queued':'Full flow failed: '+r.error, r.ok?'info':'error'); }catch(e){}
      });
    }
  }
};

// Global-name contract (see boot.js): publish the lexical const for window[name] lookups.
if (typeof window !== 'undefined') window.RunControls = RunControls;
