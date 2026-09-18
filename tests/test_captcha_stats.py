"""Captcha stats store — counters, success rate, persistence, RULE 13 tolerance."""

import json

import pytest

from app.services.captcha.stats import CaptchaStatsStore


@pytest.mark.unit
def test_fresh_store_is_zero(isolated_config_dir):
    s = CaptchaStatsStore(isolated_config_dir)
    d = s.to_dict()
    assert d["detected_total"] == 0
    assert d["auto_solved"] == 0
    assert d["auto_success_rate"] == 0.0
    assert d["last_balance"] is None


@pytest.mark.unit
def test_record_bumps_counters_and_persists(isolated_config_dir):
    s = CaptchaStatsStore(isolated_config_dir)
    s.record("detected", "arena.ai")
    s.record("auto_solved", "arena.ai")
    s.record("auto_failed", "virt.com")
    s.record("manual_solved", "virt.com")
    # fresh instance reads the same counters back
    d = CaptchaStatsStore(isolated_config_dir).to_dict()
    assert d["detected_total"] == 1
    assert d["auto_solved"] == 1
    assert d["auto_failed"] == 1
    assert d["manual_solved"] == 1
    assert d["per_site"]["arena.ai"] == {"detected": 1, "auto_solved": 1,
                                         "auto_failed": 0, "manual_solved": 0}
    assert d["per_site"]["virt.com"]["auto_failed"] == 1


@pytest.mark.unit
def test_unknown_events_ignored(isolated_config_dir):
    s = CaptchaStatsStore(isolated_config_dir)
    s.record("bogus_event", "x.com")
    s.record("task_created")
    d = s.to_dict()
    assert d["detected_total"] == 0
    assert d["tasks_created"] == 1
    assert "x.com" not in d["per_site"]


@pytest.mark.unit
def test_success_rate(isolated_config_dir):
    s = CaptchaStatsStore(isolated_config_dir)
    assert s.success_rate == 0.0  # no attempts → 0, not NaN/div0
    s.record("auto_solved")
    s.record("auto_failed")
    assert s.success_rate == 0.5
    s.record("auto_solved")
    assert s.success_rate == pytest.approx(2 / 3)


@pytest.mark.unit
def test_corrupt_file_is_zeroed(isolated_config_dir):
    path = isolated_config_dir / "captcha_stats.json"
    path.write_text("[1,2,3", encoding="utf-8")  # wrong shape
    s = CaptchaStatsStore(isolated_config_dir)
    assert s.to_dict()["detected_total"] == 0


@pytest.mark.unit
def test_partial_file_keeps_valid_fields(isolated_config_dir):
    path = isolated_config_dir / "captcha_stats.json"
    path.write_text(json.dumps({"detected_total": 7, "auto_solved": "bad"}), encoding="utf-8")
    s = CaptchaStatsStore(isolated_config_dir)
    d = s.to_dict()
    assert d["detected_total"] == 7
    assert d["auto_solved"] == 0  # invalid type reset, valid kept


@pytest.mark.unit
def test_per_site_cap_folds_into_star(isolated_config_dir):
    s = CaptchaStatsStore(isolated_config_dir)
    for i in range(55):
        s.record("detected", f"host{i}.com")
    d = s.to_dict()
    assert len(d["per_site"]) <= 50  # bounded map
    assert "*" in d["per_site"]
    assert d["per_site"]["*"]["detected"] == 6  # 55 - 49 real hosts
    assert d["per_site"]["host0.com"]["detected"] == 1


@pytest.mark.unit
def test_balance_and_error_captured(isolated_config_dir):
    s = CaptchaStatsStore(isolated_config_dir)
    s.set_balance(12.34567)
    s.set_last_error("no_credit")
    d = CaptchaStatsStore(isolated_config_dir).to_dict()
    assert d["last_balance"] == pytest.approx(12.3457)
    assert d["balance_at"]  # timestamp set
    assert d["last_error"] == "no_credit"


@pytest.mark.unit
def test_reset_clears_counters_keeps_balance(isolated_config_dir):
    """Reset wipes history; balance is API state and survives."""
    from app.services.captcha.stats import CaptchaStatsStore
    s = CaptchaStatsStore(isolated_config_dir)
    s.record("detected", "x.ai")
    s.record("auto_failed", "x.ai")
    s.set_balance(4.69)
    s.set_last_error("dialog still visible")
    s.reset()
    d = s.to_dict()
    assert d["detected_total"] == 0 and d["auto_failed"] == 0
    assert d["last_error"] == ""
    assert d["last_balance"] == 4.69  # API state, not history


def test_last_error_is_bounded(isolated_config_dir):
    s = CaptchaStatsStore(isolated_config_dir)
    s.set_last_error("x" * 500)
    assert len(CaptchaStatsStore(isolated_config_dir).last_error) <= 120
