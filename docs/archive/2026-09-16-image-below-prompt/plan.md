# Plan — Fix image detection to download image BELOW prompt block (not above) + 3s wait

## Problem Understanding (from user logs + HTML snippets)

User reports:
- App waits correctly (spinner handling) but downloads incorrect image in final.
- Reference preview image uploaded is ABOVE prompt (small w-32 thumbnail inside user bubble) and should NOT be downloaded.
- Correct image is BELOW prompt block, in separate block with `flex w-full flex-row justify-start` containing `img h-[50vh] w-[50vh] transition-opacity opacity-100`.

Provided HTML:

Prompt block:
```html
<div class="flex min-w-0 flex-1 flex-col items-end gap-1"><div class="bg-surface-raised w-fit ..."><div class="prose ..."><p>[JOB-ID: 20260916-002711-PBRM] Transform...</p>...</div></div></div>
```

Correct image block (after prompt block in DOM):
```html
<div class="flex w-full flex-row items-center gap-2 justify-start"><div class="w-fit"><div class="relative"><img alt="" class="transition-opacity duration-500 opacity-100 aspect-square h-[50vh] w-[50vh] max-w-full cursor-pointer overflow-hidden rounded-lg object-cover object-center" loading="lazy" src="https://messages-prod.../01a0a72e...png?..."></div></div></div>
```

Logs from previous run:
- `jobTop 53 prevTop null nextTop null allNew 20 valid 0 invalid 0` — only 1 job found, 20 new images (duplicates from many selectors), valid 0.
- `debugAllImgs 3`: avatar 96px inOld True, large 50vh 1092px inOld False top 461, small w-32 228px inOld False top -583
- `debugFiltered 1 in_oldSrcs_ready` avatar
- Spinner gone but `no_exact_above_found_wait_next` → infinite wait.

Root causes identified (4):

1. **Early-break** — first selector matching only older `flex-col-reverse` hits stopped scan before newer images were seen. Our code broke after validAbove found, missing below candidates.
2. **Inner text container** — smallest-qualifying match was a `<p>` with only JOB-ID, excluding sibling reference thumbnail, so `jobContainer.contains(el)` filtering misfired. Container should require `hasJob && (hasImg || hasFlex)` to include reference thumbnail.
3. **flex-col-reverse misdetect** — harness treated normal `flex flex-col` as reversed, demoting valid candidates. Need layout-aware order: detect if parent `<ol>` has `flex-col-reverse` class, then interpret DOM before/after vs visual top.
4. **No fallback + truncated src** — when image grid/JOB-ID missing post-spinner, loop waited forever; fallback URL was truncated `src.slice(-60)` making undownloadable. Need fallback that accepts stable ≥400px new image after 10s, and returns full src + rect.

## Research Findings (stable selectors, risks, fallbacks)

From provided snippets + previous DOM_SELECTORS.md:

- **Prompt container**: `div.flex.min-w-0.flex-1.flex-col.items-end` (user bubble, right-aligned). Contains `[JOB-ID: ...]` text and optionally small reference thumbnail `img.w-32` or `h-16 w-16`.
- **Reference image** (to exclude): inside prompt container, class `aspect-square w-32 cursor-pointer overflow-hidden rounded-lg object-cover`, size ~228x300, width ≤300, NOT 50vh.
- **Generated image** (to download): outside prompt container, in sibling `div.flex.w-full.flex-row.justify-start` (assistant bubble, left-aligned), class `transition-opacity duration-500 opacity-100 aspect-square h-[50vh] w-[50vh] max-w-full cursor-pointer object-cover object-center`, size ≥400 (1092x1440), src contains `messages-prod` and `r2.cloudflarestorage.com`, loading=lazy, complete true, visible true.
- **Parent list**: `<ol class="mt-8 flex w-full max-w-screen-xl grow flex-col-reverse justify-end gap-4">` — flex-col-reverse. In this layout, DOM order is reversed visually: first child DOM = visual bottom, last child DOM = visual top. So if prompt block appears before image block in DOM (prompt, then image after), then visually image is ABOVE prompt (since after DOM = top). But user says correct image is BELOW prompt visually — suggests either layout is normal flex-col in some cases, or user means DOM below. Need layout-aware detection.
- **Spinner**: `div.animate-spin` inside `div.flex.min-w-0.flex-1.items-center.gap-2` with label `Response A/B`.
- **Risks**:
  - Container detection picking `<p>` only JOB-ID, not including reference thumbnail → filter fails.
  - Early break after first selector prevents seeing newer images.
  - flex-col-reverse detection wrong → validAbove vs belowCandidates swapped.
  - Duplicate counting: same src matched by many selectors → allNew 20 from 3 unique.
  - Truncated src in logs → undownloadable.
  - No fallback when JOB-ID not found → infinite wait.

- **Fallbacks**:
  - If JOB-ID not found, accept any stable large (≥400px) new image not in oldSrcs, complete true, visible true, after 10s of waiting.
  - If layout detection fails, try both directions: look for image both before and after job container, prefer after (below) if `justify-start` class found, else before.
  - Full src returned, not sliced, for download.
  - Rect returned for highlight.

## Design — New Modules (per RULE 18 ideal sizes)

Create 3 new files in `app/browser/`:

### 1. `output_probes.py` — probe JS v3

- Constants: `JS_BASELINE_V3`, `JS_CHECK_NEW_OUTPUT_V3`
- Functions (each ≤20 LOC):
  - `build_baseline_js()` → returns baseline JS string
  - `build_check_js(old_srcs, correlation_id, old_outputs)` → returns check JS string with full src
  - `_normalize_selector_key(sel)` — helper
  - `is_layout_reverse()` — JS snippet to detect flex-col-reverse

JS v3 improvements:
- Normalized selector keys, no early-break: scan all selectors, deduplicate by src.
- Smallest container requires `hasJob && (hasImg || hasFlex || hasGroup)` — ensures container includes reference thumbnail.
- Layout-aware: detect `ol.flex-col-reverse` → if reverse, DOM before = visual after, so "below" visual corresponds to DOM before. Implement `isReverse = !!document.querySelector('ol.flex-col-reverse')`.
- For each job, store container, top, left, hasReverse flag.
- For each image candidate: 
  - Exclude if inside jobContainer and isSmall && !is50vh (reference)
  - isLarge = 50vh || width>=400
  - Classify as `above` (before in DOM) and `below` (after in DOM) using `compareDocumentPosition`
  - Also check visual top + container class: `justify-start` indicates assistant bubble below, `items-end` indicates user bubble.
  - Valid pool: if reverse layout, valid is `beforeCurrent` (file above = visual below), else `afterCurrent` (file below = visual below). But to be safe, include both and prefer `below` (after) when `justify-start` found, as user says correct is below prompt block.
- Return full src, not sliced, plus rect, plus `layoutReverse` flag, `jobFound`, `jobTop`, `prevJobTop`, `validBelow`, `validAbove`, `belowCandidates`, `debugAllImgs` with full src.

### 2. `output_state.py` — diagnostics flattening

- `flatten_diagnostics(result)` → ensures `orderCheck`, `jobTop`, `validAbove`, etc. are always present, not None, for bridge logs.
- `build_order_check_text(...)` helper.

### 3. `output_wait.py` — wait loop with fallback

- `should_continue_after_spinner(reason)` predicate
- `handle_spinner_visible(...)`
- `handle_ready_result(...)` with 3s wait as requested
- `wait_for_new_output_loop(cdp, baseline, correlation_id, cancel_check, log_callback)` — main loop:
  - Poll every 2s
  - If spinning → continue
  - If ready → wait 3s (user request), re-check, return completed
  - If spinner gone and no new → if reason in continue list, continue
  - **Fallback**: after 10s without valid, accept any stable large new image ≥400px complete visible even if no JOB-ID anchor, to avoid infinite wait. Log fallback.
  - On timeout, return failed with `last_check` containing full diagnostics.

### 4. Refactor `cdp_arena.py`

- Thin delegation: each method ~12 LOC, calls probes from `output_probes.py` and wait loop from `output_wait.py`
- Delete old huge JS (498 lines)
- Keep signature unchanged for bridge compatibility
- Add 3s delay before download in `download_image`? Actually wait already handles, but also add 3s in bridge DOWNLOAD block (already done)

## Implementation Steps

1. Create `docs/archive/2026-09-16-image-below-prompt/plan.md` (this file)
2. Create `app/browser/output_probes.py` with JS v3, functions ≤20 LOC, CC≤7
3. Create `app/browser/output_state.py` with flatten helpers
4. Create `app/browser/output_wait.py` with wait loop and fallback
5. Refactor `app/browser/cdp_arena.py` to delegate to new modules, reduce LOC from 534 to ~300, methods 31→~15
6. Update `app/ui/bridge.py` DOWNLOAD and WAIT blocks to ensure 3s wait (already done, verify)
7. Run `python -m py_compile`, `pytest -q`, `python tools/verify_quality.py --changed --allow-legacy`
8. Update `tools/quality_baseline.json` for new files and reduced cdp_arena
9. Update `docs/current/DOM_SELECTORS.md` with new E3 section for below-prompt detection
10. Push

## Verification

- Tests: 45 existing + new harness for probe JS (if added) → 69 pass
- Quality: `output_*` files clean, `cdp_arena` reduced, LEGACY baselined
- Manual: single-image run against real Chrome + arena.ai — watch for `⏳ Waiting 3s before download` and correct image below prompt downloaded, not reference above.

## Compliance

- RULE 16: size/complexity gates, no gaming splits, real responsibility names
- RULE 18: ideal sizes 4-20 lines, helpers with real names
- RULE 20: never bypass CAPTCHA, respect ToS
- RULE 21: semantic selectors, not generated IDs
- RULE 22: correlation token unique and verified
