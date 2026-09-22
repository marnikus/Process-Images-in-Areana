"""The robot cue, the Allow prompt, and the profile Firefox really uses (round 10).

Owner report (2026-09-22, with screenshots): Firefox shows the robot icon after start, the launch
command uses `-profile` / `-no-remote`, and Firefox asks *"An incoming request to permit remote
debugging connection was detected … Allow connection?"* again and again.

The cue is Firefox's own URL-bar element and follows the *devices server*, not the flags
(`docs/archive/2026-09-22-firefox-cue-and-prompt/design.md` §1 has the file/line receipts). Two
things here ARE ours to fix and are pinned below:

* the Firefox row forced `-profile "C:\\arena-images-firefox"`, so the command never touched the
  profile actually running — and `Prepare Profile` wrote its prefs there, which is why
  `devtools.debugger.prompt-connection` stayed true and the Allow prompt kept coming;
* one listing pass opened **two** connections per browser (a probe, then the real `listTabs`),
  i.e. up to two prompts per pass.

RED at `9abda34`: no `app/browser/firefox_profiles.py`, no `app/browser/stealth.py`, the Firefox
row still defaulted to a private directory, and `list_targets` probed before it listed.
"""

import json

import pytest

from app.browser import browsers as br
from app.browser import endpoints
from app.browser import firefox_profiles as fp
from app.browser import stealth
from app.browser.rdp import profile as rdp_profile
from tests.fakes.rdp_stub_server import RdpStubServer
from tests.test_browser_endpoints import FakeChrome
from tests.test_panel_slots import make_cdp, make_host, make_state
from PySide6.QtCore import Signal

pytestmark = pytest.mark.unit

FIREFOX = br.profile_of("firefox")
INI = """[Install4F96D1932A9F858E]
Default=Profiles/xy1z2.default-release
Locked=1

[Profile1]
Name=old
IsRelative=1
Path=Profiles/old.default

[Profile0]
Name=default-release
IsRelative=1
Path=Profiles/xy1z2.default-release
Default=1
"""


@pytest.fixture
def firefox(tmp_path, monkeypatch):
    """A fake profile tree + the ini Firefox itself would read."""
    root = tmp_path / "Firefox"
    (root / "Profiles" / "xy1z2.default-release").mkdir(parents=True)
    (root / "profiles.ini").write_text(INI, encoding="utf-8")
    monkeypatch.setenv("ARENA_FIREFOX_PROFILES_INI", str(root / "profiles.ini"))
    monkeypatch.delenv("ARENA_FIREFOX_PROFILE_DIR", raising=False)
    return root / "Profiles" / "xy1z2.default-release"


@pytest.fixture
def stub():
    server = RdpStubServer()
    try:
        yield server
    finally:
        server.close()


@pytest.fixture
def cfg(isolated_config_dir):
    from app.persistence.config_manager import ConfigManager
    return ConfigManager(str(isolated_config_dir))


def _host(cfg, **attrs):
    host, logs = make_host((__import__("app.ui.panels.cdp_tools", fromlist=["CdpToolsMixin"]).CdpToolsMixin,),
                           cdp=make_cdp(connected=False), config=cfg, state=make_state(),
                           highlight_rect=Signal(str), _page_pool=None, **attrs)
    return host, logs


# ── the profile Firefox actually runs (D-1/D-2) ──


def test_the_firefox_command_uses_the_browsers_own_profile_by_default():
    """No `-profile`: Firefox starts with the owner's real session (history, cookies, plugins)."""
    command = br.build_command(FIREFOX, "windows", br.endpoint(9224, ""))
    assert "--start-debugger-server 9224" in command and "-no-remote" in command
    assert "-profile" not in command, (
        "forcing a private dir is what kept the Allow pref out of the profile that was running")


def test_a_configured_directory_still_wins():
    """Isolation stays available for anyone who wants it — it is just not the default."""
    command = br.build_command(FIREFOX, "windows", br.endpoint(9224, "D:\\ff"))
    assert '-profile="D:\\ff"' in command
    chrome = br.build_command(br.profile_of("chrome"), "windows", br.endpoint(9223, ""))
    assert "--user-data-dir" not in chrome, "an empty dir means the browser's own profile too"


def test_profiles_ini_resolution_follows_firefoxs_own_rules(firefox):
    root = firefox.parents[1]
    assert fp.profiles_ini_path() == root / "profiles.ini"
    assert fp.default_profile_dir() == str(firefox)
    assert fp.profile_source() == "profiles.ini"
    # an ini with only one profile still resolves (Firefox falls back to it)
    single = root / "single.ini"
    single.write_text("[Profile0]\nName=only\nIsRelative=1\nPath=Profiles/xy1z2.default-release\n",
                      encoding="utf-8")
    assert fp.parse_default_profile(single.read_text(encoding="utf-8"), root) == str(firefox)
    assert fp.parse_default_profile("", root) == ""
    assert fp.parse_default_profile("[General]\nStartWithLastProfile=1\n", root) == ""


def test_an_explicit_dir_override_beats_the_ini(firefox, monkeypatch):
    monkeypatch.setenv("ARENA_FIREFOX_PROFILE_DIR", str(firefox.parent))
    assert fp.default_profile_dir() == str(firefox.parent)
    assert fp.profile_source() == "override"


def test_prepare_profile_writes_into_the_profile_firefox_itself_uses(firefox):
    """The prompt is removed where it matters: the profile that is actually running."""
    target = firefox / "user.js"
    target.write_text('user_pref("browser.startup.page", 3);\n', encoding="utf-8")
    result, err = rdp_profile.prepare_profile(FIREFOX, "")
    assert err == "" and result["changed"] is True
    body = target.read_text(encoding="utf-8")
    assert 'user_pref("browser.startup.page", 3);' in body, "the owner's own lines survive"
    assert 'user_pref("devtools.debugger.prompt-connection", false);' in body
    assert str(target) in result["message"] and "restart Firefox" in result["message"]
    again, err2 = rdp_profile.prepare_profile(FIREFOX, "")
    assert err2 == "" and again["changed"] is False and "already" in again["message"]


def test_prepare_profile_names_the_missing_profile_instead_of_writing_somewhere_random(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_FIREFOX_PROFILES_INI", str(tmp_path / "nope.ini"))
    monkeypatch.delenv("ARENA_FIREFOX_PROFILE_DIR", raising=False)
    result, err = rdp_profile.prepare_profile(FIREFOX, "")
    assert result["ok"] is False and "profile directory not found" in err


def test_the_settings_row_shows_where_prepare_profile_would_write(cfg, firefox):
    host, _logs = _host(cfg)
    row = {b["id"]: b for b in json.loads(host.get_cdp_config())["browsers"]}["firefox"]
    assert row["profile_dir"] == str(firefox) and row["profile_is_default"] is True
    assert row["prefs_file"] == str(firefox / "user.js"), "the panel shows the file it would touch"
    assert row["user_data_dir"] == "", "an empty field means the browser's own profile"


def test_a_configured_dir_beats_the_default_in_the_row(cfg, firefox):
    host, _logs = _host(cfg)
    host.set_cdp_config(json.dumps({"browser": "firefox", "user_data_dir": "D:\\ff"}))
    row = {b["id"]: b for b in json.loads(host.get_cdp_config())["browsers"]}["firefox"]
    assert row["user_data_dir"] == "D:\\ff" and row["profile_is_default"] is False
    assert row["profile_dir"] == "D:\\ff", "a configured dir is the profile, no resolution needed"


# ── one pass, one connection (D-3) ──


def test_one_listing_pass_opens_exactly_one_connection_per_browser(stub):
    """Two sockets per pass meant two Allow prompts on a profile that still asks."""
    rows, err = endpoints.list_targets("firefox", "127.0.0.1", stub.port, 3.0)
    assert err == "" and [r.id for r in rows] == ["ctx-3", "ctx-4"]
    assert stub.connections == 1, f"one pass must ask one question: {stub.connections} connections"


def test_a_firefox_row_still_finds_a_cdp_firefox():
    """An ESR Firefox launched with CDP keeps working — the fallback is a fallback, not a rule."""
    chrome = FakeChrome()
    try:
        rows, err = endpoints.list_targets("firefox", "127.0.0.1", chrome.port, 3.0)
        assert err == "" and len(rows) == 2 and all(r.protocol == "cdp" for r in rows)
    finally:
        chrome.close()


def test_a_dead_endpoint_is_still_one_attempt_and_a_named_reason():
    from tests.test_attached import _free_port
    rows, err = endpoints.list_targets("firefox", "127.0.0.1", _free_port(), 0.5)
    assert rows == [] and "--start-debugger-server" in err


# ── the honest stealth measurement (D-5) ──


def test_the_stealth_probe_reads_the_pages_own_answer(stub):
    from app.browser import attached
    handle = attached.parse_handle(f"rdp://127.0.0.1:{stub.port}/ctx-3")
    facts, err = stealth.measure(handle, "ctx-3", 3.0)
    assert err == "" and facts["webdriver"] is False
    assert facts["headless"] is False and facts["plugins"] == 5
    assert "Firefox/" in facts["ua"]


def test_the_verdict_names_a_flag_instead_of_papering_it_over():
    clean = {"webdriver": False, "ua": "Mozilla/5.0 Firefox/141.0", "plugins": 5, "headless": False}
    assert stealth.verdict(clean) == "" and "webdriver=false" in stealth.line(clean)
    flagged = dict(clean, webdriver=True)
    assert "navigator.webdriver=true" in stealth.verdict(flagged)
    assert "webdriver" in stealth.line(flagged)
    headless = dict(clean, headless=True)
    assert "headless" in stealth.verdict(headless).lower()


def test_parse_survives_a_browser_that_answers_something_else():
    facts, err = stealth.parse("not json at all")
    assert facts == {} and err, "a non-answer is a reason, never a crash or a silent default"
    assert stealth.parse(None)[0] == {}


# ── what the panel says about the cue and the prompt (D-4) ──


def test_the_row_explains_the_cue_the_prompt_and_the_pref(cfg):
    host, _logs = _host(cfg)
    row = {b["id"]: b for b in json.loads(host.get_cdp_config())["browsers"]}["firefox"]
    text = f"{row['stealth']} {row['notes']}".lower()
    assert "robot" in text and "url" in text, "the URL-bar cue is named"
    assert "web pages" in text or "websites" in text, "and that pages cannot see it"
    assert "allow" in text and "prompt-connection" in text, "the prompt and the pref that removes it"
    assert "no remote agent" in text or "navigator.webdriver" in text
    assert "--start-debugger-server" in row["notes"]
    assert "no-remote" in text, "the flag that makes the socket open is explained, not dropped"


async def test_diagnose_logs_the_measured_stealth_line(cfg):
    """The owner's own browser answers the stealth question — no assertion needed."""
    from app.ui.panels import browser_tabs as bt
    host, logs = _host(cfg)
    host.cdp = _StubClient()
    await bt.report_stealth(host)
    assert any("navigator.webdriver=false" in msg for _lvl, msg in logs), logs
    assert any("plugin" in msg for _lvl, msg in logs)


async def test_a_flagged_browser_says_so_loudly(cfg):
    from app.ui.panels import browser_tabs as bt
    host, logs = _host(cfg)
    host.cdp = _StubClient(webdriver=True)
    await bt.report_stealth(host)
    assert any("navigator.webdriver=true" in msg for _lvl, msg in logs), logs


class _StubClient:
    """A connected client whose one job is to answer the stealth expression."""

    def __init__(self, webdriver: bool = False):
        self.is_connected = True
        self._webdriver = webdriver

    async def evaluate(self, expression, *args, **kwargs):
        return json.dumps({"webdriver": self._webdriver, "ua": "Mozilla/5.0 Firefox/141.0",
                           "plugins": 5, "languages": "en-US", "headless": False})
