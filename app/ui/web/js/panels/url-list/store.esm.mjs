/* url-list/store.esm.mjs — ESM for c8 */
export const UrlListStore = {
  _lastConnectUrl: '',
  _lastConnectTs: 0,
  poolPages: [],
  esc(s) {
    if (!s) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  },
  snapshotUrls() {
    return (globalThis.App && globalThis.App.state && globalThis.App.state.urls) ? globalThis.App.state.urls : [];
  },
  extractUrl(q) {
    if (!q) return '';
    q = q.trim();
    let m = q.match(/\(https?:\/\/[^\s\)]+\)/);
    if (m) {
      let inside = m[0].slice(1,-1).trim();
      if (inside.startsWith('http')) return inside;
    }
    q = q.replace(/^\[+/, '').replace(/\]+$/, '').replace(/^\(+/, '').replace(/\)+$/, '').trim();
    let http = q.match(/(https?:\/\/[^\s\]\)]+)/);
    if (http) return http[1].trim();
    return q;
  },
  shouldDebounce(url) {
    const now = Date.now();
    if (url === this._lastConnectUrl && (now - this._lastConnectTs) < 1500) return true;
    this._lastConnectUrl = url;
    this._lastConnectTs = now;
    return false;
  },
};
if (typeof window !== 'undefined') window.UrlListStore = UrlListStore;
export default UrlListStore;
