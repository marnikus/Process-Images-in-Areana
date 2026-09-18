"""Per-site CAPTCHA timing database — verdict classification and adaptive timeout."""

import pytest

from app.services.captcha.timing_db import TimingDatabase, TimingSample, classify_verdict


def sample(solve_sec, token_sec=0.0, success=False, kind="", patience=None):
    return TimingSample(solve_sec=solve_sec, token_sec=token_sec, success=success,
                        kind=kind, page_patience_sec=patience)


@pytest.mark.unit
def test_timing_db_records_and_classifies(tmp_path):
    db = TimingDatabase(tmp_path)
    host = "arena.ai"
    # First two attempts: verdict stays unknown
    db.record_attempt(host, sample(70, 65, False, "recaptcha_enterprise", 60))
    db.record_attempt(host, sample(75, 70, False, "recaptcha_enterprise", 60))
    assert db.get_verdict(host) == "unknown"

    # Third attempt: enough data to classify
    db.record_attempt(host, sample(80, 75, False, "recaptcha_enterprise", 60))
    assert db.get_verdict(host) == "impossible"


@pytest.mark.unit
def test_timing_db_fast_site(tmp_path):
    db = TimingDatabase(tmp_path)
    for _ in range(5):
        db.record_attempt("fast.example", sample(8, 6, True, "recaptcha_v2", 120))
    assert db.get_verdict("fast.example") == "fast"


@pytest.mark.unit
def test_timing_db_marginal_site(tmp_path):
    db = TimingDatabase(tmp_path)
    for _ in range(4):
        db.record_attempt("marginal.example", sample(50, 45, True, "recaptcha_enterprise", 70))
    assert db.get_verdict("marginal.example") == "marginal"


@pytest.mark.unit
def test_timing_db_adaptive_timeout(tmp_path):
    db = TimingDatabase(tmp_path)
    # No data: returns user timeout
    assert db.get_effective_timeout("unknown.host", 180.0) == 180.0

    # With data: min(user, patience * 0.8)
    for _ in range(3):
        db.record_attempt("arena.ai", sample(70, 65, False, patience=60))
    effective = db.get_effective_timeout("arena.ai", 180.0)
    assert effective == pytest.approx(48.0)  # 60 * 0.8


@pytest.mark.unit
def test_timing_db_corrupt_file(tmp_path):
    (tmp_path / "captcha_timing.json").write_text("not-json")
    db = TimingDatabase(tmp_path)
    assert db.to_dict() == {}


@pytest.mark.unit
def test_timing_db_caps_hosts(tmp_path):
    db = TimingDatabase(tmp_path)
    for i in range(55):
        db.record_attempt(f"host{i}.example", sample(10, 8, True))
    assert len(db.to_dict()) <= 50


@pytest.mark.unit
def test_classify_verdict_insufficient_data():
    assert classify_verdict({"attempts": 1, "successes": 0}) == "unknown"
    assert classify_verdict({"attempts": 0}) == "unknown"


@pytest.mark.unit
def test_classify_verdict_low_success_rate():
    entry = {"attempts": 10, "successes": 0, "failures": 10,
             "avg_solve_sec": 10, "p95_solve_sec": 15,
             "page_patience_sec": 120}
    assert classify_verdict(entry) == "impossible"


@pytest.mark.unit
def test_timing_db_get_entry_empty(tmp_path):
    db = TimingDatabase(tmp_path)
    assert db.get_entry("nonexistent") == {}


@pytest.mark.unit
def test_timing_db_round_trip(tmp_path):
    db = TimingDatabase(tmp_path)
    db.record_attempt("x.test", sample(5, 4, True))
    db2 = TimingDatabase(tmp_path)
    assert db2.get_entry("x.test")["attempts"] == 1


@pytest.mark.unit
def test_timing_db_blank_host_ignored(tmp_path):
    db = TimingDatabase(tmp_path)
    db.record_attempt("", sample(5, 4, True))
    assert db.to_dict() == {}
