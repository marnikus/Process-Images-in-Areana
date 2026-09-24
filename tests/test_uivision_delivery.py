"""Address-bar delivery — the autorun URL into a running window, no remoting.

RULE 8: the `ops` seam carries every OS primitive, so the key sequence, the
foreground verification and the clipboard save/restore run for real against
fakes on any OS; only `Win32Ops` itself touches windll (and only in methods).
"""

import pytest

from app.browser.uivision import delivery

pytestmark = pytest.mark.unit


class FakeOps:
    """The OS half as a script: foreground answer + recorded calls."""

    def __init__(self, foreground=11, clip="saved-clip", fail_keys=False):
        self.calls = []
        self._foreground = foreground
        self.clip = clip
        self._fail_keys = fail_keys

    def raise_window(self, hwnd):
        self.calls.append(("raise", hwnd))
        return 1

    def foreground_window(self):
        self.calls.append(("foreground",))
        if isinstance(self._foreground, Exception):
            raise self._foreground
        return self._foreground

    def send_ctrl(self, letter):
        self.calls.append(("ctrl", letter))
        if self._fail_keys:
            raise delivery.DeliveryError("SendInput failed")

    def press_enter(self):
        self.calls.append(("enter",))

    def get_clipboard(self):
        return self.clip

    def set_clipboard(self, text):
        self.calls.append(("clipboard", text))
        self.clip = text

    def sleep(self, seconds):
        self.calls.append(("sleep", seconds))


def test_deliver_url_sends_new_tab_paste_enter_and_restores_clipboard():
    ops = FakeOps()
    delivery.deliver_url(11, "file:///autorun?macro=M", ops=ops)
    keys = [call for call in ops.calls if call[0] in ("ctrl", "enter")]
    assert keys == [("ctrl", "t"), ("ctrl", "v"), ("enter",)]
    assert ops.calls[0] == ("clipboard", "file:///autorun?macro=M")  # URL staged first
    assert ("raise", 11) in ops.calls                     # the window comes front first
    assert ops.clip == "saved-clip"                       # the user's clipboard is back


def test_deliver_url_verifies_the_foreground_before_typing():
    ops = FakeOps(foreground=99)                          # another window owns it
    with pytest.raises(delivery.DeliveryError, match="would not come to the front"):
        delivery.deliver_url(11, "file:///autorun", ops=ops)
    assert [c for c in ops.calls if c[0] == "raise"] == [("raise", 11)] * delivery.DELIVER_TRIES
    assert not [c for c in ops.calls if c[0] in ("ctrl", "enter")]  # no blind typing
    assert ops.clip == "saved-clip"                       # restored even on failure


def test_deliver_url_without_ops_refuses_off_windows():
    with pytest.raises(delivery.DeliveryError, match="needs Windows"):
        delivery.deliver_url(11, "file:///autorun")


def test_delivery_error_is_an_os_error():
    assert issubclass(delivery.DeliveryError, OSError)  # the sequence catches OSError
