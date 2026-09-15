# Dark workspace and durable global undo

Steps 2–3 extract the **actual retained sash-grid** (tree model, panel/window controls,
drag/drop, resize and dock) into `src/image_queue/ui/`, rendered by PySide6 WebEngine
and WebChannel. There is no runtime import from the old app and no database.

## Start

```sh
python -m pip install -e '.[dev,desktop]'
npm ci --ignore-scripts
python -m image_queue desktop
```

Windows Command Prompt uses `".[dev,desktop]"` rather than single quotes. Python 3.11+
is required. Linux additionally needs Qt's system GL/EGL, NSS, DBus, XKB and audio
libraries (see the inactive desktop CI template at `tools/ci/quality.yml`). No sandbox-disabling flags are added by the app.
An optional `--data-dir <directory>` selects an isolated workspace, useful for testing.
Otherwise `platformdirs` chooses the platform's per-user `ImageQueue` data directory.
The app never launches Chrome. Explicit discovery/check commands are available in Step 5; no connection occurs on startup.

## Retained interactions

- Drag a window title; drop on an edge to split. Resize by dragging a sash.
- Minimize to the bottom dock, close a panel, reopen it from Windows, or show all.
- Choose original built-in layouts A/B/C/Default in Layouts.
- Save, apply and delete named **layout** presets. Apply is one global undo command.
- Edit prompt, exact URL lines, source-folder path, local debug endpoint and rectangle
  timing. Folder picker stores the chosen path; **Scan / reconcile** explicitly scans it.
- Undo/Redo spans all these editable surfaces chronologically. Ctrl/Cmd+Z, Shift+Z,
  and Ctrl+Y operate globally outside an editor. Focused text fields retain native
  text editing; toolbar Undo/Redo first commits that editing session.
- Text commits on blur/change; a drag/resize commits once on release. Repeated save
  hooks within the same gesture coalesce. Native close awaits a final checkpoint.

The generation button remains disabled. Preset/template/variable libraries, inert
workflow/block editing, Chrome checks and image scanning are now available; see
[Steps 4–6 operation and limitations](STEPS-4-6.md). Old files remain intact and are
never imported automatically. All editable fields share the same workspace/history.

## Explicit panel mapping

Stable old IDs retain geometry meaning; visible content is new. No old stored layout
or preset is automatically imported into a changed product.

| Retained ID | New title |
|---|---|
| stats | Progress |
| filters | Source folder |
| stack | Workflow |
| config | Settings |
| composer | Prompt |
| people | Image queue |
| log | Activity |
| history | Job history |
| userdb | Saved outputs |
| collector | File changes |
| labels | Variables |
| dbconn | Chrome URLs |
| botchat | Job inspector |
| botprompt | Prompt templates |

Closed-by-default future panels are available from Windows with an honest not-yet-built
message. All fourteen IDs remain in every validated tree, including closed panels.
`ui/retained-manifest.json` records original paths/hashes. Sash-core's visible labels
are the only change to its model; the persistence adapter overrides the old localStorage
hooks. The old default layout version is 4; imported old portable presets require an
explicit compatibility preview in Step 4, not automatic reuse by format coincidence.

## One JSON authority

`state.json` contains version/revision, editable workspace, history/cursor and reserved
immutable `jobs` data. `state.backup.json` is the previous valid snapshot. There is no
independent localStorage/config/undo writer. The embedded page uses an off-the-record
profile with localStorage disabled; only the worker-owned service can publish state.

Each user command carries its expected revision. The service copies/validates state,
computes before/after history, writes and reads back the complete snapshot, then
publishes the new revision. A gesture, named-layout operation or settings edit has one
entry; history is capped at the previous system's 100 entries. Editing after undo
truncates redo. No-op commands do not write or inflate history. Jobs never enter undo.
Future active jobs can lock conflicting edits through the coordinator's `busy` gate.

An OS-backed `FileLock` permits one cooperating app instance per data directory and is
released on crash. Do not manually edit JSON while the application is open. Snapshot
integrity is SHA-256 over canonical JSON (corruption detection, not authentication).
Strict schemas reject unknown keys/versions, duplicate JSON keys, invalid tree sizes,
unknown/duplicate panel IDs, invalid history chains/cursors, non-finite data and oversized
snapshots. A 32 MiB snapshot limit and 30 named layouts bound the MVP workspace.

Writes use unique same-directory partials with restrictive permissions, flush/fsync,
validation, atomic replacement and final readback. POSIX additionally fsyncs the directory;
Windows lacks a portable directory-fsync API, so guarantees exclude hardware/power-loss
or network-filesystem behaviors not established by OS testing. Ordinary process-crash
recovery is tested. Backup is validated before use. A missing primary alongside backup
or orphan partials is recovery evidence, never a fresh empty workspace.

## Failures, recovery and close

Corrupt/unsupported state stops startup. A native dialog offers explicit recovery from
the last valid backup or exit unchanged. Before recovery the current primary is retained
as `state.corrupt-<id>.json`. Neither history nor preset data silently falls back to empty.
If both snapshots are invalid, recovery fails visibly without continuing into the UI.

Failed writes/readback do not advance in-memory state or acknowledge success. A fault
latches the writer; reopen to inspect what actually reached disk, particularly if failure
occurred after atomic publication. Lost Qt acknowledgements also lock frontend edits;
no request is automatically replayed. The close handshake waits for pending edits and
geometry to save, then closes. A missing close acknowledgement offers a confirmation
before exiting; it never pretends unsaved edits are safe. Native geometry restoration
currently preserves bounds, but multi-monitor off-screen placement remains a release
manual check.

## Verification

`python tools/check.py` runs headless behavior/coverage/quality gates, the retained JS
baseline and the extracted DOM against the **real Python service and filesystem** over
a test-only JSON-lines channel. It also executes a real QtCore/QWebChannel transport
test across an actual QThread; the facade stays on the UI thread. `python tools/desktop_smoke.py` separately requires the
real Qt/WebEngine system libraries and tests the actual Qt channel, native recovery
choices, close checkpoint, restart and local-page navigation gate. DOM doubles are not
reported as proof of native Qt success. Native rendering is still unverified here; the CI template is inactive because workflow-write permission is missing. Measured outcomes live in IMPLEMENTATION-STATUS.md.
