"""Whose keys may land where — UIPI integrity levels for the delivery path.

SendInput into a higher-integrity window is silently dropped — and per MSDN
"neither GetLastError nor the return value will indicate the failure was
caused by UIPI blocking". So before the first keystroke the delivery compares
OUR integrity level with the target window's process
(GetWindowThreadProcessId + OpenProcess + GetTokenInformation, the Whisperlet
#67 recipe) and refuses LOUDLY on a mismatch instead of typing into the void.
"""

from __future__ import annotations

import ctypes

TOKEN_QUERY = 0x0008
TOKEN_INTEGRITY_LEVEL = 25            # TokenIntegrityLevel information class
PROCESS_QUERY_LIMITED = 0x1000        # PROCESS_QUERY_LIMITED_INFORMATION

_RID_NAMES = {0x0000: "untrusted", 0x1000: "low", 0x2000: "medium",
              0x2100: "medium-plus", 0x3000: "high", 0x4000: "system",
              0x5000: "protected"}


def level_name(rid) -> str:
    """'medium' etc. for a mandatory-label RID (unknown RIDs stay numeric)."""
    return _RID_NAMES.get(int(rid), f"0x{int(rid):04x}")


def check_delivery(hwnd, ops):
    """None when the keys may go; the refusal message when UIPI forbids them.

    `ops` answers window_pid/process_integrity/own_integrity (Win32Ops
    delegates below; tests fake them). Only PROOF refuses — except an
    unopenable Firefox process: same-level Firefox always opens for a limited
    query, so unopenable ≈ elevated (the Whisperlet #67 signal).
    """
    pid = ops.window_pid(hwnd)
    if not pid:
        return (f"the window ({hwnd}) closed before the keys went out — nothing "
                f"to aim at")
    target = ops.process_integrity(pid)
    if target is None:
        return (f"Firefox's process (pid {pid}) cannot be opened for an integrity "
                f"check (protected or elevated) — the keys would be dropped "
                f"silently; run the app and Firefox at the same level, or use the "
                f"manual steps below")
    own = ops.own_integrity()
    if own is not None and target > own:
        return (f"UIPI blocks the keys: this app runs at {level_name(own)} integrity, "
                f"Firefox (pid {pid}) at {level_name(target)} — run both at the same "
                f"level (both normal, or both as administrator)")
    return None


def _bind_integrity(user32, kernel32, advapi32) -> None:
    """The trust-query signatures (DWORD stays 32-bit: c_uint32, no wintypes)."""
    from ctypes import wintypes
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(ctypes.c_uint32)]
    user32.GetWindowThreadProcessId.restype = ctypes.c_uint32
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, wintypes.BOOL, ctypes.c_uint32]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, ctypes.c_uint32,
                                          ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID,
                                             ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.GetSidSubAuthorityCount.argtypes = [wintypes.LPVOID]
    advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
    advapi32.GetSidSubAuthority.argtypes = [wintypes.LPVOID, ctypes.c_uint32]
    advapi32.GetSidSubAuthority.restype = ctypes.POINTER(ctypes.c_uint32)


def _dlls():
    """(user32, kernel32, advapi32), bound — one place for the three DLLs."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    advapi32 = ctypes.windll.advapi32
    _bind_integrity(user32, kernel32, advapi32)
    return user32, kernel32, advapi32


def read_window_pid(hwnd):
    """The process behind `hwnd` (None when the window is already gone)."""
    user32, _, _ = _dlls()
    pid = ctypes.c_uint32()
    if not user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
        return None
    return pid.value or None


def _rid_of_token(token, advapi32):
    """The integrity RID inside an open token (None when unreadable)."""
    needed = ctypes.c_uint32()
    advapi32.GetTokenInformation(token, TOKEN_INTEGRITY_LEVEL, None, 0, ctypes.byref(needed))
    size = needed.value or 64
    buf = ctypes.create_string_buffer(size)
    if not advapi32.GetTokenInformation(token, TOKEN_INTEGRITY_LEVEL, buf, size,
                                        ctypes.byref(needed)):
        return None
    sid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
    if not sid:
        return None
    count = advapi32.GetSidSubAuthorityCount(sid)
    if not count or not count[0]:
        return None
    rid = advapi32.GetSidSubAuthority(sid, count[0] - 1)
    return rid[0] if rid else None


def read_process_integrity(pid):
    """The integrity RID of `pid` (None when the process won't open)."""
    from ctypes import wintypes
    _, kernel32, advapi32 = _dlls()
    proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
    if not proc:
        return None
    try:
        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(proc, TOKEN_QUERY, ctypes.byref(token)):
            return None
        try:
            return _rid_of_token(token, advapi32)
        finally:
            kernel32.CloseHandle(token)
    finally:
        kernel32.CloseHandle(proc)


def read_own_integrity():
    """Our own integrity RID (None only when Windows won't say)."""
    from ctypes import wintypes
    _, kernel32, advapi32 = _dlls()
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_QUERY,
                                     ctypes.byref(token)):
        return None
    try:
        return _rid_of_token(token, advapi32)
    finally:
        kernel32.CloseHandle(token)
