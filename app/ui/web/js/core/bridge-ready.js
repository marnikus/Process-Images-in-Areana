/* BridgeReady — single QWebChannel handshake + boot queue */
'use strict';
window.BridgeReady = (function () {
  const queue = [];
  const st = { bridge: null, connected: false };

  /* ErrorTrail — startup forensics: route every uncaught exception/rejection
     into the LogConsole with the full stack, so a bare "TypeError: fn is not a
     function" always names its file, line and cause instead of vanishing. */
  const ErrorTrail = {
    log(kind, ev) {
      const err = ev && (ev.error || ev.reason) || null;
      const at = kind === 'error'
        ? `${ev.filename || ''}:${ev.lineno || 0}:${ev.colno || 0}`
        : '(unhandledrejection)';
      const msg = err && err.stack ? err.stack : String(err || ev && ev.message || 'unknown error');
      console.error(`[ErrorTrail] ${kind} @ ${at}\n${msg}`);
      let consoleMsg = true;
      try {
        if (typeof LogConsole !== 'undefined' && LogConsole && LogConsole.log) {
          LogConsole.log(`JS ${kind} @ ${at} — ${String(msg).split('\n')[0]}`, 'error');
          consoleMsg = false;
        }
      } catch (_) { /* fall through to console */ }
      if (consoleMsg && ev && ev.message) console.error(`[ErrorTrail] ${kind} @ ${at}: ${ev.message}`);
    },
    install() {
      try {
        window.addEventListener('error', (ev) => ErrorTrail.log('error', ev));
        window.addEventListener('unhandledrejection', (ev) => ErrorTrail.log('unhandledrejection', ev));
      } catch (_) { /* no DOM events in a headless sandbox — keep loading */ }
    },
  };
  ErrorTrail.install();
  function flush() { while (queue.length) { try { queue.shift()(st.bridge); } catch (e) { console.error(e); } } }
  function resolveApp() { return (typeof App !== 'undefined') ? App : window.App; }
  function onChannel(ch) {
    st.bridge = ch.objects.bridge;
    window.CaptchaRecordingsBridge = ch.objects.captchaRecordings || null;
    st.connected = true;
    const a = resolveApp();
    if (a) { a.bridge = st.bridge; a.ready = true; }
    console.log('QWebChannel connected');
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
    ready(fn) {
      if (typeof fn !== 'function') { console.warn('[BridgeReady] ready() needs a function'); return; }
      if (st.connected) fn(st.bridge); else queue.push(fn);
    },
    get bridge() { return st.bridge; },
    get connected() { return st.connected; },
    errorTrail: ErrorTrail,
  };
})();
