# Recording history visibility and removal — design

Date: 2026-09-18

## Request

1. Let the Recordings window show every locally retained recording, rather than imposing a UI/API page limit.
2. Let the user remove recordings.

## Existing behavior and constraints

- The canonical schema-v2 store is `config/captcha_recordings/`.
- Storage is deliberately bounded by the existing retention policy (200 sessions / 512 MiB). “All” therefore means every recording still retained locally; already-pruned evidence cannot be reconstructed.
- The UI currently requests 200 rows and the store clamps list requests to 1–1000.
- There is no removal API.
- Recording folders contain privacy-sensitive evidence. Removal is permanent and must require explicit confirmation.
- An active recording must never be deleted while its writer is running.

## Design

### Listing

`RecordingStore.list_sessions(limit=None)` returns all retained summaries when the limit is omitted or non-positive. Positive limits remain supported for compatibility. The QWebChannel bridge exposes `list_all_sessions()`, and the panel uses it with a fallback to the old bounded slot.

The summary says “all N retained sessions” so “all ever done” is not confused with evidence already removed by retention.

### Removal

- `RecordingStore.delete_session(id)` validates the ID through the existing confined `_folder` lookup and permanently removes that one folder.
- `RecordingManager.delete_session(id)` rejects active session IDs before delegating.
- `RecordingManager.delete_all_sessions()` removes every inactive retained session and reports deleted/skipped counts.
- QWebChannel slots return the standard JSON success/error envelopes.
- Each table row gets a Delete action; the title bar gets Delete all. Both use the shared in-app `Dialog.confirm` modal and refresh after success.
- Comparison selections are reset after deletion to prevent stale evidence panes.

## Safety and verification

Tests must prove: unlimited listing, single deletion, path validation, active-session refusal, bulk deletion with active sessions skipped, bridge envelopes, and UI behavior. Run focused tests, complete Python and JavaScript suites, RULE 16, compileall, and diff checks.
