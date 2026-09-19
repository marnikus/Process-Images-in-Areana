/* cdp-store.esm.mjs — ESM wrapper for c8 coverage C14, mirrors cdp-store.js */
export const CDPStore = {
  tabs: [],
  connected: false,
  selectedWs: '',
  lastMatchQuery: '',
  _lastAutoConnectWs: '',
  _lastAutoConnectTs: 0,
  _lastConnectWs: '',
  _lastConnectTs: 0,
  currentConfig: { host: '127.0.0.1', port: 9222, user_data_dir: 'C:\\arena-images-chrome' },

  _devPrefixes() { return ['devtools://', 'chrome://', 'chrome-extension://', 'about:', 'edge://']; },
  _isDevUrl(url) { return this._devPrefixes().some(p => url.startsWith(p)); },
  _isDevTitle(title, url) {
    if (title.startsWith('devtools')) return true;
    if (title.includes('devtools') && url.includes('devtools')) return true;
    return false;
  },
  _isDevBundled(url) { return url.includes('devtools/bundled') || url.includes('device_mode_emulation_frame'); },
  isDevTab(t) {
    if (!t) return true;
    const url = (t.url || '').toLowerCase();
    const title = (t.title || '').toLowerCase();
    if (this._isDevUrl(url)) return true;
    if (this._isDevTitle(title, url)) return true;
    if (this._isDevBundled(url)) return true;
    return false;
  },
  getRealTabs(tabs) {
    const src = tabs || this.tabs || [];
    return src.filter(t => !this.isDevTab(t));
  },
  _extractFromParen(q) {
    const m = q.match(/\(https?:\/\/[^\s\)]+\)/);
    if (!m) return null;
    const inside = m[0].slice(1, -1).trim();
    return inside.startsWith('http') ? inside : null;
  },
  _extractUrl(q) {
    if (!q) return '';
    q = q.trim();
    const paren = this._extractFromParen(q);
    if (paren) return paren;
    q = q.replace(/^\[+/, '').replace(/\]+$/, '').replace(/^\(+/, '').replace(/\)+$/, '').trim();
    const http = q.match(/(https?:\/\/[^\s\]\)]+)/);
    if (http) return http[1].trim();
    return q;
  },
  _scoreExact(tabUrl, query) {
    if (tabUrl === query) return { score: 500, kind: 'url_exact' };
    return null;
  },
  _scorePrefix(tabUrl, query) {
    if (tabUrl.startsWith(query) || query.startsWith(tabUrl)) return { score: 300, kind: 'url_path' };
    return null;
  },
  _scoreHost(tabUrl, query, origUrl) {
    try {
      const u1 = new URL(origUrl);
      const u2 = new URL(tabUrl);
      if (u1.host === u2.host) return { score: 200, kind: 'host' };
    } catch {}
    return null;
  },
  _scoreKeyword(tabUrl, query) {
    if (tabUrl.includes(query)) return { score: 60, kind: 'keyword' };
    return null;
  },
  _scoreTab(tabUrlLower, queryLower, origUrl) {
    return this._scoreExact(tabUrlLower, queryLower) || this._scorePrefix(tabUrlLower, queryLower) || this._scoreHost(tabUrlLower, queryLower, origUrl) || this._scoreKeyword(tabUrlLower, queryLower) || { score: 0, kind: 'keyword' };
  },
  findBestTabForUrl(url) {
    if (!this.tabs || !this.tabs.length) return null;
    const realTabs = this.getRealTabs(this.tabs);
    const pool = realTabs.length > 0 ? realTabs : this.tabs;
    const q = url.toLowerCase();
    let best = null;
    let bestScore = -1;
    for (const t of pool) {
      const tabUrl = (t.url || '').toLowerCase();
      const { score } = this._scoreTab(tabUrl, q, url);
      if (score > bestScore) { bestScore = score; best = t; }
    }
    return best;
  },
  dedupTabs(tabs) {
    const seen = new Map();
    for (const t of tabs) {
      const id = t.id;
      if (!seen.has(id)) seen.set(id, t);
      else {
        const existing = seen.get(id);
        if (existing.ws_url && existing.ws_url.includes('localhost') && t.ws_url && t.ws_url.includes('127.0.0.1')) {
          seen.set(id, t);
        }
      }
    }
    return Array.from(seen.values());
  },
};

if (typeof window !== 'undefined') window.CDPStore = CDPStore;
export default CDPStore;
