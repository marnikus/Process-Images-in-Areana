"""Unit tests for PagePool cooldown."""

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.browser.page_pool_cooldown import (
    set_cooldown,
    reset_cooldown,
    apply_penalty,
    is_in_cooldown,
    remaining,
    check_cooldowns,
)
from app.core.cooldown import now_epoch, epoch_to_iso
import time


def make_info(tid):
    return PageInfo(tab_id=tid, ws_url=f"ws://{tid}", title="T", url="https://arena.ai", is_connected=True)


def test_set_and_reset_cooldown():
    pool = PagePool()
    pool.add_page(make_info("a"))
    ok = pool.set_cooldown("a", 300)
    assert ok
    assert pool.is_in_cooldown("a") is True
    assert pool.get_cooldown_remaining("a") > 0
    p = pool.get_page("a")
    assert p.status == PageStatus.COOLDOWN
    # not free when in cooldown
    assert p.is_free() is False

    # reset
    ok2 = pool.reset_cooldown("a")
    assert ok2
    assert pool.is_in_cooldown("a") is False
    p2 = pool.get_page("a")
    assert p2.status == PageStatus.STEADY
    assert p2.is_free() is True


def test_apply_captcha_penalty_stacks():
    pool = PagePool()
    pool.add_page(make_info("b"))
    pool.set_cooldown("b", 60)
    first_rem = pool.get_cooldown_remaining("b")
    # apply penalty 900
    pool.apply_captcha_penalty("b", 900)
    second_rem = pool.get_cooldown_remaining("b")
    assert second_rem > first_rem
    assert second_rem >= 900
    p = pool.get_page("b")
    assert p.captcha_count == 1

    # second penalty stacks
    pool.apply_captcha_penalty("b", 900)
    third_rem = pool.get_cooldown_remaining("b")
    assert third_rem > second_rem
    assert p.captcha_count == 2


def test_check_cooldowns_moves_to_steady():
    pool = PagePool()
    pool.add_page(make_info("c"))
    # set cooldown to past
    p = pool.get_page("c")
    past = epoch_to_iso(now_epoch() - 10)
    p.cooldown_until = past
    p.status = PageStatus.COOLDOWN
    moved = pool.check_cooldowns()
    assert moved == 1
    assert p.status == PageStatus.STEADY


def test_cooldown_functions_direct():
    pool = PagePool()
    pool.add_page(make_info("d"))
    assert set_cooldown(pool, "d", 120) is True
    assert is_in_cooldown(pool, "d") is True
    assert remaining(pool, "d") > 0
    assert apply_penalty(pool, "d", 60) is True
    assert reset_cooldown(pool, "d") is True
    assert is_in_cooldown(pool, "d") is False
