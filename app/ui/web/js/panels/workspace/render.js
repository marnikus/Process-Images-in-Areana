/**
 * panels/workspace/render.js — every DOM write this window makes.
 *
 * Pure rendering: the element handles and the pending-preview state arrive as
 * arguments, so nothing here reaches back into the flow. A row is pre-ticked
 * only when the restore would really restore it — the preview runs the same
 * gates the restore runs, so `ok` is a promise and the other statuses are the
 * reasons the restore will skip that domain (I-81).
 *
 * Sliced from `panels/workspace.js` (audit #3 L9).
 */
'use strict';

// grabbed once per mount(): wsStatus, wsSaveBtn, …
let wsEl = {};
let wsPreview = null;   // the manifest+gate preview for the pending restore

// A row is pre-ticked only when the restore would really restore it. The
// preview runs the same gates the restore runs, so `ok` is a promise; the
// statuses below are the reasons the restore will skip that domain (I-81).
const WS_RESTORABLE = ['ok', 'size_mismatch'];

function wsStatusText(text) {
  if (wsEl.wsStatus) wsEl.wsStatus.textContent = text;
}

function wsEsc(text) {
  // regex escaper (no DOM round-trip): the headless test harness's fake DOM
  // does not emulate textContent→innerHTML, and this is auditable anyway
  return String(text == null ? '' : text).replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[ch]));
}

function wsRenderRecent(recent, last) {
  if (!wsEl.wsRecentList) return;
  if (!recent.length) { wsEl.wsRecentList.innerHTML = 'none yet'; return; }
  const rows = recent.map((path) => {
    const mark = path === last ? ' ⏱ last' : '';
    const links = `<a href="#" data-load="${wsEsc(path)}" style="color:var(--accent)">load</a>` +
      ` · <a href="#" data-open="${wsEsc(path)}" style="color:var(--accent)">open</a>`;
    return `<div>• ${wsEsc(path.split(/[\\/]/).pop())}${mark} ${links}</div>`;
  });
  wsEl.wsRecentList.innerHTML = rows.join('');
}

function wsSaveSummary(reply) {
  const excluded = (reply.domains || []).filter((d) => d.excluded);
  const rows = [`Snapshot: ${reply.path || ''}`,
    `Result: ${reply.result} — ${(reply.domains || []).length} domains`];
  for (const item of excluded) rows.push(`excluded: ${item.domain_id}`);
  for (const err of reply.errors || []) rows.push(`${err.domain_id}: ${err.cause}`);
  return { title: 'Workspace saved', rows, openPath: reply.path, raw: reply };
}

function wsRenderResult(summary) {
  if (!wsEl.wsResult) return;
  wsEl.wsResult.style.display = '';
  const rows = summary.rows.map((r) => `<div>${wsEsc(r)}</div>`).join('');
  const open = summary.openPath
    ? `<button class="btn" data-open="${wsEsc(summary.openPath)}">Open folder</button> ` : '';
  const copy = `<button class="btn" id="wsCopyBtn">Copy details</button>`;
  wsEl.wsResult.innerHTML = `<b>${wsEsc(summary.title)}</b><br>${rows}` +
    `<div style="margin-top:6px">${open}${copy}</div>`;
  wsBindCopy(summary);
}

function wsBindCopy(summary) {
  const copyBtn = document.getElementById('wsCopyBtn');
  if (!copyBtn) return;
  copyBtn.addEventListener('click', () => {
    const text = summary.raw ? JSON.stringify(summary.raw, null, 2) : summary.rows.join('\n');
    if (navigator.clipboard) navigator.clipboard.writeText(text);
  });
}

function wsRowNote(d) {
  return d.note ? ` (${wsEsc(d.note)})` : '';
}

function wsDomainRow(d) {
  const checked = WS_RESTORABLE.includes(d.status) ? 'checked' : '';
  return `<label style="display:block"><input type="checkbox" class="ws-domain" ` +
    `data-domain="${wsEsc(d.domain_id)}" ${checked}> ` +
    `${wsEsc(d.display_name)} — ${wsEsc(d.status)}${wsRowNote(d)}</label>`;
}

function wsRenderPreview(pv) {
  if (!wsEl.wsPreview) return;
  const remap = (pv.path_remap_needed || []).map((r) => `<div>⚠️ ${wsEsc(r)}</div>`);
  const rows = (pv.domains || []).map(wsDomainRow);
  wsEl.wsPreview.style.display = '';
  if (wsEl.wsRestoreActions) wsEl.wsRestoreActions.style.display = '';
  wsEl.wsPreview.innerHTML = `<b>${wsEsc(pv.name || '')}</b> · ${wsEsc(pv.created_utc || '')} · ` +
    `${wsEsc((pv.app || {}).build || '')} · ${wsEsc(pv.snapshot_kind || '')}<br>` +
    `${remap.join('')}${rows.join('')}`;
}

function wsChosenDomains() {
  return [...document.querySelectorAll('.ws-domain:checked')].map((c) => c.dataset.domain);
}

function wsSkipRow(skip) {
  const action = skip.recommended_action ? ` → ${skip.recommended_action}` : '';
  return `skipped ${skip.domain_id} [${skip.stage || 'policy'}]: ${skip.cause}${action}`;
}

function wsRestoredRows(reply) {
  const rows = [`Result: ${reply.result}`,
    `Restored: ${(reply.restored || []).join(', ') || '—'}`];
  for (const item of reply.migrated || []) rows.push(`migrated: ${item.domain_id} — ${item.note}`);
  for (const skip of reply.skipped || []) rows.push(wsSkipRow(skip));
  if (reply.backup) rows.push(`recovery backup: ${reply.backup}`);
  for (const note of reply.reconciled || []) rows.push(note);
  return rows;
}

function wsRestoreSummary(reply) {
  if (reply.ok !== true && !(reply.restored || []).length) {   // '' reply = crashed slot
    return { title: 'Restore failed', rows: [reply.error || 'unknown error'] };
  }
  return { title: 'Workspace restore', rows: wsRestoredRows(reply),
    openPath: reply.workspace, raw: reply };
}

function wsHidePreview() {
  wsPreview = null;
  if (wsEl.wsPreview) wsEl.wsPreview.style.display = 'none';
  if (wsEl.wsRestoreActions) wsEl.wsRestoreActions.style.display = 'none';
}

function wsPendingPreview() { return wsPreview; }
function wsSetPreview(reply) { wsPreview = reply; }
function wsElements(ids) {
  wsEl = {};
  for (const id of ids) wsEl[id] = document.getElementById(id);
  return wsEl;
}
