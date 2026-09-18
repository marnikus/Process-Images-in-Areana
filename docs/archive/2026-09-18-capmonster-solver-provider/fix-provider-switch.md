# Fix — provider drop-down snapped back to 2Captcha

Date: 2026-09-18 (same day as the provider feature; record of the user-reported
defect and root cause). Companion to `design.md` / `implementation.md` in this
folder.

## Reported

"Unable to switch to another provider. It resets back to 2Captcha because it is
unable to check balance. It should always let me select a provider and save the
API key — without a key it cannot connect and check balance, of course."

## Root cause (verified in code)

UI-only defect in `app/ui/web/js/panels/captcha.js`. The provider `<select>`'s
`change` handler called `loadStatus()`, and `loadStatus()` re-synced the
drop-down from the **stored** active provider (`sel.value = r.provider`). The
stored provider is still `2captcha` until a save happens — so the moment the
user picked CapMonster Cloud, the status reload snapped the selection back
before Save could ever commit it. The backend was never at fault:
`apply_settings` saves the selected provider unconditionally, a failed balance
check only writes `stats.last_error`, and no backend path ever reverts the
provider.

## Fix

The drop-down is now **user-owned**:

* `_providerTouched` flag — status reloads sync the drop-down only before the
  user's first change (initial window load); after that they never re-sync
  until a successful Save (which resets the flag — stored state then matches).
* On change, the panel renders the **selected** provider's cached per-provider
  state (enable + masked key from `status_payload().providers`), clears the key
  field, and appends `· press Save to switch` to the status line. Balance /
  last-error are shown only for the provider they were fetched from.
* Switching with no key saved is fully allowed; enabling without a key still
  saves the provider selection and logs a warning (`enable needs an API key —
  provider selection saved, paste a key and save again`).
* Balance failures keep reporting via `last error: …` — they never revert the
  selection (RULE 4: report, don't silently undo).

## Tests (RULE 8)

`tests/js/test_captcha_panel.mjs` (NEW, registered in `package.json`
`test:js`) — executes the real panel source against a stub DOM + stateful fake
bridge (mirrors the real contract: Save commits the active provider):

1. initial load syncs the drop-down to the stored provider;
2. **switching never snaps back — even on later reloads** (the regression);
3. status line shows the selected provider's state + Save hint, never the
   other provider's mask/balance;
4. Save posts the selected provider + key and the selection survives the
   post-save reload;
5. enable-without-key still saves the provider and warns;
6. balance/last-error shown only for the active provider.
