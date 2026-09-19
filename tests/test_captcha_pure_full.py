"""D5 mutation triage: captcha signals + stats + key_store, branch-complete.

Targets _evidence_kwargs (61), CaptchaSignal.from_result (16), _safe_count (12),
host_of (5), stats _save (21)/_blank (11)/record (7), key_store save (23)/
_from_dict (10)/load (3)/mask (2).
"""

import json

from app.services.captcha.key_store import (
    MAX_TIMEOUT_SEC,
    MIN_TIMEOUT_SEC,
    DEFAULT_TIMEOUT_SEC,
    CaptchaKeyStore,
    CaptchaSettings,
    clamp_timeout,
)
from app.services.captcha.signals import (
    SOLVABLE_KINDS,
    CaptchaSignal,
    SolveOutcome,
    _evidence_kwargs,
    _safe_count,
    host_of,
)
from app.services.captcha.stats import _SITE_CAP, CaptchaStatsStore


class TestSafeCount:
    def test_variants(self):
        assert _safe_count({"responseFields": 5}) == 5
        assert _safe_count({"responseFields": "7"}) == 7
        assert _safe_count({"responseFields": 3.9}) == 3
        assert _safe_count({"responseFields": None}) == 0
        assert _safe_count({}) == 0
        assert _safe_count({"responseFields": "abc"}) == 0
        assert _safe_count({"responseFields": -4}) == 0
        assert _safe_count({"responseFields": []}) == 0
        assert _safe_count({"responseFields": True}) == 1


class TestEvidenceKwargs:
    def test_empty_defaults(self):
        kw = _evidence_kwargs({})
        assert kw == {
            "integration": "unknown",
            "anchor_present": False,
            "anchor_visible": False,
            "challenge_present": False,
            "challenge_visible": False,
            "challenge_active": False,
            "challenge_title": "",
            "challenge_src": "",
            "challenge_identity": "",
            "response_fields": 0,
            "response_scope": "none",
            "sitekey_source": "none",
            "page_identity": "",
        }

    def test_full(self):
        kw = _evidence_kwargs({
            "integration": "iframe",
            "anchorPresent": True,
            "anchorVisible": True,
            "challengePresent": True,
            "challengeVisible": False,
            "challengeTitle": "verify",
            "challengeSrc": "https://x.test/rc.js",
            "challengeIdentity": "ci-1",
            "responseFields": 4,
            "responseScope": "iframe",
            "sitekeySource": "attr",
            "pageIdentity": "pid-1",
        })
        assert kw["integration"] == "iframe"
        assert kw["anchor_present"] is True
        assert kw["challenge_visible"] is False
        assert kw["challenge_title"] == "verify"
        assert kw["challenge_src"] == "https://x.test/rc.js"
        assert kw["challenge_identity"] == "ci-1"
        assert kw["response_fields"] == 4
        assert kw["response_scope"] == "iframe"
        assert kw["sitekey_source"] == "attr"
        assert kw["page_identity"] == "pid-1"

    def test_long_strings_truncated(self):
        kw = _evidence_kwargs({"challengeTitle": "t" * 300,
                               "challengeSrc": "s" * 300,
                               "challengeIdentity": "i" * 300,
                               "pageIdentity": "p" * 300})
        assert len(kw["challenge_title"]) == 120
        assert len(kw["challenge_src"]) == 120
        assert len(kw["challenge_identity"]) == 120
        assert len(kw["page_identity"]) == 120

    def test_non_string_values_coerced(self):
        kw = _evidence_kwargs({"integration": 7, "challengeTitle": None})
        assert kw["integration"] == "7"
        assert kw["challenge_title"] == ""


class TestSignalSolvable:
    def test_matrix(self):
        assert CaptchaSignal(visible=True, kind="recaptcha_v2", sitekey="k").solvable
        assert CaptchaSignal(visible=True, kind="recaptcha_enterprise", sitekey="k").solvable
        assert not CaptchaSignal(visible=False, kind="recaptcha_v2", sitekey="k").solvable
        assert not CaptchaSignal(visible=True, kind="hCaptcha", sitekey="k").solvable
        assert not CaptchaSignal(visible=True, kind="recaptcha_v2", sitekey="").solvable
        assert not CaptchaSignal().solvable
        assert SOLVABLE_KINDS == ("recaptcha_v2", "recaptcha_enterprise")


class TestSignalFromResult:
    def test_none_and_garbage(self):
        for bad in (None, 5, [1, 2], "{broken", "nope"):
            s = CaptchaSignal.from_result(bad)
            assert s.visible is False
            assert s.kind == "none"
            assert s.sitekey == ""

    def test_json_string(self):
        s = CaptchaSignal.from_result(json.dumps(
            {"visible": True, "kind": "recaptcha_v2", "sitekey": "sk", "url": "https://a.test"}))
        assert s.visible is True
        assert s.kind == "recaptcha_v2"
        assert s.sitekey == "sk"
        assert s.page_url == "https://a.test"

    def test_full_dict(self):
        s = CaptchaSignal.from_result({
            "visible": 1, "kind": "recaptcha_enterprise", "sitekey": "sk",
            "url": "https://a.test/x", "invisible": 1, "dom": "iframe",
            "integration": "js", "anchorPresent": True, "anchorVisible": True,
            "challengePresent": True, "challengeVisible": True,
            "challengeTitle": "t", "challengeSrc": "s", "challengeIdentity": "ci",
            "responseFields": 2, "responseScope": "same", "sitekeySource": "data",
            "pageIdentity": "pid",
        })
        assert s.visible is True
        assert s.is_invisible is True
        assert s.dom == "iframe"
        assert s.integration == "js"
        assert s.anchor_present is True
        assert s.challenge_visible is True
        assert s.challenge_title == "t"
        assert s.response_fields == 2
        assert s.response_scope == "same"
        assert s.sitekey_source == "data"
        assert s.page_identity == "pid"
        assert s.solvable is True


class TestHostOf:
    def test_variants(self):
        assert host_of("https://a.test/x") == "a.test"
        assert host_of("http://b.test:8080/x") == "b.test"
        assert host_of("https://[::1]/x") == "::1"
        assert host_of("") == ""
        assert host_of(None) == ""
        assert host_of("not a url") == ""
        assert host_of("ftp://c.test/f") == "c.test"


class TestSolveOutcome:
    def test_defaults(self):
        o = SolveOutcome()
        assert o.status == "none"
        assert o.attempts == 1
        assert o.polls == 0
        assert o.token_fp == ""
        assert o.continue_result == ""


class TestStatsBlankAndTypes:
    def test_blank(self):
        b = CaptchaStatsStore._blank()
        assert b["detected_total"] == 0
        assert b["last_balance"] is None
        assert b["balance_at"] == ""
        assert b["per_site"] == {}
        assert b["last_error"] == ""

    def test_valid_type(self):
        vt = CaptchaStatsStore._valid_type
        assert vt("per_site", {}) is True
        assert vt("per_site", [1]) is False
        assert vt("last_balance", None) is True
        assert vt("last_balance", 1.5) is True
        assert vt("last_balance", True) is False
        assert vt("last_balance", "x") is False
        assert vt("auto_solved", 3) is True
        assert vt("auto_solved", True) is False
        assert vt("auto_solved", "3") is False
        assert vt("last_error", "x") is True
        assert vt("last_error", 3) is False
        assert vt("unknown_key", 3) is False


class TestStatsStore:
    def make(self, tmp_path):
        return CaptchaStatsStore(tmp_path)

    def test_missing_file_blank(self, tmp_path):
        s = self.make(tmp_path)
        assert s.to_dict()["detected_total"] == 0

    def test_corrupt_file_blank(self, tmp_path):
        (tmp_path / "captcha_stats.json").write_text("{bad", encoding="utf-8")
        s = self.make(tmp_path)
        assert s.to_dict()["auto_solved"] == 0

    def test_non_dict_file_blank(self, tmp_path):
        (tmp_path / "captcha_stats.json").write_text("[1]", encoding="utf-8")
        s = self.make(tmp_path)
        assert s.to_dict()["auto_solved"] == 0

    def test_invalid_values_reset(self, tmp_path):
        (tmp_path / "captcha_stats.json").write_text(json.dumps({
            "auto_solved": "junk", "last_balance": True, "per_site": [1],
            "detected_total": 7, "last_error": "kept",
        }), encoding="utf-8")
        s = self.make(tmp_path)
        d = s.to_dict()
        assert d["auto_solved"] == 0
        assert d["last_balance"] is None
        assert d["per_site"] == {}
        assert d["detected_total"] == 7
        assert d["last_error"] == "kept"

    def test_record_events(self, tmp_path):
        s = self.make(tmp_path)
        s.record("detected", "a.test")
        s.record("auto_solved", "a.test")
        s.record("auto_failed", "b.test")
        s.record("manual_solved")
        s.record("task_created")
        s.record("task_deleted")
        s.record("nonsense")
        d = s.to_dict()
        assert d["detected_total"] == 1
        assert d["auto_solved"] == 1
        assert d["auto_failed"] == 1
        assert d["manual_solved"] == 1
        assert d["tasks_created"] == 1
        assert d["tasks_deleted"] == 1
        assert d["per_site"]["a.test"]["detected"] == 1
        assert d["per_site"]["a.test"]["auto_solved"] == 1
        assert d["per_site"]["b.test"]["auto_failed"] == 1
        assert "*" not in d["per_site"]

    def test_record_site_counters_global_only_for_detection_events(self, tmp_path):
        s = self.make(tmp_path)
        s.record("task_created", "a.test")
        assert s.to_dict()["per_site"] == {}

    def test_per_site_cap_folds_to_star(self, tmp_path):
        s = self.make(tmp_path)
        for i in range(_SITE_CAP - 1):
            s.record("detected", f"site{i}.test")
        s.record("detected", "overflow.test")
        d = s.to_dict()
        assert "overflow.test" not in d["per_site"]
        assert d["per_site"]["*"]["detected"] == 1

    def test_set_balance(self, tmp_path):
        s = self.make(tmp_path)
        s.set_balance(12.34567)
        assert s.last_balance == 12.3457
        assert len(s.balance_at) >= 10
        assert s.to_dict()["last_balance"] == 12.3457

    def test_set_last_error(self, tmp_path):
        s = self.make(tmp_path)
        s.set_last_error("e" * 300)
        assert len(s.last_error) == 120
        s.set_last_error(None)
        assert s.last_error == ""

    def test_success_rate(self, tmp_path):
        s = self.make(tmp_path)
        assert s.success_rate == 0.0
        for _ in range(3):
            s.record("auto_solved")
        s.record("auto_failed")
        assert s.success_rate == 0.75
        assert s.to_dict()["auto_success_rate"] == 0.75

    def test_round_trip(self, tmp_path):
        s1 = self.make(tmp_path)
        s1.record("detected", "a.test")
        s1.set_balance(5.5)
        s1.set_last_error("err")
        s2 = self.make(tmp_path)
        assert s2.to_dict()["detected_total"] == 1
        assert s2.last_balance == 5.5
        assert s2.last_error == "err"

    def test_no_tmp_left(self, tmp_path):
        s = self.make(tmp_path)
        s.record("detected")
        assert list(tmp_path.glob("*.tmp")) == []


class TestClampTimeout:
    def test_variants(self):
        assert clamp_timeout(100) == 100
        assert clamp_timeout(10) == MIN_TIMEOUT_SEC
        assert clamp_timeout(9999) == MAX_TIMEOUT_SEC
        assert clamp_timeout("abc") == DEFAULT_TIMEOUT_SEC
        assert clamp_timeout(None) == DEFAULT_TIMEOUT_SEC
        assert clamp_timeout(True) == MIN_TIMEOUT_SEC
        assert clamp_timeout(59.9) == 59


class TestKeyStore:
    def make(self, tmp_path):
        return CaptchaKeyStore(tmp_path)

    def test_load_missing(self, tmp_path):
        s = self.make(tmp_path).load()
        assert s.enabled is False
        assert s.api_key == ""
        assert s.solve_timeout_sec == DEFAULT_TIMEOUT_SEC

    def test_load_corrupt(self, tmp_path):
        (tmp_path / "2captcha.json").write_text("{bad", encoding="utf-8")
        s = self.make(tmp_path).load()
        assert s.api_key == ""

    def test_load_non_dict(self, tmp_path):
        (tmp_path / "2captcha.json").write_text("[1]", encoding="utf-8")
        s = self.make(tmp_path).load()
        assert s.api_key == ""

    def test_load_full(self, tmp_path):
        (tmp_path / "2captcha.json").write_text(json.dumps({
            "enabled": True, "api_key": "  key-123  ", "solve_timeout_sec": 400,
        }), encoding="utf-8")
        s = self.make(tmp_path).load()
        assert s.enabled is True
        assert s.api_key == "key-123"
        assert s.solve_timeout_sec == 400

    def test_enabled_requires_key(self, tmp_path):
        (tmp_path / "2captcha.json").write_text(json.dumps(
            {"enabled": True, "api_key": ""}), encoding="utf-8")
        assert self.make(tmp_path).load().enabled is False

    def test_timeout_clamped_on_load(self, tmp_path):
        (tmp_path / "2captcha.json").write_text(json.dumps(
            {"enabled": True, "api_key": "k", "solve_timeout_sec": 9999}), encoding="utf-8")
        assert self.make(tmp_path).load().solve_timeout_sec == MAX_TIMEOUT_SEC

    def test_save_load_round_trip(self, tmp_path):
        store = self.make(tmp_path)
        store.save(CaptchaSettings(enabled=True, api_key="k-1", solve_timeout_sec=120))
        loaded = store.load()
        assert loaded.enabled is True
        assert loaded.api_key == "k-1"
        assert loaded.solve_timeout_sec == 120
        assert not list(tmp_path.glob("*.tmp"))

    def test_save_enabled_without_key_false(self, tmp_path):
        store = self.make(tmp_path)
        store.save(CaptchaSettings(enabled=True, api_key=""))
        data = json.loads((tmp_path / "2captcha.json").read_text("utf-8"))
        assert data["enabled"] is False

    def test_save_mode_600(self, tmp_path):
        import os
        store = self.make(tmp_path)
        store.save(CaptchaSettings(api_key="k"))
        mode = os.stat(tmp_path / "2captcha.json").st_mode & 0o777
        assert mode == 0o600

    def test_mask(self):
        assert CaptchaKeyStore.mask("") == ""
        assert CaptchaKeyStore.mask(None) == ""
        assert CaptchaKeyStore.mask("short") == "short"
        assert CaptchaKeyStore.mask("1234567") == "1234567"
        assert CaptchaKeyStore.mask("abcdefgh") == "abcd****efgh"
        assert CaptchaKeyStore.mask("  abcd1234efgh  ") == "abcd****efgh"
