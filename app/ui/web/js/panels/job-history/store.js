/* job-history/store.js — the pushed payload + the history thumb cache.
   `entries` arrive newest-first from job_history_updated (and the
   get_job_history reply); the limit mirrors back into both limit inputs. */
'use strict';
window.JobHistoryStore = {
  entries: [],
  limit: 50,
  total: 0,
  nextJobNo: 1,
  thumbCache: {},

  setPayload(p) {
    if (!p || typeof p !== 'object') return false;
    if (Array.isArray(p.entries)) this.entries = p.entries;
    if (p.limit !== undefined) this.limit = p.limit;
    if (p.total !== undefined) this.total = p.total;
    if (p.next_job_no !== undefined) this.nextJobNo = p.next_job_no;
    return true;
  },
};
