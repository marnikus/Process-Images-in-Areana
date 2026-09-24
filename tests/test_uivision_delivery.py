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


def _never_called(name):
    """A fake dll function that fails the test if it ever runs."""
    def _boom(*_args):
        raise AssertionError(f"{name} must not run on this path")
    return _boom


def _dll(**funcs):
    from types import SimpleNamespace
    return SimpleNamespace(**funcs)


def test_input_struct_matches_the_windows_40_byte_layout():
    """SendInput's INPUT is 40 bytes on 64-bit Windows — undersized is an AV."""
    import ctypes
    Input, size = delivery._keyboard_structs()
    assert size == 40 == ctypes.sizeof(Input)
    union = dict(Input._fields_)["u"]
    assert [name for name, _tp in union._fields_] == ["mi", "ki", "hi"]
    assert ctypes.sizeof(union) == 32           # the mouse member sizes it


def test_clipboard_binding_declares_pointer_sized_handles():
    """Undeclared HANDLE returns truncate to 32-bit int — the 2026-09-24 AV."""
    import ctypes
    user32 = _dll(OpenClipboard=lambda _h: True, CloseClipboard=lambda: True,
                  EmptyClipboard=lambda: True,
                  IsClipboardFormatAvailable=lambda _f: True,
                  GetClipboardData=lambda _f: None, SetClipboardData=lambda _f, _h: None)
    kernel32 = _dll(GlobalAlloc=lambda _f, _s: None, GlobalLock=lambda _h: None,
                    GlobalUnlock=lambda _h: True, GlobalFree=lambda _h: None)
    delivery._bind_clipboard(user32, kernel32)
    ptr = ctypes.sizeof(ctypes.c_void_p)
    for fn in (user32.GetClipboardData, user32.SetClipboardData,
               kernel32.GlobalAlloc, kernel32.GlobalLock):
        assert ctypes.sizeof(fn.restype) == ptr


def test_keys_binding_declares_sendinput_and_foreground():
    import ctypes
    user32 = _dll(SendInput=lambda *a: 0, GetForegroundWindow=lambda: 0)
    delivery._bind_keys(user32)
    assert len(user32.SendInput.argtypes) == 3
    assert ctypes.sizeof(user32.GetForegroundWindow.restype) == ctypes.sizeof(ctypes.c_void_p)


def test_set_clipboard_frees_the_block_when_lock_fails():
    """A refused GlobalLock frees its block and refuses loudly — never memmove(NULL)."""
    freed = []
    user32 = _dll(OpenClipboard=lambda _h: True, EmptyClipboard=lambda: True,
                  CloseClipboard=lambda: True,
                  SetClipboardData=_never_called("SetClipboardData"))
    kernel32 = _dll(GlobalAlloc=lambda _f, _s: 0xBEEF,
                    GlobalLock=lambda _h: None,            # the refusal
                    GlobalUnlock=lambda _h: True,
                    GlobalFree=freed.append)
    with pytest.raises(delivery.DeliveryError, match="GlobalLock failed"):
        delivery._set_clipboard_text(user32, kernel32, "file:///autorun")
    assert freed == [0xBEEF]                                  # the block never leaks


def test_set_clipboard_writes_the_url_into_the_locked_block():
    """The happy path through the real function: bytes staged, handle published."""
    import ctypes
    buf = ctypes.create_string_buffer(256)
    published = []
    user32 = _dll(OpenClipboard=lambda _h: True, EmptyClipboard=lambda: True,
                  CloseClipboard=lambda: True,
                  SetClipboardData=lambda fmt, handle: published.append((fmt, handle)) or True)
    kernel32 = _dll(GlobalAlloc=lambda _f, _s: 0xBEEF,
                    GlobalLock=lambda _h: ctypes.addressof(buf),
                    GlobalUnlock=lambda _h: True,
                    GlobalFree=_never_called("GlobalFree"))
    delivery._set_clipboard_text(user32, kernel32, "file:///autorun")
    assert published == [(delivery.CF_UNICODETEXT, 0xBEEF)]
    staged = "file:///autorun".encode("utf-16-le")
    assert bytes(buf)[:len(staged)] == staged
