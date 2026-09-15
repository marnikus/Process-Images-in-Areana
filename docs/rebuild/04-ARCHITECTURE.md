# 04 — Architecture and JSON-only persistence

## Retained desktop stack and existing Chrome/CDP controller

Retain Python 3.11+, **PySide6 Qt WebEngine/WebChannel**, existing dark HTML/CSS/JS shell, sash-grid/drag-drop systems and compatible Qt/async lifecycle (including qasync where required). Do not replace the workspace with Qt Widgets. Preserve the JS-to-Qt command boundaries for layout, undo, presets and variables; add image-specific commands through typed services. Keep/adapt the existing CDP client, transport, events, discovery service and connection UI to attach to user-opened Chrome. Keep aiohttp/websockets; no Playwright replacement or app-launched browser is planned. Pillow/image validation and per-user paths remain proposed. Keep work asynchronous and UI-responsive; no concurrent state writers. “Lightweight” means removing unrelated product features, not removing the requested workspace or promising tiny packaging.

Confirmed browser strategy: user starts Chrome with remote debugging; app attaches to the requested existing tabs and verifies each connection. See [connection contract](08-CHROME-CONNECTION.md). Do not expose a debugging port publicly. Licensing, selected Chrome channel, supported OS and packaging must be checked before release.

## Responsibility and dependency map

Proposed paths, **not created code**:

| Package under `src/image_queue/` | Owns | Must not own |
|---|---|---|
| `app/` | Bootstrap, dependency wiring, lifecycle, worker shutdown | Selectors and job decisions |
| `ui/` | Retained dark HTML/JS window grid, drag/drop, view models, commands and local picker bridge | DOM, direct JSON writes, workflow branching |
| `domain/` | Typed configuration, statuses, attempts, transitions, correlation decisions/errors | Qt, browser or filesystem imports |
| `workflow/` | Sequential coordinator, checkpoints, retry policy, round-robin, recovery | Site-specific selectors |
| `filesystem/` | Recursive scan, fingerprints, thumbnails, validated atomic output | Browser/session state |
| `persistence/` | Versioned JSON schemas, atomic writes, backups, locking, validated migration of supported workspace/preset data (no DB) | SQL, remote state or legacy DB import |
| `browser/` | Authorized context/tabs, navigation, downloads, visual action runner | Job completion decisions or arbitrary target selection |
| `adapters/arena_image/` | Evidence-backed scoped selectors, readiness, attachment/message/output observations | Queue selection and output naming |
| `verification/` | Pure correlation/input rules; explicit evidence verdicts | Clicking or silently approving uncertain results |
| `diagnostics/` | Structured redacted events, consented limited artifacts | Credentials or raw transcript harvesting |

Dependency direction: UI → application commands → workflow → narrow browser/filesystem/persistence interfaces; implementations plug in at bootstrap. Domain stays independent. Browser adapter returns structured observations; verifier decides; coordinator persists and advances. A failed UI event handler is logged but cannot discard a job checkpoint. Retain the existing action/stack editor and preset authoring interfaces, but route image jobs through the mandatory verified coordinator. Do not grow a new general plugin framework or restore the chat execution engine.

## Browser/adapter contracts

Operations: inspect readiness; observe baseline; attach one file; verify preview; fill/read prompt; submit once; observe submission/current response; identify permitted original download; inspect security/error state; highlight exact action target. Each returns explicit success/failure/uncertainty with limited evidence and typed error code. Timeout and cancellation are first-class inputs, not scattered sleeps. Selectors reside in the adapter only, with full specifications from research doc 01.

Map each configured row to an explicitly matched existing tab; never create or navigate a tab automatically. One global active job; reuse the existing single-client model with serialized target attachment/checks. Per-row status distinguishes live attached from previously verified, not currently attached. Match tabs by stored mapping plus verified exact navigation, not title substring. A manually navigated tab loses readiness. Unexpected redirects require approval; do not upload to a login page or silently choose another conversation. User authorizes the target site and its normal upload/CDN infrastructure; app must not repurpose other endpoints or reverse-engineer hidden APIs. Download redirects must remain permitted and correlated.

## Persistence without a database

Local user-data directory, outside repository/source folders:

| File/directory | Content |
|---|---|
| `config.json` | Revisioned startup/export projection (authoritative editable config is in state.json): schema version, all configurable UI parameters, exact URL rows, chosen root, prompt, scan/output/browser policies and presentation preferences |
| `state.json` | Schema/revision, editable workspace/config and libraries, global undo timeline/cursor, queue records, immutable attempt history, URL last-check metadata, scheduling cursor, run mode, save intents and completion fingerprints |
| `presets/<name>.json` | Versioned export/import of all user-editable configuration, including view/highlight settings; no credentials or job outcomes |
| `logs/events-<date>.jsonl` | Rotated sanitized events, not authoritative recovery state |
| `diagnostics/` | Opt-in sanitized screenshot/limited snapshot, retention-limited |
| User-owned debug Chrome profile | User launches/owns it; app does not create, move, delete, export or manage its contents. Session stays in Chrome, outside presets/repository |

A single app-instance lock protects the workspace and serializes state writes. The authoritative state includes the editable workspace snapshot and global undo timeline/cursor in the same atomic commit; JSON library files are exports or rebuildable projections, not competing authorities. See doc 07 for migration and history semantics. MVP uses a single authoritative state snapshot to avoid cross-file job transactions. Editable settings and undoable library changes commit with the workspace snapshot; `config.json` is a validated startup/export projection, not a separately committed undo authority. Runtime job changes remain outside user undo. each attempt freezes its relevant config revision/prompt/URL so later UI edits cannot alter an active job. Large-history compaction or JSON sharding is deferred until measured need; set a tested queue/history envelope before claiming scale.

## Data model

| Record | Required fields |
|---|---|
| Configuration | schema version, config revision, raw prompt, root path, URL row IDs/exact text/enabled, timeout/retry/backoff policy, types/max bytes/max decoded pixels, naming/collision mode, review setting, CDP loopback host/port and connection preferences, diagnostics consent/retention, highlight and UI preferences |
| URL check | row ID, checked-at, status/reason/action, actual final destination, adapter version, readiness evidence summary; no tokens/headers |
| Image | stable image ID, root/relative/absolute path, size, mtime_ns, optional hash and filesystem identity, present/changed flags, inclusion, user decision timestamp, effective status, active attempt ID, output metadata |
| Attempt | UUID-based unique correlation ID (readable UTC prefix optional), image ID/fingerprint, attempt number, raw configured URL/row ID, exact final prompt, config revision, step/status/checkpoint, created/intent/submitted/completed timestamps, baseline/current-response evidence, retry classification, error/action, output/save intent |
| Output | actual format/extension, final path, byte length, dimensions, SHA-256, source asset/message metadata (redacted as appropriate), observed-after ordering, validation verdict, completed-at |
| Run | idle/running/paused/stopping, active attempt, round-robin cursor, cancellation/stop reason, last durable revision |

Queue inclusion and processing status are orthogonal. Status vocabulary includes pending, processing, completed, skipped, failed, needs_review and interrupted; cancelled is recorded in attempt history and maps visibly to skipped/review depending on submission risk. Missing/changed source is an explicit reason, not a fake completed state. Attempt count never resets silently when retrying.

Path + size + mtime_ns fingerprints detect ordinary changes, not all same-size/time edits. For stronger safety, hash at scan/admission or before upload and compare again before side effects. Rename matching is only reliable with trusted file identity/hash; otherwise show missing old/new file and ask rather than inheriting completion. Symlinks are not followed by default; avoid loops/root escapes. Changes produce a new file revision while preserving prior decisions/history with explicit review policy. Rescan on launch/root selection/manual action; watch mode is deferred.

## Atomic state and recovery

Validate schema before replacing data. Write a uniquely named same-directory temporary JSON, flush/fsync, then atomic replace; fsync directory where supported. Maintain last-known-good backup, revision and actionable write failure. Missing first-run state differs from corrupt existing state. **Never turn corrupt history into an empty queue and continue.** Validate readback/backup before advancing; protect unknown future schema versions from downgrade overwrite. JSONL failure is observable; authoritative state failure blocks further side effects.

Crash startup never starts processing. Persisted active attempts become interrupted; retest URL and reconcile source and planned/final output hash. If a valid already-published output matches durable save-intent metadata, finish recovery without generation. If remote submission may exist, inspect its marked message/result and ask user; absent evidence is not proof no submission occurred. Orphan partial files are quarantined/inspectable, not promoted blindly. Loss of browser tab/context makes uncertain jobs reviewable, not retryable by default.

## Output safety

Decode downloaded bytes with Pillow; reject HTML, truncated data, unsupported/animated formats unless explicitly supported, oversized encoded files and decompression bombs. Proposed source/output defaults PNG, JPEG and WebP based on E1 accept attribute; size limits still require user/site confirmation. Honor actual decoded format, not URL/extension/MIME alone.

Save beside source: `name_AI.png`, then `name_AI_2.png`, etc. Ignore case-insensitive `_AI` and `_AI_<number>` generated patterns by default **and** recorded generated paths. Do not exclude arbitrary filenames just containing AI. Never move/change source. Canonical-path and same-file checks prevent source overwrite via aliases/symlinks. Check destination races; simple exists-then-replace is insufficient with overwrite disabled. Use OS-appropriate exclusive reservation/no-clobber publication and test it on supported filesystems.

Download/validate into a unique same-directory partial; persist save intent including target/hash; publish atomically with collision policy; verify final file; persist completed. Explicit overwrite may replace an existing generated destination only, never source. Failure after publish but before checkpoint is recoverable by intent/hash. State/output cannot be one filesystem transaction; this two-phase recovery is deliberate. Network-drive atomicity/durability must be qualified in OS testing.

## All UI settings and JSON presets

Persist URL edits/enabled state; folder/scan/types/size settings; prompt; timeouts/retries; naming/overwrite; review and diagnostics; browser preference; highlight toggle/duration/color/width/pre-click delay; window geometry, column widths/order, sorting/filter and log detail level. Queue decisions and run state persist in state rather than portable presets. Button presses and transient “checking” spinners are events/status, not settings to replay. Imported preset never starts work or marks a URL ready.

Use one typed schema/default source for widgets, runtime, validation and preset serialization. Explicit schema migration for supported previous layout/stack/block/template/variable formats, with backup, preview and stable ID mapping; reject unsupported future versions, show validation errors, preserve current config on failure. Import previews changed fields and sensitive local paths/URLs, requires approval, and snapshots current configuration. Export excludes credentials/profile contents and history; warn that URLs, paths and prompt are private. Round-trip tests cover every editable field; no arbitrary silent dropping of unknown fields.

## Click rectangle

Reuse/adapt the existing `backend/visual_click.py` and `dom_highlight.py` implementation and its tests rather than rewriting a second runner. The runner resolves the exact semantic element, validates uniqueness/visibility/enabled state, scrolls if needed, draws a red/orange rectangular overlay above it, waits configured pre-click delay, revalidates the same live target, and clicks once. If target detaches/changes, re-observe or stop; never click stale screen coordinates. Overlay has `pointer-events:none`, transparent fill, no layout effects and a high stacking order; it tracks scroll/resize or is removed when invalid. Preserve existing `highlight_enabled`, `confirm_pause_ms` (700 ms default) and `highlight_ms` (1200 ms default) parameters and the staged CLICK pause (250 ms); expose duration in seconds if desired while round-tripping stored milliseconds. Verify actual timing/cleanup in the adapted runner before promising post-click duration. Always clean up on timeout/navigation/cancel. Highlight uploads via visible Add control, not invisible file input; no highlight/click automation inside security challenge. Highlight is observability, not verification of business success.
