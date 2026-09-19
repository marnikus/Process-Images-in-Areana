# Batch B — fourth pass: the remaining deferred work (2026-09-19)

Scope: implement the deferred items left by `improvements-2026-09-19.md` — the
class-fragment selector primaries (RULE 21) and the two pre-existing `.mjs` failures.
The repo-wide coverage gap is **not** implementable in one pass (see Rejected below).

## 1. The two pre-existing `.mjs` failures — fixed

* **`test_captcha_recording.mjs` (0/1 → 4/4):** root cause was environmental, not code —
  the test imports `jsdom`, which `package.json` declares (`dependencies.jsdom ^24.0.0`)
  but `node_modules/` had never been installed in this workspace. `npm install` (lockfile
  present, `node_modules/` gitignored) → 4/4 pass. No test/code change.
* **`test_title_fit.mjs` (9/10 → 10/10):** real test bug — "fit holds across resize drags
  on the user layout" iterated `ALL_WINDOW_IDS` (15) while the user layout fixture
  (`USER_TREE`, the user's real saved 13-window grid from the bug report) predates the
  `captcha`/`captcha_records` windows; production **skips** windows absent from a saved
  tree (`sash-grid-windows.js`: panel missing → warn + continue), so the harness correctly
  renders 13. The test now asserts the invariant over the **rendered** windows with a
  guard (`ids.length >= 10`) so it cannot pass vacuously.

## 2. RULE 21 class-fragment primaries — resolved (fallback added or accepted debt)

The map is generated from the live probes and `--check` enforces exact lockstep, so every
improvement is made in the probe and regenerated. Per entry:

**Implemented (behaviour-safe, append-only):**
* `output_region` `['div.no-scrollbar']` → `['div.no-scrollbar', 'main']`:
  `JS_PAGE_READY`'s checks now carry a selector **chain** per concept (single-element
  chains for prompt/send/file — byte-identical behaviour). The output check is a
  readiness *sanity* gate; the other four checks are the real gates, and `main` exists
  exactly when the app shell has rendered, so the check only loosens in the safe
  direction. Probe verified: no test/harness depends on `JS_PAGE_READY`'s old shape
  (grep: none; the .mjs harness extracts only `JS_INSERT_PROMPT`/`JS_SEND_STATE`).

**Accepted debt — documented per entry in the generated-map report (`tierNote`),**
because a safe fallback does not exist without live-page verification (RULE 22) or would
invert semantics:
* `processing_spinner` — state detector: a false-positive fallback (bare tag /
  `[aria-busy]`) extends generation waits; `animate-spin` is a core (stable) Tailwind utility.
* `model_label` — informational only: a miss already degrades to label `unknown`
  (pre-existing miss path, no behaviour at risk).
* `model_label_scope` — `closest()` takes ONE selector list; a broad comma part matches
  the nearest `div` and inverts the scope. A JS-level fallback isn't representable in the
  map model (generic tags are scan-pattern excludes by design).
* `message_container` — the closest() list already carries the structural
  `div[data-message-id]` part; tier reflects the primary part only.
* `message_container_plain` — closest() to the job bubble; on drift detection degrades
  gracefully via the structural `output_image` chains (src patterns, `main` scope).
* `message_list_reverse` — a false positive flips the layout direction (output
  correlation inverts); generic `ol` is too broad.
* `grecaptcha_badge` — Google-owned stable class; a false negative prompts a manual solve
  (visible, recoverable); no semantic equivalent exists.
* `wait_output_default`, `attachment_preview_block` — user-configurable block defaults
  (RULE 3): a broad structural part risks a false output/verified detection.

**Report change:** `--report` now distinguishes `⚠` (unaddressed — now zero) from
`· accepted: <reason>`; the note lives in the generator's entry metadata (not in the
generated file), so the map stays data-only.

## 3. Result

* `--report`: **0 unaddressed RULE 21 flags** (was 13); `output_region` 1 → 2 selectors.
* JS suite: **11/11 files, 115 tests, 0 fails** (was 2 files failing).
* Python suite: 455 passed. pyflakes/vulture: zero. New-surface functions: 0 >20 ln.

## Rejected (with reasons)

* **Repo-wide coverage 42.7% → 80%/75% in one pass:** ~3,400 statements to cover,
  dominated by the 5,000-line `bridge.py` (UI glue) and `output_wait.py` — that is a
  multi-batch test-writing campaign, not a step; faking it with shallow tests would
  breach the anti-gaming rules. Batch B's own code is already at 78–100%.
* **Wiring `is_page_ready`'s other checks to the map** (design-B3 option, still open):
  the chain probe now exists, but switching the prompt/send/file checks from
  literals to `get_selector()`-built JS would make `JS_PAGE_READY` import-time-generated —
  a workflow change with no reader benefit (it is not harness-constrained, and the
  generated map already mirrors it). Revisit if more call sites need the map.
