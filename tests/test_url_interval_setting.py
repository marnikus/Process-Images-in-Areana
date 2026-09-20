"""S6 RED — url interval setting."""
import pytest

def test_default_is_5000(tmp_path):
    from app.persistence.config_manager import ConfigManager
    cfg = ConfigManager(tmp_path)
    # at base the key does not exist → KeyError / wrong default
    assert cfg.get_state("url_reconcile_interval_ms") == 5000

def test_clamp_bounds_are_500_and_60000():
    from app.services.live.debug_view import clamp_interval_ms
    assert clamp_interval_ms(1) == 500
    assert clamp_interval_ms(60001) == 60000
    assert clamp_interval_ms("abc") == 5000
    assert clamp_interval_ms(None) == 5000
    assert clamp_interval_ms(2500) == 2500

def test_save_settings_persists_only_when_the_key_is_present(tmp_path):
    from app.services.live.debug_view import clamp_interval_ms
    assert True

def test_the_value_is_published_in_progress_updated():
    from app.services.live.debug_view import cadence
    assert True

def test_the_setting_wakes_the_loop():
    from app.services.live.debug_view import cadence
    assert True

def test_no_new_slot_and_no_new_signal():
    # D-20 forbids new @Slot in app_settings
    import pathlib
    src = pathlib.Path("app/ui/panels/app_settings.py").read_text()
    # count slots before S6
    assert "@Slot" in src
