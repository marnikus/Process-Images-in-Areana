"""Declared browser endpoints: one base port, a protocol per slot (I-63)."""

import pytest

from app.browser.endpoints import (CHROME, FIREFOX, BrowserEndpoint, default_endpoints,
                                   derive_ports, endpoint_label, parse_endpoints)

pytestmark = pytest.mark.unit


def test_ports_derive_from_one_base():
    assert derive_ports(9223, 3) == [9223, 9224, 9225]


def test_a_zero_or_unusable_base_derives_nothing_rather_than_guessing():
    assert derive_ports(0, 3) == [] and derive_ports("nope", 3) == []
    assert derive_ports(9223, 0) == [] and derive_ports(9223, "x") == []


def test_derived_ports_stop_at_the_top_of_the_port_range():
    assert derive_ports(65534, 5) == [65534, 65535]


def test_each_row_declares_its_own_protocol():
    rows = [{"kind": "chrome"}, {"kind": "firefox"}]
    found = parse_endpoints(rows, base=9223)
    assert [(e.port, e.kind) for e in found] == [(9223, CHROME), (9224, FIREFOX)]


def test_an_explicit_port_beats_the_derived_one():
    found = parse_endpoints([{"kind": "firefox", "port": 9999}], base=9223)
    assert found[0].port == 9999


def test_an_unknown_kind_is_dropped_rather_than_assumed_to_be_chrome():
    """Guessing the protocol is what produced the /json/list loop."""
    assert parse_endpoints([{"kind": "safari"}, {"kind": ""}, {}], base=9223) == []


def test_rows_that_are_not_even_dicts_are_ignored():
    assert parse_endpoints(["chrome", None, 7], base=9223) == []


def test_no_configuration_is_empty_not_a_default():
    assert parse_endpoints([], base=9223) == [] and parse_endpoints(None) == []


def test_two_rows_on_one_port_collapse_to_the_first():
    rows = [{"kind": "chrome", "port": 9223}, {"kind": "firefox", "port": 9223}]
    found = parse_endpoints(rows)
    assert len(found) == 1 and found[0].kind == CHROME


def test_a_row_may_override_the_host():
    found = parse_endpoints([{"kind": "chrome", "port": 9223, "host": "localhost"}])
    assert found[0].host == "localhost"


def test_firefox_does_not_speak_cdp_and_chrome_does():
    """The single predicate that routes protocol — /json/list is Chrome-only."""
    assert BrowserEndpoint("127.0.0.1", 9223, CHROME).speaks_cdp is True
    assert BrowserEndpoint("127.0.0.1", 9224, FIREFOX).speaks_cdp is False


def test_an_endpoint_is_labelled_with_its_real_browser_name():
    firefox = BrowserEndpoint("127.0.0.1", 9224, FIREFOX)
    assert firefox.label == "Firefox"
    assert endpoint_label(firefox) == "Firefox 127.0.0.1:9224"
    assert firefox.key == "firefox@127.0.0.1:9224"


def test_the_legacy_single_chrome_setup_still_produces_one_endpoint():
    found = default_endpoints("127.0.0.1", 9222)
    assert len(found) == 1 and found[0].kind == CHROME and found[0].port == 9222


def test_a_legacy_setup_with_no_port_produces_nothing():
    assert default_endpoints("127.0.0.1", 0) == []


def test_a_row_whose_derived_port_would_overflow_is_dropped():
    """No usable port means no endpoint — never a silent fallback."""
    assert parse_endpoints([{"kind": "chrome"}], base=65535) != []
    assert parse_endpoints([{"kind": "chrome"}, {"kind": "firefox"}], base=65535) == [
        BrowserEndpoint("127.0.0.1", 65535, CHROME)]
