/* Redacted CAPTCHA session recorder. Returns a structural snapshot and
   drains normalized MutationObserver events. Never reads values or bodies. */
(() => {
  const root = document.documentElement;
  const safe = (x) => String(x || '').slice(0, 120);
  const semantic = (el) => {
    if (!el || !el.tagName) return 'node';
    const text = safe(el.getAttribute('role') || el.getAttribute('title') || el.tagName).toLowerCase();
    if (text.includes('recaptcha') || text.includes('challenge')) return 'recaptcha';
    if (text.includes('security')) return 'security-dialog';
    if (el.classList && [...el.classList].some(c => c === 'animate-spin')) return 'generation-spinner';
    return el.tagName.toLowerCase();
  };
  const frame = [...document.querySelectorAll('iframe')].find(f => /challenge|bframe/i.test(f.title || f.src || ''));
  const fields = document.querySelectorAll('textarea[name="g-recaptcha-response"], textarea[id*="g-recaptcha-response"]').length;
  const security = document.querySelector('div[role="dialog"][data-state="open"]');
  const resources = typeof performance !== 'undefined' && performance.getEntriesByType ? performance.getEntriesByType('resource').slice(-50).map((r) => ({
    name: safe(String(r.name || '').split('?')[0]), initiator: safe(r.initiatorType),
    duration_ms: Math.round(Number(r.duration || 0)), transfer: Number(r.transferSize || 0)
  })) : [];
  const snapshot = {
    url: location.href.split('?')[0].slice(0, 300),
    page_identity: location.href.split('?')[0] + '|' + (typeof performance !== 'undefined' ? String(performance.timeOrigin || '') : ''),
    title: safe(document.title),
    dom: {
      node_count: root ? root.querySelectorAll('*').length : 0,
      security: {dialog: !!security, challenge: !!frame, challenge_src: frame ? safe(frame.src).split('?')[0] : '', response_fields: fields},
      spinners: document.querySelectorAll('.animate-spin').length,
      errors: [...document.querySelectorAll('[role="alert"]')].map(x => safe(x.textContent)).slice(0, 10)
    },
    network: resources
  };
  if (!window.__arenaCaptchaRecordQueue) window.__arenaCaptchaRecordQueue = [];
  if (!window.__arenaCaptchaRecordObserver) {
    window.__arenaCaptchaRecordObserver = new MutationObserver((list) => {
      const changes = [];
      list.slice(0, 100).forEach(m => {
        changes.push({op: m.type, target: semantic(m.target), name: m.attributeName ? safe(m.attributeName) : ''});
      });
      if (changes.length) window.__arenaCaptchaRecordQueue.push({kind: 'mutation', changes});
    });
    window.__arenaCaptchaRecordObserver.observe(root, {subtree: true, childList: true, attributes: true, attributeFilter: ['data-state', 'class', 'aria-busy', 'aria-disabled']});
  }
  const queued = window.__arenaCaptchaRecordQueue.splice(0, 100);
  return {snapshot, events: queued};
})()
