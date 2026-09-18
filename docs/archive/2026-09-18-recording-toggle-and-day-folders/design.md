# Recording toggle + per-day folders — design

Date: 2026-09-18 · Scope: `app/services/captcha_recording/`, `app/ui/services/captcha_recordings_bridge.py`, records panel HTML/JS, `tools/analyze_captcha_recording.py`.

## 1. Request

1. **Record on/off toggle** in the Captcha Session Records window so the user decides
   which sessions are captured for debugging (instead of always-on).
2. **Split all records by day folders** — one folder per UTC day.

## 2. Problem understanding

- Recording lifecycle: `CaptchaService.handle_captcha` → `RecordingManager.start(ctrl, encounter)`
  per visible encounter → `finish/abort/note`. Start is the **only** creation point, and it is
  already fail-open (returns `None` on any problem). Toggle check belongs there.
- Storage: `RecordingStore` writes `config/captcha_recordings/<session_id>/` flat
  (manifest.json + events.jsonl + snapshots/). 34 legacy sessions already exist in that flat
  layout and must keep working (listing, detail view, open-folder, delete, analyzer, retention).
- Consumers of the layout: `RecordingStore`, `EvidenceReader`, `prune_recordings`
  (retention), `tools/analyze_captcha_recording.py`, and the tests. All key off
  `root/<session_id>` today — the single change point is the folder location, discovered by
  session id (ids are time-prefixed `YYYYMMDDTHHMMSS-hex`, unique across days).
- Persistence conventions: local settings live in `config/*` JSON files owned by their service
  (`2captcha.json`, `captcha_stats.json`). The recordings package is self-contained and Qt-free;
  its toggle belongs in its own root, not in app_state.
- UI conventions: checkbox row like `#captchaEnabled` in the 2Captcha panel; bridge slots return
  JSON strings; JS panels are small DOM functions.

## 3. Design

### F1 — recording toggle

- **State**: `config/captcha_recordings/settings.json` → `{"recording_enabled": true}`.
  Default **on** (preserves today's always-on behavior; turning off is the user's opt-out).
- **Owners**:
  - `store.py`: module fns `recording_enabled(root)` / `save_recording_enabled(root, enabled)`
    (missing/corrupt file → default on, fail-open) + thin `RecordingStore.is_enabled()` /
    `set_enabled(bool)`.
  - `manager.py`: pass-through `is_enabled()` / `set_enabled(bool)`; `start()` returns `None`
    **before** building any recorder when disabled (no session folder, no CDP probes, no log
    noise — the UI switch is the status source of truth).
  - `CaptchaRecordingsBridge`: slots `recording_enabled()` and `set_recording_enabled(bool)`
    → JSON, same error shape as the other slots.
  - Records panel HTML: checkbox row `#captchaRecordToggle` under the recording note;
    `captcha-recordings.js` loads the state on init and persists on change.
- **In-flight behavior**: toggling never interrupts an active recording — a session runs to its
  natural end (bounded by the encounter, ≤ ~2 min). New encounters respect the current state.
  `finish/abort/note` already no-op on `recorder=None`, so the disabled path changes nothing
  else in the service.
- Deleting the whole `config/captcha_recordings/` folder resets the toggle to on (acceptable:
  the setting is scoped to the recording store).

### F2 — per-day folders

- **Layout**: `config/captcha_recordings/YYYY-MM-DD/<session_id>/…`, day = UTC date derived
  from the session-id stamp (single source of time, consistent with `started_at`).
- **Layout detection** (migration-safe, both layouts coexist):
  - child of root matching `^\d{4}-\d{2}-\d{2}$` → **day folder** → its subdirs are sessions;
  - any other child → **legacy flat session folder** (the existing 34 sessions, unchanged).
  Session ids can never look like a day stamp, so the discriminator is unambiguous.
- **Shared layout helpers** live in `retention.py` (the leaf module `store.py` already imports —
  no cycle; it becomes the disk-layout module, docstring updated):
  - `day_dirs(root)`, `session_folders(root)` (both layouts, oldest-first by name),
  - `find_session_folder(root, session_id)` (legacy first, then days).
  `store.py` drops its own `session_folders`; `EvidenceReader.folder()` and `store.session_folder()`
  both use `find_session_folder` — no duplicated traversal.
- **`store.create()`** writes under the day folder (mkdir parents);
  **`store.session_folder(session_id)`** becomes the public lookup (replaces private `_folder`,
  5 call sites renamed);
  **`delete_session()`** removes the day folder when it loses its last session;
  **`prune_recordings()`** keeps the byte-cap semantics, walks both layouts, and drops emptied
  day folders after each removal.
- **No manifest schema change** — the folder path is self-describing; `schema_version` stays 1.
- **Analyzer**: `main()` root walk becomes `_find_session_folders(root)` covering
  `root/manifest.json` (single-folder mode), flat `root/*/manifest.json`, and
  `root/*/*/manifest.json` (day layout); `settings.json` is a file and never matches.
- **Not touched**: session-id format, retention byte cap, sanitization, UI table model
  (`list_sessions` output shape unchanged — the day folder is invisible to the UI).

## 4. RULE 18 size budget (function 4–20 lines, file 150–300 ideal)

| File | now | after | notes |
|---|---|---|---|
| `retention.py` | 35 | ~66 | +4 small layout fns |
| `store.py` | 161 | ~190 | settings fns + day create + lookup rename |
| `reader.py` | 67 | ~72 | shared lookup |
| `manager.py` | 88 | ~100 | 2 pass-throughs + 1 guard line |
| `models.py` | 33 | ~41 | `day_folder_for` |
| UI bridge | 77 | ~97 | 2 slots |
| HTML / JS | — | +2 / +~25 | checkbox row + toggle loader |

No function exceeds 20 lines; no file leaves the 150–300 ideal band (small leaves stay small,
matching existing precedent: `sanitize.py` 66, `probes.py` 25).

## 5. Tests (written first, RED → GREEN)

Store: session lands under `root/<UTC day>/<id>`; flat-legacy + day sessions list together;
delete-last-session drops the empty day; toggle round-trip + default-on.
Manager: `start()` short-circuits when disabled (zero CDP calls, zero sessions); records when
enabled (reusing the `FakeRecordingCDP` double).
Retention: day-layout prune removes oldest and drops the emptied day.
Reader: detail lookup through a day folder (existing evidence-reader test now exercises this
automatically via `store.create`).
Bridge: toggle slots round-trip on the fake manager.
Analyzer: `_find_session_folders` finds flat + day + single-folder layouts.
Recorder test updated to the public `session_folder()` lookup (flat-layout assumption removed).

## 6. Boundaries

- Recordings stay local; `config/captcha_recordings/` remains git-ignored (settings.json too).
- RULE 20 untouched: the toggle affects evidence capture only, never solve policy.
- No force-push, session-branch-only push as always.
