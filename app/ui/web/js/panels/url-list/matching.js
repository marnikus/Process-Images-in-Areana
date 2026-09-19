/* url-list/matching.js — pool matching logic, ≤150 LOC, CC≤10 via helpers */
'use strict';
window.UrlListMatching = {
  _store() { return window.UrlListStore; },
  _pages() {
    if (typeof PagePoolPanel === 'undefined') return [];
    return (PagePoolPanel.snapshot && PagePoolPanel.snapshot.pages) || [];
  },

  _findBound(boundTabId, pages) {
    if (!boundTabId) return null;
    return pages.find(p => p && p.tab_id === boundTabId) || null;
  },

  _findExactOrPrefix(q, pages) {
    for (const p of pages) {
      const pu = (p.url || '').toLowerCase();
      if (!pu) continue;
      if (pu === q) return p;
      if (pu.startsWith(q) || q.startsWith(pu)) return p;
    }
    return null;
  },

  _findHostBest(url, pages) {
    try {
      const host = new URL(url).host;
      for (const p of pages) {
        try { if (p.url && new URL(p.url).host === host) return p; } catch {}
      }
    } catch {}
    return null;
  },

  matchPoolPage(url, boundTabId) {
    if (!url || typeof PagePoolPanel === 'undefined') return null;
    const pages = this._pages();
    if (!pages.length) return null;
    const bound = this._findBound(boundTabId, pages);
    if (bound) return bound;
    const q = this._store().extractUrl(url).toLowerCase();
    const exact = this._findExactOrPrefix(q, pages);
    if (exact) return exact;
    return this._findHostBest(url, pages);
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

  _claimBound(rows, pages, claimed, taken) {
    rows.forEach((tr, ri) => {
      const bound = tr.dataset ? (tr.dataset.tabId || '') : '';
      if (!bound) return;
      const pi = (pages || []).findIndex(p => p && p.tab_id === bound);
      if (pi >= 0 && !taken.has(pi)) { claimed.set(ri, pi); taken.add(pi); }
    });
  },

  _buildCandidates(rows, pages) {
    const cands = [];
    rows.forEach((tr, ri) => {
      (pages || []).forEach((p, pi) => {
        const s = this.scorePoolPage(tr.dataset.url || '', p.url);
        if (s > 0) cands.push({ri, pi, s});
      });
    });
    cands.sort((a,b)=>b.s-a.s);
    return cands;
  },

  assignPoolPages(rows, pages) {
    const claimed = new Map(), taken = new Set();
    this._claimBound(rows, pages, claimed, taken);
    const cands = this._buildCandidates(rows, pages);
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
