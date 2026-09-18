"""Solver-provider key store — per-provider creds, legacy migration, masking.

RULE 13: corrupt/missing file → defaults (never brick). RULE 20: only masked
forms leave the store; the file is git-ignored and 0600 best-effort. The
legacy single-provider `config/2captcha.json` migrates read-only on load.
"""

import json
import os

import pytest

from app.services.captcha.key_store import (
    CaptchaKeyStore, CaptchaSettings, ProviderCreds, clamp_timeout,
)


@pytest.mark.unit
def test_missing_file_gives_disabled_defaults(isolated_config_dir):
    store = CaptchaKeyStore(isolated_config_dir)
    s = store.load()
    assert s.provider == "2captcha"
    assert s.enabled is False
    assert s.api_key == ""
    assert s.solve_timeout_sec == 180


@pytest.mark.unit
def test_save_load_roundtrip_per_provider(isolated_config_dir):
    store = CaptchaKeyStore(isolated_config_dir)
    store.save(CaptchaSettings.for_provider("2captcha", enabled=True,
                                            api_key="  abc123def456  ",
                                            solve_timeout_sec=240))
    s = CaptchaKeyStore(isolated_config_dir).load()
    assert s.provider == "2captcha"
    assert s.enabled is True
    assert s.api_key == "abc123def456"  # stripped
    assert s.solve_timeout_sec == 240


@pytest.mark.unit
def test_two_providers_store_independently(isolated_config_dir):
    store = CaptchaKeyStore(isolated_config_dir)
    store.save(CaptchaSettings.for_provider("2captcha", enabled=True, api_key="twokey0001"))
    fresh = store.load()
    fresh.creds["capmonster"] = ProviderCreds(enabled=True, api_key="capkey00001")
    fresh.provider = "capmonster"
    store.save(fresh)

    s = CaptchaKeyStore(isolated_config_dir).load()
    assert s.provider == "capmonster"
    assert s.api_key == "capkey00001" and s.enabled is True  # active view
    assert s.creds["2captcha"].api_key == "twokey0001"       # sibling untouched
    data = json.loads((isolated_config_dir / CaptchaKeyStore.FILENAME).read_text())
    assert data["provider"] == "capmonster"
    assert set(data["providers"]) == {"2captcha", "capmonster"}


@pytest.mark.unit
def test_enabled_requires_key(isolated_config_dir):
    store = CaptchaKeyStore(isolated_config_dir)
    store.save(CaptchaSettings.for_provider("capmonster", enabled=True, api_key=""))
    s = CaptchaKeyStore(isolated_config_dir).load()
    assert s.provider == "capmonster"
    assert s.enabled is False and s.api_key == ""


@pytest.mark.unit
def test_corrupt_file_falls_back_to_defaults(isolated_config_dir):
    path = isolated_config_dir / CaptchaKeyStore.FILENAME
    path.write_text("{not json", encoding="utf-8")
    s = CaptchaKeyStore(isolated_config_dir).load()
    assert s.enabled is False and s.api_key == ""


@pytest.mark.unit
def test_legacy_2captcha_json_migrates_read_only(isolated_config_dir):
    legacy = isolated_config_dir / CaptchaKeyStore.LEGACY_FILENAME
    legacy.write_text(json.dumps({"enabled": True, "api_key": "legacykey123",
                                  "solve_timeout_sec": 300}), encoding="utf-8")
    s = CaptchaKeyStore(isolated_config_dir).load()
    assert s.provider == "2captcha"
    assert s.enabled is True and s.api_key == "legacykey123"
    assert s.solve_timeout_sec == 300
    assert legacy.read_text() == json.dumps({"enabled": True, "api_key": "legacykey123",
                                             "solve_timeout_sec": 300})  # untouched
    assert not (isolated_config_dir / CaptchaKeyStore.FILENAME).exists()  # load never writes


@pytest.mark.unit
def test_new_store_wins_over_legacy(isolated_config_dir):
    (isolated_config_dir / CaptchaKeyStore.LEGACY_FILENAME).write_text(
        json.dumps({"enabled": True, "api_key": "legacykey123"}), encoding="utf-8")
    store = CaptchaKeyStore(isolated_config_dir)
    store.save(CaptchaSettings.for_provider("capmonster", enabled=True, api_key="newkey00001"))
    s = CaptchaKeyStore(isolated_config_dir).load()
    assert s.provider == "capmonster" and s.api_key == "newkey00001"


@pytest.mark.unit
def test_corrupt_legacy_is_ignored(isolated_config_dir):
    (isolated_config_dir / CaptchaKeyStore.LEGACY_FILENAME).write_text("{oops", encoding="utf-8")
    s = CaptchaKeyStore(isolated_config_dir).load()
    assert s.enabled is False and s.api_key == ""


@pytest.mark.unit
def test_unknown_provider_id_falls_back(isolated_config_dir):
    path = isolated_config_dir / CaptchaKeyStore.FILENAME
    path.write_text(json.dumps({"provider": "bogus", "providers": {}}), encoding="utf-8")
    s = CaptchaKeyStore(isolated_config_dir).load()
    assert s.provider == "2captcha"  # default, with an empty active entry


@pytest.mark.unit
def test_bad_types_fall_back(isolated_config_dir):
    path = isolated_config_dir / CaptchaKeyStore.FILENAME
    path.write_text(json.dumps({"provider": 7, "solve_timeout_sec": "abc",
                                "providers": {"2captcha": {"api_key": 12345,
                                                           "enabled": "yes"}}}),
                    encoding="utf-8")
    s = CaptchaKeyStore(isolated_config_dir).load()
    assert s.api_key == "12345"        # str-coerced
    assert s.solve_timeout_sec == 180  # bad type → default
    assert s.provider == "2captcha"    # bad type → default


@pytest.mark.unit
def test_timeout_clamped(isolated_config_dir):
    store = CaptchaKeyStore(isolated_config_dir)
    store.save(CaptchaSettings.for_provider("2captcha", enabled=True,
                                            api_key="abcdefgh", solve_timeout_sec=1))
    assert CaptchaKeyStore(isolated_config_dir).load().solve_timeout_sec == 30
    store.save(CaptchaSettings.for_provider("2captcha", enabled=True,
                                            api_key="abcdefgh", solve_timeout_sec=99999))
    assert CaptchaKeyStore(isolated_config_dir).load().solve_timeout_sec == 600
    assert clamp_timeout(None) == 180
    assert clamp_timeout("x") == 180


@pytest.mark.unit
def test_file_is_0600_when_possible(isolated_config_dir):
    store = CaptchaKeyStore(isolated_config_dir)
    store.save(CaptchaSettings.for_provider("2captcha", enabled=True, api_key="abcdefgh1234"))
    mode = os.stat(store._path).st_mode & 0o777
    assert mode == 0o600


@pytest.mark.unit
def test_mask_shapes():
    assert CaptchaKeyStore.mask("") == ""
    assert CaptchaKeyStore.mask("short") == "short"  # <8: as-is (already unguessable short)
    assert CaptchaKeyStore.mask("abcd1234wxyz") == "abcd****wxyz"


@pytest.mark.unit
def test_save_is_atomic_replace(isolated_config_dir):
    store = CaptchaKeyStore(isolated_config_dir)
    store.save(CaptchaSettings.for_provider("2captcha", enabled=True, api_key="abcdefgh1234"))
    first = store._path.read_text()
    store.save(CaptchaSettings.for_provider("capmonster", enabled=True, api_key="zzzzzzzz8888"))
    data = json.loads(store._path.read_text())
    assert data["providers"]["capmonster"]["api_key"] == "zzzzzzzz8888"
    assert first != store._path.read_text()
    # no leftover temp files
    leftovers = [p for p in isolated_config_dir.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []
