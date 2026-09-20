"""S10 equivalence: pure URL policy exercised with real rows, not placeholders."""
import copy

import pytest

from app.core.models import UrlRow
from app.services.live import url_policy as policy


def row(tid='', url='https://arena.ai/image', enabled=True):
    value = UrlRow.create(url, enabled=enabled, tab_id=tid)
    value.last_status = 'valid'
    return value


@pytest.mark.parametrize('case,reason', [('duplicate', 'duplicate'), ('gone', 'tab_gone'),
                                         ('pattern', 'pattern_mismatch'), ('invalid', 'invalid')])
def test_removable_rows_names_each_reason_without_mutating_input(case, reason):
    rows = [row('t1')]
    spec = policy.RemovalSpec(rows=rows, live_keys={'t1'}, misses={'t1': 2})
    if case == 'duplicate':
        rows.append(row('t1'))
    elif case == 'gone':
        spec.live_keys = {'other'}
    elif case == 'pattern':
        spec.pattern = 'example.org'
    else:
        rows[0].url = 'not-a-url'
    before = copy.deepcopy(rows)
    removals = policy.removable_rows(spec)
    assert [(r.row_id, r.reason) for r in removals] == [(rows[-1].id, reason)]
    assert rows == before


def test_live_job_and_never_linked_unchecked_rows_are_kept():
    busy, new = row('gone'), UrlRow.create('https://arena.ai/new')
    spec = policy.RemovalSpec(rows=[busy, new], live_keys={'other'}, busy_tabs={'gone'},
                              misses={'gone': 99}, pattern='nonmatching')
    assert policy.removable_rows(spec) == []
    spec.busy_tabs = set()  # positive control, same missing tab now removable
    assert policy.removable_rows(spec)[0].row_id == busy.id


def test_hysteresis_and_reappearance_reset_misses():
    rows = [row('t1')]
    misses = {}
    for n in range(3):
        spec = policy.RemovalSpec(rows=rows, live_keys=set(), misses=misses)
        assert bool(policy.removable_rows(spec)) is (n == 2)
        misses = policy.advance_misses(rows, set(), misses)
    assert misses == {'t1': 3}
    assert policy.advance_misses(rows, {'t1'}, misses) == {}
    assert misses == {'t1': 3}  # does not mutate caller's counter snapshot


def test_dedupe_prefers_checked_owner_and_keeps_unlinked_order():
    unchecked, checked, duplicate = row('t1', enabled=False), row('t1'), row('t1')
    unlinked = row()
    rows = [unchecked, unlinked, checked, duplicate]
    kept, dropped = policy.dedupe_rows(rows)
    assert kept == [unlinked, checked]
    assert dropped == [unchecked, duplicate]
    assert len(rows) == 4


def test_checkbox_memory_is_bounded_and_reused_without_duplication():
    original = {'old': False}
    memory = policy.remember([row('t1', enabled=False)], original)
    assert original == {'old': False}
    assert policy.restore_enabled('t1', memory) is False
    assert policy.restore_enabled('new', memory) is True
    rows = []
    assert policy.add_rows(rows, [('https://arena.ai/image', 't1')] * 2, memory) == 1
    assert rows[0].enabled is False
    assert len(policy.remember([row(str(i)) for i in range(210)])) == 200


def test_removal_log_preserves_reason_for_each_row():
    removals = [policy.Removal('1', 'https://arena.ai/a', 'tab_gone'),
                policy.Removal('2', 'https://arena.ai/b', 'duplicate')]
    lines = policy.removal_lines(removals)
    assert len(lines) == 2
    assert 'https://arena.ai/a' in lines[0] and 'tab_gone' in lines[0]
    assert 'https://arena.ai/b' in lines[1] and 'duplicate' in lines[1]
    assert policy.removal_lines([]) == []
