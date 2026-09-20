# Integration/contract lane: real collaborators; not counted as function units.
"""LiveBus (S4) — the ONE wake event queue mutations ring.

Spec: `app/services/live/bus.py` — `attach(loop)`, `wake(reason)`,
`wait(timeout_s)`, `throttle(key, ms)`, `reasons()`; `live_bus(bridge)`
gives one bus per bridge. Reasons parked before a waiter arms are never
lost; `wait` drains them all at once and then reports nothing.
"""


from app.services.live.bus import LiveBus
from app.services.live import LiveBus as LiveBusReexport  # facade re-exports

import pytest

pytestmark = pytest.mark.integration


def test_live_bus_exists_and_reexports():
    bus = LiveBus()
    assert bus is not None
    assert LiveBusReexport is LiveBus
    assert LiveBus.__module__ == "app.services.live.bus"
