"""Exact URL authorization rules: no silent normalization or fuzzy destination selection."""

import pytest

from image_queue.domain.connections import MatchStatus, PageTarget, match_open_tabs
from image_queue.domain.urls import UrlRow, validate_url
from image_queue.domain.validation import ContractError

URL = "https://arena.ai/c/Case-Sensitive?mode=edit&x=1#image"


@pytest.mark.parametrize(
    "value",
    [
        URL,
        "http://localhost:8080/a",
        "https://[::1]:443/a",
        "https://例え.jp/a",
        "https://example.org/a%20b",
    ],
)
def test_valid_text_is_preserved_exactly(value):
    assert validate_url(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "example.org",
        "/relative",
        "file:///tmp/x",
        "javascript:alert(1)",
        " https://arena.ai/",
        "https://arena.ai/ ",
        "https://arena.ai/a\nb",
        "https://arena.ai/\x00",
        "https://arena.ai/\x7f",
        "https://arena.ai/a b",
        "https://user:SECRET@arena.ai/",
        "https://user@arena.ai/",
        "https://@arena.ai/",
        "https:///path",
        "https://[::1",
        "https://arena.ai:wrong/",
        "https://arena.ai:65536/",
        "https://arena.ai:0/",
        "https://arena.ai:/",
        "https://arena.ai\\other/",
        "https://arena.ai/a%2",
        None,
        42,
    ],
)
def test_invalid_input_is_actionable_without_echoing_values(value):
    with pytest.raises(ContractError) as raised:
        validate_url(value)
    assert "SECRET" not in str(raised.value)


@pytest.mark.parametrize("row_id", ["", "with space", "x" * 81, None])
def test_stable_ids_must_be_valid(row_id):
    with pytest.raises(ContractError):
        UrlRow(row_id, URL)


def test_row_is_immutable_and_requires_boolean():
    with pytest.raises(ContractError):
        UrlRow("row-1", URL, 1)
    from dataclasses import FrozenInstanceError

    row = UrlRow("row-1", URL)
    with pytest.raises(FrozenInstanceError):
        row.enabled = False


@pytest.mark.parametrize(
    "other",
    [
        URL.lower(),
        URL.replace("https:", "http:"),
        URL.replace("x=1", "x=2"),
        URL.replace("#image", "#other"),
        URL.replace("Case-Sensitive", "Case-Sensitive/"),
        "https://arena.ai/c/other",
        URL.replace("Case", "%43ase"),
        URL.replace("mode=edit&x=1", "x=1&mode=edit"),
    ],
)
def test_near_matches_are_never_authorized(other):
    result = match_open_tabs(UrlRow("row", URL), (PageTarget("tab", other),))
    assert result.status is MatchStatus.MISSING
    assert result.target_ids == ()


def test_one_exact_candidate_is_not_connection_or_readiness():
    result = match_open_tabs(UrlRow("row", URL), (PageTarget("tab", URL),))
    assert result.status is MatchStatus.UNIQUE
    assert result.status.value == "exact_candidate"
    assert result.row_id == "row"
    assert result.target_ids == ("tab",)


def test_duplicates_require_choice_and_remain_independent_rows():
    targets = (PageTarget("first", URL), PageTarget("second", URL))
    first = match_open_tabs(UrlRow("row1", URL), targets)
    second = match_open_tabs(UrlRow("row2", URL), targets)
    assert first.status is MatchStatus.AMBIGUOUS
    assert first.target_ids == ("first", "second")
    assert first.row_id != second.row_id
    assert first.target_ids == second.target_ids


def test_duplicate_discovery_ids_fail_closed():
    with pytest.raises(ContractError, match="duplicate target IDs"):
        match_open_tabs(UrlRow("row", URL), (PageTarget("id", URL), PageTarget("id", URL)))


@pytest.mark.parametrize(
    "targets", [(), (PageTarget("", URL),), (PageTarget("id", URL, "worker"),)]
)
def test_missing_or_non_page_targets_cannot_match(targets):
    assert match_open_tabs(UrlRow("row", URL), targets).status is MatchStatus.MISSING


def test_disabled_row_gets_no_candidates_even_if_open():
    result = match_open_tabs(UrlRow("row", URL, False), (PageTarget("id", URL),))
    assert result.status is MatchStatus.DISABLED
    assert result.target_ids == ()


@pytest.mark.parametrize(
    "value",
    [
        "https://bad%20host/",
        "https://-bad.example/",
        "https://bad_.example/",
        "https://host../",
        "https://" + "a" * 64 + ".example/",
        "https://" + ".".join(["a" * 60] * 5) + "/",
        "https://arena.ai/<bad>",
        "https://\ud800.example/",
    ],
)
def test_invalid_hostname_and_forbidden_uri_characters(value):
    with pytest.raises(ContractError):
        validate_url(value)


def test_dns_name_spelling_is_not_changed():
    assert validate_url("https://Example.COM./Path") == "https://Example.COM./Path"


def test_conflicting_duplicate_discovery_id_cannot_authorize_wrong_page():
    targets = (PageTarget("same", URL), PageTarget("same", "https://arena.ai/c/other"))
    with pytest.raises(ContractError):
        match_open_tabs(UrlRow("row", URL), targets)


def test_invalid_unicode_in_path_is_rejected_before_serialization():
    with pytest.raises(ContractError, match="Unicode"):
        validate_url("https://arena.ai/\ud800")
