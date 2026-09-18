"""2Captcha key store — local file, masked getters, corrupt tolerance.

RULE 13: corrupt/missing file → defaults (never brick). RULE 20: only masked
forms leave the store; file is git-ignored and 0600 best-effort.
"""

import json
import os

import pytest

from app.services.captcha.key_store import CaptchaKeyStore, CaptchaSettings, clamp_timeout


@pytest.mark.unit
def test_missing_file_gives_disabled_defaults(isolated_config_dir):
    store = CaptchaKeyStore(isolated_config_dir)
    s = store.load()
    assert s.enabled is False
    assert s.api_key == ""
    assert s.solve_timeout_sec == 180


@pytest.mark.unit
def test_save_load_roundtrip(isolated_config_dir):
    store = CaptchaKeyStore(isolated_config_dir)
    store.save(CaptchaSettings(enabled=True, api_key="  abc123def456  ",
                               solve_timeout_sec=240))
    s = CaptchaKeyStore(isolated_config_dir).load()
    assert s.enabled is True
    assert s.api_key == "abc123def456"  # stripped
    assert s.solve_timeout_sec == 240


@pytest.mark.unit
def test_enabled_requires_key(isolated_config_dir):
    store = CaptchaKeyStore(isolated_config_dir)
    store.save(CaptchaSettings(enabled=True, api_key=""))
    assert CaptchaKeyStore(isolated_config_dir).load().enabled is False


@pytest.mark.unit
def test_corrupt_file_falls_back_to_defaults(isolated_config_dir):
    path = isolated_config_dir / CaptchaKeyStore.FILENAME
    path.write_text("{not json", encoding="utf-8")
    s = CaptchaKeyStore(isolated_config_dir).load()
    assert s.enabled is False and s.api_key == ""


@pytest.mark.unit
def test_bad_types_fall_back(isolated_config_dir):
    path = isolated_config_dir / CaptchaKeyStore.FILENAME
    path.write_text(json.dumps({"api_key": 12345, "enabled": "yes",
                                "solve_timeout_sec": "abc"}), encoding="utf-8")
    s = CaptchaKeyStore(isolated_config_dir).load()
    assert s.api_key == "12345"  # str-coerced
    assert s.solve_timeout_sec == 180  # bad type → default


@pytest.mark.unit
def test_timeout_clamped(isolated_config_dir):
    store = CaptchaKeyStore(isolated_config_dir)
    store.save(CaptchaSettings(enabled=True, api_key="abcdefgh", solve_timeout_sec=1))
    assert CaptchaKeyStore(isolated_config_dir).load().solve_timeout_sec == 30
    store.save(CaptchaSettings(enabled=True, api_key="abcdefgh", solve_timeout_sec=99999))
    assert CaptchaKeyStore(isolated_config_dir).load().solve_timeout_sec == 600
    assert clamp_timeout(None) == 180
    assert clamp_timeout("x") == 180


@pytest.mark.unit
def test_file_is_0600_when_possible(isolated_config_dir):
    store = CaptchaKeyStore(isolated_config_dir)
    store.save(CaptchaSettings(enabled=True, api_key="abcdefgh1234"))
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
    store.save(CaptchaSettings(enabled=True, api_key="abcdefgh1234"))
    first = store._path.read_text()
    store.save(CaptchaSettings(enabled=False, api_key="zzzzzzzz8888"))
    data = json.loads(store._path.read_text())
    assert data["api_key"] == "zzzzzzzz8888"
    assert first != store._path.read_text()
    # no leftover temp files
    leftovers = [p for p in isolated_config_dir.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []
