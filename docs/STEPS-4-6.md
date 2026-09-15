# Presets, existing Chrome and local image queue

Implemented on the session branch after owner authorization of Steps 4–6.
Automated verification does **not** close the native GUI/Windows manual exit gates.
See [measured status](IMPLEMENTATION-STATUS.md).

## 4 — Full named libraries, templates and variables

Open **Prompt templates**, **Variables** and **Workflow** from the retained Windows
menu. Libraries cover stacks, blocks, templates, prompts, variables, connections and
windows, plus an inert archive family for lossless legacy backups.

- Choose a family and a chip to inspect all fields without applying anything.
- Capture current settings, enter a name, then **Create**. **Update** is explicit;
  it cannot silently create a missing entry or overwrite during Create. Chip ×
  deletes through the global undo history. To rename, create under the new name,
  inspect it, then delete the old name; both operations are undoable.
- **Apply reviewed entry** is one global edit. Stored scripts/selectors/blocks are
  inert plans in this build. Applying a connection preset saves configuration only;
  it never opens a browser or makes a connection.
- Workflow uses the actual retained StackDrag implementation. Click a block to
  edit its typed fields; nested values and the complete block remain JSON-editable.
  Reorder, add, edit and delete are global undo operations. Imported unknown block
  types and parameters are preserved, not executed or silently replaced.
- Variables are named text values. Prompt mode defaults to **Literal**. Template
  mode reuses the retained single-pass `{name}` substitution approach. Preview
  shows unresolved/malformed placeholders and never substitutes a shipped default.
  Values containing placeholders are not recursively expanded. No file/config/API
  access is available to a resolver. Old chat aliases need explicit saved values;
  this image app does not manufacture person/conversation context.
- Browser textareas normalize displayed line endings. Unchanged imported CRLF
  prompt text remains exact in storage across unrelated UI edits; newly edited
  textarea text uses its actual browser value.

### Import/export and compatibility

Import a JSON file or paste JSON, **Preview import**, inspect it, then **Import
reviewed data**. Backend confirmation binds the exact text by SHA-256 and rejects
name collisions. Invalid imports, changed previews, malformed JSON, duplicate keys,
unsupported versions and size/schema violations leave durable state untouched.

**Export full backup** includes every named family plus quick layouts from the
Layouts menu (mapped into portable windows). Conflicting quick/portable layout names
are rejected rather than overwritten. JSON also appears in the editor; the native
save dialog creates a new file only. Existing files are never overwritten. This
backs up named libraries, not source images, live sockets or job/completion records.
Active editable settings/history have their separate authoritative workspace snapshot.

Accepted compatibility inputs:

| Retained input | Mapping |
|---|---|
| `chat-v-bot/stack-preset` v1 | Stack plus all custom blocks; full original in `legacy_source` |
| `chat-v-bot/action-block` v1 | Block with complete original export metadata |
| `config/presets.json` section shape | Stack/template/prompt/connection families; full original, including unknown sections, in Archives |
| `chat-v-bot.window-preset` schema 1 | Same 14-ID sash tree and closed/minimized states; all original screen/bounds/title metadata preserved |
| `config/window_presets.json` section shape | Portable window entries plus full original in Archives |

Archives are inspectable/exportable, never applied. Original files are never changed.
Legacy window screen/floating bounds are preserved as evidence, not blindly applied
to another screen; sash layout is the active mapping. Unsupported old SQLite inputs
are not opened. No database is introduced. Imported provider-specific connections
remain data; applying to the Chrome configuration must pass its strict local schema.

Limits: 1 MB aggregate libraries/imports, 100 entries per family, 200 blocks per stack,
200 variables, 64,000 characters per variable, 1,000,000-character rendered prompt.
Library numbers must fit JavaScript's safe numeric range (use text for larger IDs),
object keys must be text, and nesting is bounded to 50 levels. Unsupported values
are rejected before an import can silently round them. Boolean and numeric edits
remain distinct in global history. The existing 32 MiB snapshot/history cap applies. Backups can
contain private user-authored text; do not share them as diagnostics without review.

## 5 — User-opened debug Chrome

Run the desktop application on the **same computer** as your Chrome. A remote web
preview cannot access Chrome on your Windows computer. Start Chrome yourself:

```cmd
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\arena-images-chrome"
```

Open authorized exact pages and log in manually. Save URL rows in Chrome URLs and
use each row's enabled checkbox. Then **Discover existing Chrome**. This queries
only the configured loopback `/json/list`; it does not visit candidate websites.

- Missing/disabled/unique/duplicate discovery outcomes remain distinct.
- Duplicate exact matches show separate title/short-ID choices. Click the specific
  **Check this tab** button. Even a unique candidate needs this explicit check.
- Checking refreshes discovery, attaches the chosen existing target, enables Page
  and Runtime, checks `Target.getTargetInfo`, and evaluates only location/readyState.
  Exact URL/target identity and a complete document are required. Redirects/loading,
  malformed responses, timeout, socket close and CDP errors fail closed.
- Readiness remains **adapter_not_verified**, never Ready for scheduling. No image
  selectors, CAPTCHA interaction, upload, prompt insertion or Send exist here.
- A single persistent CDP client uses the retained lease's cancellation-safe handoff.
  Checks serialize. Moving to another row detaches the previous socket. Status and
  verification time are historical observations, not durable authorization. Use
  **Refresh status** to read the latest connection observation; it is not a new
  page round-trip. Use **Check this tab** for a fresh liveness check.
- Navigation (including SPA same-document navigation), context destruction and
  disconnect invalidate backend attachment status. The UI labels its last observation;
  it does not claim an always-live background heartbeat.
- No automatic reconnect/replay, browser/tab creation/navigation, cookie extraction,
  `Browser.close` or `Target.closeTarget`. Disconnect/exit releases app resources only.
  An active job's configuration lock refuses discovery/check commands.
- Changed endpoint/URL settings replace the runtime session on the next explicit
  Chrome command. Old target IDs/check states are not written to presets or snapshots.

Discovery and WebSocket responses are bounded to 1 MB; HTTP redirects and environment
proxies are disabled. Errors omit websocket endpoints, unrelated titles and raw
protocol exception details. Targets are not logged. The actual manual Windows debug-
Chrome test is still outstanding, as is native WebEngine rendering.

## 6 — Folder scan, thumbnails and selection

Choose a local source folder, optionally include subfolders, set the maximum source
size and an output folder to exclude, then **Scan / reconcile**. Nothing scans on
startup and nothing starts processing after a scan.

- PNG, JPEG, WebP, BMP and TIFF suffixes are candidates; bytes must decode as a
  supported single-frame image. Corrupt, animated/multipage and oversized files are
  invalid, never selected. The actual decoded format is recorded.
- Default maximum 32 MiB per source (configurable up to 64 MiB), 40 million pixels,
  2,000 images per scan, 256 MiB aggregate read budget and bounded traversal/time.
  A large scan can take time; the frontend allows up to 120 seconds for its one
  acknowledgement, never retries it. Choose smaller folders if a limit is reached.
- Symlinks/junctions/reparse entries are excluded, hardlink aliases deduplicated by
  filesystem identity, and `_AI` / `_AI_2` / numbered variants excluded case-insensitively.
  The output folder cannot contain the source root. No source is overwritten.
- Reads compare filesystem identity/size/mtime before and after, store SHA-256 and
  dimensions, and create small metadata-free JPEG thumbnails. A changing/unreadable
  source becomes invalid. This is not a guarantee against a hostile process racing
  parent-directory replacement; use trusted local folders, not mutable network mounts.
- New files start deselected/requiring review. Check a row or use **Select valid**,
  **Skip valid**, **Require review**. These are explicit, undoable local decisions.
  Bulk Select includes changed valid files: inspect the list before choosing it.
- Selection is bound to the observed content fingerprint. Changed bytes invalidate
  an old selection; missing/invalid files are never eligible. Undo cannot turn an
  old fingerprint into permission to use changed bytes. A failed directory traversal
  does not mark unseen files missing or publish a partial reconciliation.
- Observations/thumbnails live outside undo under `jobs.sources`; selection lives
  in editable state. Restart preserves both but does not revalidate files or start
  work. **Rescan after restart**; the future preparation step must re-read/fingerprint
  each selected source immediately before use. Cached “available” is not live proof.
- No completion is inferred from output filenames. Manual decisions cannot fabricate
  completed jobs, reset attempts or remove submission/output evidence. Detailed output
  reconciliation belongs to Steps 9–10, not this pre-submission scanner.

## Extraction/provenance

Byte-identical retained UI modules and source SHA-256 are recorded/tested in
`ui/retained-manifest.json`: preset template chips, stack drag family/styles, block
form row builders, plus the already extracted sash system. New adapters wire these
to one JSON state authority and escape user-provided field names/text.

Python is **adapted, not byte-identical**: `workspace/libraries.py`, `library_io.py`
and `legacy_libraries.py` retain the named JSON-store/portable-preview contracts from
`stores/preset_store.py`, `services/preset_io.py`, window validators and `bot_presets.py`.
`workspace/variables.py` adapts `services/bot_variables.py`'s regex/one-pass/visible-
unknown behavior. `browser/transport.py`, `discovery.py`, `lease.py` and `session.py`
adapt `backend/cdp_client_transport.py`, `backend/cdp_client.py` and
`services/cdp_service.py`: same aiohttp discovery, websocket request IDs/pending
futures/receive loop, lease handoff and discovery-vs-connection separation. Removed
chat consumers, fuzzy matching, cookie/input helpers and unsafe logging; no Playwright
replacement or old-folder runtime imports. The high/low collector priority distinction
is unnecessary here; user checks share cancellation-safe FIFO ownership.
