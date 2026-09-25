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

import ctypes

from . import integrity


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
        refused = integrity.check_delivery(hwnd, real)
        if refused:
            raise DeliveryError(refused)
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


class _MouseInput(ctypes.Structure):
    """Windows MOUSEINPUT — the INPUT union's largest member (sizes the union)."""

    _fields_ = [("dx", ctypes.c_int32), ("dy", ctypes.c_int32),
                ("mouseData", ctypes.c_uint32), ("dwFlags", ctypes.c_uint32),
                ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_void_p)]


class _KeyboardInput(ctypes.Structure):
    """Windows KEYBDINPUT — the only member SendInput touches here."""

    _fields_ = [("wVk", ctypes.c_uint16), ("wScan", ctypes.c_uint16),
                ("dwFlags", ctypes.c_uint32), ("time", ctypes.c_uint32),
                ("dwExtraInfo", ctypes.c_void_p)]


class _HardwareInput(ctypes.Structure):
    """Windows HARDWAREINPUT — completes the union (never sent)."""

    _fields_ = [("uMsg", ctypes.c_uint32),
                ("wParamL", ctypes.c_uint16), ("wParamH", ctypes.c_uint16)]


class _InputUnion(ctypes.Union):
    """The INPUT union — 32 bytes, the mouse member sizes it."""

    _fields_ = [("mi", _MouseInput), ("ki", _KeyboardInput), ("hi", _HardwareInput)]


class _Input(ctypes.Structure):
    """Windows INPUT — 40 bytes on 64-bit (type + padding + the union)."""

    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_uint32), ("u", _InputUnion)]


def _keyboard_structs():
    """(INPUT, size) — the real Windows INPUT layout (40 bytes on 64-bit).

    Widths are pinned explicitly (a Windows LONG stays 32-bit on 64-bit),
    so the layout measures identical wherever the tests run.
    """
    return _Input, ctypes.sizeof(_Input)


def _bind_clipboard(user32, kernel32) -> None:
    """Clipboard HANDLE/pointer signatures — undeclared windll returns default
    to 32-bit int, truncating 64-bit HANDLEs into access violations (2026-09-24)."""
    from ctypes import wintypes
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL


def _bind_keys(user32) -> None:
    """SendInput + GetForegroundWindow signatures (the same truncation trap)."""
    from ctypes import wintypes
    user32.SendInput.argtypes = [wintypes.UINT, wintypes.LPVOID, ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND


def _ctrl_sequence(letter: str) -> list:
    """[(vk, down)] for Ctrl+<letter> — Ctrl wraps the letter, down-up order."""
    vk = ord((letter or "")[:1].upper())
    return [(VK_CONTROL, True), (vk, True), (vk, False), (VK_CONTROL, False)]


def _enter_sequence() -> list:
    """[(vk, down)] for a bare Enter (down, then up)."""
    return [(VK_RETURN, True), (VK_RETURN, False)]


def _key_inputs(events):
    """[(vk, down)] → a real INPUT array + its byte size (pure bytes, no windll)."""
    pair, size = _keyboard_structs()
    array = (pair * len(events))()
    for pos, (vk, down) in enumerate(events):
        array[pos].type = INPUT_KEYBOARD
        array[pos].ki.wVk = vk
        array[pos].ki.dwFlags = 0 if down else KEYEVENTF_KEYUP
    return array, size


def _send_keys(events) -> None:
    """[(vk, down)] through SendInput — one call, the count asserted exactly.

    MSDN's own example compares `uSent != ARRAYSIZE`: a partial injection (a
    hook, hotkey app, or antivirus swallowing some events) is a failure, not
    a success — truthiness here once reported swallowed keys as delivered.
    """
    import ctypes
    user32 = ctypes.windll.user32
    _bind_keys(user32)
    array, size = _key_inputs(events)
    injected = user32.SendInput(len(events), array, size)
    if injected != len(events):
        raise DeliveryError(f"Windows accepted {injected} of {len(events)} keystrokes — "
                            f"something intercepted the input (a keyboard hook, hotkey "
                            f"app, or antivirus swallowing keys?)")


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
        if not locked:
            kernel32.GlobalFree(handle)
            raise DeliveryError("Windows refused the clipboard (GlobalLock failed)")
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
        user32 = ctypes.windll.user32
        _bind_keys(user32)
        return user32.GetForegroundWindow()

    def send_ctrl(self, letter: str) -> None:
        """Ctrl+<letter> (Ctrl+T new tab, Ctrl+V paste)."""
        _send_keys(_ctrl_sequence(letter))

    def press_enter(self) -> None:
        """A bare Enter (navigates the pasted address-bar URL)."""
        _send_keys(_enter_sequence())

    def get_clipboard(self):
        """Current clipboard text or None."""
        import ctypes
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        _bind_clipboard(user32, kernel32)
        return _clipboard_text(user32, kernel32)

    def set_clipboard(self, text: str) -> None:
        """Replace the clipboard text."""
        import ctypes
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        _bind_clipboard(user32, kernel32)
        _set_clipboard_text(user32, kernel32, text)

    def sleep(self, seconds: float) -> None:
        """A real settle pause (tests inject instant fakes)."""
        import time
        time.sleep(seconds)

    def foreground_title(self):
        """The foreground window's title (the autorun receipt reads it)."""
        import ctypes
        user32 = ctypes.windll.user32
        _bind_keys(user32)
        hwnd = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value

    def window_pid(self, hwnd):
        """The process behind `hwnd` (None when the window is gone)."""
        return integrity.read_window_pid(hwnd)

    def process_integrity(self, pid):
        """The integrity RID of `pid` (None when it won't open)."""
        return integrity.read_process_integrity(pid)

    def own_integrity(self):
        """Our own integrity RID (None when Windows won't say)."""
        return integrity.read_own_integrity()
