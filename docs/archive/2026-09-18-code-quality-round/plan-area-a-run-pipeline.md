# Area A — Run pipeline unification + Bridge decomposition

**Problem fixed:** P1 (Critical), P2 (Critical) — see [`problem-priority.md`](problem-priority.md).
**Branch (recommended):** `arena/quality-a-run-pipeline` (one worktree), branched after Round 0 + Area B.
**Owns (writes):** `app/ui/bridge.py`, `app/ui/panels/**` (new), `app/services/single_job_runner.py`,
`app/services/multi_page_dispatcher.py`, `app/services/batch_orchestrator.py` (new),
`app/services/run_state.py` (new), new files under `tests/characterization/**` and `tests/test_pipeline_*.py`.
**Must not touch:** `app/browser/**`, `app/core/**`, `app/services/captcha*/**`, `tests/js/**`.
**Invariants that must hold at every step:** SYSTEM_OF_RECORD I-1, I-2, I-3, I-4, I-6, I-7, I-13,
I-16, I-17, I-22, I-24…I-33 (the run pipeline is where they live).

## Why this area is first in size

| Fact | Value |
|---|---:|
| `Bridge._do_run_batch` | 1,205 LOC · radon CC **354** · cognitive **1,097** · nesting **23** · 0% covered |
| Inline block loop inside it (lines 2,676–3,671) | 995 LOC re-implementing 17 block types |
| `class Bridge` | 4,991 LOC · 200 methods · 119 slots · LCOM4 **11** · MI **0.00** |
| Fails owned | **53 / 120 (44%)** |
| Uncovered lines owned | **3,500 / 6,599 (53%)** |
| Fan-out | 31 internal import edges — the only seam between UI and the rest |

The same job lifecycle already exists in a testable service: `single_job_runner.py`
dispatches 12 block types through `_handler_map()` (covered at 33.9%, used by
`multi_page_dispatcher.py` on the pooled path). The bridge loop is a second
implementation with 17 inline branches. Every block-level behaviour fix in the
last five rounds had to be applied twice; that is the duplicated-work and
"works on one path only" mechanism behind the captcha rounds.

## Target architecture

```
app/ui/bridge.py                    ≤300 lines  — QObject facade: signals + 119 @Slot
                                                   methods that are 1–5 line delegations
app/ui/panels/                      ~12 files, ≤300 lines each, ≤10 methods each
  layout_panel.py  presets_panel.py  urls_panel.py  queue_panel.py
  prompt_panel.py  settings_panel.py blocks_panel.py run_panel.py
  watcher_panel.py captcha_panel.py  cdp_pool_panel.py  misc_panel.py
  (mixins over a shared `BridgeContext`; no cross-mixin calls except through services)
app/services/                       plain Python, no Qt, testable without an app
  run_state.py           pause/cancel/stop-after flags, run state, emit-once helpers
  batch_orchestrator.py  the outer per-image loop (guards, tab resolve, cooldown wait,
                         status emit, save, tab finish) — RULE 18 file ≤300 lines
  single_job_runner.py   the shared per-block pipeline (one handler map, all block types)
  multi_page_dispatcher.py unchanged role: pooled/parallel path over PagePool
```

Enforced seams (new tests, cheap): `app/services/**` must not import PySide6
(source scan test); `app/ui/bridge.py` must stay ≤300 lines and every `@Slot`
body must be ≤10 statements; `tests/test_bridge_slots.py` already guards slot names.

## Steps — biggest problem first

### A1 — Characterization harness for the run pipeline (before any change)

Build golden traces of the current sequential path so the refactor is provably
behaviour-preserving: fake `ctrl` (CDPArenaController), fake CDP client, fake
bridge with an in-memory state, action stacks covering all 17 block types, and
a recorded trace of (block, status, log, emitted signal, file write) per image.
Scenarios: happy path, disabled block, block failure mid-stack, cancel during
pre-delay, stop-after-current, captcha pause/resume, page-error abort.

* Delivers: `tests/characterization/test_run_pipeline_golden.py` (~250 LOC), 8–12 goldens.
* Verify: goldens pass against the *unmodified* `_do_run_batch`.
* Why first: this is the only way a 1,205-line function can be cut with evidence.

### A2 — Converge the two pipelines (port the missing handlers)

Port the block types the shared runner lacks into `single_job_runner`'s handler
map: `HIGHLIGHT_ATTACH`, `HIGHLIGHT_PROMPT`, `HIGHLIGHT_SUBMIT`, `HIGHLIGHT`,
`PAUSE`, `TYPE_PROMPT`, `VERIFY_ATTACHMENT`, `VERIFY_PROMPT`. Keep the
`_handle_one_block` default ("Skipped {btype}") for unknown types.
One handler per function, ≤20 LOC each, params ≤3 (pass the `JobCtx`).

* Verify: parametrized handler tests (one per block type, RULE 8 style with fakes);
  both paths still live; goldens from A1 unchanged.
* Metric delta: `single_job_runner` coverage 33.9% → ≥80%; block-type coverage 12 → 20.

### A3 — Extract the outer loop into `batch_orchestrator.py`

Move the *outer* per-image loop out of `_do_run_batch` (guards: cancel,
stop-after, pause; tab re-resolution; cooldown wait; per-image assignment,
attempt count, status, save; primary-tab finish) into
`app/services/batch_orchestrator.py`, one responsibility per function:

| New function (target ≤20 LOC, CC ≤7) | Was inside `_do_run_batch` |
|---|---|
| `should_continue(...)` / `await_pause_or_abort(...)` | lines 2,602–2,617 (cancel/stop/pause gates) |
| `resolve_and_claim_tab(...)` | 2,620–2,634 |
| `await_cooldown_if_pooled(...)` | 2,625–2,634 |
| `mark_processing(...)` | 2,637–2,643 |
| `build_job_ids(...)` | 2,645–2,651 |
| `finish_image(...)` (success/fail/cancel branches) | 3,673–3,708 |
| `run_batch(...)` (the loop body, 4 calls) | 2,602–3,708 |

* RULE 19 order applied inside the step: flatten the guards first (early
  `continue`/`break` instead of nested `if`), then split decisions, then size.
* Verify: A1 goldens green; new unit tests per extracted function; no file >300 lines.

### A4 — Flip `start_run` onto the shared runner and delete the duplicate

`start_run` → `batch_orchestrator.run_batch()`; for each image the orchestrator
calls `single_job_runner.run_blocks_for_image(ctx)` and, when a PagePool is
active, `multi_page_dispatcher` for pooled images — one lifecycle, two
schedulers. Then delete the whole 995-line inline block loop and the
`_do_run_batch` shell.

* Verify: goldens (A1) byte-identical traces; 444+ tests green; a manual smoke
  run per `docs/manual_test_checklist.md` (single image, batch, captcha pause).
* Metric delta: 53 fails → 0 for `bridge.py`; longest function in repo 1,205 →
  124 LOC (`watcher.check_once`, Area C); `bridge.py` 5,118 → ≤1,500 lines after A3/A4.

### A5 — Split `Bridge` into facade + panel mixins

Mechanical move, no behaviour change, slot names/signals frozen:

1. Create `app/ui/panels/` and move method bodies by the LCOM4/domain clustering
   already measured (run-control 9 methods, browser/cdp 39, urls/folder/queue 33,
   layout/presets/theme 35, undo 11, settings/prompt/blocks 18, watcher 7,
   captcha 6, misc 42).
2. `Bridge` becomes `class Bridge(CorePanelMixin, LayoutPanelMixin, …)`; the
   class body keeps only `__init__`, signal declarations and the slot definitions
   that JS calls (a slot may be a 1-line delegation).
3. Every file lands ≤300 lines, ≤10 methods per mixin, ≤20 LOC per method.
   Methods over 20 LOC that are *not* in the A3/A4 path are split here or handed
   to Area C (listed explicitly in the PR: `_arena_to_js`, `_emit_job_action_status`,
   `get_image_thumbnail`, `copy_path_to_clipboard`, `_schedule_coro`, `_do_connect_tab`,
   `load_arena_preset`, `save_settings`, `set_watcher_config`, `set_cdp_config`).

* Verify: `tests/test_bridge_slots.py` (REQUIRED_SLOTS/NEVER_SLOTS) plus a new
  test asserting the signal names/arities; goldens; import-seam tests.
* Metric delta: `bridge.py` ≤300 lines, Bridge class ≤120 LOC / ≤10 methods in
  the file, `Bridge` LCOM4 11 → one component per mixin.

### A6 — Decompose `Bridge.__init__` (122 LOC / CC 14)

Introduce a `BridgeContext` dataclass (state, config, stores, services) built by
`_build_context()`; service wiring split into `_wire_*()` functions (≤15 LOC
each); `__init__` becomes ≤20 LOC. No singleton/global state — the context is
passed to mixins.

* Verify: a test that constructs `Bridge` with tmp-dir stores and asserts every
  service attribute exists (replaces today's 1% coverage of `__init__`).

### A7 — Sweep, recheck, hand over

Remove orphaned helpers, dead imports and now-unused bridge tests; run the
per-area exit criteria (README §"Shared acceptance gates"); write the
implementation note into `docs/archive/2026-09-18-code-quality-round/implementation-area-a.md`;
update `docs/current/SYSTEM_OF_RECORD.md` §7 (key modules/layers) — the pipeline
now lives in `app/services/`, the UI is a facade.

## Acceptance criteria (area exit)

* [ ] `python tools/verify_quality.py --changed` → 0 fails in every owned file
* [ ] every new/edited function ≤20 LOC, ≤3 params, CC ≤7, cognitive ≤10, nesting ≤3
* [ ] every new/edited file 150–300 lines; every class ≤120 LOC / ≤10 methods
* [ ] `_do_run_batch` no longer exists; no block type is implemented twice
* [ ] goldens + 444 tests + 99 JS tests + `bash tools/pre_push_check.sh` green
* [ ] coverage: `single_job_runner` ≥80%, `batch_orchestrator` ≥80%, `run_state` ≥80%, `app/services` ≥80%; global ≥55%
* [ ] `bridge.py` ≤300 lines, MI ≥40; repo longest function ≤130 LOC
* [ ] no `quality-override:` added in this area

## Risks and rollback

| Risk | Mitigation |
|---|---|
| Behaviour drift in the 17-block pipeline | A1 goldens + per-handler tests before deletion; delete only in A4 |
| Slot/signal breakage (QWebChannel drops unknown calls silently) | `tests/test_bridge_slots.py` + new signal-signature test + manual smoke run |
| Async semantics (background loop, `_schedule_coro`, thread-affine CDP calls) | keep the scheduling seam in exactly one module (`run_state.py`); no new threads; `asyncio` loop ownership tested |
| Mixin split turning into `foo_part1` gaming | split follows LCOM4 clusters + domain vocabulary, each mixin named after its UI window; reviewer checks RULE 16 §16.2 explicitly |
| Rollback | each step is one commit; A2/A3 are additive, A4/A5 revert cleanly to the last green commit |
