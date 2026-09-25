# Design — the autorun handoff proves it landed (delivery receipt + autopsy)

Date: 2026-09-25 · Owner report: *"the log reaches `delivered — waiting for the
savelog file` and never advances"* (90 s freeze, no new tab, XModules present,
file-URL access ON).

## The failure (as diagnosed)

`SendInput` reports success while the keys vanish — focus loss, a modal dialog,
UIPI silence — so the macro never starts and no savelog is ever written (the
savelog is written on success OR error, so no savelog ⟺ the macro never
completed). The old code trusted the keystroke report and waited the full
timeout blind. Deep research cleared the suspects in the macro path instead:
the `tab={pos−count}` math is correct (0-based `pos`, the Ctrl+T invocation tab
appends last, Ui.Vision counts `selectWindow` tabs relative to the macro's
start tab), and the vendored `ui.vision.html` matches the canonical 2019
handshake (`kantuSaveAndRunMacro` / `kantuInvokeSuccess`, `#203` after 8 s,
`#204` after 3 reloads) — no event rename, no template drift.

## The staged wait (`app/browser/uivision/verify.py`)

Receipt, layered cheapest-first, for every address-bar delivery whose keys went
out:

1. **Title receipt** — 1.5 s after Enter the foreground title is read
   (`delivery.Win32Ops.foreground_title`, new `GetWindowTextW` bindings); the
   autostart page in front proves the handoff → the full savelog wait runs.
2. **Bounded store watch** — 25 s (one ~15 s store flush + margin) for this
   run's own savelog stamp in a tab URL. The tab open means the macro is slow
   or silent → progress line + the full wait; anything else the poll answers
   (ok / error / stopped / corrupt) returns as-is.
3. **One confident re-send** — only when a re-read, readable store proves the
   tab absent (transient focus loss is the common flake). A refusal degrades
   to manual; an unreadable store skips the re-send (never re-send blind —
   two tabs would race one savelog).
4. **The named miss** — still nothing after the second watch → `timeout`
   verdict *"no autorun tab opened — the address-bar keystrokes missed (see
   the checklist above)"* + focus/dialog/Ctrl+T/elevation checklist + the
   manual URL reprinted.

A **refused** prime delivery skips the receipt theater: the manual fallback
already printed, so the run waits the full deadline patiently (the user is the
delivery mechanism now). Every timeout — staged, patient, cold, or manual —
gets the **autopsy**: open-but-silent (file-URL/`#204`/case-exact/first-run
checks) and never-opened (focus/dialog/remap/elevation checks) are different
failures with different checklists, plus the manual URL reprinted while warm
(reason + step; the wait line would lie after expiry). The autopsy adds lines
only — the poll's verdict stands.

## Prefright + structure

* **Per-profile addon preflight** — the global detect only knew SOME profile
  has Ui.Vision; `verify.warn_addonless_profiles` warns per target profile
  whose `extensions.json` lacks it (runs there stall on `#204` every time).
  Unreadable stores stay silent (RULE 4: no guessing from silence).
* **`Sequence` 191 → 85 lines** — the attempt/foreground/deliver/cold engine is
  module functions now (`_attempt_run`, `_foreground_run`, `_deliver_and_poll`,
  `_send_addressbar`, `_cold_launch`); the class keeps the loop + rollup.
* **`plan.run_scope`** is the single source of the `run i/n (label): ` prefix
  (was a 191-line-class private method used 15×).
* Rejected: `loadmacrotree=1` (tree-UI only), extension-storage XModule-home
  preflight (undocumented keys), an elevation/UIPI probe (over-scope), failing
  on a title-receipt miss (unsafe — the store watch is the backstop), and a
  `RAISE_SETTLE` bump (the re-send is the robust answer, not blind tuning).
* RULE 18 note: `uivision/` is now 16 modules (past the ~15 ideal) — one
  cohesive feature (one window, one flow); splitting the package would scatter
  it. All new/edited code is within the absolute limits; the suite + gate
  numbers are in the commit message.

## Follow-up (same day): the count assert + UIPI precheck

The first field log (0-for-4: prime + re-send × two windows, readable store,
verified foreground) proved a DETERMINISTIC silent miss, not a flake — which
sent the audit back into `delivery.py`, where it found a real bug:
`if not user32.SendInput(...)` treats a PARTIAL injection (3 of 4 events
accepted — a hook, hotkey app, or antivirus swallowing some) as success,
because only 0 is falsy. MSDN's own example asserts the exact count
(`uSent != ARRAYSIZE`), and Whisperlet #67 (2026-09) documents the identical
"silently dropped and reported as done" shape with the identical fix — plus
the integrity-level comparison, since "neither GetLastError nor the return
value will indicate the failure was caused by UIPI blocking". So:

* `_send_keys` asserts `injected != len(events)` → `DeliveryError` naming the
  interception (a 0-return keeps failing as before, now with its count).
* New `integrity.py` (~145 lines): `check_delivery(hwnd, ops)` compares OUR
  mandatory-label RID with the target window's process (GetWindowThreadProcessId
  + OpenProcess + GetTokenInformation) and `deliver_url` refuses LOUDLY before
  the first keystroke on proof of mismatch (target higher), on an unopenable
  process (≈ elevated — same-level Firefox always opens for a limited query),
  or on a dead window; unknowns proceed (the receipt ladder backstops them).
* The key bytes are now pinned on Linux too: `_ctrl_sequence` / `_enter_sequence`
  / `_key_inputs` are pure (event lists → real INPUT arrays), and the SendInput
  count assert is tested through a fake `windll` (3-of-4 must raise, full echo
  must not) — the previously untestable seam, closed.
* RULE 18 note: `delivery.py` is now ~326 lines (past the 300 ideal) — one
  responsibility (address-bar actuation: keys + clipboard paste are inseparable),
  the trust half already split to `integrity.py`; `uivision/` is 17 modules
  under the same one-feature reason as before.
