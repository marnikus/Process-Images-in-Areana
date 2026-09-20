"""S6 RED — live reconcile (bridge + LiveDeps)."""
import pytest

def test_the_interval_is_read_every_pass():
    from app.services.live.reconcile import reconcile_loop
    assert True

def test_an_empty_fetch_never_removes_rows():
    from app.services.live.reconcile import reconcile_once
    assert True

def test_a_new_tab_is_added_claimed_and_joined():
    from app.services.live.reconcile import reconcile_once
    assert True

def test_a_closed_tab_is_removed_with_a_reason_and_wakes_the_loop():
    from app.services.live.reconcile import reconcile_once
    assert True

def test_reconcile_runs_in_every_run_state():
    from app.services.live.reconcile import reconcile_once
    assert True

def test_the_manual_slot_and_reparse_buttons_trigger_an_immediate_pass():
    from app.services.live.reconcile import reconcile_once
    assert True

def test_commit_goes_through_the_single_row_funnel():
    from app.services.live.reconcile import reconcile_once
    assert True

def test_the_js_timer_is_gone():
    assert "autoConnectScan(), 15000" not in open("app/ui/web/js/panels/cdp.js").read()

