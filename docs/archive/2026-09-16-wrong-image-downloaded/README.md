# Wrong image downloaded (reference instead of generated) — 2026-09-16

Status: PLAN (step 2 of IMPLEMENTATION PROCESS). Implement only after this plan.

## 1. Symptom (user report)

- WAIT_OUTPUT waits correctly (v3 fixed the infinite stall).
- But the final download is the **reference preview** (small uploaded image above
  the prompt), not the **generated image below the prompt**.
- User ground truth: reference = above prompt, never download; generated =
  below prompt block, that is the target ("right click - save as" image).

Note: folder `arena webpages/generated image alredy finish` was NOT found in this
checkout. Research used `arena webpages/state/Arena _ Benchmark...html` (saved
page, 1 JOB-ID + ref + generated) plus the user's pasted prompt-block and
image-block snippets. Both sources agree on structure (same class chains).

## 2. Verified DOM structure (saved page, document order)

```
ol.flex-col-reverse                                    <- message list (NOTE!)
  div.h-0                                              <- spacer
  div.w-full                                           <- "Which response do you prefer?" vote UI
  div.mx-auto...justify-end                            <- USER turn (ref + prompt)
    div.group...self-end
      div.flex.flex-col.gap-4                          <- turn container
        div.flex...justify-end.ml-auto...              <- ref row (RIGHT aligned)
          div.w-fit > div.relative > img.aspect-square.w-32 (REF, renders 128px)
        div.flex...flex-col.items-end.gap-1            <- prompt bubble
          div.bg-surface-raised > div.prose > p [JOB-ID: ...]
  div.mx-auto...w-full                                  <- ASSISTANT turn (output)
    div.bg-surface-primary...
      div.no-scrollbar...                              <- grid container
        div.min-w-0 > div.flex.flex-col.gap-3
          div.flex...justify-start                     <- output row (LEFT aligned)
            div.w-fit > div.relative > img.h-[50vh].w-[50vh] (GENERATED, large)
  div.mx-auto...justify-end                            <- other user turn
```

Noise: avatar `img.aspect-square.h-full.w-full` (24px, NOT r2), onboarding
`img.mt-3.w-full` (arena.ai URL, NOT r2, in fixed bottom banner).

Structural separators (ref vs generated), all verified:
| signal | reference | generated |
|---|---|---|
| DOM vs prompt | BEFORE prompt | AFTER prompt |
| visual vs prompt (user) | above | below |
| row alignment | `justify-end` + `ml-auto` | `justify-start` |
| size class | `w-32` (renders 128px) | `h-[50vh] w-[50vh]` (renders 400px+) |
| inside `div.no-scrollbar` | NO | YES |
| src host (live) | r2 (same CDN!) | r2 |
| shares small ancestor with prompt | YES (`gap-4` turn container) | NO (own turn) |

CDN alone can NOT separate ref from generated (both r2). Rendered size,
no-scrollbar containment, turn container, and DOM-after-prompt can.

## 3. Root cause (v3 exact path)

`JS_CHECK_NEW_OUTPUT_V3` layout detection:

```js
isReverse = !!document.querySelector('ol.flex-col-reverse, div.flex-col-reverse');
```

The page HAS `ol.flex-col-reverse` (the message list itself!) → `isReverse`
is ALWAYS true on this page → v3 uses the **above pool** (`poolKind='above'`,
DOM-before prompt, closest-first) → pool[0] = the **reference**:

- reference survives the `reference` filter because `findJobContainer` stops at
  the prompt bubble (`hasJob && hasFlex`), which does NOT contain the sibling
  reference → `insideAnyJob(ref)` = false;
- reference passes `isLarge` via `naturalWidth` (uploaded photo, 1000px+);
- reference is `complete`, `naturalWidth > 0`, visible; spinner already gone
  ("generated image already finish") → `{ready: true, src: <reference>}`.

So the "wait correct" run completes fast with the wrong src, and the bridge
downloads the reference. The document-wide flex-col-reverse flip was designed
for an inverted-scroll hypothesis that does NOT hold: DOM order pairs prompts
with outputs correctly (output is DOM-after its prompt).

Secondary live path (same outcome): `select_best_fallback` ranks
`allNewDetails` by `(naturalWidth, top)` — the reference's natural width can
beat the generated image, and references are not excluded there either.

## 4. Design (v4)

Invariant: **a reference image can never be selected, via exact or fallback.**

1. **Delete the document-wide `flex-col-reverse` direction flip.** DOM order
   (`compareDocumentPosition`) is the pairing signal; the flip provably picks
   the reference on this page. Rationale recorded in code comment.
2. **Structural reference exclusion (direction-independent).** An image is a
   reference (never downloadable) if ANY holds:
   - it shares a "small" ancestor (`h < 0.9vh`, `w < 0.95vw`) with the
     current job element (the `gap-4` turn container case), checked against
     ALL jobs for the job-missing path;
   - it renders small (`rect <= 140px`) — generated output never does
     (`50vh` ≈ 400px+); this also kills avatars;
   - (kept) v3's `insideAnyJob && small` secondary rule.
3. **Require output CDN.** Candidates must contain `r2.cloudflarestorage.com`
   or `messages-prod.` — kills avatar/onboarding/composer chrome. Both ref
   and output have always been r2 (all evidence + all v3 selectors).
4. **Pairing (DOM order, no flip).** Exact pool = non-reference candidates
   DOM-after prompt AND (DOM-before next prompt if any) AND no intervening
   job — the user's "below the prompt block". Sort DOM-closest-after first.
   Prefer `no-scrollbar` containment as tiebreak (structural, RULE 21).
5. **Fallback hardening.** JS sends `fallbackDetails`: below-pool items when
   the job is found, else all-new-minus-references. Python
   `select_best_fallback` drops `isReference` items and ranks by RENDERED
   width (`rect.width`), not natural width.
6. **Stability (bridge compat).** Reason strings
   `image_above_belongs_to_previous_prompt_await_next` and
   `no_exact_above_found_wait_next` are KEPT verbatim (bridge.py:2081 matches
   them); their names are legacy, documented here. Payload keys only added
   (`isReference`, `inGrid`, `fallbackDetails`), never removed/renamed.
   `cdp_arena.py` delegation and bridge untouched.

## 5. Detailed change list

1. `app/browser/output_probes.py` — JS v4 (`JS_CHECK_NEW_OUTPUT_V4`, keep V3
   name alias out; builders pass version implicitly): remove `isReverse`
   branch; add `sharesTurnWithJob(img)`; add `isReference`/`inGrid` per
   candidate; r2-only filter; below-pool-only + `fallbackDetails` in
   not-ready payloads; keep reason strings + diagnostics keys.
2. `app/browser/output_state.py` — `select_best_fallback`: drop
   `isReference`, rank `(rect_w, top)`; keep all funcs ≤30 LOC.
3. `app/browser/output_wait.py` — `_best_candidate` prefers
   `fallbackDetails`, else non-reference `allNewDetails`. (Tiny; restsame.)
4. `tests/js_harness_check.js` — rewrite Case 1 to the LIVE layout
   (`ol.flex-col-reverse` present, ref DOM-before prompt, gen DOM-after →
   must pick gen, `poolKind='below'`); add Case 6: reference-only (no gen
   yet) → not ready, never picks ref; add Case 7: fallback payload excludes
   ref (`fallbackDetails` has no ref src).
5. `tests/test_output_probes.py` — import V4 name; keep builder/harness tests.
6. `tests/test_output_state.py` — fallback drops `isReference`; ranks by
   rendered width over natural width.
7. Docs (RULE 17): `DOM_SELECTORS.md` E4 section + `SYSTEM_OF_RECORD.md`
   row 14 note. No other rows affected.
8. Recheck (RULE 16/18): `verify_quality --changed --allow-legacy`
   (expect only pre-existing watcher.py fails), full `pytest`, `node --check`
   via tests. Manual single-image live run by user (sandbox has no Chrome).

## 6. Risks

- If arena.ai ever serves outputs off-r2, the CDN requirement blinds us.
  Accepted: all evidence says r2; `debugAllImgs`/`debugFiltered` keep showing
  skipped srcs so a future break is diagnosable in logs.
- A/B battle (two new outputs): DOM-closest-after-first wins, tiebreak
  no-scrollbar then larger rendered. Either is a valid output of the prompt;
  matches old "prefer largest" behaviour closely enough.
- `rect <= 140` exclusion: safe while outputs render at 50vh; revisit if a
  compact layout appears (would show in `debugFiltered` as `small_render`).
