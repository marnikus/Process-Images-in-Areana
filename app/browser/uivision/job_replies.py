# ideal-size: ~330 lines reason=the one reader of the five job documents — every verdict (attach/prompt/guard/submit/result/bytes) parses the same answer vocabulary and is tested as one contract (RULE 18.2)
"""The Firefox image job's savelog answers → stage verdicts.

Each stage macro echoes one `ARENA_<STAGE>=<answer>` line per probe
(`echo | ARENA_STATE=${arenaState}` renders the variable, so the savelog holds
the answer itself); the unrendered `…=${arenaState}` row is skipped because it
is not valid JSON — the same rule `identify.parse_reply` uses. The LAST answer
for a marker wins: a stage that ran twice reports what the page says now.

Verdicts live here, not in the macro: the macro records facts, this module
decides. Attachment verified only for exactly one NEW preview matching the file
name, prompt verified only by read-back equality (length + FNV-1a over UTF-16
code units — the JS `hashOf` loop mirrors it byte for byte), a result ready only
when it is new AND correlated to this job, and ambiguity is a first-class answer
(`needs_review`, RULE 4) — never rounded to success.

Imports: stdlib only.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field

STATE_MARK = "ARENA_STATE="
STATE2_MARK = "ARENA_STATE2="
ATTACH_MARK = "ARENA_ATTACH="
ATTACH_SEL_MARK = "ARENA_ATTACH_SEL="
REMOVE_SEL_MARK = "ARENA_REMOVE_SEL="
PROMPT_MARK = "ARENA_PROMPT="
GUARD_MARK = "ARENA_GUARD="
WHY_MARK = "ARENA_WHY="
SEND_SEL_MARK = "ARENA_SEND_SEL="
SUBMIT_MARK = "ARENA_SUBMIT="
RESULT_MARK = "ARENA_RESULT="
DATA_MARK = "ARENA_DATA="
NEWCHAT_SEL_MARK = "ARENA_NEWCHAT_SEL="

JSON_MARKS = (STATE_MARK, STATE2_MARK, ATTACH_MARK, PROMPT_MARK, RESULT_MARK, DATA_MARK)
TEXT_MARKS = (ATTACH_SEL_MARK, REMOVE_SEL_MARK, GUARD_MARK, WHY_MARK, SEND_SEL_MARK,
              SUBMIT_MARK, NEWCHAT_SEL_MARK)

# Result states the caller maps to image statuses (never "completed" on doubt).
READY, AMBIGUOUS, REJECTED, UNCERTAIN, MISSING = "ready", "ambiguous", "rejected", "uncertain", "missing"


def prompt_hash(text: str) -> str:
    """FNV-1a over the string's UTF-16 code units — the page's `hashOf` mirror."""
    h = 2166136261
    for byte in str(text or "").encode("utf-16-le"):
        h = ((h ^ byte) * 16777619) & 0xFFFFFFFF
    return f"{h:08x}"


def _marked_json_line(line: str, mark: str):
    """The JSON object after `mark` on one line, or None (torn/foreign lines)."""
    found = re.search(re.escape(mark) + r"(\{.*\})", line)
    if not found:
        return None
    try:
        data = json.loads(found.group(1))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def marked_json(lines, mark: str) -> dict:
    """Last rendered JSON answer for one marker ({} when the stage never ran)."""
    for line in reversed(tuple(lines or ())):
        found = _marked_json_line(str(line), mark)
        if found is not None:
            return found
    return {}


def marked_text(lines, mark: str) -> str:
    """Last rendered scalar answer for one marker ('' when absent)."""
    for line in reversed(tuple(lines or ())):
        text = str(line)
        at = text.find(mark)
        if at >= 0:
            return text[at + len(mark):].strip()
    return ""


@dataclass(frozen=True)
class StageReplies:
    """One stage run's answers — all of them optional (a stage proves a subset)."""

    state: dict = field(default_factory=dict)
    state2: dict = field(default_factory=dict)
    attach: dict = field(default_factory=dict)
    attach_sel: str = ""
    remove_sel: str = ""
    prompt: dict = field(default_factory=dict)
    guard: str = ""
    guard_why: str = ""
    send_sel: str = ""
    submit: str = ""
    result: dict = field(default_factory=dict)
    data: dict = field(default_factory=dict)
    newchat_sel: str = ""

    @property
    def answered(self) -> bool:
        """True when the run answered at least one probe (an empty log is a gap)."""
        return bool(self.state or self.state2 or self.attach or self.prompt or self.result
                    or self.data or self.guard or self.submit)


def parse(lines) -> StageReplies:
    """Every ARENA_* answer the savelog holds (last occurrence wins)."""
    return StageReplies(
        state=marked_json(lines, STATE_MARK),
        state2=marked_json(lines, STATE2_MARK),
        attach=marked_json(lines, ATTACH_MARK),
        attach_sel=marked_text(lines, ATTACH_SEL_MARK),
        remove_sel=marked_text(lines, REMOVE_SEL_MARK),
        prompt=marked_json(lines, PROMPT_MARK),
        guard=marked_text(lines, GUARD_MARK),
        guard_why=marked_text(lines, WHY_MARK),
        send_sel=marked_text(lines, SEND_SEL_MARK),
        submit=marked_text(lines, SUBMIT_MARK),
        result=marked_json(lines, RESULT_MARK),
        data=marked_json(lines, DATA_MARK),
        newchat_sel=marked_text(lines, NEWCHAT_SEL_MARK),
    )


def preview_key(entry: dict) -> str:
    """The `alt|src` identity the attach probe uses for "was it there before"."""
    return f"{entry.get('alt', '')}|{entry.get('src', '')}"


def baseline_of(replies: StageReplies) -> list:
    """The output srcs captured before the attach — the later snapshot wins."""
    for state in (replies.state2, replies.state):
        srcs = state.get("srcs")
        if srcs:
            return [str(s) for s in srcs if s]
    return []


def previews_of(replies: StageReplies) -> list:
    """The attachment tiles the later snapshot saw ([] when it answered none)."""
    for state in (replies.state2, replies.state):
        if "previews" in state:
            return list(state.get("previews") or [])
    return []


def attach_verdict(reply: dict, cleaned: bool = False) -> tuple:
    """(verified, reason) — exactly one NEW preview matching the sent file is the only pass."""
    if not reply:
        return False, "no attachment answer (the attach probe did not report)"
    if reply.get("security"):
        return False, "security dialog visible — manual action required"
    if reply.get("ok"):
        found = reply.get("found") or {}
        name = str(found.get("alt", "")) or "(unnamed blob tile)"
        tail = " (one stale tile was dropped first)" if cleaned else ""
        return True, f"preview “{name}” is new and unique{tail}"
    if reply.get("reason"):
        return False, str(reply["reason"])[:200]
    return False, "attachment not verified"


def _prompt_agrees(reply: dict, want: str, got: str) -> bool:
    """The read-back counts only when it says ok and matches the hash we know."""
    return bool(reply.get("ok")) and (not want or want == got)


def _prompt_mismatch(reply: dict, want: str, got: str) -> str:
    """Why the read-back failed: the probe's own words plus the hash comparison."""
    detail = str(reply.get("reason", "") or "read-back differs")
    if got and want and got != want:
        return f"{detail} — hash {got} != {want}"
    return detail


def prompt_verdict(reply: dict, expected_hash: str = "") -> tuple:
    """(verified, reason) — read-back equality, plus hash agreement when one is known."""
    if not reply:
        return False, "no prompt answer (the insert probe did not report)"
    want = expected_hash or str(reply.get("expected_hash", "") or "")
    got = str(reply.get("hash", "") or "")
    if _prompt_agrees(reply, want, got):
        return True, f"read-back matched ({reply.get('len', 0)} chars, hash {got or 'n/a'})"
    detail = _prompt_mismatch(reply, want, got)
    size = f"{reply.get('len', 0)}/{reply.get('expected_len', 0)} chars"
    return False, (f"prompt not verified: {detail} "
                   f"({size}, {reply.get('occurrences', 0)} occurrence(s))")


def guard_verdict(word: str, why: str = "") -> tuple:
    """(passed, reason) — the guard answers `"true"`/`"false"`; `why` explains a refusal."""
    text = (word or "").strip()
    if text == "true":
        return True, "prompt, attachment and send button re-verified"
    reason = (why or "").strip()
    if not reason or reason == "ready":
        reason = "guard did not answer (the checkpoint could not be re-read)"
    return False, reason


def submit_count(word: str) -> int:
    """How many Send clicks the submit macro recorded (0 when it refused/never ran)."""
    try:
        return max(0, int(str(word or "").strip() or 0))
    except ValueError:
        return 0


def submitted(replies: StageReplies) -> tuple:
    """(submitted, evidence) — a recorded click OR this job's token on the page."""
    clicks = submit_count(replies.submit)
    if clicks >= 1:
        return True, f"submit click recorded (x{clicks})"
    if replies.result.get("token_seen"):
        return True, "prompt token seen on the page (click acknowledgment lost)"
    return False, "no submit evidence"


def locate_verdict(word: str) -> tuple:
    """(locator, ok) — an `xpath=…` the extension can click, or '' when none was found."""
    text = (word or "").strip()
    return (text, True) if text.startswith("xpath=/") else ("", False)


def _decode_payload(raw: str, declared: int) -> tuple:
    """(ok, data, note) — strict base64, and the announced length must be the real one."""
    try:
        data = base64.b64decode(raw, validate=True)
    except Exception as exc:
        return False, b"", f"base64 payload unreadable: {exc}"
    if declared and declared != len(raw):
        return False, b"", f"base64 payload is {len(raw)} chars, the page announced {declared}"
    return True, data, ""


def bytes_from(reply: dict) -> tuple:
    """(ok, data, note) — the base64 the fetch probe answered, length-checked."""
    if not reply:
        return False, b"", "no fetch answer (the download probe did not report)"
    if not reply.get("ok"):
        return False, b"", str(reply.get("note", "") or "in-page fetch failed")[:200]
    raw = str(reply.get("b64", "") or "")
    if not raw:
        return False, b"", "the page answered no bytes"
    declared = int(str(reply.get("len", "0") or 0) or 0)
    ok, data, note = _decode_payload(raw, declared)
    if not ok:
        return ok, data, note
    return True, data, f"{len(data)} bytes via {reply.get('method', '?')}"


def _preferred(candidates) -> list:
    """Candidates after the token's container and outside it (current-job proof)."""
    return [c for c in (candidates or []) if c.get("after") and not c.get("in_user")]


def _largest(candidates: list) -> dict:
    """Biggest candidate by natural width, then rendered width (Chrome's preference)."""
    return max(candidates, key=lambda c: (int(c.get("nat", 0)), int(c.get("w", 0))))


def _pick_candidate(preferred: list) -> tuple:
    """(status, candidate, reason) for the images only this job could have produced.

    One large candidate is the answer; one small one is still the answer; anything
    more is a choice the app refuses to make silently (step 18).
    """
    large = [c for c in preferred if c.get("large")]
    if len(large) == 1:
        return READY, large[0], "one large candidate after this job's token"
    if not large and len(preferred) == 1:
        return READY, preferred[0], "one candidate after this job's token"
    return AMBIGUOUS, _largest(large or preferred), f"{len(preferred)} candidate(s) after the token"


def _correlate_candidates(candidates: list) -> tuple:
    """(status, src, reason) from the images the page reported, baseline already applied."""
    preferred = _preferred(candidates)
    if not preferred:
        return REJECTED, "", (f"{len(candidates)} new image(s) exist but none after this job's "
                              f"message — an older result was rejected")
    status, choice, reason = _pick_candidate(preferred)
    return status, str(choice.get("src", "")), reason


def _correlate_nothing(reply: dict) -> tuple:
    """(status, src, reason) when the page showed no candidate image at all."""
    if reply.get("timed_out"):
        if reply.get("token_seen"):
            return UNCERTAIN, "", "the prompt was submitted but no new image appeared in the budget"
        return MISSING, "", "no new image and this job's token is not on the page"
    if reply.get("spinning"):
        return UNCERTAIN, "", "generation still running when the wait budget ended"
    return MISSING, "", "no candidate image reported"


def correlate(reply: dict) -> tuple:
    """(status, src, reason) for one result answer — `ready` needs real evidence."""
    if not reply:
        return MISSING, "", "no result answer (the wait probe did not report)"
    if reply.get("security"):
        return UNCERTAIN, "", "security dialog visible — manual action required"
    candidates = list(reply.get("candidates") or [])
    if candidates:
        return _correlate_candidates(candidates)
    return _correlate_nothing(reply)


def clean_verdict(state: dict) -> tuple:
    """(clean, reason) for the New-chat verification — the page, not the click."""
    if not state:
        return False, "no page state answer (the reset probe did not report)"
    if state.get("clean"):
        return True, "composer empty, nothing attached, no spinner, no dialog"
    if not state.get("textarea"):
        return False, "composer not found on the new chat"
    if state.get("security"):
        return False, "security dialog visible after the reset"
    if state.get("spinning"):
        return False, "a generation is still running on the new chat"
    if state.get("previews"):
        return False, f"{len(state['previews'])} attachment(s) still on the new chat"
    length = (state.get("composer") or {}).get("len", 0)
    return False, f"composer is not empty ({length} chars) or the page is still loading"
