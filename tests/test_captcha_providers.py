"""Solver provider registry — specs, task types, error classification.

RULE 8: pure data + classifiers exercised directly; deleting provider_for or
either spec fails these. The stable reason tokens are the contract the solver
and service consume — they must not differ per provider.
"""

import pytest

from app.services.captcha.providers import (
    DEFAULT_PROVIDER, PROVIDERS, ProviderSpec, provider_for,
)


@pytest.mark.unit
def test_two_providers_registered_with_default():
    assert DEFAULT_PROVIDER == "2captcha"
    assert set(PROVIDERS) == {"2captcha", "capmonster"}


@pytest.mark.unit
def test_provider_for_known_unknown_and_junk():
    assert provider_for("capmonster") is PROVIDERS["capmonster"]
    assert provider_for("2captcha") is PROVIDERS["2captcha"]
    assert provider_for("does-not-exist") is PROVIDERS[DEFAULT_PROVIDER]
    assert provider_for(None) is PROVIDERS[DEFAULT_PROVIDER]
    assert provider_for(123) is PROVIDERS[DEFAULT_PROVIDER]


@pytest.mark.unit
def test_task_types_per_provider_and_fallback():
    ent2, v22 = "RecaptchaV2EnterpriseTaskProxyless", "RecaptchaV2TaskProxyless"
    entc, v2c = "RecaptchaV2EnterpriseTask", "RecaptchaV2Task"
    two, cap = PROVIDERS["2captcha"], PROVIDERS["capmonster"]
    assert two.task_type_for("recaptcha_enterprise") == ent2
    assert two.task_type_for("recaptcha_v2") == v22
    assert cap.task_type_for("recaptcha_enterprise") == entc
    assert cap.task_type_for("recaptcha_v2") == v2c
    # unknown kind falls back to the enterprise type (established default)
    assert two.task_type_for("image") == ent2
    assert cap.task_type_for("") == entc


@pytest.mark.unit
def test_wire_facts_differ_per_docs():
    two, cap = PROVIDERS["2captcha"], PROVIDERS["capmonster"]
    assert two.api_base == "https://api.2captcha.com"
    assert cap.api_base == "https://api.capmonster.cloud"
    assert two.poll_interval_sec >= 2.0 and cap.poll_interval_sec >= 2.0
    assert two.can_delete is True   # deleteTask refunds abandoned tasks
    assert cap.can_delete is False  # CapMonster has no deleteTask (unsolved not charged)
    assert two.enterprise_invisible is True   # isInvisible documented for enterprise
    assert cap.enterprise_invisible is False  # not documented there
    assert two.title == "2Captcha" and cap.title == "CapMonster Cloud"


@pytest.mark.unit
def test_2captcha_error_reasons_stable():
    r = PROVIDERS["2captcha"].error_reason
    assert r(1, None) == "unavailable"
    assert r(2, "KEY_DOESNT_EXIST") == "bad_key"
    assert r(3, "NOT_ENOUGH_CREDIT") == "no_credit"
    assert r(16, "TASK_NOT_FOUND") == "not_found"
    assert r(99, "WHATEVER") == "task_error"
    assert r("x", None) == "task_error"
    assert r(None, None) == "task_error"


@pytest.mark.unit
def test_capmonster_error_reasons_map_to_same_tokens():
    r = PROVIDERS["capmonster"].error_reason
    assert r(1, "ERROR_KEY_DOES_NOT_EXIST") == "bad_key"
    assert r(1, "ERROR_ZERO_BALANCE") == "no_credit"
    assert r(1, "ERROR_NO_SUCH_CAPCHA_ID") == "not_found"
    assert r(1, "WRONG_CAPTCHA_ID") == "not_found"
    assert r(1, "ERROR_SERVICE_NOT_AVAILABLE") == "unavailable"
    assert r(1, "ERROR_TOO_MUCH_REQUESTS") == "unavailable"
    assert r(1, "ERROR_CAPTCHA_UNSOLVABLE") == "task_error"
    assert r(1, None) == "task_error"
    assert r(1, "") == "task_error"


@pytest.mark.unit
def test_capmonster_not_ready_is_pending_not_terminal():
    """CAPTCHA_NOT_READY = still solving — the poll loop must continue."""
    assert PROVIDERS["capmonster"].error_reason(1, "CAPTCHA_NOT_READY") == "pending"


@pytest.mark.unit
def test_spec_is_a_closed_data_table():
    """Adding a provider = one spec entry; specs carry no behaviour branches."""
    assert isinstance(PROVIDERS["capmonster"], ProviderSpec)
    for spec in PROVIDERS.values():
        assert spec.id in ("2captcha", "capmonster")
        assert spec.api_base.startswith("https://")
        assert set(spec.task_types) == {"recaptcha_enterprise", "recaptcha_v2"}
