"""The autorun URL into its profile's window — no remoting, no new process (Windows).

`deliver_url` opens the URL as a NEW tab in an already-running Firefox window:
raise it, verify it owns the foreground (the OS may refuse — retried), Ctrl+T,
paste the URL, Enter. The user's current tab is never touched. The OS
primitives ride the injectable `ops` (`Win32Ops`: SendInput keys + clipboard);
tests inject fakes, so this module is exercised on any OS. Anything that
refuses becomes `DeliveryError` and the sequence degrades to the manual
fallback (print the URL + steps, still poll the savelog) instead of crashing.
"""

from __future__ import annotations

class DeliveryError(OSError):
    """The autorun URL could not be delivered to its profile's window."""


DELIVER_TRIES = 3        # foreground-verify attempts before the delivery gives up
RAISE_SETTLE_SEC = 0.3   # the OS needs a beat after SetForegroundWindow
ADDRESS_SETTLE_SEC = 0.4  # a fresh Ctrl+T tab needs a beat before the paste lands
PASTE_SETTLE_SEC = 0.2   # the paste needs a beat before Enter navigates


def _ensure_foreground(hwnd, ops, tries: int = DELIVER_TRIES) -> None:
    """Raise until the window owns the foreground (the OS may refuse — retry)."""
    for _ in range(max(1, tries)):
        ops.raise_window(hwnd)
        ops.sleep(RAISE_SETTLE_SEC)
        try:
            if ops.foreground_window() == hwnd:
                return
        except Exception:
            pass
    raise DeliveryError(f"window {hwnd} would not come to the front — keystrokes "
                        f"cannot be aimed at it")


def _restore_clipboard(ops, saved) -> None:
    """Best-effort clipboard restore — a failed restore never fails the run."""
    if saved is None:
        return
    try:
        ops.set_clipboard(saved)
    except Exception:
        pass


def deliver_url(hwnd, url: str, ops=None) -> None:
    """Open `url` as a NEW tab in the `hwnd` window: raise → Ctrl+T → paste → Enter.

    The user's current tab is never touched (Ctrl+T opens a fresh tab, already
    address-bar-focused). `ops` carries the OS primitives (`Win32Ops` default);
    an explicitly injected `ops` owns its platform so tests run anywhere, while
    the default path refuses off-Windows with a `DeliveryError` (→ manual).
    """
    import sys
    if ops is None and sys.platform != "win32":
        raise DeliveryError("address-bar delivery needs Windows — open the "
                            "autorun URL in the profile's window by hand")
    real = ops or Win32Ops()
    try:
        saved = real.get_clipboard()
    except Exception:
        saved = None
    try:
        real.set_clipboard(url)
        _ensure_foreground(hwnd, real)
        real.send_ctrl("t")
        real.sleep(ADDRESS_SETTLE_SEC)
        real.send_ctrl("v")
        real.sleep(PASTE_SETTLE_SEC)
        real.press_enter()
    finally:
        _restore_clipboard(real, saved)


# ── Win32 primitives (SendInput keys + clipboard; windll touched only in methods) ──

VK_CONTROL = 0x11
VK_RETURN = 0x0D
INPUT_KEYBOARD = 0
KEYEVENTF_KEYUP = 0x0002
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def _keyboard_structs():
    """(INPUT, size) — the SendInput structures (pure ctypes, safe to build anywhere)."""
    import ctypes

    class KeyboardInput(ctypes.Structure):
        _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                    ("dwFlags", ctypes.c_uint), ("time", ctypes.c_uint),
                    ("dwExtraInfo", ctypes.c_void_p)]

    class Input(ctypes.Structure):
        class _Union(ctypes.Union):
            _fields_ = [("ki", KeyboardInput)]
        _anonymous_ = ("u",)
        _fields_ = [("type", ctypes.c_uint), ("u", _Union)]

    return Input, ctypes.sizeof(Input)


def _send_keys(events) -> None:
    """[(vk, down)] through SendInput — one call, keys in order."""
    import ctypes
    pair, size = _keyboard_structs()
    array = (pair * len(events))()
    for pos, (vk, down) in enumerate(events):
        array[pos].type = INPUT_KEYBOARD
        array[pos].ki.wVk = vk
        array[pos].ki.dwFlags = 0 if down else KEYEVENTF_KEYUP
    if not ctypes.windll.user32.SendInput(len(events), array, size):
        raise DeliveryError("Windows refused the keystrokes (SendInput failed)")


def _clipboard_text(user32, kernel32):
    """Current CF_UNICODETEXT or None (unreadable/empty is not an error)."""
    import ctypes
    if not user32.OpenClipboard(None):
        return None
    try:
        if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        locked = kernel32.GlobalLock(handle) if handle else None
        if not locked:
            return None
        try:
            return ctypes.wstring_at(locked)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def _set_clipboard_text(user32, kernel32, text: str) -> None:
    """Replace the clipboard with `text` (raises DeliveryError on refusal)."""
    import ctypes
    if not user32.OpenClipboard(None):
        raise DeliveryError("Windows refused the clipboard (OpenClipboard failed)")
    try:
        user32.EmptyClipboard()
        data = (text or "").encode("utf-16-le") + b"\x00\x00"
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            raise DeliveryError("Windows refused the clipboard (GlobalAlloc failed)")
        locked = kernel32.GlobalLock(handle)
        ctypes.memmove(locked, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            raise DeliveryError("Windows refused the clipboard (SetClipboardData failed)")
    finally:
        user32.CloseClipboard()


class Win32Ops:
    """The real key/clipboard/foreground primitives (Windows only; tests fake them)."""

    def raise_window(self, hwnd) -> int:
        """Restore + foreground one handle (best effort — the OS may refuse)."""
        from app.utils.win_popup import raise_handles
        return raise_handles([hwnd])

    def foreground_window(self):
        """The handle owning the foreground right now."""
        import ctypes
        return ctypes.windll.user32.GetForegroundWindow()

    def send_ctrl(self, letter: str) -> None:
        """Ctrl+<letter> (Ctrl+T new tab, Ctrl+V paste)."""
        vk = ord((letter or "")[:1].upper())
        _send_keys([(VK_CONTROL, True), (vk, True), (vk, False), (VK_CONTROL, False)])

    def press_enter(self) -> None:
        """A bare Enter (navigates the pasted address-bar URL)."""
        _send_keys([(VK_RETURN, True), (VK_RETURN, False)])

    def get_clipboard(self):
        """Current clipboard text or None."""
        import ctypes
        return _clipboard_text(ctypes.windll.user32, ctypes.windll.kernel32)

    def set_clipboard(self, text: str) -> None:
        """Replace the clipboard text."""
        import ctypes
        _set_clipboard_text(ctypes.windll.user32, ctypes.windll.kernel32, text)

    def sleep(self, seconds: float) -> None:
        """A real settle pause (tests inject instant fakes)."""
        import time
        time.sleep(seconds)
