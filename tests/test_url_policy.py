"""S6/S7/S10 policy units, exactly one definition per named function."""
import copy

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo
from app.services.run_state import pooled_ids
from app.core.models import UrlRow
from app.services.live import url_policy as policy

pytestmark = pytest.mark.unit


def row(tid='', url='https://arena.ai/image', enabled=True):
    value = UrlRow.create(url, enabled=enabled, tab_id=tid)
    value.last_status = 'valid'
    return value


@pytest.mark.target('app.services.live.url_policy:removable_rows')
@pytest.mark.parametrize('case,reason', [('duplicate','duplicate'), ('gone','tab_gone'),
    ('pattern','pattern_mismatch'), ('invalid','invalid'), ('busy',None), ('unchecked',None), ('miss1',None), ('miss2',None)])
def test_removable_rows(case, reason):
    rows = [row('t1')]
    spec = policy.RemovalSpec(rows=rows, live_keys={'t1'}, misses={'t1':2})
    if case == 'duplicate':
        rows.append(row('t1'))
    if case in ('gone', 'busy', 'miss1', 'miss2'):
        spec.live_keys = {'other'}
    if case.startswith('miss'):
        spec.misses = {'t1':int(case[-1])-1}
    if case == 'pattern':
        spec.pattern = 'example.org'
    if case == 'invalid':
        rows[0].url = 'bad'
    if case == 'busy':
        spec.busy_tabs = {'t1'}
        spec.pattern = 'nonmatching'
    if case == 'unchecked':
        rows[0] = UrlRow.create('https://arena.ai/new')
        spec.pattern = 'nonmatching'
    before = copy.deepcopy(rows)
    result = policy.removable_rows(spec)
    assert [(r.row_id, r.reason) for r in result] == ([(rows[-1].id, reason)] if reason else [])
    assert rows == before
    if case == 'busy':
        spec.busy_tabs = set()
        assert policy.removable_rows(spec)[0].row_id == rows[0].id


@pytest.mark.target('app.services.live.url_policy:advance_misses')
@pytest.mark.parametrize('present', [False, True])
@pytest.mark.parametrize('previous', [0, 1, 2])
def test_advance_misses(present, previous):
    misses = {'t1':previous} if previous else {}
    expected = {} if present else {'t1':previous+1}
    assert policy.advance_misses([row('t1')], {'t1'} if present else set(), misses) == expected
    assert misses == ({'t1':previous} if previous else {})


@pytest.mark.target('app.services.live.url_policy:dedupe_rows')
@pytest.mark.parametrize('empty', [False, True])
def test_dedupe_rows(empty):
    rows = [] if empty else [row('t1', enabled=False), row(), row('t1'), row('t1')]
    kept, dropped = policy.dedupe_rows(rows)
    assert kept == ([] if empty else [rows[1], rows[2]])
    assert dropped == ([] if empty else [rows[0], rows[3]])
    assert len(rows) == (0 if empty else 4)


@pytest.mark.target('app.services.live.url_policy:add_rows')
@pytest.mark.parametrize('wire', ['tuple', 'dict'])
@pytest.mark.parametrize('enabled', [False, True])
def test_add_rows(wire, enabled):
    item = ('https://arena.ai/a','t1') if wire == 'tuple' else {'url':'https://arena.ai/a','tab_id':'t1'}
    rows = []
    assert policy.add_rows(rows, [item, item], {'t1':enabled}) == 1
    assert (rows[0].tab_id, rows[0].enabled) == ('t1', enabled)


@pytest.mark.target('app.services.live.url_policy:remember')
@pytest.mark.parametrize('count', [0, 1, 210])
def test_remember(count):
    original = {'old':False}
    memory = policy.remember([row(str(i), enabled=False) for i in range(count)], original)
    assert original == {'old':False}
    assert len(memory) == min(count+1,200)
    assert set(memory.values()) == {False}
    if count == 210:
        assert set(memory) == {str(i) for i in range(10,210)}


@pytest.mark.target('app.services.live.url_policy:restore_enabled')
@pytest.mark.parametrize('memory,expected', [(None,True), ({},True), ({'t1':False},False), ({'t1':True},True)])
def test_restore_enabled(memory, expected):
    assert policy.restore_enabled('t1', memory) is expected


@pytest.mark.target('app.services.live.url_policy:removal_lines')
@pytest.mark.parametrize('empty', [False, True])
def test_removal_lines(empty):
    rows = [] if empty else [policy.Removal('1','https://arena.ai/a','tab_gone'), policy.Removal('2','https://arena.ai/b','duplicate')]
    lines = policy.removal_lines(rows)
    assert len(lines) == len(rows)
    for line, item in zip(lines, rows):
        assert item.url in line and item.reason in line


CASES = [(False,'t1',{'t1'},{'t1'},'unchecked'), (True,'',set(),{'t1'},'not linked'),
         (True,'t1',{'t1'},set(),'offline'), (True,'t1',set(),{'t1'},'unchecked'),
         (True,'t1',{'t1'},{'t1'},'')]


@pytest.mark.target('app.services.live.url_policy:receiver_reason')
@pytest.mark.parametrize('enabled,tid,allowed,pooled,expected', CASES)
def test_receiver_reason(enabled, tid, allowed, pooled, expected):
    assert policy.receiver_reason(row(tid, enabled=enabled), allowed, pooled) == expected


@pytest.mark.target('app.services.live.url_policy:mark_receivers')
@pytest.mark.parametrize('enabled,tid,allowed,pooled,reason', CASES)
def test_mark_receivers(enabled, tid, allowed, pooled, reason):
    item = row(tid, enabled=enabled)
    item.receiver = bool(reason)
    assert policy.mark_receivers([item], allowed, pooled) == 1
    assert item.receiver is (reason == '')
    assert policy.mark_receivers([item], allowed, pooled) == 0


@pytest.mark.target('app.services.live.url_policy:connected_tab_ids')
@pytest.mark.parametrize('state', ['none', 'empty', 'mixed'])
def test_connected_tab_ids(state):
    pool = None if state == 'none' else PagePool()
    if state == 'mixed':
        pool.add_page(PageInfo(tab_id='one'))
        pool.add_page(PageInfo(tab_id='two'))
        pool.get_page('two').is_connected = False
    assert policy.connected_tab_ids(pool) == ({'one'} if state == 'mixed' else set())
    if state == 'mixed':
        assert pooled_ids(pool) == {'one','two'}  # disconnected is still registered
