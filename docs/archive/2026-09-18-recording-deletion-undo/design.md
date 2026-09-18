# Recording deletion without prompts, with undo — design

Date: 2026-09-18

## Corrected request

- Deleting one recording must happen immediately, with no confirmation.
- No recording operation needs confirmation except **Delete all**.
- Every recording deletion, including Delete all, must be undoable.

## Design

The recording window owns a small, persistent, one-operation undo boundary rather than coupling evidence storage into the main app's unrelated JSON undo projections.

- A new `RecordingDeletionUndo` service stages deletions by moving recording folders into `config/captcha_recordings/.delete_undo/` on the same filesystem. Move is reversible and avoids partially copying privacy-sensitive evidence.
- The service records the moved session IDs in `operation.json`. It persists across an app restart.
- One deletion operation is undoable at a time, matching ordinary Undo semantics. Starting the next deletion permanently purges the previous operation before staging the new one.
- A single delete stages one folder immediately, without a modal.
- Delete all keeps the shared confirmation modal and stages all inactive folders as one operation, so one Undo restores the whole group.
- Active recordings are never staged and Delete all reports them as skipped.
- The store's listing and retention scans exclude hidden control directories, so undo data never appears as a recording and is not mistaken for an old session.
- An **Undo delete** title-bar button invokes a dedicated QWebChannel slot. The UI refreshes and clears stale comparison panes after deletion or restoration.

## Failure behavior

All source folders are validated before staging. If a move fails, already-moved folders are restored before the error is returned. Undo refuses destination collisions rather than overwriting a recording.

## Verification

Tests cover immediate single deletion without confirmation, the sole confirmation on Delete all, single and bulk restoration, active-session skips, persistence across manager reconstruction, path confinement, bridge envelopes, and UI refresh/reset behavior.
