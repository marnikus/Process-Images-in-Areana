"""The output wait is never silent + the user message selector (I-70, 2026-09-27).

Owner report: after Submit the log said nothing for 78 s while the finished image was on
the page — `not_complete` / `zero_width` / `hidden` / `no_new` answers were never logged, so
nobody could see what the wait was waiting on.
"""

from app.browser import output_wait as ow
from app.browser.output_wait import LoopState, WaitSpec, _remember, note_reason, wait_for_new_output_with_spec


def _state():
    return LoopState(last={"ready": False, "reason": "not_started"})


def test_a_new_answer_is_logged_once_with_the_image_tail():
    said, state = [], _state()
    for _ in range(3):
        _remember(state, {"reason": "not_complete", "src": "https://x.r2.cloudflarestorage.com/a/full.png"}, said.append)
    assert said == ["🔍 Output check: not_complete (https://x.r2.cloudflarestorage.com/a/full.png)"]
    assert state.last["reason"] == "not_complete"


def test_a_changed_answer_is_logged_again():
    said, state = [], _state()
    for reason in ("no_new", "no_new", "zero_width", "no_new"):
        _remember(state, {"reason": reason}, said.append)
    assert said == ["🔍 Output check: no_new", "🔍 Output check: zero_width", "🔍 Output check: no_new"]


def test_answers_the_spinner_and_mismatch_handlers_word_are_not_repeated():
    said = []
    for reason in ("generating_spinner_visible", "generating_no_new_yet",
                   "no_exact_below_found_wait_next", "job_id_mismatch_no_matching_image", ""):
        note_reason({"reason": reason}, said.append)
    assert said == []


async def test_the_wait_loop_tells_what_it_waits_on_then_takes_the_image(monkeypatch):
    """Integration: the real loop logs the silent answer, then completes on the ready image."""
    async def no_sleep(_s):
        return None
    monkeypatch.setattr(ow.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(ow, "_recheck_after_delay", _no_recheck)
    answers = iter([{"ready": False, "reason": "not_complete", "src": "https://r2/full.png"},
                    {"ready": False, "reason": "not_complete", "src": "https://r2/full.png"},
                    {"ready": True, "src": "https://r2/out.png"}])

    async def check():
        return next(answers)
    said = []
    result = await wait_for_new_output_with_spec(check, said.append, None, WaitSpec(timeout=60, poll_interval=0))
    assert result["ready"] is True and result["src"] == "https://r2/out.png"
    assert said.count("🔍 Output check: not_complete (https://r2/full.png)") == 1


async def _no_recheck(_check_fn, _log_cb):
    return None


def test_the_user_message_selector_comes_from_site_adapter():
    from app.browser.output_probes import build_check_js
    from app.browser.probe_selectors import user_message_selector
    from app.browser.site_adapter import get_selector
    sel = user_message_selector()
    assert sel == ", ".join(get_selector("user_message").all_selectors())
    assert "self-end" in sel
    assert f"el.closest({__import__('json').dumps(sel)})" in build_check_js([], "J", [])
