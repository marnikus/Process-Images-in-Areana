"""S4 unit owners. Concurrency and real-Bridge reset contracts are integration tests."""
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from app.core.run_scope import eligible_images
from app.services.live import feed
from app.services.live.bus import live_bus

pytestmark = pytest.mark.unit


def image(status='pending', selected=True, filename='i.png', assigned=None):
    return NS(status=status, selected=selected, filename=filename, error='old', assigned_url_id=assigned)


def host(images, pool=None):
    return NS(state=NS(images=images, recalculate_progress=Mock()), _page_pool=pool,
              _save_arena=Mock(), _emit_arena_state=Mock(), _queue_undo_push=Mock())


@pytest.mark.target('app.core.run_scope:eligible_images')
@pytest.mark.parametrize('selected', [True, False])
def test_eligible_images(selected):
    statuses = ['pending', 'failed', 'selected', 'needs_review', 'processing', 'skipped', 'completed', 'deselected']
    images = [image(s, selected) for s in statuses]
    assert [i.status for i in eligible_images(images)] == (statuses[:4] if selected else [])
    assert [i.status for i in images] == statuses


@pytest.mark.target('app.services.live.feed:commit_queue')
@pytest.mark.parametrize('undo', [True, False])
def test_commit_queue(undo):
    bridge = host([image(), image('processing'), image('completed')])
    count = feed.commit_queue(bridge, 'reset_all', undo=undo)
    assert count == 1
    bridge.state.recalculate_progress.assert_called_once()
    bridge._save_arena.assert_called_once()
    bridge._emit_arena_state.assert_called_once()
    assert bridge._queue_undo_push.call_count == int(undo)
    if undo:
        bridge._queue_undo_push.assert_called_once_with(bridge)
    assert live_bus(bridge).reasons() == ['reset_all']


@pytest.mark.target('app.services.live.feed:recover_stale_processing')
@pytest.mark.parametrize('active', [True, False])
def test_recover_stale_processing(active):
    live, dead, done = image('processing', filename='live.png'), image('processing'), image('completed')
    pool = NS(_pages={'t1': NS(current_image='live.png')}) if active else None
    bridge = host([live, dead, done], pool)
    assert feed.recover_stale_processing(bridge) == (1 if active else 2)
    assert live.status == ('processing' if active else 'pending')
    assert (dead.status, dead.selected, dead.error) == ('pending', True, None)
    assert done.status == 'completed'


@pytest.mark.target('app.services.live.feed:clear_row_assignments')
@pytest.mark.parametrize('removed,count', [([], 0), (['u1'], 1), (['u1','u2'], 2)])
def test_clear_row_assignments(removed, count):
    bridge = host([image(assigned='u1'), image(assigned='u2'), image()])
    assert feed.clear_row_assignments(bridge, removed) == count
    assert [i.assigned_url_id for i in bridge.state.images] == [None if k in removed else k for k in ['u1','u2',None]]
