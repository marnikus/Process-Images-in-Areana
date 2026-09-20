/* block-views.js — secondary views of the Action Blocks window (B11 split)
   Everything that is not the stack list (block-render.js) or the config
   form (block-config.js). DOM contract (index.html + css/arena.css):
     #jobActionStack > .job-block-row.jb-<status>[data-block-id]   (current job, one row per block)
     #allJobsStack   > .ab-job-tabs > .ab-job-tab[.ab-job-tab--active]  (one tab per job seen)
     #abTotalSteps #abSelectedSteps #actionBlocksCount              (footer / title counters)
     #customBlockChips #stackPresetChips                            (preset chips via UIHelpers.chip)
   Statuses come from job_action_status payloads {status, message, rect, …}
   (running | waiting | success | failed | skipped); a block without an
   event yet is "pending".
   RULE18: file 150-300, func ≤30, CC≤10
*/
'use strict';

window.ActionBlocksViews = {
  jobStackEl() { return document.getElementById('jobActionStack'); },
  allJobsEl() { return document.getElementById('allJobsStack'); },

  _el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null && text !== '') node.textContent = String(text);
    return node;
  },

  statusText(st) {
    if (!st) return 'pending';
    return typeof st === 'string' ? st : (st.status || 'pending');
  },

  messageOf(st) { return st && typeof st === 'object' ? (st.message || '') : ''; },

  _placeholder(container, text) {
    container.innerHTML = '';
    container.appendChild(this._el('span', 'ab-view-empty', text));
  },

  _rectButton(block, onRect) {
    const btn = this._el('button', 'ab-edit-btn jb-rect');
    btn.title = 'Re-highlight this block\'s selector on the page';
    const ic = this._el('span', 'material-icons', 'center_focus_strong');
    btn.appendChild(ic);
    btn.addEventListener('click', (e) => { e.stopPropagation(); onRect(block); });
    return btn;
  },

  _jobRow(block, st, onRect) {
    const status = this.statusText(st);
    const row = this._el('div', `job-block-row jb-${status}`);
    row.dataset.blockId = block.id;
    row.appendChild(window.ActionBlocksRender.icon(block.icon, '', block.color));
    row.appendChild(this._el('span', 'jb-name', block.custom_name || block.name || block.block_id));
    row.appendChild(this._el('span', 'jb-msg', this.messageOf(st)));
    row.appendChild(this._el('span', 'jb-status', status));
    if (st && typeof st === 'object' && st.rect && block.selector) row.appendChild(this._rectButton(block, onRect));
    return row;
  },

  /** spec = { jobId, blocks, statuses, onRect(block) } */
  renderJobStack(spec) {
    const container = this.jobStackEl();
    if (!container) return;
    if (!spec.jobId) { this._placeholder(container, 'No job running — start a job to see live blocks with rect confirmations as it makes clicks'); return; }
    const jobStatus = (spec.statuses && spec.statuses[spec.jobId]) || {};
    container.innerHTML = '';
    const head = this._el('div', 'jb-head', `Job ${String(spec.jobId).slice(0, 8)} — ${this._summaryText(jobStatus)}`);
    container.appendChild(head);
    (spec.blocks || []).forEach((block) => container.appendChild(this._jobRow(block, jobStatus[block.id], spec.onRect || (() => {}))));
  },

  _summary(jobStatus) {
    const out = { success: 0, failed: 0, running: 0, skipped: 0, total: 0 };
    Object.keys(jobStatus || {}).forEach((k) => {
      const s = this.statusText(jobStatus[k]);
      out.total += 1;
      if (s in out) out[s] += 1;
      if (s === 'waiting') out.running += 1;
    });
    return out;
  },

  _summaryText(jobStatus) {
    const s = this._summary(jobStatus);
    return `✓ ${s.success} · ✗ ${s.failed} · ⏵ ${s.running} · ⤼ ${s.skipped}`;
  },

  _jobTab(jid, n, spec) {
    const btn = this._el('button', `ab-job-tab${jid === spec.currentJobId ? ' ab-job-tab--active' : ''}`);
    btn.dataset.jobId = jid;
    btn.title = `${jid} — click to show this job's stack`;
    btn.textContent = `#${n} ${String(jid).slice(0, 8)} · ${this._summaryText(spec.jobStatuses[jid])}`;
    btn.addEventListener('click', () => spec.onSelectJob(jid));
    return btn;
  },

  /** spec = { jobOrder, currentJobId, jobStatuses, onSelectJob(jobId) } */
  renderAllJobs(spec) {
    const container = this.allJobsEl();
    if (!container) return;
    const order = spec.jobOrder || [];
    if (!order.length) { this._placeholder(container, 'No jobs yet — run batch to see all jobs with rect confirmations'); return; }
    container.innerHTML = '';
    const tabs = this._el('div', 'ab-job-tabs');
    order.forEach((jid, i) => tabs.appendChild(this._jobTab(jid, i + 1, spec)));
    container.appendChild(tabs);
  },

  _setText(id, text) {
    const e = document.getElementById(id);
    if (e) e.textContent = text;
  },

  updateFooter(blocks) {
    const list = blocks || [];
    this._setText('abTotalSteps', `Total: ${list.length} steps`);
    this._setText('abSelectedSteps', `Selected: ${list.filter((b) => b.enabled !== false).length} steps`);
    this._setText('actionBlocksCount', `${list.length} blocks`);
  },

  _chip(entry, spec) {
    const opts = { title: entry.name, meta: spec.meta ? spec.meta(entry) : '', tooltip: spec.tooltip || 'Click to load',
      onLoad: () => spec.onLoad(entry), onDelete: () => spec.onDelete(entry.name) };
    const h = window.UIHelpers;
    return h && h.chip ? h.chip(opts) : this._el('span', 'chip', entry.name);
  },

  /** Preset chips; spec = { emptyText, meta(entry), tooltip, onLoad(entry), onDelete(name) } */
  renderChips(containerId, entries, spec) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '';
    if (!entries.length) { container.appendChild(this._el('span', 'preset-row-empty', spec.emptyText || 'No presets yet')); return; }
    entries.forEach((entry) => container.appendChild(this._chip(entry, spec)));
  },
};
