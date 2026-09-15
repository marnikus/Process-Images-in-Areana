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
  }
};
