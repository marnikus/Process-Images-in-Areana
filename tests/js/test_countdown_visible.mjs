/**
 * The countdown never hides (D-4).
 *
 * User report: "the timer shows only + 15:00, not real time elapsing; it hides
 * after Cancel current run — never hide it". The cells were gated on
 * `status === 'cooldown'`, so a page whose status label moved while its timer
 * ran showed a dash or a frozen `+15:00 pending`. Both views must now read
 * `cooldown_remaining` (the value the Python snapshot computes from the timer)
 * whatever the status says, keep a `00:00` clock when nothing runs, and label a
 * debt as a debt.
 *
 * Harness notes: fake_dom does not parse innerHTML into children, so rendered
 * rows are read as HTML strings (`rowsHtml`) and the cells the JS fills later
 * (`fillCoolCell`, the 1 s tickers) are driven with real El trees built here.
 * `document.querySelectorAll` is empty in the sandbox, so the pool ticker gets
 * its clocks injected.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { El } from './fake_dom.mjs';
import { bootPage } from './page_harness.mjs';

const FULL = '1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d';

/* fake_dom stores one innerHTML per element: rows are CHILDREN of the tbody. */
function rowsHtml(el) {
  return [...el.children].map((c) => c.innerHTML || '').join('\n');
}

function worker(extra = {}) {
  return {
    tab_id: FULL, tab_label: 'marnikus@gmail.com_3045', worker_no: 3, status: 'steady',
    title: 'Arena', url: 'https://arena.ai/c/1', jobs_completed: 0,
    cooldown_remaining: 0, cooldown_total: 0, pending_penalty: 0, ...extra,
  };
}

const snapOf = (page) => ({ total: 1, steady: 1, busy: 0, cooling: 0, free: 1, pages: [page] });

/* fake_dom keeps one innerHTML string per row: cells are sliced, not queried. */
function cellsOf(rowHtml) {
  return rowHtml.split('<td').slice(1).map((c) => '<td' + c);
}

function poolRow(extra = {}) {
  const h = bootPage();
  h.emit('page_pool_updated', JSON.stringify(snapOf(worker(extra))));
  return { h, html: rowsHtml(h.anyEl('poolTableBody')) };
}

/** A `<tr>` with the two cells + buttons `fillCoolCell` looks up. */
function urlRowStub() {
  const tr = new El('tr');
  const add = (tag, cls) => {
    const e = new El(tag);
    if (cls) e.className = cls;
    tr.appendChild(e);
    return e;
  };
  add('td', 'url-tab-cell');
  add('td', 'url-cool-cell');
  for (const action of ['cool-reset', 'cool-edit']) {
    const btn = add('button', 'btn-small');
    btn.dataset.action = action;
  }
  return tr;
}

/** `<td class="url-cool-cell"><span data-cool-left data-cool-at></span></td>`. */
function clockCell(left, atMs, text) {
  const cell = new El('td');
  cell.className = 'url-cool-cell';
  const clock = new El('span');
  clock.textContent = text || '15:00 / 15:00';
  clock.dataset['cool-left'] = String(left);
  clock.setAttribute('data-cool-left', String(left));
  clock.setAttribute('data-cool-at', String(atMs));
  cell.appendChild(clock);
  return cell;
}

function urlCell(extra = {}) {
  const h = bootPage();
  const tr = urlRowStub();
  h.run('UrlListCells').fillCoolCell(tr, worker(extra));
  return { h, tr, html: tr.querySelector('.url-cool-cell').innerHTML };
}

describe('the worker table always shows a countdown', () => {
  test('a cooling page shows the ticking value with its total', () => {
    const { html } = poolRow({ status: 'cooldown', cooldown_remaining: 900, cooldown_total: 900 });
    assert.match(html, /data-cool-left="900"/);
    assert.match(html, /data-cool-at="\d+"/);
    assert.ok(html.includes('15:00'), html);
  });

  test('a live timer is shown even when the status label says otherwise', () => {
    for (const status of ['steady', 'busy', 'waiting_captcha', 'error']) {
      const { html } = poolRow({ status, cooldown_remaining: 900, cooldown_total: 900 });
      assert.match(html, /data-cool-left="900"/, `status ${status}`);
      assert.ok(html.includes('15:00'), `status ${status}`);
    }
  });

  test('a ready page shows 00:00 in the countdown cell, never a dash', () => {
    const h = bootPage();
    h.emit('page_pool_updated', JSON.stringify(snapOf(worker())));
    const cool = cellsOf(rowsHtml(h.anyEl('poolTableBody'))).at(-2);  // last is Actions
    assert.ok(cool.includes('00:00'), cool);
    assert.match(cool, /data-cool-left="0"/);
    assert.ok(!cool.includes('—'), 'the countdown slot is never a dash');
  });

  test('a stacked debt is labelled as a debt, not as a bare +15:00', () => {
    const { html } = poolRow({ status: 'busy', pending_penalty: 900 });
    assert.ok(html.includes('00:00'), 'the countdown slot still shows a time');
    assert.match(html, /\+15:00\s*debt/, html);
    assert.ok(!html.includes('+15:00 pending'), 'the frozen pending label is gone');
  });

  test('the 1 s tick counts down and lands on 00:00', () => {
    const h = bootPage();
    h.emit('page_pool_updated', JSON.stringify(snapOf(worker({
      status: 'cooldown', cooldown_remaining: 900, cooldown_total: 900 }))));
    const el = new El('span');
    el.textContent = '15:00 / 15:00';
    el.setAttribute('data-cool-left', '900');
    el.setAttribute('data-cool-at', String(Date.now() - 3000));
    h.sb.document.querySelectorAll = (sel) => (sel === '[data-cool-tab]' ? [el] : []);
    h.run('PagePoolPanel').tickCountdowns();
    assert.ok(el.textContent.includes('14:57'), el.textContent);
    assert.ok(el.textContent.includes('/ 15:00'), 'the total survives the tick');
    el.setAttribute('data-cool-at', String(Date.now() - 900000));
    h.run('PagePoolPanel').tickCountdowns();
    assert.equal(el.textContent.trim(), '00:00');
  });
});

describe('the URL list shows the same countdown', () => {
  test('a live timer carries both anchors', () => {
    const { html } = urlCell({ status: 'cooldown', cooldown_remaining: 900, cooldown_total: 900 });
    assert.match(html, /data-cool-left="900"/);
    assert.match(html, /data-cool-at="\d+"/);
    assert.match(html, /data-cool-tab="1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d"/);
    assert.ok(html.includes('15:00'), html);
  });

  test('a live timer outranks the busy label', () => {
    const { html } = urlCell({ status: 'busy', cooldown_remaining: 900, cooldown_total: 900 });
    assert.match(html, /data-cool-left="900"/, html);
    assert.ok(!html.includes('🔵 busy'), 'the timer is the more useful truth');
  });

  test('a ready row shows 00:00 instead of ✅ ready', () => {
    const { html } = urlCell();
    assert.ok(html.includes('00:00'), html);
    assert.ok(!html.includes('✅ ready'), 'the cell still carries a countdown');
  });

  test('a busy row keeps its marker and shows the debt honestly', () => {
    const { html } = urlCell({ status: 'busy', pending_penalty: 900 });
    assert.ok(html.includes('🔵 busy'), html);
    assert.match(html, /\+15:00\s*debt/, html);
    assert.ok(html.includes('00:00'), html);
  });

  test('the URL ticker counts down to 00:00 and stays there', () => {
    const h = bootPage();
    const tbody = h.anyEl('urlTableBody');
    tbody.appendChild(clockCell(900, Date.now() - 3000));
    const clock = tbody.children[0].children[0];
    h.run('UrlListCells').tick(tbody);
    assert.ok(clock.textContent.includes('14:57'), clock.textContent);
    clock.setAttribute('data-cool-at', String(Date.now() - 900000));
    h.run('UrlListCells').tick(tbody);
    assert.equal(clock.textContent.trim(), '00:00');
  });

  test('a row whose tab is not pooled still says so', () => {
    const h = bootPage();
    const tr = urlRowStub();
    h.run('UrlListCells').fillCoolCell(tr, null);
    const html = tr.querySelector('.url-cool-cell').innerHTML;
    assert.ok(html.includes('Tab not in pool'), html);
  });
});
