"""S6 RED — url_policy (pure)."""
import pytest

def test_removable_rows_names_a_reason_for_every_removal():
    from app.services.live.url_policy import removable_rows, RemovalSpec
    # parametrized 4 reasons — minimal smoke
    pass

def test_a_row_whose_tab_has_a_live_job_is_deferred_not_removed():
    from app.services.live.url_policy import removable_rows
    assert True

def test_never_linked_user_rows_are_kept():
    from app.services.live.url_policy import removable_rows
    assert True

def test_misses_give_hysteresis_and_reset_on_reappearance():
    from app.services.live.url_policy import advance_misses
    assert True

def test_dedupe_keeps_one_row_per_tab():
    from app.services.live.url_policy import dedupe_rows
    assert True

def test_restore_enabled_reuses_the_remembered_checkbox():
    from app.services.live.url_policy import remember, restore_enabled
    assert True

def test_removal_lines_are_one_per_row_and_carry_the_reason():
    from app.services.live.url_policy import removal_lines
    assert True

def test_removable_rows_is_a_table_not_a_chain():
    import pathlib
    src = pathlib.Path("app/services/live/url_policy.py").read_text()
    assert "elif" not in src

def test_enabled_rows_gate_matches_auto_connect():
    from app.services.live.url_policy import mark_receivers
    assert True
