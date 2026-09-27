# Output detection stalls the Arena renderer — research and design

**Status:** implemented and verified · **Date:** 2026-09-27

## Reported failure

After Submit, the generated image was visibly on the Arena page, but the job did not advance to download. The log showed `Output check: no_new`, then CDP `Runtime.evaluate` timed out, every later check reported `page_unresponsive`, and the 120-second wait failed. The New Chat reset then failed against the same unresponsive tab. The supplied prompt was 4,052 characters.

## Findings

The output check is one large in-page JavaScript probe (`app/browser/output_probes.py`). Before it can decide whether a candidate image is ready, it:

1. queries every `div`, `span`, `p` and `pre`;
2. reads each element's `textContent` (which re-traverses that element's descendants) and measures rectangles while searching for every historical `[JOB-ID: …]`;
3. repeats a broad element scan to find the current correlation token when the first scan found only sidebar/history markers.

This makes token discovery proportional to the sum of all descendant-text lengths, rather than the DOM size. Nested conversation trees amplify the repeated traversal. The current prompt exceeds the first scan's 2,000-character limit, so a sidebar marker can make the broad fallback scan run on the next path. The scan runs synchronously on Chrome's renderer main thread. If it monopolizes that thread, an image already rendered in the DOM cannot be observed or downloaded: further `Runtime.evaluate` pings queue behind the same blocked thread. I-71 limits the cost of repeated pings but does not remove the work that blocks the first check.

The download itself already has a Python URL-fetch fallback, but it cannot help until a renderer-side probe supplies the image URL. Existing output tests establish the correlation and user-reference safety contracts; they do not bound the job-marker scan's work.

## Design

Keep the existing strict correlation and candidate/readiness decisions, but make marker discovery a single linear text-node walk:

* Use one `TreeWalker(SHOW_TEXT)` pass scoped to the conversation `ol` when present (otherwise the document body) to find `[JOB-ID: …]` markers and the current correlation token, including when it appears inside a prompt longer than 2,000 characters.
* Derive each candidate marker's nearby container by walking its ancestors (bounded to the existing 12-level limit); do not call `textContent` on each ancestor. The text node itself proves the marker is present in those ancestors.
* Keep duplicate IDs within the conversation scope long enough to prefer the active user-message occurrence; when an `ol` exists, sidebar/history labels are excluded from the walk. Preserve downstream ordering, image association, spinner, and two-step correlation checks.
* Remove the broad `querySelectorAll('div, span, p, pre')` fallback. Keep the focused image/spinner selectors, readiness-first selection, user-message exclusion, and existing diagnostic result shapes.

This is a targeted complexity repair rather than a timeout increase or an unverified fallback: no image is accepted without the existing job/candidate checks, and no behavior is added that bypasses CAPTCHA or site policy.

## Verification / acceptance

1. Execute the real generated output-check payload against a page with sidebar JOB markers, a 4,052+ character prompt, nested conversation markup, and a ready generated image. It must return the correct image and associate it with the current conversation's marker.
2. Assert the probe no longer requests the broad all-element selector, while markers in long text nodes remain discoverable.
3. Keep the existing tests for strict mismatch rejection, spinner wait, reference-image exclusion, lazy/broken candidates, and result-shape contracts green.
4. Run focused Python/JS tests, then RULE 16 changed-file quality gate and full fast/JS suites available in the environment. Review edited-function complexity and context-file sizes before completion.

## Implementation and verification result

* Implemented: the output-check marker walk is scoped to the conversation list, reads text nodes once, retains long prompt tokens, and selects the active prompt occurrence for the current job. The broad element scans are removed; output association/readiness/download contracts are unchanged.
* Focused Python output/recovery tests: **104 passed**. Full fast Python lane: **2,776 passed, 13 skipped**. Full JS lane: **475 passed, 4 skipped** (479 tests).
* `tools/verify_quality.py --changed-files app/browser/output_probes.py --allow-legacy`: **0 fails**; the only warning is missing generated `coverage.json`. `radon`: `build_check_js` CC 2 and `build_baseline_js` CC 1. `py_compile` and `git diff --check` pass.
* The default `--changed` gate could not find a shared `origin/main` base and fell back to checking all app files; it reported four unrelated legacy ratchet deltas in `app/main.py`, `app/services/live/bus.py`, `app/utils/hashing.py`, and `app/utils/win_find.py`. The touched-file gate above passes. No real Chrome session was available in this checkout, so renderer behavior is validated with the real generated payload against the saved-page jsdom harness, not a live Arena run.

## Non-goals

No change to the 120-second generation deadline, image URL download policy, correlation token format, reset/cooldown behavior, or recovery semantics for genuine network/CDP failures.
