"""Actual validated settings preserve old visual timing and reject dangerous endpoint values."""

import pytest

from image_queue.domain.settings import ChromeEndpoint, ConnectionPreset, HighlightSettings
from image_queue.domain.urls import UrlRow
from image_queue.domain.validation import ContractError


def test_defaults_preserve_existing_cdp_and_visual_contracts():
    preset = ConnectionPreset()
    assert preset.endpoint.discovery_origin == "http://127.0.0.1:9222"
    assert preset.highlight.highlight_enabled is True
    assert preset.highlight.confirm_pause_ms == 700
    assert preset.highlight.highlight_ms == 1200
    assert preset.urls == ()


@pytest.mark.parametrize("host,expected", [("localhost", "localhost"), ("::1", "[::1]")])
def test_loopback_origin(host, expected):
    assert ChromeEndpoint(host, 9333).discovery_origin == f"http://{expected}:9333"


@pytest.mark.parametrize(
    "host",
    [
        "0.0.0.0",
        "example.com",
        "192.168.1.2",
        "localhost.evil",
        "http://localhost",
        "127.0.0.2",
        " LOCALHOST",
        None,
        [],
    ],
)
def test_endpoint_is_loopback_only(host):
    with pytest.raises(ContractError):
        ChromeEndpoint(host)


@pytest.mark.parametrize("port", [0, 65536, -1, True, 9222.0, "9222"])
def test_port_is_strict_integer_in_range(port):
    with pytest.raises(ContractError):
        ChromeEndpoint(port=port)


@pytest.mark.parametrize("field", ["confirm_pause_ms", "highlight_ms"])
@pytest.mark.parametrize("value", [-1, 30001, True, 1.5, "1200"])
def test_visual_timing_is_validated(field, value):
    with pytest.raises(ContractError):
        HighlightSettings(**{field: value})


def test_visual_setting_can_be_disabled_with_zero_delay():
    assert HighlightSettings(False, 0, 0).highlight_ms == 0
    assert HighlightSettings(True, 30000, 30000).confirm_pause_ms == 30000
    with pytest.raises(ContractError):
        HighlightSettings(highlight_enabled="false")


def test_distinct_row_ids_allow_duplicate_urls():
    rows = (UrlRow("a", "https://arena.ai/"), UrlRow("b", "https://arena.ai/"))
    assert ConnectionPreset(urls=rows).urls == rows
    with pytest.raises(ContractError):
        ConnectionPreset(urls=(rows[0], rows[0]))


@pytest.mark.parametrize(
    "kwargs", [{"endpoint": {}}, {"highlight": {}}, {"urls": []}, {"urls": ("not-row",)}]
)
def test_direct_construction_cannot_bypass_types(kwargs):
    with pytest.raises(ContractError):
        ConnectionPreset(**kwargs)
