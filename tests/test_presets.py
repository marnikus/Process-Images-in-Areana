"""Codec round-trip/negative tests; no disk state or legacy preset silently overwritten."""

import json
from dataclasses import fields

import pytest

from image_queue.domain.presets import MAX_PRESET_BYTES, dumps_preset, loads_preset
from image_queue.domain.settings import ChromeEndpoint, ConnectionPreset, HighlightSettings
from image_queue.domain.urls import UrlRow
from image_queue.domain.validation import ContractError


def custom_preset():
    return ConnectionPreset(
        ChromeEndpoint("::1", 9333),
        HighlightSettings(False, 350, 4567),
        (
            UrlRow("row-a", "https://arena.ai/c/Case?x=2&y=1#anchor", False),
            UrlRow("row-b", "https://例え.jp/a", True),
        ),
    )


def test_every_implemented_parameter_round_trips():
    preset = custom_preset()
    text = dumps_preset(preset)
    assert loads_preset(text) == preset
    data = json.loads(text)
    assert set(data["endpoint"]) == {f.name for f in fields(ChromeEndpoint)}
    assert set(data["highlight"]) == {f.name for f in fields(HighlightSettings)}
    assert set(data["urls"][0]) == {f.name for f in fields(UrlRow)}
    assert "例え" in text
    assert text.endswith("\n")


def test_defaults_round_trip():
    assert loads_preset(dumps_preset(ConnectionPreset())) == ConnectionPreset()


@pytest.mark.parametrize("text", ["{", "null", "[]", "{}", '{"x":1,"x":2}', "[" * 2000])
def test_malformed_or_incomplete_json_is_not_empty_configuration(text):
    with pytest.raises(ContractError):
        loads_preset(text)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", 2),
        ("schema_version", True),
        ("format", "chat-v-bot/stack-preset"),
        ("endpoint", {"host": "evil.example", "port": 9222}),
        ("urls", {}),
        ("urls", [{"row_id": "a", "exact_url": 123, "enabled": True}]),
        ("urls", [{"row_id": "a", "exact_url": "https://arena.ai", "enabled": "false"}]),
        ("highlight", {"highlight_enabled": False, "highlight_ms": 2}),
    ],
)
def test_invalid_fields_do_not_mutate_existing_preset(field, value):
    original = custom_preset()
    payload = json.loads(dumps_preset(original))
    payload[field] = value
    with pytest.raises(ContractError):
        loads_preset(json.dumps(payload))
    assert original == custom_preset()


def test_unknown_fields_are_not_silently_dropped():
    payload = json.loads(dumps_preset(ConnectionPreset()))
    payload["future_setting"] = "value"
    with pytest.raises(ContractError, match="unsupported fields"):
        loads_preset(json.dumps(payload))


def test_duplicate_keys_in_nested_objects_fail():
    text = dumps_preset(ConnectionPreset()).replace('"port": 9222', '"port": 9222, "port": 9223')
    with pytest.raises(ContractError, match="duplicate keys"):
        loads_preset(text)


def test_import_export_size_budget_is_symmetric():
    with pytest.raises(ContractError, match="limit"):
        loads_preset(" " * (MAX_PRESET_BYTES + 1))
    huge = UrlRow("row", "https://arena.ai/?x=" + "a" * MAX_PRESET_BYTES)
    with pytest.raises(ContractError, match="limit"):
        dumps_preset(ConnectionPreset(urls=(huge,)))


def test_invalid_unicode_is_a_contract_error_not_an_empty_preset():
    with pytest.raises(ContractError, match="Unicode"):
        loads_preset("\ud800")
