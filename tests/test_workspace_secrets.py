"""Workspace secrets — no API-key material ever leaves the machine (RULE 20/I-29).

Scans the exported tree byte-for-byte for the raw key; locks the masked
presence metadata, the recordings exclusion, and the deterministic report
shape.
"""

import json
from pathlib import Path

import pytest

from app.persistence.config_manager import ConfigManager
from app.services.captcha.key_store import CaptchaKeyStore, CaptchaSettings
from app.services.workspace import save as ws_save
from app.services.workspace.coordinator import SaveRequest
from app.services.workspace.registry import get
from app.ui.bridge import Bridge

pytestmark = pytest.mark.unit

RAW_KEY = "aaaaaaaaaaaaaaaaaaaaaaaa1234"


@pytest.fixture()
def bridge_with_key(tmp_path):
    bridge = Bridge(config_manager=ConfigManager(config_dir=str(tmp_path)),
                    state_path=tmp_path / "app_state.json")
    CaptchaKeyStore(str(tmp_path)).save(CaptchaSettings(
        provider="2captcha", solve_timeout_sec=120, keys={"2captcha": RAW_KEY}))
    return bridge


def _all_bytes(root: Path) -> bytes:
    return b"".join(p.read_bytes() for p in root.rglob("*") if p.is_file())


def test_raw_key_never_appears_in_the_exported_tree(bridge_with_key):
    reply = ws_save.save_workspace(bridge_with_key, SaveRequest(name="sec"))
    assert reply["ok"]
    assert RAW_KEY.encode() not in _all_bytes(Path(reply["path"]))
    # not even a prefix leaks
    assert RAW_KEY[:8].encode() not in _all_bytes(Path(reply["path"]))


def test_manifest_carries_masked_presence_only(bridge_with_key):
    reply = ws_save.save_workspace(bridge_with_key, SaveRequest(name="masked"))
    manifest = json.loads((Path(reply["path"]) / "manifest.json").read_text())
    entry = manifest["domains"]["captcha_keys"]
    assert entry["path"] == "" and entry["sensitivity"] == "secret"
    reference = entry["capture"]["redacted_reference"]
    assert reference["providers"]["2captcha"] == {"present": True, "masked": "aaaa****1234"}
    assert "RULE 20" in entry["capture"]["excluded_reason"]
    assert RAW_KEY.encode() not in _all_bytes(Path(reply["path"]))


def test_keys_absent_after_restore_get_a_reenter_action(bridge_with_key, tmp_path):
    reply = ws_save.save_workspace(bridge_with_key, SaveRequest(name="re"))
    fresh = Bridge(config_manager=ConfigManager(config_dir=str(tmp_path / "other")),
                   state_path=tmp_path / "other" / "app_state.json")
    from app.services.workspace.apply import restore_workspace
    out = restore_workspace(fresh, reply["path"], selected=["captcha_keys"])
    row = out["skipped"][0]
    assert row["policy"] is True and "Re-enter the API key" in row["recommended_action"]


def test_recordings_domain_is_excluded_by_policy(bridge_with_key):
    capture = get("captcha_recordings").capture(bridge_with_key)
    assert capture.excluded and "opt-in" in capture.excluded_reason


def test_save_report_is_deterministic_for_unchanged_state(bridge_with_key):
    one = ws_save.save_workspace(bridge_with_key, SaveRequest(name="p1"))
    two = ws_save.save_workspace(bridge_with_key, SaveRequest(name="p2"))
    strip = lambda reply: {k: v for k, v in reply.items()
                           if k not in ("path", "snapshot_id", "started_utc",
                                        "finished_utc")}
    assert strip(one) == strip(two)


def test_policy_strings_have_one_home():
    """F3: advice + inclusion codes live in providers/policies.py only."""
    from app.services.workspace import save as ws_save
    from app.services.workspace.providers import policies
    from app.services.workspace.registry import get
    assert get("captcha_keys").restore_advice == policies.KEYS_REAPPLY
    assert ws_save.inclusion_policy() == policies.INCLUSION_POLICY
    assert "captcha_keys" in policies.INCLUSION_POLICY
