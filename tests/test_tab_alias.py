"""Readable tab ids — the pure half (`app/core/tab_alias.py`), RED-first.

User spec: a worker tab shows `{email}_{4 digits}` (e.g. `marnikus@gmail.com_3045`),
never the 32-hex CDP id; two tabs of one account share the prefix and differ by
the number; the number is unique per tab and (owner decision) survives a restart.
"""

import pytest

from app.core.tab_alias import (
    ALIAS_MAX,
    FALLBACK_PREFIX,
    AliasBook,
    email_from_probe,
    format_alias,
    next_alias_no,
)

pytestmark = pytest.mark.unit


# ---- format_alias ---------------------------------------------------------

def test_format_uses_the_users_example():
    assert format_alias("marnikus@gmail.com", 3045) == "marnikus@gmail.com_3045"
    assert format_alias("marnikus@gmail.com", 1134) == "marnikus@gmail.com_1134"


def test_format_normalizes_the_owner():
    assert format_alias("  Marnikus@Gmail.COM  ", 7) == "marnikus@gmail.com_0007"


def test_format_pads_the_number_to_four_digits():
    assert format_alias("a@b.co", 1) == "a@b.co_0001"
    assert format_alias("a@b.co", ALIAS_MAX) == "a@b.co_9999"


def test_format_falls_back_to_the_aka_prefix():
    assert FALLBACK_PREFIX == "aka"
    assert format_alias("", 3045) == "aka_3045"
    assert format_alias("   ", 3045) == "aka_3045"


@pytest.mark.parametrize("no", [0, -1, ALIAS_MAX + 1])
def test_format_without_a_valid_number_is_empty(no):
    assert format_alias("marnikus@gmail.com", no) == ""


# ---- email_from_probe (boundary table) ------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ('{"email": "zeusthunder1991@gmail.com", "via": "selector"}', "zeusthunder1991@gmail.com"),
    ('{"email": "  Marnikus@Gmail.COM "}', "marnikus@gmail.com"),
    ("zeusthunder1991@gmail.com", "zeusthunder1991@gmail.com"),          # plain string reply
    ('{"email": "a+tag@sub.domain.co"}', "a+tag@sub.domain.co"),
    ('not json but has x@y.io inside', "x@y.io"),
    ('{"email": "a@b.co."}', "a@b.co"),
    (["", {"email": "a@b.co"}], "a@b.co"),
    ({"email": "a@b.co"}, "a@b.co"),
    (None, ""),
    ("", ""),
    ("{}", ""),
    ("{broken json", ""),
    ('{"email": "not-an-email"}', ""),
    ('{"email": "a@b"}', ""),                    # no TLD
    ('{"email": "a b@c.co"}', ""),               # whitespace inside
    ('{"email": 42}', ""),
    ('{"email": "Sign in"}', ""),
    ('{"email": "' + "x" * 80 + '@gmail.com"}', ""),   # over the length cap
    ('{"email": "' + "x" * 40 + '@gmail.com"}', "x" * 40 + "@gmail.com"),
])
def test_email_from_probe_accepts_only_a_real_email(raw, expected):
    assert email_from_probe(raw) == expected


# ---- next_alias_no --------------------------------------------------------

@pytest.mark.parametrize("taken,expected", [
    ([], 1),
    ([1, 2, 3], 4),
    ([5, 1], 6),                 # highest used + 1, order does not matter
    ({9999}, 1),                 # wrap into the lowest free number
    ({9999, 1}, 2),
    ({9999, 1, 2, 5}, 3),
    ([0, -3, "x", None], 1),     # junk ignored
])
def test_next_alias_no_is_monotone_and_wrap_safe(taken, expected):
    assert next_alias_no(taken) == expected


def test_next_alias_no_never_reuses_a_live_number():
    taken = {1, 2, 3, 9800}
    assert next_alias_no(taken) == 9801


def test_next_alias_no_raises_when_every_number_is_taken():
    with pytest.raises(ValueError):
        next_alias_no(range(1, ALIAS_MAX + 1))


# ---- AliasBook ------------------------------------------------------------

def test_book_allocates_once_per_tab_and_keeps_it():
    book = AliasBook()
    assert book.no_for("tab-a") == 1
    assert book.no_for("tab-b") == 2
    assert book.no_for("tab-a") == 1        # stable while the tab lives
    assert book.label_for("tab-a") == "aka_0001"


def test_book_without_a_tab_id_allocates_nothing():
    book = AliasBook()
    assert book.no_for("") == 0
    assert book.label_for("") == ""


def test_book_restores_persisted_numbers_and_continues_above_them():
    book = AliasBook({"t1": {"no": 3045, "email": "m@gmail.com"}})
    assert book.no_for("t1") == 3045
    assert book.owner_for("t1") == "m@gmail.com"
    assert book.label_for("t1") == "m@gmail.com_3045"
    assert book.no_for("t2") == 3046


def test_book_remember_updates_the_email_and_never_the_number():
    book = AliasBook({"t1": {"no": 3045, "email": "old@x.io"}})
    book.remember("t1", "new@x.io")
    assert book.label_for("t1") == "new@x.io_3045"
    book.remember("ghost", "nope@x.io")     # unknown tab: never allocate here
    assert book.as_dict().keys() == {"t1"}


def test_book_round_trips_through_as_dict():
    book = AliasBook({"t1": {"no": 3045, "email": "m@gmail.com"}})
    book.no_for("t2")
    again = AliasBook(book.as_dict())
    assert again.no_for("t1") == 3045
    assert again.no_for("t2") == 3046
    assert again.owner_for("t1") == "m@gmail.com"


@pytest.mark.parametrize("bad", [
    {"t": 5},
    {"t": {"no": "x"}},
    {"t": {"no": 0}},
    {"t": {"no": ALIAS_MAX + 1}},
    {"t": {"no": None}},
    {"": {"no": 5}},
])
def test_book_drops_malformed_entries(bad):
    book = AliasBook(bad)
    assert book.as_dict() == {}
    assert book.no_for("fresh") == 1


def test_book_carries_the_email_into_a_partial_entry():
    book = AliasBook({"t1": {"no": 7}})     # persisted before the probe ran
    assert book.owner_for("t1") == ""
    assert book.label_for("t1") == "aka_0007"
