# Validation — stalled-session repair, 2026-09-27

## Result and limitation

Implemented I-72. This fixes the reproducible URL-selection defect and the
missing recovery path for a websocket session that remains connected but stops
answering. It does **not** establish why the owner's Chrome stopped answering.
A truly stuck renderer can remain stuck after reconnection. No bypass of output
verification, forced save, navigation, or duplicate submission was introduced.

The attempted local Chromium installation failed with CDN TLS connection resets;
no live Chrome/Arena success is claimed. The owner's Windows Chrome and local
image folder are not reachable from this sandbox.

## Tests

- Before implementation: 4/8 new route tests failed; all four initial transport
  recovery tests failed (including the existing false-positive healthy ping).
- Final Python suite under coverage: **2,795 passed, 13 skipped**, six existing
  warnings (unawaited coroutines in unrelated tests / asyncio marker on sync test).
- JavaScript suite: **474 passed, 4 skipped, zero failures**.
- Seven new recovery tests use the real CDPClient, transport receive loop, command
  routing, domain enable and connection lock. Only the websocket boundary is fake.
  They cover dropped replies, valid responses after replacement, protocol-error
  health replies, concurrent callers, genuinely unhealthy replacement, cancel,
  deadline, failed open, broken log callback and re-arming a later outage.
- Eight new URL tests cover the owner's query, route segment boundaries, host
  isolation, exact query match, fragment/trailing slash and keyword/host modes.
- Normal probe/JOB-ID/download tests are unchanged and passed in the full suites.

## RULE 16 / RULE 18 review

| Production file | Lines | Largest function | Maximum CC | Maximum cognitive |
|---|---:|---:|---:|---:|
| `app/browser/cdp/recovery.py` | 81 | 13 | 5 | 4 |
| `app/browser/page_recovery.py` | 165 | 21 (existing) | 8 | 7 |
| `app/browser/tab_matcher.py` | 115 | 19 | 8 | 7 |

New functions are below the 20-line ideal, at most two parameters; no new class.
The repair stays in the CDP layer rather than growing the transport facade.
No new duplication group or vulture finding in changed files. Vulture still
reports two existing unused imports in `app/ui/bridge.py`. jscpd: 28 groups,
0.8814% duplicated lines, none involving these production changes.

Coverage: **91.30% statements / 87.24% branches**, above stored floors
89.34 / 86.37. New recovery module: **100% statements and branches**.
`git diff --check` passes.

The authoritative gate passes with zero failures/warnings using the explicit
three-file change list:

```
.venv/bin/python tools/verify_quality.py --changed-files \
  app/browser/page_recovery.py app/browser/tab_matcher.py \
  app/browser/cdp/recovery.py --allow-legacy --coverage-ratchet
```

The `--changed --base 137458b` lane excludes uncommitted changes and falls back
to the entire repo when its committed diff is empty. That fallback exposed
unrelated existing baseline debt; it was not reported as a clean full-repo gate.
Use the explicit file list above for this uncommitted working-tree patch.

One stale baseline correction, not a relaxed limit: tab_matcher `max_cog` was 0.
Measured original source with `git show HEAD:app/browser/tab_matcher.py` and
cognitive-complexity: **9 before**, **7 after**. Corrected its baseline to the
original measured **9** only; no other baseline field was changed.

## Owner acceptance on the affected Chrome

1. Restart the app with this patch; keep the generated-image tab open.
2. Connect using `https://arena.ai/image/direct?model_a=max`. It must choose
   `/image/direct`, never `/agent/...` or `/c/...` merely because they share a host.
3. Run one image. If CDP stalls, expect one `reconnecting to the same tab
   (no reload or resubmit)` message, followed by either `response restored` or
   an explicit repair failure. There must be no second Submit from this repair.
4. On restored responses, normal verification must accept the current JOB-ID's
   image and save beside the source through the existing atomic-save path.
5. If repair fails, retain the log including the new repair outcome. The remaining
   investigation is renderer/browser liveness, not another image-selector tweak.

Timing note: the initial health ping uses three seconds; replacement connection,
domain setup and fresh ping share an eight-second budget. Acquiring a connection
lock already held by other work, dialog handling and socket cleanup can add time.
