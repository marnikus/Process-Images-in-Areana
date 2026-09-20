"""S6/S9 function units; Qt/bridge/pool signal wiring is covered separately."""
import copy
import json
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from app.services.live import debug_view as view

pytestmark = pytest.mark.unit


def host(images=None, rows=None):
    return NS(state=NS(images=images or [], urls=rows or []), _run_state='paused',
              config=NS(get_state=Mock(return_value=1200)), _last_reconcile_at=1000.25, _reconcile_passes=3)


@pytest.mark.target('app.services.live.debug_view:clamp_interval_ms')
@pytest.mark.parametrize('raw,expected', [(1,500), (60001,60000), ('abc',5000), (None,5000), (2500,2500)])
def test_clamp_interval_ms(raw, expected):
    assert view.clamp_interval_ms(raw) == expected


@pytest.mark.target('app.services.live.debug_view:interval_ms')
@pytest.mark.parametrize('broken', [False, True])
def test_interval_ms(broken):
    bridge = host()
    if broken:
        bridge.config.get_state.side_effect = RuntimeError('unreadable')
    assert view.interval_ms(bridge) == (5000 if broken else 1200)


@pytest.mark.target('app.services.live.debug_view:cadence')
def test_cadence():
    assert view.cadence(host()) == {'url_interval_ms':1200, 'last_pass_at':1000.25, 'passes':3}


@pytest.mark.target('app.services.live.debug_view:next_queued')
@pytest.mark.parametrize('statuses,selected,expected', [([],[],''), (['completed','processing'],[True,True],''),
    (['pending','failed','needs_review'],[False,True,True],'i1.png'), (['pending'],[True],'i0.png')])
def test_next_queued(statuses, selected, expected):
    images = [NS(status=s,selected=on,filename=f'i{i}.png') for i,(s,on) in enumerate(zip(statuses,selected))]
    assert view.next_queued(images) == expected
    assert [i.status for i in images] == statuses


@pytest.mark.target('app.services.live.debug_view:receiver_counts')
@pytest.mark.parametrize('flags', [[],[True,False,True],[False,False]])
def test_receiver_counts(flags):
    rows = [NS(receiver=f, enabled=False) for f in flags]
    assert view.receiver_counts(rows) == {'total':len(flags),'receivers':sum(flags),'not_receivers':len(flags)-sum(flags)}


@pytest.mark.target('app.services.live.debug_view:live_view')
@pytest.mark.parametrize('empty', [False, True])
def test_live_view(empty):
    images = [] if empty else [NS(status='pending',selected=True,filename='first.png')]
    bridge = host(images, [NS(receiver=True,enabled=False)])
    bridge._page_pool = NS(status_snapshot=Mock(side_effect=AssertionError('must not sample pool')))
    before = copy.deepcopy(bridge.state)
    result = view.live_view(bridge)
    assert result == {'url_interval_ms':1200,'last_pass_at':1000.25,'passes':3,'queued':int(not empty),
                      'next_image':'' if empty else 'first.png', 'receivers':{'total':1,'receivers':1,'not_receivers':0},'run_state':'paused'}
    assert bridge.state == before
    assert json.loads(json.dumps(result)) == result
    bridge._page_pool.status_snapshot.assert_not_called()
    with pytest.raises(AssertionError, match='must not sample pool'):
        bridge._page_pool.status_snapshot()  # positive control for the counter
    bridge._page_pool.status_snapshot.assert_called_once()
