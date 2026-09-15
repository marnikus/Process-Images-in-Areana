# 03 — Product, interface and verified workflow

## Existing dark drag/drop workspace

Retain the existing modern dark HTML/JS desktop UI in the Qt shell: draggable panels/windows, split/resize grid, saved layouts, global undo/redo and named preset controls. Replace unrelated panel content, not the workspace mechanics. Preserve readable contrast, keyboard focus and status text/icons. Native directory picker accesses the user's local filesystem; the authorized browser remains separately visible for login/manual challenges. See [retention contracts](07-RETAINED-WORKSPACE.md).

| Area | Controls and information |
|---|---|
| URLs (top) | Exact URL text rows; stable row ID; add/edit/remove/enable/disable; Test row/Test enabled; last check, final destination, status and action. Editing invalidates readiness. Active assigned rows cannot be silently edited away. |
| Folder | Choose root, visible absolute path, rescan; recursion, supported types and generated-output exclusion settings |
| Queue (main table) | Thumbnail, relative path, filename, inclusion checkbox, status, step, assigned URL, attempt count, output path and actionable error. Sort/filter without changing job identity. Open source/output folder; manual include/exclude, skip, retry, reset, inspect. |
| Bulk toolbar | Select all, deselect all, select pending, retry failed, clear completed **from view**, not history. Hidden-row selection scope explicitly shown. |
| Prompt | Multiline exact text; final preview `[JOB-ID: <generated-on-attempt>]` then newline then text. Show actual immutable marker once job created; preview is not a reusable ID. |
| Run toolbar | Start, Pause, Resume, Stop after current item, Cancel current item, Retry; availability derived from state |
| Summary | Total, selected, pending, processing, completed, skipped, failed, needs review, interrupted. Selected is an independent count, not another mutually exclusive status. |
| Activity | Timestamped readable steps; expandable sanitized technical evidence/recovery options |
| Settings/presets | Timeouts, bounded retries/backoff, types/size limits, output collision behavior, diagnostic consent, review policy, highlight duration/color/width, import/export/save preset. Persist UI layout/filter/sort as well. |

Deselection never deletes history. Pre-submit deselection stops that job safely; post-submit deselection prevents future work but cannot undo a website request. Reset of completed/review/interrupted work requires confirmation, keeps old attempts/output metadata and warns of duplicate generation. “Completed” cannot be manually fabricated; manual approval after inspection is separately recorded and must not bypass valid-file checks.

## Workspace editing, undo and preset controls

Retain drag/drop stack/block authoring and all layout, workflow, block, prompt-template and variable libraries with save/load/update/delete/import/export. Add Undo/Redo controls with next-action labels and existing shortcut behavior. All image workflow plans are validated before execution: editing cannot omit attachment/prompt/output verification or introduce duplicate submission. Layout preset application is one global undo operation. Undo changes editable local state only, never website submissions, completed-job evidence or saved image bytes.

Prompt text is literal by default. In explicitly enabled template mode, resolve saved variables deterministically, show the final rendered prompt, then prepend the reserved job marker. Persist raw template, resolved variable snapshot and final submitted text; do not silently substitute defaults for unknown variables.

## URL gate and scheduling

Use the retained existing CDP connection UI/service against **already-open** debug Chrome tabs. See [doc 08](08-CHROME-CONNECTION.md). Each row shows open-tab match, actual target URL/title, connection state, last check and independent site readiness. No matching tab means “Page not open”; ask the user to open it, never silently navigate/create a tab. “Connected” requires a live harmless page round-trip, not only discovery. Sequential row checks must not display all previously checked tabs as simultaneously connected.


Store raw input exactly; do not trim/rewrite path/query or replace destination silently. Report leading/trailing whitespace and ask user to edit. Allow approved HTTP(S) only (HTTPS recommended), reject embedded credentials and unsupported schemes. Reachability/readiness tests use the same dedicated browser context as actual jobs, not a separate unauthenticated HTTP request. Record redirects separately; unexpected destinations require approval, especially before upload. Exact URL rows remain independent even if their destinations coincide; serialize access to a shared page/conversation.

Statuses: unchecked → checking → ready / unavailable / authentication required / user action required / unsupported page / error. Transient loading stays checking up to timeout. HTTP 200 does not prove ready. No generic catch-all Arena adapter for unrelated Agent Mode pages. Readiness requires unique image composer, attachment entry/input, correct Send control presence, output observation strategy, approved destination and no blocking error. Send must become enabled before submission, not necessarily on an empty idle composer. Recheck before every job; persisted ready is historical, startup invalidates it.

**Scheduling:** one active image globally. Round-robin in enabled row order over freshly ready URLs; persist cursor and chosen row in attempt. Unready/disabled rows receive no jobs. No ready URL means pause with action, not an empty successful batch. Duplicate URL rows do not create concurrency. No reassignment of a potentially submitted attempt.

## Main state diagram

```text
launch → load/validate JSON → reconcile files and interrupted attempts → idle
  (missing/corrupt required state → recovery UI, never auto-start)
idle → configure/test URLs → scan → user reviews selection → start
  → choose selected pending image + ready URL → create unique attempt
  → verify source fingerprint + readiness → capture baseline
  → attach → verify current preview → fill prompt → exact readback
  → optional review approval → persist submission-intent checkpoint
  → recheck prerequisites → highlight and SUBMIT ONCE
  → confirm current marked message / processing → persist confirmation
  → wait for current response → correlate new completed output
  → download permitted original → validate bytes → stage safe save
  → atomically publish output → persist completion → next selected item
  → batch summary when no eligible work remains

Any step:
  source/page/input failure before submit → bounded safe retry or failed
  security/auth user action → paused checkpoint → manual action → reverify
  submission possibly happened / ownership uncertain → needs_review
  process crash with active attempt → interrupted → inspect/recover/confirm
  local cancel → cancelled/skipped before send; needs_review after send
```

Research is a design/adapter-update gate, not an automatic startup operation that replays saved web pages.

## Step contracts and durability

| Step | Advance only when | Recovery |
|---|---|---|
| Restore/reconcile | Schema valid; sources/outputs reconciled; no active auto-resubmission | Corrupt JSON preserved; recovery prompt; active attempts interrupted |
| Prepare | Selected at execution time; file unchanged; approved ready row assigned | Missing/changed source actionable failure, not upload of unexpected bytes |
| Baseline | Existing composer content, user/response ordering, known outputs and navigation identity captured | Old attachment/text: pause to clear with approval; prior generation: wait/ask, never commandeer it |
| Attach | One intended file appears newly in current composer; trusted upload identity/filename matches | No prompt submission; safe cleanup/retry only with verified state |
| Prompt | Exact header + newline + unmodified prompt read back | Correct/verify or fail; no blind Send |
| Submit | Prerequisites remain true; intent durably written; single target clicked once | Missing confirmation is uncertainty, not permission to click again |
| Confirm/wait | Current marked user message and same-flow processing/response observed | Challenge manually handled; timeout/error after potential send → review |
| Correlate | Output absent from baseline, within assistant response following this exact marked prompt, navigation unchanged, generation complete and image loaded | Old/reused/ambiguous images, multiple unassigned outputs, foreign prompt or lost page context → review |
| Download | Permitted original/highest-quality asset provenance recorded; size bounded; bytes decode as supported image | Expired link may be refreshed from verified current response; no resubmit |
| Save | Validated same-directory partial, safe destination reserved, atomic publication, final file exists and metadata persisted | Disk/permissions/collision visible; recover save without new generation |

Core rule: **observe → one action → verify → persist → advance**. Persist intent **before** a non-idempotent submit to cover crashes between click and confirmation. Exactly-once remote execution cannot be guaranteed without site support; the app guarantees no blind duplicate click/retry and escalates ambiguity.

Correlation uses full per-attempt ID, current user-message boundary, response ordering, baseline identities, observation sequence and timestamp. Changed signed URL alone is not new content; preserve durable asset path/message identity where available, never just remove all queries and assume equivalent. Capture node identity and asset identity independently. Local time alone cannot prove server ownership. Spinner disappearance and nonzero image dimensions are necessary hints, not ownership proof.

## Run-control semantics

- **Pause:** stop before next side effect. If submitted, continue non-mutating observation and checkpoint evidence; do not send another job. Save/download behavior while paused should be explicit (proposed: require Resume to perform further writes except state/diagnostics).
- **Resume:** user-authorized safe checkpoint continuation after page/file checks, never re-click a possibly used Send. After challenge, verify normal state and current response; do not require an idle Send while current generation is still running.
- **Stop after current:** finish verifying/saving active job, then stop scheduling. Remains persisted until user restarts.
- **Cancel current:** interrupt local waits promptly. Before send, cancel safely. After send, no claim of remote cancellation; mark review. A remote Stop generation action is optional only after selector/effect research and explicit user approval.
- **Retry:** new attempt/ID; old immutable attempt retained. Automatic retries only for provably pre-submit safe operations; exponential bounded backoff. Post-submit failures allow inspection/download recovery, not automatic generation.
- **Skip:** keeps an explicit user decision. Clear completed hides records rather than clearing completion fingerprints. Added/changed files never become selected work without the approved selection policy (proposed: newly scanned files pending but deselected).
