/* block-status.js — C12 split: pause badge/corner/status + job lifecycle
   RULE18: file 150-300, func ≤30, CC≤10
*/
'use strict';

window.ActionBlocksStatus = {
  _updateBadge(paused, reason) {
    const badge = document.getElementById('abPauseBadge');
    if (!badge) return;
    badge.classList.toggle('hidden', !paused);
    if (paused) badge.title = reason || 'Paused';
  },

  _updateCorner(paused, reason) {
    const corner = document.getElementById('pauseCornerOverlay');
    if (!corner) return;
    corner.classList.toggle('visible', !!paused);
    const reasonEl = document.getElementById('pauseCornerReason');
    if (reasonEl) reasonEl.textContent = reason || 'Captcha / Security detected';
  },

  _updateStatus(paused, reason) {
    const statusEl = document.getElementById('abStatus');
    if (!statusEl) return;
    statusEl.textContent = paused ? `Status: ON PAUSE — ${reason || 'Captcha'}` : 'Status: Awaiting run command';
    statusEl.style.color = paused ? '#FFAA00' : '';
    statusEl.style.fontWeight = paused ? '700' : '';
  },

  setPaused(panel, paused, reason) {
    panel._isPaused = !!paused;
    panel._pauseReason = reason || '';
    this._updateBadge(paused, reason);
    this._updateCorner(paused, reason);
    this._updateStatus(paused, reason);
    if (paused && typeof LogConsole !== 'undefined') LogConsole.log(`⏸ ON PAUSE — ${reason || 'Captcha'}`, 'warn');
  },

  _isCaptchaStatus(status) {
    const name = (status.block_name || '').toLowerCase();
    const msg = (status.message || '').toLowerCase();
    return name.includes('security') || name.includes('captcha') || msg.includes('captcha') || msg.includes('security verification');
  },

  detectPause(panel, status) {
    const isCaptcha = this._isCaptchaStatus(status);
    const isWaiting = ['running', 'waiting', 'paused'].includes(status.status);
    if (isCaptcha && isWaiting) this.setPaused(panel, true, status.message || 'Security Verification');
    if (status.status === 'success' && isCaptcha) this.setPaused(panel, false, '');
  },

  _ensureJob(panel, jobId) {
    if (panel.jobStatuses[jobId]) return;
    panel.jobStatuses[jobId] = {};
    panel.jobOrder.push(jobId);
    if (panel.jobOrder.length > 20) {
      const old = panel.jobOrder.shift();
      delete panel.jobStatuses[old];
    }
  },

  onJobStarted(panel, jobId) {
    panel.currentJobId = jobId;
    this._ensureJob(panel, jobId);
    this.setPaused(panel, false, '');
    panel.renderJobStack(jobId);
    panel.renderAllJobs();
    panel.updateFooter();
  },

  onJobActionStatus(panel, jobId, blockId, statusJson) {
    try {
      const status = typeof statusJson === 'string' ? JSON.parse(statusJson) : statusJson;
      this._ensureJob(panel, jobId);
      panel.jobStatuses[jobId][blockId] = status;
      panel.currentJobId = jobId;
      this.detectPause(panel, status);
      panel.renderJobStack(jobId);
      panel.renderAllJobs();
      panel.updateFooter();
    } catch {}
  },

  onJobFinished(panel, jobId) {
    this.setPaused(panel, false, '');
    panel.renderJobStack(jobId);
    panel.renderAllJobs();
    panel.updateFooter();
  },

  onJobPaused(panel, reason) { this.setPaused(panel, true, reason); },
  onJobResumed(panel) { this.setPaused(panel, false, ''); },
  onJobFailed(panel, jobId) { this.onJobFinished(panel, jobId); },
};

if (typeof window !== 'undefined') window.ActionBlocksStatus = window.ActionBlocksStatus;
