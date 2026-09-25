/* BridgeReady — single QWebChannel handshake + boot queue */
'use strict';
window.BridgeReady = (function () {
  const queue = [];
  const st = { bridge: null, connected: false };
  function flush() { while (queue.length) { try { queue.shift()(st.bridge); } catch (e) { console.error(e); } } }
  function resolveApp() { return (typeof App !== 'undefined') ? App : window.App; }
  function onChannel(ch) {
    st.bridge = ch.objects.bridge;
    window.CaptchaRecordingsBridge = ch.objects.captchaRecordings || null;
    st.connected = true;
    const a = resolveApp();
    if (a) { a.bridge = st.bridge; a.ready = true; }
    // success stays silent (owner 2026-09-25: startup noise); only the failure path below warns
    flush();
  }
  function boot() {
    if (typeof QWebChannel !== 'undefined' && typeof qt !== 'undefined' && qt.webChannelTransport) {
      new QWebChannel(qt.webChannelTransport, onChannel);
    } else {
      console.warn('QWebChannel not available — standalone');
      st.connected = true;
      flush();
    }
  }
  document.addEventListener('DOMContentLoaded', boot);
  return {
    ready(fn) { if (st.connected) fn(st.bridge); else queue.push(fn); },
    get bridge() { return st.bridge; },
    get connected() { return st.connected; },
  };
})();
