"""UIPI trust for the delivery path: the IL comparison that names silent drops.

RULE 8: SendInput into a higher-integrity window is dropped without a trace
(MSDN: neither the return value nor GetLastError names UIPI) — every branch
below pins one answer of the pre-keystroke trust check.
"""

from types import SimpleNamespace

import pytest

from app.browser.uivision import integrity

pytestmark = pytest.mark.unit


def _ops(pid=1234, target=0x2000, own=0x2000):
    return SimpleNamespace(window_pid=lambda _h: pid,
                           process_integrity=lambda _p: target,
                           own_integrity=lambda: own)


def test_level_name_knowns_rids_and_passes_unknowns_through():
    assert integrity.level_name(0x1000) == "low"
    assert integrity.level_name(0x2000) == "medium"
    assert integrity.level_name(0x3000) == "high"
    assert integrity.level_name(0x4000) == "system"
    assert integrity.level_name(0x9999) == "0x9999"


def test_matching_or_lower_integrity_proceeds():
    assert integrity.check_delivery(11, _ops()) is None                    # medium → medium
    assert integrity.check_delivery(11, _ops(target=0x1000)) is None      # higher → lower ok


def test_mismatch_names_both_levels_and_the_fix():
    message = integrity.check_delivery(11, _ops(own=0x2000, target=0x3000))
    assert "UIPI blocks the keys" in message
    assert "medium" in message and "high" in message and "pid 1234" in message
    assert "same level" in message


def test_unopenable_process_refuses_as_upi_suspect():
    message = integrity.check_delivery(11, _ops(target=None))
    assert "cannot be opened" in message and "pid 1234" in message
    assert "same level" in message and "manual steps" in message


def test_dead_window_says_so():
    message = integrity.check_delivery(11, _ops(pid=None))
    assert "closed before the keys" in message and "(11)" in message


def test_unknown_self_proceeds():
    assert integrity.check_delivery(11, _ops(own=None)) is None  # cannot compare: the ladder backstops


def test_bind_declares_the_trust_queries():
    import ctypes
    user32 = SimpleNamespace(GetWindowThreadProcessId=lambda *_a: 0)
    kernel32 = SimpleNamespace(GetCurrentProcess=lambda: 0, OpenProcess=lambda *_a: 0,
                               CloseHandle=lambda *_a: 0)
    advapi32 = SimpleNamespace(OpenProcessToken=lambda *_a: 0, GetTokenInformation=lambda *_a: 0,
                               GetSidSubAuthorityCount=lambda *_a: 0,
                               GetSidSubAuthority=lambda *_a: 0)
    integrity._bind_integrity(user32, kernel32, advapi32)
    assert len(user32.GetWindowThreadProcessId.argtypes) == 2
    assert len(kernel32.OpenProcess.argtypes) == 3
    assert len(advapi32.OpenProcessToken.argtypes) == 3
    assert len(advapi32.GetTokenInformation.argtypes) == 5
    assert len(advapi32.GetSidSubAuthority.argtypes) == 2
    assert kernel32.CloseHandle.restype is not None
    assert ctypes.sizeof(advapi32.GetTokenInformation.argtypes[3]) == 4  # DWORD is 32-bit
