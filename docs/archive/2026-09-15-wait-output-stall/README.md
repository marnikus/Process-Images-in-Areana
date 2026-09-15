# Wait-Output Stall — Root Cause & Fix Design

Date: 2026-09-15
Status: design (before implementation)
Applies to: `app/browser/cdp_arena.py` JS_CHECK_NEW_OUTPUT + wait_for_new_output
User report: spinner gone but "waiting for image to appear" forever,
even though last image is ready to download. Failed several times.

## 1. Problem (from user log 23:49-23:51)

- Baseline: 4 existing outputs.
- Submit OK, spinner visible (2, Response A/B), then spinner gone.
- Loop forever: "Spinner disappeared but no new image yet".
- Cancel/pause pressed but loop continues (stop not honoured promptly
  inside inner wait in old build; current build has cancel_check).

Second paste: page text shows 5x "Message from Max [JOB-ID...]"
with prompt text, no image URLs in text dump. Text dump strips <img>,
so it proves JOB-ID renders in user bubbles, not that images missing.

## 2. DOM truth (from docs/research/*.html)

- `<ol class="... flex-col-reverse ...">` — DOM first = visual bottom.
- Newest assistant bubble is DOM-early (index 1), newest user bubble
  next (index 2). So generated image is DOM-BEFORE its user prompt.
- Assistant bubble contains `div.no-scrollbar` with spinner
  `div.animate-spin > canvas` + "Generating image..." shimmer.
  After finish, same region should contain large `<img>` (50vh).
- User bubble contains reference `<img class="w-32 ...">` (CSS 128px,
  but naturalWidth can be 1000+) + prompt text with [JOB-ID].
- No saved HTML contains a COMPLETED generated image. All R2
  selectors are unverified against real completed DOM. This is the
  deepest risk: we match a pattern never seen in evidence.

## 3. Root causes (ranked)

H1 HIGH — jobContainer too large. JS walks 10 ancestors and keeps
overwriting `container` for each qualifying ancestor, so LARGEST wins.
Then `isReferenceImage` returns true for ANY img inside jobContainer,
even large. If container is whole scroll area, generated image is
filtered as reference and never detected.

H2 HIGH — isLarge filters before ready check. Code drops candidates
with width<200 before pushing to allNew. A loading image (natural 0,
rect 0) is dropped as not_large instead of reported as not_complete.
Result is no_new instead of awaiting load, and lazy images never
trigger scroll-into-view.

H3 MEDIUM — pool too strict. When jobFound=true but validAbove empty,
pool=[] even if belowCandidates has large new images. If DOM order
assumption flips (gen after user due to layout change), image is
ignored forever. No fallback to newest-large-stable after spinner gone.

H4 MEDIUM — exact URL match. R2 presigned URLs rotate query (?X-Amz-).
Baseline oldSrcs exact `includes` fails after reload: all old appear
new, or new with same key but new signature miscompared. Must compare
by normalized key (path without query).

H5 MEDIUM — JOB-ID flapping. Search skips textContent>2000 and uses
inner divs; virtualization or long prompt split can make jobFound flip
true/false between polls, changing classification. Detection must be
stable across polls and degrade to newest-large when job missing.

H6 MEDIUM — lazy loading. `loading="lazy"` images outside viewport
stay naturalWidth 0 until scrolled. Wait loop never scrolls, so image
never loads. Must scroll candidate into view when not complete.

H7 MEDIUM — selector drift. Completed image may not be inside
div.no-scrollbar or R2 host. Must add generic fallbacks (any large img
in main/ol, aspect-square, object-cover) and always return diagnostics
(debugAllImgs) so timeout logs show what exists.

## 4. Current metrics (before)

From tools/verify_quality.py (radon not installed, AST approx):

- app/browser/cdp_arena.py: class 503 LOC, 23 methods,
  wait_for_new_output 76 LOC CC24, download_image 60 LOC CC14.
  Baseline file allows legacy but must not worsen (RULE 16.5).
- app/ui/bridge.py: class 3504 LOC, 130 methods,
  _do_run_batch 1022 LOC CC299 nesting 23. Must not touch.
- app/services/watcher.py: 3 fails (new file, not legacy).
  Out of scope for this fix, but must not add more fails.

Target: no new function >30 LOC, no new class >150 LOC,
params <=4, CC<=10, nesting<=4, cognitive<=15.
Ideals (RULE 18): function 4-20 lines, file 150-300 lines,
module 5-15 files. Current browser/ has 9 files, +2 = 11 OK.

## 5. Design — new modules (no hotspot growth)

New file 1: app/browser/output_probes.py (~180 lines)
- build_baseline_js() — small wrapper, JS literal exception.
- build_check_new_output_js(old_keys, correlation_id) — single JS
  payload implementing v3 logic (normalize, smallest container,
  all-imgs diagnostics, DOM+visual classify, scroll assist).
- build_scroll_bottom_js() — scroll no-scrollbar to bottom.
Each Python function 4-20 lines, CC<=3. JS length exempt per
RULE 16.1.5 (single string literal), Python flow still gated.

New file 2: app/browser/output_state.py (~200 lines)
Pure, testable, no CDP/Qt:
- normalize_src_key(src) — strip query/hash, keep path tail.
- normalize_old_keys(srcs) — set of keys.
- is_large_candidate(cand) — width>=200 or 50vh/object-cover.
- is_reference_candidate(cand, job_containers) — inside + small.
- select_exact_above(cands, job, prev) — DOM-between + no intervening.
- select_fallback_newest(cands) — largest, bottom-most.
- should_accept_fallback(spinning, stable_polls, elapsed) — after
  spinner gone + stable 3 polls + >10s, accept with warning.
- interpret_check_result(result) — maps JS dict to (status, detail)
  with empty-vs-broken distinct (RULE 4).
Each 4-20 lines, CC<=7, params<=3.

Modified: app/browser/cdp_arena.py (shrink, not grow)
- wait_for_new_output delegates JS build to output_probes and
  interpretation to output_state. Keeps cancel_check (RULE 7),
  incremental logging (RULE 5), GREEN collect on ready (RULE 1).
- capture_baseline also normalizes keys via output_state.
- Net LOC/CC must go down, not up. No new methods on class;
  reuse existing two methods only.

Not touched: app/ui/bridge.py. Fix is fully in controller layer,
bridge benefits automatically. Avoids growing 1022-line function.

## 6. New JS v3 logic (exact order + fallback)

1. Normalize old keys (strip ?#) in JS too, compare by key.
2. Find JOBs via TreeWalker on text nodes containing JOB-ID,
   then smallest qualifying container (first ancestor meeting
   height/width/not-no-scrollbar, break). Record top/left/DOM node.
3. Collect ALL imgs with full diagnostics (src,key,cls,rect,
   natural,complete,visible,inOld,insideJob,top).
4. Exclude only blob:/data:, tiny <50 natural both, inOld by key.
   Mark isLarge and isReference, but DO NOT drop non-large yet.
   Drop only isReference small from valid pool, keep in diagnostics.
5. Classify each: beforeCurrentDOM, afterPrevDOM, aboveVisual,
   betweenVisual, hasInterveningDOM. ValidAbove = DOM-between +
   no intervening. Below = afterCurrentDOM. InvalidAbove = before
   prev (belongs to previous).
6. If validAbove large+complete+visible and not spinning -> ready.
   If validAbove large but !complete -> scrollIntoView + not_complete.
   If validAbove empty but below large new exists -> report
   below_found with details, not ready yet.
7. Always return debugAllImgs(15), debugFiltered(15), allJobs,
   valid/invalid/below counts+details, orderCheck string.
8. Python fallback: if spinning false for >10s and same large src
   stable 3 polls, accept best large new even if orderCheck says
   invalid, log warning "fallback_newest_large", still verify
   downloadable before save (RULE 15 fails closed on download).

Dishonest reductions rejected:
- Splitting wait_for_new_output into part1/part2 to game LOC.
- Hiding params behind **kwargs (RULE 3 keeps explicit).
- Lambda dispatch to hide if-count for CC.
- Deleting real branches (spinner vs ready vs not_complete vs
  hidden vs fallback) to lower CC. Floor is CC>=6 for 5 outcomes.
- String-assert tests that pass with feature deleted (RULE 8).

## 7. Tests (RULE 8, real execution)

- tests/test_output_state.py: pure logic with canned candidates.
  Each test fails if function deleted or boolean inverted.
  Covers empty-vs-broken, normalize with query rotation,
  exact-above vs belongs-to-previous, fallback stable logic,
  stop predicate (RULE 7) via wait helper.
- tests/js_harness_check.js + tests/test_output_probes.py:
  Node harness builds DOM stub mimicking flex-col-reverse ol
  (h0, gen_A 50vh, user QJ9K w-32+JOB, gen_B, user older) and
  runs build_check_new_output_js via node. Asserts ready src
  is gen_A, not reference, and invalidAbove for previous.
  If node missing, Python test skips with warning, but CI has node.
- Existing suite must stay green (equivalence gate for refactor).

## 8. Docs (RULE 17)

- Update docs/current/DOM_SELECTORS.md section E2 with v3 order
  + fallback + normalized keys + smallest container.
- Update docs/current/SYSTEM_OF_RECORD.md row 14 (output detection)
  with fallback + scroll assist.
- This archive doc stays frozen as record of belief on this date.

## 9. Rollout

1. Add output_probes.py + output_state.py (new, gated).
2. Add tests, run node harness + pytest.
3. Refactor cdp_arena.py two methods to delegate (shrink).
4. Run tools/verify_quality.py --changed --allow-legacy + pytest.
5. Manual: run one image, check logs show orderCheck + fallback,
   GREEN rect on new output, no infinite stall, cancel prompt.
