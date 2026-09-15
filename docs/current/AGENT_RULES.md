# Agent Rules — Arena Image Processor (New App)

What an AI agent (or a human) **MUST** follow when adding or changing code here.
This file is the **detailed code-quality rules** for the new app, adapted from Old App's `docs/current/AGENT_RULES.md` (which had 19 rules) but adjusted to Arena's image-to-image workflow.

* Current behaviour, invariants and flows: [`SYSTEM_OF_RECORD.md`](SYSTEM_OF_RECORD.md)
* Living selector reference: [`DOM_SELECTORS.md`](DOM_SELECTORS.md)
* Doc map (what is current vs historical): [`../README.md`](../README.md) and `docs/` index
* Rule numbers are **stable** — production code cites them (`RULE 1` … `RULE 19`). Never renumber; append instead.

| # | Rule | Kind | Adapted from Old App |
|---|---|---|---|
| 1 | All find-and-click goes through the shared visual runner | behaviour | Old RULE 1 — visual confirmation RED/ORANGE/GREEN |
| 2 | Report every step through `engine.report()` / `bridge._log()` | behaviour | Old RULE 2 — log console + JSONL trace |
| 3 | Block settings are plain instance attributes | behaviour | Old RULE 3 — action blocks round-trip |
| 4 | Distinguish "empty" from "broken" | behaviour | Old RULE 4 — queue vs error |
| 5 | Long-running work reports progress incrementally | behaviour | Old RULE 5 — on_collect callback |
| 6 | Filtered-out entities must not persist | data | Old RULE 6 — ignore *_AI |
| 7 | Stop must be honoured by every long-running loop | behaviour | Old RULE 7 — stop/pause gates |
| 8 | Tests execute the real thing | testing | Old RULE 8 — real DOM, fake CDP |
| 9 | A guard that skips work must not stall the stack | behaviour | Old RULE 9 — action blocks skip |
| 10 | One control per decision | behaviour | Old RULE 10 — settings |
| 11 | "Don't add" must still mean "do the work" | behaviour | Old RULE 11 — scan-only vs queue |
| 12 | One global history for every editable surface | data | Old RULE 12 — undo timeline |
| 13 | Never persist state you cannot read back | data | Old RULE 13 — grid layout validation |
| 14 | The output is not the queue | data | Old RULE 14 — archive vs queue adapted |
| 15 | Nothing is saved without the two-step verification gate | data | Old RULE 15 — baseline + token + atomic save |
| 16 | Code-quality gates on every production change | quality | Old RULE 16 — size/complexity/coverage |
| 17 | One current doc, dated archive | docs | Old RULE 17 |
| 18 | Ideal sizes: write for the reader's context budget | quality | Old RULE 18 |
| 19 | Fix complexity before size (nesting → CC → cognitive → size) | quality | Old RULE 19 |
| 20 | Never bypass CAPTCHA, respect ToS, user-authorized URLs only | compliance | New for Arena |
| 21 | Selector priority: semantic > structural > class fragment | quality | New for Arena |
| 22 | Correlation token [JOB-ID] must be unique and verified | data | New for Arena |
| 23 | Atomic save *_AI.ext beside source, never overwrite without flag | data | New for Arena |

---

## RULE 1 — All find-and-click goes through the shared visual runner

> **Any action block that locates a DOM element and clicks it MUST call `app.browser.dom_highlight.build_highlight_js()` / `build_clear_js()` and `CDPArenaController.highlight_selector()` or `backend.visual_click` equivalent. Never call `element.click()` from a hand-rolled probe inside a block without visual confirmation.**

The runner is the single place that implements the mandatory two-phase, visually confirmed click:

| Phase | What is logged | What is drawn |
|---|---|---|
| **FIND** | success/failure, selector tried, visibility, count | thin **RED** outline `#ff2d2d` on detected element, then pause `confirm_pause_ms` |
| **CLICK** | whether target is clickable, then click result | thin **ORANGE** outline `#ff9500` on click-target area, then click |
| **COLLECT** | when output image detected | **GREEN** outline `#00c853` on new output |

### Why centralised (same as Old App)

* every block behaves identically, log predictable;
* element found in phase 1 stashed and reused in phase 2, click never lands on different node than user saw highlighted;
* overlays `pointer-events:none` with transparent background, never intercept click or shift layout;
* fixing UX happens in exactly one file: `app/browser/dom_highlight.py` and `app/browser/cdp_arena.py`.

### Required params on every such block (adapted)

```python
highlight_enabled: bool = True
highlight_duration_ms: int = 2000  # configurable, saved in preset JSON
color: str = "#FF0000"  # RED for find, ORANGE for click, GREEN for collect
selector: str = ""  # primary selector, with fallbacks in site_adapter.py
pre_delay_ms: int = 200  # pause before FIND
confirm_pause_ms: int = 700  # pause after FIND so user can look
```

Blocks currently compliant: `HIGHLIGHT_ATTACH`, `ATTACH_IMAGE`, `HIGHLIGHT_PROMPT`, `INSERT_PROMPT`, `HIGHLIGHT_SUBMIT`, `SUBMIT`, `WAIT_OUTPUT`.

### Overlay colour convention (same as Old App, adapted)

| Colour | Constant | Meaning |
|---|---|---|
| **RED** `#ff2d2d` | `COLOR_FIND` | element detected during FIND |
| **ORANGE** `#ff9500` | `COLOR_CLICK` | area about to be clicked |
| **GREEN** `#00c853` | `COLOR_COLLECT` | new output image detected |
| **BLUE** `#00AAFF` | prompt textarea |
| **YELLOW** `#FFAA00` | submit button |

For pure visual confirmation with **no** click, use `build_highlight_js()`. It never touches click stash and never calls `scrollIntoView` — moving viewport during baseline capture would corrupt output detection.

---

## RULE 2 — Report every step through engine.report() / bridge._log()

Blocks receive the running engine (`CDPArenaController` + `Bridge._log`). Use `engine.report(message, level)` or `self._log(msg, level)` (`info`/`success`/`warn`/`error`) for each meaningful step. These reach UI log console **and** file log **and** job trace. A block that fails silently is a bug — always say why, include selector tried, rect, and correlation ID.

Old App: `engine.report()` streamed to UI log console and JSONL run trace. New App: `Bridge._log()` → `arena_log` signal → `LogConsole.log()`, plus `job_action_status` signal with rect.

---

## RULE 3 — Block settings are plain instance attributes

`ActionBlock.to_dict()` serialises every public instance attribute, which makes settings round-trip through presets. So:

* store configuration as `self.foo = ...` in `__init__`, with default;
* accept unknown keys via `**extra` so older presets keep loading;
* describe each field in `config_schema()` or `BLOCK_DEFINITIONS` so UI can render it;
* mirror defaults/labels in `app/ui/web/js/panels/action-blocks.js` (`getDefaultBlocks()`).

Never read settings out of global config from inside a block when they belong to that block — block owns its own parameters. Same as Old App RULE 3.

Example from `app/core/action_blocks.py`:

```python
@dataclass
class ActionBlock:
    id: str
    block_id: str  # OBSERVE_BASELINE, ATTACH_IMAGE, etc.
    name: str
    enabled: bool = True
    selector: str = ""
    color: str = "#FF0000"
    timeout_ms: int = 30000
    required: bool = False
    custom_name: str = ""
    pre_delay_ms: int = 200
    highlight_duration_ms: int = 2000
```

---

## RULE 4 — Distinguish "empty" from "broken"

An empty result must be reported distinctly from failure. Engine follows this:

* empty image queue vs. scan found 0 vs. folder not set vs. CDP not connected
* empty URL list vs. URL unreachable vs. auth required
* baseline 0 outputs vs. baseline capture failed

Never let no-op path end with success-looking log. Same as Old App RULE 4.

---

## RULE 5 — Long-running work reports progress incrementally

Anything that loops over many items (folder scan, batch runner, tab fetch) must surface each result **as it happens**, not batch at end. Batch runner emits `job_started` → `job_action_status` per block → `job_finished` → `progress_updated`, so UI updates live.

Two matching requirements (same as Old App):

* callback into UI must never kill pipeline — wrap in try/except and log warning;
* support both sync and async callbacks (`asyncio.iscoroutine`).

Old App: Scroll & Parse took `on_collect` callback wired to `person_collected()` → `person_found` signal → `users_updated`. New App: `CDPArenaController` reports via `log_callback` → `Bridge._log()` → `arena_log`.

---

## RULE 6 — Filtered-out entities must not persist

When scanner filters items (ignore `*_AI`, supported types), only items that **pass** may be written to queue. Never persist "everything we saw" for bookkeeping. A re-scan under stricter filter must make list shrink, never grow.

Invariant: *after any scan, `state.images` contains only entities that pass currently configured filter (supported types, ignore AI suffix).*

Same as Old App RULE 6, adapted from people filtering to image filtering.

---

## RULE 7 — Stop must be honoured by every long-running loop

Stop flag checked only in outermost loop is not stop. Long-running phases must accept `should_stop` predicate and check it:

* at top of each iteration, **and**
* inside any inner wait/poll loop (e.g., `wait_for_new_output` polling, CAPTCHA wait), so stop during multi-second timeout is prompt.

Distinguish "stopped" from "failed" in return value — reusing `None` for both produced bogus errors. `asyncio.CancelledError` always propagates untouched; only `RunStopped` maps to `"stopped"`.

Same as Old App RULE 7.

---

## RULE 8 — Tests execute the real thing

JavaScript probes tested by running them through `tests/js_harness.js` against DOM stub, not asserting on generated strings. Pipelines tested against fake CDP client that behaves like real page, including baseline capture and output detection. If test would pass with feature deleted, it is not a test.

Same as Old App RULE 8.

For Arena, we have `tests/` with scanner, naming, persistence, correlation, state transitions, verification, selector tests — all must run real logic.

---

## RULE 9 — A guard that skips work must not stall the stack

A setting that makes a phase decline to do its work is only allowed to skip *that work*, never phases downstream. Example: `HIGHLIGHT_ATTACH` disabled skips only highlighting, not `ATTACH_IMAGE`. `CHECK_SECURITY` disabled skips CAPTCHA check, but does not skip attach.

Two corollaries (same as Old App):

* **Fail open.** If security check fails to detect dialog (probe error), fail open to normal flow, so read problem never silently stops block.
* **Skipping is success.** Skipped block returns `success` with message "Skipped (disabled)", not failure — guard firing is correct behaviour.

---

## RULE 10 — One control per decision

A setting must not duplicate decision another setting already makes. Example: Don't have both `supported_types` in folder picker and `file_types` in settings that both filter same list invisibly. One source of truth.

When setting retired, constructor must accept and discard its key (`extra.pop(dead, None)`), because `to_dict()` re-emits and would otherwise write dead key back into presets forever.

Same as Old App RULE 10.

---

## RULE 11 — "Don't add" must still mean "do the work"

Old App: scroll-only mode scrolled hunting for someone already in list who is not yet messaged, and added nobody, but still counted newly rendered people for stall detection.

New App adaptation:

* **Scan-only mode** (folder scan without auto-select) scans and reports, but adds nothing to selected set — still counts for stats.
* **Deselect All** does not delete images from queue, only clears selected flag — work of discovering files is still done.

A mode that declines to add must still do its observation work.

---

## RULE 12 — One global history for every editable surface

Every editable surface — action blocks stack, grid layout, URL list, folder, image queue selection, prompt, settings, window states, arena presets — records onto **ONE** chronological undo timeline, so one `Ctrl+Z` always reverses most recent edit regardless of which panel produced it. No separate undo/redo controls.

* **Kinds:** `grid`, `urls`, `folder`, `queue`, `prompt`, `settings`, `window_states`, `arena`, `action_blocks`. Each entry `{kind, value, seq}`; `UndoService` validates per kind.
* **Where it lives:** app-level entries persist in `config/session.json` `undo_history` and `config/undo.json`; 100 entries cap, truncate-on-branch.
* **Automatic engine side-effects** (run marking images completed, progress recalc) are NOT recorded — only explicit user actions.

Same as Old App RULE 12, adapted kinds.

---

## RULE 13 — Never persist state you cannot read back

Grid layout validated (version, node shape, sizes summing to 100, exact window set) and **REJECTED** when invalid, leaving previously stored layout untouched — `LayoutService.canonical_grid_payload()` decides, `Bridge.save_grid_layout()` refuses. Storing unreadable layout would brick UI on every start — bad payload must cost one failed save, not whole layout.

Corollary for "reset to default": restoring default tree is not enough when hidden panel releases grid space. `resetToDefault()` also un-hides every window, and any window that can be shown while empty needs empty state (RULE 4) so it does not look broken.

Same as Old App RULE 13.

For Arena, also applies to `AppState` persistence: `load_state()` must handle corrupt JSON gracefully, never crash, and `save_state()` uses atomic write (temp file + replace).

---

## RULE 14 — The output is not the queue

Adapted from Old App RULE 14 "archive is not queue".

Since new app has no DB, both live in same JSON file but different concerns:

* **`images` queue** answers "which images should I process under current filter" and may shrink at any time — scans purge, selections toggle, reset clears status.
* **`output files` (*_AI.ext)** answer "what was actually generated" and are **on filesystem**, not in JSON. No filter, purge, undo or queue edit may delete output files. Deleting an image from queue does NOT delete its *_AI file.
* Only explicit user file deletion in OS deletes output, never automatic.

---

## RULE 15 — Nothing is saved without the two-step verification gate

Adapted from Old App RULE 15 "nothing is archived without two-step gate".

An image may be saved beside source **only** when all checks pass:

1. Baseline captured before generation, new output detected not in baseline (genuinely new, not old image)
2. Correlation token `[JOB-ID: <unique>]` present in prompt and verified in page (or at least prompt read-back matches)
3. Downloaded bytes validated as valid image (not HTML, width>0, height>0)
4. Atomic write: temp file + replace, never partial file

The verification lives in one place: `CDPArenaController.wait_for_new_output()` + `download_image()` + `PIL.Image.open()` validation, and fails **closed**: if any check fails, nothing is saved, job marked failed, error recorded.

Media follows same ownership: bytes saved beside source that was processed, never in global pile, and UI shows output path rather than remote URL.

---

## RULE 16 — Code-quality gates on every production change

Mandatory for every change to production Python. Numbers, scopes, tools and exceptions frozen here. Origin: Old App `docs/current/AGENT_RULES.md` §16 and `CODE_QUALITY_GATES_DESIGN`.

Executable form: `tests/test_rule16_new_code.py` (run it; do not re-derive). Baseline snapshot: `reports/CODE_QUALITY_METRICS_2026-09-10.md` if exists.

### 16.0 When this applies

| Situation | Gate |
|---|---|
| New production function/class in `core/`, `browser/`, `ui/`, `persistence/`, `services/`, `app/`, `main.py` | **Hard fail** if any threshold in §16.1–§16.2 exceeded |
| Edit of existing function that already violates threshold (legacy) | Must not **worsen** metric; prefer reduce (§16.5) |
| Tests, `tools/`, docs, HTML dumps, generated caches | **Out of scope** for size/CC (tests still must exist for new production paths) |
| Embedded JavaScript inside Python string builders (`dom_highlight`, `cdp_arena`) | Length limit does **not** force split of JS payload. CC of Python wrapper still applies |
| Compatibility facades / `__init__` that only re-export | Method-count / class-LOC may be waived with override comment (§16.4) |

If change would pass with feature deleted, it is not test (RULE 8). Coverage that only executes lines without asserting behavior does **not** satisfy §16.3.

### 16.1 Size and volume — hard limits on **new** code

| Check | Prefer | **Fail if** | How counted |
|---|---:|---:|---|
| Function / method physical LOC | ≤ 20 | **> 30** | Inclusive AST source span: first `def`/`async def` line through last line of body. Includes blanks and docstring. Excludes decorator lines. Nested functions counted separately. Lambdas ignored. |
| Class physical LOC | ≤ 120 | **> 150** | Inclusive AST span of `class` body. Nested classes counted separately. |
| Parameters per function | ≤ 3 | **> 4** | Exclude leading `self`/`cls`. Count keyword-only args. Count `*args` and `**kwargs` as one each. |
| Direct methods per class | ≤ 10 | **> 15** | Methods defined on class body only (not inherited). Include `__init__`, properties' fget/fset if defined as `def` on class. |

These are **fail** lines. Sizes to *aim at* are RULE 18.

**16.1.1 When approaching limit**

1. **Do not** split function into `foo_part1`/`foo_part2` solely to game LOC. Extraction allowed only when helper's name states real responsibility (`_capture_baseline`, `_attach_and_verify`).
2. **Do not** hide parameters behind catch-all `**kwargs` to dodge param cap. Block settings stay as explicit instance attributes (RULE 3). Wide `__init__` on action blocks is **legacy**; new blocks take ≤ 4 constructor params besides `self`.
3. New classes that would exceed 15 methods must be designed as collaborating types *before* writing 16th method.

**16.1.5 Embedded-JS exception (explicit)**

`app/browser/dom_highlight.py` `build_highlight_js` may be >30 LOC because it embeds JS probe. **Do not refactor that builder to meet 30 LOC.** New probe builders may exceed 30 LOC **only** when excess is single JS/HTML string literal. Python control flow around literal must still be CC ≤10 and nesting ≤4.

### 16.2 Complexity — block merge if exceeded on new code

| Check | Tool | **Fail if** | Counting rules (frozen) |
|---|---|---:|---|
| Cyclomatic complexity | `radon cc -s` | **> 10** | Radon: base 1; +1 per `if`/`elif`/`except`/`for`/`while`/`assert`/`with` (if extra); +1 per `and`/`or`; +1 per comprehension `if`; +1 per ternary. `try` itself and `in` tests cost 0. |
| Cognitive complexity | `cognitive-complexity` 1.3.x | **> 15** | Library default. Nested functions scored separately. |
| Nesting depth | custom AST walker | **> 4** | Maximum ancestry of `if`/loops/`with`/`try`/`match`. `elif` is nested AST `if`. Sibling blocks do not add. |

**Anti-gaming (non-negotiable).** Forbidden: one-line helpers that only re-host original body; dispatch tables of lambdas whose only purpose is to hide `if` count; inferring control flow from flag to drop real exception branch. Allowed: deleting dead branches; extracting helper that already exists as named concept in domain; replacing `except Exception` + `isinstance` scaffolding with narrow `except`.

Floor example: four independent binary outcomes cannot cost less than CC 5 (1 base + 4 branches). Do not lower CC by deleting real decision.

### 16.3 Test coverage — new code must be tested

| Metric | Target | Tool | Fail rule |
|---|---:|---|---|
| Line coverage | **≥ 80%** overall; **never decrease** vs baseline | `pytest --cov --branch` with `--source=app` | fail if overall line or branch % drops below stored baseline |
| Branch coverage | **≥ 75%** overall | same | same |
| Uncovered **new** functions | **0** without override | coverage JSON diff vs base SHA | every new function with 0 hits listed in review |
| Test-to-code ratio | ~1:1 nonblank non-comment Python LOC | audit script | warn, do not fail |

Branch 75% read from `coverage.json` (`totals.covered_branches / totals.num_branches`), not from `--cov-fail-under` (line-only).

**What "tested" means.** For every new production function: at least one test that would **fail if function deleted** or boolean inverted; empty vs broken distinguished (RULE 4); stop/cancel paths honoured if it loops (RULE 7); JS probes go through `tests/js_harness.js` (RULE 8).

**Coverage command (copy-paste):**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m coverage run --branch --source=app -m pytest tests -q
COVERAGE_FILE=.coverage .venv/bin/python -m coverage json -o coverage.json
```

### 16.4 Smells and override mechanism

| Smell | Detector | Action |
|---|---|---|
| Duplicated logic | pylint `R0801` / exact-AST clones ≥6 lines | Extract named helper **in owning layer**; never copy-paste probes, report strings or SQL |
| Dead code | `vulture --min-confidence 90` | Remove unused imports/vars. Unused args on protocol/callback signatures may stay |
| Long method / god class | §16.1 | Split by responsibility, not line quota |
| Feature envy | review | Move method; no automated gate yet |

Zero **new** smells on diff. Pre-existing smells are inventory, not licence to add more.

Override comment format:

```python
def wide_legacy_adapter(self, a, b, c, d, e):  # quality-override: params=5 reason=CDP wire matches Chrome DevTools payload
    ...
```

Strict format: `quality-override: <metric>=<value> reason=<one line, ≥20 chars>` with `<metric>` ∈ `loc, class-loc, params, methods, cc, cognitive, nesting, coverage, vulture, dup`. Reason must name **constraint** (wire format, generated JS, Qt slot signature), not "faster to ship". One override per metric per symbol; never override to skip test.

### 16.5 Legacy code (already over line)

You **must** not increase CC, cognitive, nesting, LOC, params or method count of legacy offender, and must not add methods to class already over 15 without netting down. Touch hotspot only with tests that lock current behaviour first.

For Arena, hotspots: `Bridge` (large QObject), `CDPArenaController`, `CDPClient` — do not grow, extract on touch.

### 16.6 Agent workflow (implementation process)

1. **Understand problem fully.** Read `SYSTEM_OF_RECORD.md` and rules 1–15, plus size ideals in RULE 18. Then matching archived design — `docs/README.md` indexes.
2. **Research and design structure in doc first** when change moves complexity across files (new class, extraction from hotspot). Record current radon numbers, target numbers, and dishonest reductions rejected. Put in `docs/archive/<YYYY-MM-DD>-<topic>/` (RULE 17).
3. **Tests first** for behaviour changes (RULE 8). Refactors claiming behaviour-preservation run existing suite as equivalence gate.
4. **Measure**: `radon cc -s path/to/file.py`. Any new function at `C` or worse (CC≥11) → stop and redesign, in order RULE 19 prescribes.
5. **Update current docs** in same change (RULE 17).

### 16.7 Acceptance checklist (self-review before claiming done)

```text
[ ] No new function >30 physical LOC (except documented JS-literal builders)
[ ] No new class >150 LOC or >15 methods
[ ] No new function with >4 params (excluding self/cls)
[ ] radon CC ≤10, cognitive ≤15, nesting ≤4 on every new/edited function
[ ] overall line coverage ≥80% and not below baseline; branch ≥75%
[ ] every new function has test that would fail if deleted
[ ] no new vulture unused-import findings; no new duplication groups
[ ] quality-override comments used only with real constraint
[ ] did not game metrics with dummy helpers
[ ] new code aims at RULE 18 ideals (function 4-20 lines, file 150-300, module 5-15 files); every deviation carries ideal-size: reason
[ ] any complexity/size remediation followed RULE 19 order (nesting -> cyclomatic -> cognitive -> size last)
[ ] SYSTEM_OF_RECORD.md + docs/README.md updated if behaviour/docs moved
```

---

## RULE 17 — One current doc, dated archive

Documentation follows same rule as code: **one source of truth, no rot.**

* `docs/current/` holds only what is true today — `SYSTEM_OF_RECORD.md` (spec, invariants, flows), `AGENT_RULES.md` (rules), `DOM_SELECTORS.md` (living selector reference). If not true today it does not belong here.
* Every design/plan/root-cause doc goes straight into `docs/archive/<YYYY-MM-DD>-<topic>/`, dated by day written. Archived docs never edited to "catch up" — they are record of what was believed then.
* **Do not add new top-level doc for feature.** Write design into archive, then update rows of `SYSTEM_OF_RECORD.md` it affects (behaviour table, invariants, flows, "history of X" links) and map in `docs/README.md`.
* Reference doc by its **full repo-relative path on one line** so it stays greppable.
* Doc that no longer describes reality gets either (a) content folded into `SYSTEM_OF_RECORD.md`, or (b) one-line pointer to what replaced it — never deletion, because reasoning is value.

Same as Old App RULE 17.

---

## RULE 18 — Ideal sizes: write for reader's context budget

> **These are preferences, not fail lines.** Only things that *fail* change are RULE 16 thresholds. This rule states what to **aim at by default**, and requires stated reason when you aim elsewhere.

| Element | Ideal size | Sweet spot |
|---|---|---:|
| **Function / method** | **4–20 physical lines** | ~8–12 lines |
| **Single file** | **150–300 lines** | ~200 lines |
| **Module** (one directory) | **5–15 files**, cohesive | 7–10 files |
| **Context file** (`docs/current/*`) | **60–200 lines** | ~120 lines |

**Preferences only — nothing in this table fails build.** Enforced thresholds are RULE 16's.

### 18.1 Functions — 4–20 lines

* Under 4 fine when name earns place: domain concept (`check_stopped`), required hook, predicate used in several places. Not fine when body is one call re-hosted under meaningless name — metric-gaming pattern §16.2 forbids.
* 4–20 band where reader holds whole body in mind at once, including every `except` branch. Most new code should land here.
* Over 20 usually means second responsibility hiding inside first. How to get back down — and in which order — is RULE 19.

### 18.2 Files — 150–300 lines

* One **primary responsibility** per file, and module docstring that says what file owns *and* which direction its imports go ("no Qt in `core/`", "no `browser.*` import from `ui/`").
* Under 150 normal and good for leaves, shims, pure-data modules. Merge two small files only when they always change together.
* Over 300 — stop and look for second responsibility before adding next feature, then split by single responsibility.

### 18.3 Modules — 5–15 cohesive files

* Cohesion test: files in one directory should change together and share vocabulary. If two files in same directory never change in same commit, they belong in different directories.
* Past ~15 files, split — either by sub-package or prefix family.

### 18.4 Context files — 60–200 lines

A **context file** is any doc reader expected to load *whole* before working: files in `docs/current/`, root `CLAUDE.md`/`AGENTS.md`, package README. Test is not "is it complete?" but **"can agent read all of it and still have room for code it must change?"**

* That single test is why `docs/current/` holds three files and everything else is archived: pointer outward beats wall of prose.
* Over 200 lines, move detail into `docs/archive/<date>-<topic>/` and leave link here.

### 18.5 When you exceed ideal

Allowed, with reason next reader can see:

```python
# ideal-size: 78 lines reason=single JS payload for the probe; splitting string literal would break in-page agent contract
```

* Reason must name **constraint** (wire format, one JS/HTML literal, Qt slot signature, frozen contract), not convenience.
* Never satisfy ideal by gaming it (§16.2): no `foo_part1`/`foo_part2`, no lambdas that only hide `if` count.

---

## RULE 19 — Fix complexity before size (remediation order)

> When code over line, fix in this order: **nesting → cyclomatic → cognitive → size.** Size is symptom; other three are cause. Splitting first turns one complicated function into several files that share one complicated decision — greener metrics, worse code (§16.2 gaming).

**Step 1 — nesting (>4 → flatten).** Guard clauses: refuse early and return so happy path never indented. Invert conditions (`if not ok: return`, not `if ok:` around body). Extract innermost deep block first.

**Step 2 — cyclomatic (>10 → simplify).** Dispatch instead of branching on type; strategies for interchangeable behaviour; lookup tables instead of if/elif chains — tables are data, not branches. Never delete real decision to reach number.

**Step 3 — cognitive (>15 → clarify).** Name compound: called predicate reads, `if a and not b and c or d` does not. Obvious beats clever.

**Step 4 — size, last; usually already fixed.** If not, extract **by concept** with name that already exists in domain — never `foo_part1`. Class over ideal gets single-responsibility split; too many params get parameter object.

Steps 1–3 quote **fail lines** (RULE 16: nesting 4, CC 10, cognitive 15). Step 4 quotes **ideals** (RULE 18 / §16.1 "prefer": 20/120/3) — not fail lines, which are 30/150/4. Nothing in step 4 rejects change on its own. Order works because each earlier step **deletes decisions**, and deleting decisions moves every later metric.

**Verify after every step.** `radon cc -s <file>`, then gate: `pytest tests/test_rule16_new_code.py`. Step not finished because number moved — finished when existing suite still green, because steps 1–3 must be behaviour-preserving.

---

## RULE 20 — Never bypass CAPTCHA, respect ToS, user-authorized URLs only

* Do not bypass/defeat/outsource/solve CAPTCHA; pause with `USER_ACTION_REQUIRED`, let user solve manually.
* Respect target site terms, permissions, rate limits; only use user-authorized URLs.
* Credentials out of logs, session in browser profile dir, upload only to user-configured URLs.
* Same as old app's security rules, adapted to Arena.

---

## RULE 21 — Selector priority: semantic > structural > class fragment

Prefer semantic selectors: role, aria-label, name, type, visible text, placeholder. Do not depend on generated IDs (`radix-*`), blob URLs, session URLs, long utility classes (Tailwind). Selector priority:

1. **Semantic**: `[aria-label="Send message"]`, `textarea[name="message"]`, `button[aria-label="Add files"]`, role queries
2. **Structural**: `form:has(textarea[name="message"])`, `div.flex:has(input[type="file"])`, parent/child relationships
3. **Class fragment** (last resort): `div.no-scrollbar`, `img.aspect-square` — use only with verification and fallbacks

All selectors centralized in `app/browser/site_adapter.py` with primary + fallbacks. See `DOM_SELECTORS.md`.

Same principle as Old App's selector strategy.

---

## RULE 22 — Correlation token [JOB-ID] must be unique and verified

* Every job gets unique correlation ID via `generate_correlation_id()`
* Final prompt built as `[JOB-ID: <unique>]\n<user prompt>` via `build_final_prompt()`
* Prompt insertion verified by reading back textarea value — must match exactly
* Token used to verify output belongs to current job (not older request) — search for token in page or use baseline comparison
* Persist token in job history for traceability

---

## RULE 23 — Atomic save *_AI.ext beside source, never overwrite without flag

* Save new image beside source with `_AI` suffix: `get_output_path()` + `atomic_write_bytes()` (temp file + replace)
* Preserve format if configured, otherwise use downloaded ext
* Unique suffix if exists: `{base}_AI_{n}{ext}` unless overwrite flag true
* Validate before save: not HTML, valid image dimensions >0, bytes >0
* Never leave partial file — atomic write guarantees
* Persist progress so work can resume after interruption

Same as Old App's media handling but adapted to image files.
