# Grid "save not working": layout is saved fine — the boot restore has one fragile path

## 1. Report

User (2026-09-18): "fix grid save is not working! still move the win and close app but
win on restart is resetted. but should see same frin as i leav the last time!" — i.e.
after dragging panel windows (the sash-grid "windows") and closing, restart shows the
default layout instead of the saved one. This is despite the round-5 fix
(`978bdd7`: sync close-flush + boot restore guard).

## 2. Research

**The save side is verified sound.**
Drag end → `SashGrid._save()` → `App.bridge.save_grid_layout(payload)` → bridge slot →
`config.set_state(grid_layout=…)` → `SessionStore.set()` → **immediate atomic write to
`config/session.json`** (no debounce; `SessionStore.set` calls `save()`). The 11:26 close
flush (round 5) is a second safety. The user's own `session.json` contains a live v4 tree
(14 panels) written by exactly this path — saving demonstrably reaches disk.

**The restore side is a single fragile point.**
On boot, `SashGrid.init()` → `_loadFromBackend()` →
`App.bridge.get_grid_layout((raw) => { apply; _finishRestore() })`.
That is ONE QWebChannel `invokeMethod → response` round trip. The callback fires only if
the response message arrives:

- a Python slot exception inside the meta-invoke (or any PySide/Qt version quirk) →
  no response sent → callback **never fires**;
- the slot returning `""` (no saved layout / canonicalization reject) → the `if (raw)`
  branch is skipped **silently**;
- `SashCore.deserialize` reject → `console.warn` only — invisible to the user (browser
  console, not the LogConsole panel).

Any of these leaves the grid on the default tree, **with zero log lines in the app** —
the user just sees "reset". Same pattern applies to `get_window_states`
(closed/minimized panels).

**Why the round-5 guard did not catch this.** It fixed a *save* race (boot-time save
overwriting the not-yet-arrived restore). It assumed the restore response arrives. No node
test exercises `_loadFromBackend` at all (zero references to `get_grid_layout` in
`tests/js/`) — the guard was tested for the save side only.

**The proven delivery channel is the signal path.** Every log line, stat, balance, and
pool update reaches the user's UI via QWebChannel **signals** — those demonstrably work in
the user's environment. A signal push of the saved layout at boot is immune to a lost
`invokeMethod` response: the JS side requests the push *after* it has just successfully
invoked a slot (proof the channel is ready), so the signal cannot be lost to a handshake
race.

## 3. Design

1. **Signal-push boot restore (the fix).**
   - `Bridge` gains signals `grid_layout_restored(str)`, `window_states_restored(str)` and
     slots `request_grid_restore()`, `request_window_states_restore()`. Each slot reads the
     saved value (via the existing `get_grid_layout` / `get_window_states`) and, if
     non-empty, emits it as a signal; both log the decision (Python side).
   - JS `_loadFromBackend()` keeps the callback path as primary, then calls
     `_bindRestorePush()` (connects the two signals once) and the two request slots.
   - New idempotent appliers `_applyBackendGrid(raw)` / `_applyBackendStates(raw)`
     (single writers): apply only when the payload differs from the current root/states,
     so callback-then-push double delivery renders once.
2. **Observability (reason visible, round-3 principle):**
   - JS LogConsole lines: `🪟 Grid restored from session (N windows[, migrated])` /
     `🪟 Grid restore rejected: <reason>` / `🪟 Grid restore failed: <e>` /
     `🪟 Grid restore: backend response pending — guard released (3 s)` (the 3 s guard
     timeout with nothing applied — the smoking gun if the whole restore path is dead).
   - Python lines: `Grid restore: pushing saved layout (N chars) to UI` /
     `Grid restore: no saved layout — UI keeps default`.
3. **Invariants kept:** backend `session.json` remains the single source of truth; save
   path unchanged; restore guard (`_restorePending`/`_saveQueued`) unchanged; one writer
   per state; badge/dialog visibility predicates untouched.

## 4. RULE 18 recheck (changed code)

- `bridge.py`: `request_grid_restore` 11 LOC, `request_window_states_restore` 6 — 4–20
  band; ≤1 param; CC 2. (Class-level [LEGACY] warnings unchanged/grandfathered.)
- `sash-grid-windows.js`: `_applyBackendGrid` 20, `_applyBackendStates` 12,
  `_bindRestorePush` 8, `_loadFromBackend` 24 (callback bodies moved to appliers),
  `_finishRestore` 11.
- Tests: AST guard (`REQUIRED_SLOTS` +2), node restore scenarios (6, new
  `test_sash_restore.mjs` + harness `sandbox` export), Python functional (4;
  emit asserted only where real Qt loads — headless sandboxes without GL fall
  back to the module's fake Signal stubs).

## 5. Verification (2026-09-18)

- node 96/96 (was 90): restore via push when the response is lost; callback+push
  double delivery renders once; nothing delivered → default kept + `🪟 Grid restore:
  no backend response` warning; callback-only apply + log; window states via push;
  no-bridge boot stays quiet.
- pytest **299** (was 295): slot returns saved payload + emits (real-Qt env),
  no saved layout → `""` + no emit, window-states round trip, restart round trip.
- gates: `verify_quality.py --changed --allow-legacy` **0 fails**.
- live acceptance: next restart must show `🪟 Grid restored from session (N windows)`
  in the LogConsole and the exact frame the user left; a failed restore must now
  name its reason in the log instead of silently resetting.
