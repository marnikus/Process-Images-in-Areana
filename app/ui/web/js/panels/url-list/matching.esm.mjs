/* url-list/matching.esm.mjs — ESM for c8 */
import { UrlListStore } from './store.esm.mjs';
export const UrlListMatching = {
  _store() { return UrlListStore; },
  matchPoolPage(url, boundTabId) {
    if (!url || typeof globalThis.PagePoolPanel === 'undefined') return null;
    const pages = (globalThis.PagePoolPanel.snapshot && globalThis.PagePoolPanel.snapshot.pages) || [];
    if (!pages.length) return null;
    if (boundTabId) {
      const bound = pages.find(p => p && p.tab_id === boundTabId);
      if (bound) return bound;
    }
    const q = this._store().extractUrl(url).toLowerCase();
    let hostBest = null;
    for (const p of pages) {
      const pu = (p.url || '').toLowerCase();
      if (!pu) continue;
      if (pu === q) return p;
      if (pu.startsWith(q) || q.startsWith(pu)) return p;
      try { if (!hostBest && new URL(p.url).host === new URL(url).host) hostBest = p; } catch {}
    }
    return hostBest;
  },
  scorePoolPage(rowUrl, pageUrl) {
    const q = this._store().extractUrl(rowUrl).toLowerCase();
    const pu = (pageUrl || '').toLowerCase();
    if (!pu || !q) return 0;
    if (pu === q) return 500;
    if (pu.startsWith(q) || q.startsWith(pu)) return 300;
    try { if (new URL(pageUrl).host === new URL(rowUrl).host) return 200; } catch {}
    return 0;
  },
  assignPoolPages(rows, pages) {
    const claimed = new Map(), taken = new Set();
    rows.forEach((tr, ri) => {
      const bound = tr.dataset ? (tr.dataset.tabId || '') : '';
      if (!bound) return;
      const pi = (pages || []).findIndex(p => p && p.tab_id === bound);
      if (pi >= 0 && !taken.has(pi)) { claimed.set(ri, pi); taken.add(pi); }
    });
    const cands = [];
    rows.forEach((tr, ri) => {
      (pages || []).forEach((p, pi) => {
        const s = this.scorePoolPage(tr.dataset.url || '', p.url);
        if (s > 0) cands.push({ri, pi, s});
      });
    });
    cands.sort((a,b)=>b.s-a.s);
    cands.forEach(c => {
      if (!claimed.has(c.ri) && !taken.has(c.pi)) { claimed.set(c.ri, c.pi); taken.add(c.pi); }
    });
    return claimed;
  },
  matchUnclaimedPage(rowUrl, pages, claimed) {
    const taken = new Set((claimed || new Map()).values());
    let best = null, bestScore = 299;
    (pages || []).forEach((p, pi) => {
      if (taken.has(pi)) return;
      const s = this.scorePoolPage(rowUrl, p.url);
      if (s > bestScore) { bestScore = s; best = p; }
    });
    return best;
  },
  jobLineForTab(pages, tabId) {
    if (!tabId) return '';
    const p = (pages || []).find(x => x && x.tab_id === tabId);
    const name = p ? (p.current_image || '') : '';
    return name ? `\u25b6 ${name}` : '';
  },
};
if (typeof window !== 'undefined') window.UrlListMatching = UrlListMatching;
export default UrlListMatching;
