"""What a crashed Firefox job must do next — decided from evidence, never from hope.

Step 16 of the owner's brief, one row per bullet, in the order the evidence is
trusted (the files first, the journal second, the page last — so the page probe
is only asked when the page is the only witness left):

| Evidence found                                          | Action   | Why |
|---|---|---|
| the planned output file, or a fresh `_AI` sibling, exists | `done`  | the job finished; reconcile and mark completed, never resubmit |
| the staging file exists                                 | `finalize` | the bytes are here; validate, atomic-save, completed |
| journal says submitted + a correlated `src`             | `collect` | generated-but-not-downloaded: take that result, no second submit |
| journal says submitted, no `src` yet                    | `probe`  | the page is the only witness; then correlate — no resubmit |
| journal exists without a submit record                  | `fresh`  | nothing reached the page that cannot be redone from the checkpoint |
| no evidence at all                                      | `fresh`  | a first try |

`review` is returned when the page claims a submit whose result the app can no
longer identify — the owner decides, the app never guesses.

Imports: `firefox_result` (paths/validation), dataclasses/stdlib.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import firefox_result as result

DONE, FINALIZE, COLLECT, PROBE, FRESH, REVIEW = "done", "finalize", "collect", "probe", "fresh", "review"


@dataclass(frozen=True)
class Evidence:
    """Everything the decision table may look at (one param object, RULE 16)."""

    journal: dict
    final_path: Path
    source_path: Path
    settings: object


@dataclass(frozen=True)
class Recovery:
    """What to do before this job may run: the action plus its evidence."""

    action: str
    final_path: str = ""
    data: bytes = b""
    src: str = ""
    note: str = ""


def _credited_submit(journal_data: dict) -> bool:
    """True when the journal records a submit (clicks > 0) or a phase past it."""
    try:
        if int(journal_data.get("submit_clicks", 0) or 0) > 0:
            return True
    except Exception:
        pass
    return str(journal_data.get("phase", "")) in ("submitted", "correlated", "downloaded")


def _witness(ev: Evidence):
    """The output file this job already produced, or None (planned name, then siblings)."""
    final = Path(ev.final_path)
    if result.final_file_evidence(final):
        return final, "the planned output file is already on disk"
    if not ev.journal:
        return None, ""
    recent = result.find_recent_output(ev.source_path, ev.settings, str(ev.journal.get("started_at", "")))
    if recent is not None:
        return recent, "an `_AI` file from this job's own window is already on disk"
    return None, ""


def plan(ev: Evidence) -> Recovery:
    """The decision table above for one image (pure: files + journal, no page)."""
    found, note = _witness(ev)
    if found is not None:
        return Recovery(DONE, final_path=str(found), note=f"{note} — reconciling, not resubmitting")
    staged = result.staged_bytes(ev.final_path)
    if staged:
        ok, _ext, staged_note = result.validate_bytes(staged)
        if ok:
            return Recovery(FINALIZE, final_path=str(ev.final_path), data=staged,
                            note=f"finishing the staged download ({staged_note})")
        result.discard_staging(ev.final_path)
    if not ev.journal:
        return Recovery(FRESH, final_path=str(ev.final_path), note="no journal — a first try")
    if _credited_submit(ev.journal):
        src = str(ev.journal.get("src", "") or "")
        if src:
            return Recovery(COLLECT, final_path=str(ev.final_path), src=src,
                            note="this job already submitted — collecting that result, never resubmitting")
        return Recovery(PROBE, final_path=str(ev.final_path),
                        note="a submit is recorded without a result — asking the page, never resubmitting")
    return Recovery(FRESH, final_path=str(ev.final_path),
                    note="nothing was submitted — the checkpoint can be redone")


def after_probe(ev: Evidence, reply: dict, correlate) -> Recovery:
    """Fold one probe answer into the plan: a ready result is collected, doubt is `review`."""
    status, src, reason = correlate(reply.get("result") or {})
    tail = str(ev.final_path)
    if status == "ready" and src:
        return Recovery(COLLECT, final_path=tail, src=src,
                        note=f"the page still holds this job's result ({reason})")
    if status == "ambiguous":
        return Recovery(REVIEW, final_path=tail, note=f"several candidate results — a human must choose ({reason})")
    if status == "rejected":
        return Recovery(REVIEW, final_path=tail, note=f"the page's new images belong to other jobs ({reason})")
    return Recovery(REVIEW, final_path=tail,
                    note=f"the page shows no result this job can claim ({reason})")
