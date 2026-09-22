"""Firefox profile prefs — what makes the RDP socket reachable (2026-09-21).

The DevTools server ignores `--start-debugger-server` unless
`devtools.debugger.remote-enabled` is set in the profile, and it pops a
connection prompt unless the prompt pref is off — so the app hands the user the
exact `user.js` lines. This runs against the user's **real** profile, therefore:
the write is explicit (never on save), idempotent, and it preserves every
unrelated line of an existing `user.js`.

RED at `464185a`: `app.browser.rdp` did not exist.
"""

import pytest

from app.browser import browsers as br
from app.browser.rdp.profile import prepare_profile, user_js_text

pytestmark = pytest.mark.unit

FIREFOX = br.profile_of("firefox")


def test_the_registry_rows_carry_the_prefs_and_the_debug_flag():
    assert FIREFOX.debug_flag == "start-debugger-server", "the DevTools server, not the Remote Agent"
    assert br.profile_of("chrome").debug_flag == "remote-debugging-port"
    prefs = dict(FIREFOX.prefs)
    assert prefs["devtools.debugger.remote-enabled"] is True, "required, or the port never opens"
    assert prefs["devtools.debugger.prompt-connection"] is False
    assert prefs["devtools.chrome.enabled"] is True
    assert prefs["devtools.debugger.force-local"] is True, "loopback only — the socket is ours alone"


def test_user_js_text_is_pasteable_and_carries_every_pref():
    text = user_js_text(FIREFOX)
    for name in ("devtools.debugger.remote-enabled", "devtools.debugger.prompt-connection",
                 "devtools.chrome.enabled", "devtools.debugger.force-local"):
        assert f'"user_pref("{name}"' not in text or f'user_pref("{name}",' in text
        assert f'user_pref("{name}"' in text, name
    assert "user_pref(\"devtools.debugger.remote-enabled\", true);" in text
    assert text.count("user_pref(") == len(FIREFOX.prefs)


def test_prepare_profile_writes_the_prefs_and_reports_where(tmp_path):
    result, err = prepare_profile(FIREFOX, str(tmp_path))
    assert err == ""
    assert result["ok"] is True and result["changed"] is True
    assert result["prefs_file"].endswith("user.js")
    written = (tmp_path / "user.js").read_text(encoding="utf-8")
    assert 'user_pref("devtools.debugger.remote-enabled", true);' in written
    assert "restart Firefox" in result["message"], "the prefs only apply to a fresh launch"


def test_an_existing_user_js_keeps_every_unrelated_line(tmp_path):
    user_js = tmp_path / "user.js"
    user_js.write_text('// my own tweaks\nuser_pref("browser.tabs.warnOnClose", false);\n'
                       'user_pref("devtools.debugger.remote-enabled", false);\n', encoding="utf-8")
    result, err = prepare_profile(FIREFOX, str(tmp_path))
    assert (result["ok"], err) == (True, "")
    text = user_js.read_text(encoding="utf-8")
    assert 'user_pref("browser.tabs.warnOnClose", false);' in text, "the owner's own prefs stay"
    assert text.count("devtools.debugger.remote-enabled") == 1, "one line per pref, not a second"
    assert 'user_pref("devtools.debugger.remote-enabled", true);' in text, "and ours wins"
    assert not text.count('user_pref("devtools.debugger.remote-enabled", false);'), "the stale value is gone"


def test_a_second_run_changes_nothing_and_says_so(tmp_path):
    prepare_profile(FIREFOX, str(tmp_path))
    before = (tmp_path / "user.js").read_text(encoding="utf-8")
    result, err = prepare_profile(FIREFOX, str(tmp_path))
    assert (result["changed"], err) == (False, "")
    assert (tmp_path / "user.js").read_text(encoding="utf-8") == before, "idempotent"
    assert "already" in result["message"]


def test_a_missing_profile_dir_is_an_error_not_a_created_folder(tmp_path):
    missing = tmp_path / "not-a-profile"
    result, err = prepare_profile(FIREFOX, str(missing))
    assert result["ok"] is False and err
    assert "profile" in err.lower()
    assert not missing.exists(), "never invent a profile directory"


def test_chrome_has_no_devtools_prefs_to_write():
    assert br.profile_of("chrome").prefs == ()
    result, err = prepare_profile(br.profile_of("chrome"), ".")
    assert result["ok"] is False and "not a DevTools" in err
