/**
 * One readable tab id in every view that references a tab (D-5/D-7).
 *
 * The pool key stays the 32-hex CDP target id (identity); the label is
 * `{email}_{4 digits}` and the hex id lives on as the tooltip, so a row can
 * still be traced to the padlock/DevTools listing.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { El } from './fake_dom.mjs';
import { bootPage } from './page_harness.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PANELS = path.resolve(__dirname, '../../app/ui/web/js/panels');

const FULL = '1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d';
const LABEL = 'marnikus@gmail.com_3045';

function rowsHtml(el) {
  return [...el.children].map((c) => c.innerHTML || '').join('\n');
}

function worker(extra = {}) {
  return {
    tab_id: FULL, tab_label: LABEL, worker_no: 3, status: 'steady', title: 'Arena',
    url: 'https://arena.ai/c/1', jobs_completed: 0, cooldown_remaining: 0,
    cooldown_total: 0, pending_penalty: 0, ...extra,
  };
}

const snapOf = (page) => ({ total: 1, steady: 1, busy: 0, cooling: 0, free: 1, pages: [page] });

describe('worker table', () => {
  test('shows the readable id, keeps the number and the full hex as the tooltip', () => {
    const h = bootPage();
    h.emit('page_pool_updated', JSON.stringify(snapOf(worker())));
    const html = rowsHtml(h.anyEl('poolTableBody'));
    assert.match(html, /#3<\/b>\s*marnikus@gmail\.com_3045/);
    assert.ok(html.includes(`title="${FULL}"`), 'the hex id is still reachable');
    assert.ok(!html.includes(`>${FULL}<`), 'no raw hex as the visible id');
  });

  test('falls back to the short id when the snapshot carries no label', () => {
    const h = bootPage();
    h.emit('page_pool_updated', JSON.stringify(snapOf(worker({ tab_label: '' }))));
    const html = rowsHtml(h.anyEl('poolTableBody'));
    assert.ok(html.includes(FULL.slice(0, 8)), html);
    assert.ok(!html.includes(FULL.slice(0, 12) + '<'), 'never the 12-char slice');
    assert.ok(html.includes(`title="${FULL}"`));
  });
});

describe('URL list', () => {
  function urlRowStub() {
    const tr = new El('tr');
    const cell = new El('td');
    cell.className = 'url-tab-cell';
    tr.appendChild(cell);
    return tr;
  }

  /* The fake DOM cannot parse `<tr>` innerHTML into cells, so the filled cell
     is read from the cells module the way the 1 s refresh calls it. */
  function tabCell(page) {
    const h = bootPage();
    const tr = urlRowStub();
    h.run('UrlListCells').fillTabCell(tr, page);
    return tr.querySelector('.url-tab-cell').innerHTML;
  }

  test('the row template declares the cell the fill step writes into', () => {
    const h = bootPage();
    h.emit('arena_state_updated', JSON.stringify({
      urls: [{ id: 'u1', url: 'https://arena.ai/c/1', enabled: true, status: 'ready', tab_id: FULL }],
      images: [],
    }));
    h.flushTimers();
    const html = rowsHtml(h.anyEl('urlTableBody'));
    assert.ok(html.includes('url-tab-cell'), html);
  });

  test('the row carries the same label as the worker table, hex in the tooltip', () => {
    const html = tabCell(worker());
    assert.ok(html.includes(LABEL), html);
    assert.ok(html.includes(`title="${FULL}"`), 'the hex id stays reachable');
  });

  test('the row shows the same visual worker number as the Page Pool (#N before the badge)', () => {
    const html = tabCell(worker({ browser: 'firefox', tab_label: 'mailreceiverpro@gmail.com' }));
    assert.ok(html.includes('<b class="worker-no">#3</b> 🦊 mailreceiverpro@gmail.com</span>'), html);
  });

  test('a page without a worker number shows no stray #', () => {
    for (const worker_no of [0, '', undefined, 'x']) {
      const html = tabCell(worker({ worker_no }));
      assert.ok(!html.includes('worker-no') && !html.includes('#'), html);
    }
  });

  test('falls back to the short id when the snapshot carries no label', () => {
    const html = tabCell(worker({ tab_label: '' }));
    // D8: the short id sits behind the browser badge (🌐/🦊) — never bare.
    assert.ok(html.includes(`🌐 ${FULL.slice(0, 8)}</span>`), html);
    assert.ok(!html.includes(`>${FULL}<`), 'never the raw 32-char id as the text');
  });

  test('a row whose tab is not pooled shows a dash, not a stale label', () => {
    const html = tabCell(null);
    assert.ok(html.includes('Tab not in pool'), html);
    assert.ok(!html.includes(LABEL), html);
  });
});

describe('Live Debug', () => {
  test('the worker line names the tab the same way', () => {
    const h = bootPage();
    h.emit('page_pool_updated', JSON.stringify(snapOf(worker())));
    const html = h.anyEl('liveWorkers').innerHTML || '';
    assert.ok(html.includes(LABEL), html);
    assert.ok(html.includes(`title="${FULL}"`), html);
  });
});

describe('Job History', () => {
  function history(extra = {}) {
    return {
      entries: [{ job_no: 7, job_id: 'j7', tab_id: FULL, worker_no: 3, status: 'completed',
        error: '', image_id: 'i1', image: 'a.png', image_path: '/in/a.png', folder: '/out',
        output_path: '/out/a_AI.png', captcha: 0, started: '2026-09-21T09:59:01+00:00',
        finished: '2026-09-21T09:59:20+00:00', ...extra }],
      limit: 50, total: 1, next_job_no: 8,
    };
  }

  test('a finished-job row names the tab exactly like the worker table and the URL list', () => {
    const h = bootPage();
    h.emit('page_pool_updated', JSON.stringify(snapOf(worker())));
    h.emit('job_history_updated', JSON.stringify(history()));
    const html = h.anyEl('historyTableBody').innerHTML || '';
    assert.ok(html.includes(LABEL), html);
    assert.ok(html.includes(`title="${FULL}"`), 'the hex id stays reachable in the tooltip');
    assert.ok(!html.includes(`>${FULL}<`), 'never the raw 32-char id as the visible id');
  });

  test('the row carries the pool worker number beside the label', () => {
    const h = bootPage();
    h.emit('page_pool_updated', JSON.stringify(snapOf(worker())));
    h.emit('job_history_updated', JSON.stringify(history()));
    const html = h.anyEl('historyTableBody').innerHTML || '';
    assert.ok(html.includes('>#3<'), html);
  });

  test('a tab that already left the pool falls back to the short id', () => {
    const h = bootPage();
    h.emit('job_history_updated', JSON.stringify(history({ tab_id: 'deadbeefcafe0000', worker_no: '' })));
    const html = h.anyEl('historyTableBody').innerHTML || '';
    assert.ok(html.includes('>deadbeef</td>'), html);
    assert.ok(!html.includes('>deadbeefcafe0000<'), 'never the raw 32-char id as the visible id');
    assert.ok(html.includes('>—</td>'), 'no worker number left behind for a gone tab');
  });
});

describe('log lines', () => {
  test('core/tab-label.js is the one place a tab id becomes a label', () => {
    const h = bootPage();
    h.run('PagePoolStore').setSnapshot(snapOf(worker()));
    const tl = h.run('TabLabel');
    assert.equal(tl.of(FULL), LABEL, 'known tab → the readable id');
    assert.equal(tl.of('deadbeefcafe0000'), 'deadbeef', 'unknown tab → short id');
    assert.equal(tl.of(''), '', 'nothing to name → empty, never "undefined"');
  });

  test('a page object named without a lookup prints the same label', () => {
    const h = bootPage();
    const tl = h.run('TabLabel');
    assert.equal(tl.of(FULL, worker()), LABEL);
    assert.equal(tl.of(FULL, worker({ tab_label: '' })), FULL.slice(0, 8));
  });

  test('no panel log line slices a tab id by hand any more', () => {
    // 2026-09-21 (D-7): the URL row's Stop / Clear-time log lines moved to the
    // new url-list/reset.js (the frozen actions.js only delegates now), so the
    // label check follows the owner and the no-slicing rule covers both files.
    for (const rel of ['page-pool/actions.js', 'url-list/actions.js', 'url-list/reset.js', 'captcha.js',
      'job-history/render.js']) {
      const text = fs.readFileSync(path.join(PANELS, rel), 'utf8');
      assert.ok(!/tabId\.slice\(0, *8\)|solving_tab\.slice|\.tab_id \|\| ''\)\.slice/.test(text),
        `${rel} must not slice a tab id by hand`);
    }
    for (const rel of ['page-pool/actions.js', 'url-list/reset.js', 'captcha.js', 'job-history/render.js']) {
      const text = fs.readFileSync(path.join(PANELS, rel), 'utf8');
      assert.ok(text.includes('TabLabel.of('), `${rel} must name the tab by its label`);
    }
  });
});
