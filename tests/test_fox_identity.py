"""I-64 · Stable Firefox tab ids across rescans — the identity book (pure).

`{profileDirName}_tab{N}` must survive moves, navigations, session-store
hiccups and app restarts, and a new tab must never take an id that may still
come back.
"""

import pytest

from app.browser.uivision.pool.identity import (GRACE_SCANS, FoxTabBook, Seen, match_known,
                                                number_new)

pytestmark = pytest.mark.unit

D = "9THrgpBc.Profile1"


def tid(n):
    return f"{D}_tab{n}"


def ids(book, *tabs):
    return book.assign(D, list(tabs))


def test_first_sight_numbers_by_flat_position():
    assert ids(FoxTabBook(), ("u1", 2), ("u2", 5)) == [tid(2), tid(5)]


def test_an_unchanged_scan_keeps_every_id():
    book = FoxTabBook()
    first = ids(book, ("u1", 1), ("u2", 2))
    assert ids(book, ("u1", 1), ("u2", 2)) == first


def test_a_moved_tab_keeps_its_id_before_a_neighbour_claims_its_place():
    book = FoxTabBook()
    ids(book, ("u1", 1), ("u2", 2), ("u3", 3))
    # u1 closed: u2/u3 shift left — neither may inherit the id of the place it moved into
    assert ids(book, ("u2", 1), ("u3", 2)) == [tid(2), tid(3)]


def test_a_navigated_tab_keeps_its_id():
    book = FoxTabBook()
    ids(book, ("u1", 1), ("u2", 2))
    assert ids(book, ("u1", 1), ("u9", 2)) == [tid(1), tid(2)]


def test_a_tab_back_within_the_grace_gets_its_old_id():
    book = FoxTabBook()
    ids(book, ("u1", 1), ("u2", 2))
    ids(book, ("u1", 1))                                # a hiccup: u2 missing once
    assert ids(book, ("u1", 1), ("u2", 2)) == [tid(1), tid(2)]


def test_a_missing_id_is_kept_for_the_grace_then_forgotten():
    book = FoxTabBook()
    ids(book, ("u1", 1), ("u2", 2))
    for _ in range(GRACE_SCANS):
        ids(book, ("u1", 1))
    assert tid(2) in book.known_ids(D)                  # still in grace
    ids(book, ("u1", 1))
    assert book.known_ids(D) == [tid(1)]


def test_a_new_id_skips_every_number_still_held():
    assert number_new(D, {tid(2), tid(3)}, 2) == tid(4)
    assert number_new(D, set(), 0) == tid(1)            # positions are 1-based


def test_rules_run_over_all_tabs_before_the_next_rule():
    known = {tid(1): Seen("a", 1), tid(2): Seen("b", 2)}
    # "b" moved to 1 and a new "c" sits at 2: "b" must take tab2 by URL before "c" takes it by place
    assert match_known(known, [("b", 1), ("c", 2)]) == [tid(2), None]


def test_seeded_rows_keep_their_ids_across_a_restart():
    book = FoxTabBook()
    assert book.seed([(tid(4), "u4"), ("ABCDEF", "chrome"), (tid(4), "dup")]) == 1
    assert ids(book, ("u4", 1)) == [tid(4)]             # same URL wins over position
    assert book.assign("abc.Profile2", [("u4", 1)]) == ["abc.Profile2_tab1"]   # profiles never mix
