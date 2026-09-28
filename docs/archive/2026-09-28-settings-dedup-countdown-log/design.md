# Settings de-duplication + countdown log (2026-09-28, owner request)

Owner: *"1 change — do not need duplicate settings (min cooldown, captcha penalty):
remove from Settings, it exists in the URL list; leave those controls in URL only.
2 fix — the log repeats the cooldown countdown every few seconds: only every
1 min, and 2 in the last minute maximum."*

## 1. What the code does today (read first)

| Fact | Where | Consequence |
|---|---|---|
| Settings → Job Cycle box has `cooldownEnabled`, `cooldownMinMinutes`, `cooldownCaptchaMinutes` | `index.html`, `settings.js` (`saveCooldown`, `_onCooldownConfig`, …) | duplicates the URL List bar (`⏳ pause · +captcha · +limit · on · Save`, `url-list/actions.js` + `cooldown.js`) — same session keys |
| Settings **Save** also calls `saveCooldown` with ITS copies, and no rate-limit value | `settings.js save()` | Settings Save overwrote the URL List's values and reset the rate-limit penalty to the 30 min default |
| `set_cooldown_config` writes every key, absent = default; `new_tab` absent = off | `ui/panels/page_pool.py`, `new_tab.save_setting` (I-79) | **bug from I-79: the URL List Save turned "Start new chat as new tab" off** |
| Workspace restore reloads `SettingsPanel.loadCooldownConfig` | `workspace.js WS_CONFIG_RELOADERS` | the only live reload of restored cooldown values (RULE 24) — the URL List bar was never reloaded |
| `wait_for_tab_ready` logs `⏳ Tab … cooling MM:SS — next job waits` every `_LOG_EVERY_SEC` = 10 s | `cooldown_service.py` | the spam: ~30 lines per 5-minute pause; the only repeating cooling line (finish / restore / Clear time lines are one-off) |

## 2. Decisions

* **D1 — one home for the pause values: the URL List bar.** The Settings box loses
  the enable checkbox (same key as the bar's `on`) and both minute inputs; it keeps
  the I-79 option and a pointer line to the URL List bar.
* **D2 — a save writes only what it carries.** `set_cooldown_config` stores a cooldown
  key only when the payload has it (bad value → clamp default, as before) and the
  new-tab keys only when `new_tab` is present; the reply is the full stored config.
  Settings Save sends only `{new_tab, new_tab_url}`; the URL List Save only its four.
* **D3 — restore reloads both owners**: `UrlList.loadCooldownConfig` + `NewTabSetting.load`
  replace `SettingsPanel.loadCooldownConfig`.
* **D4 — countdown milestones** (`core/cooldown.countdown_mark`): whole minutes while
  more than a minute is left, then `01:00` and `00:30`; a line is written when the
  mark changes (the first check writes one). 5-minute pause: 6 lines instead of ~30.

## 3. Tests first

`tests/test_cooldown_countdown_log.py` (marks + a scripted 5-minute wait: 6 lines,
≤ 2 in the last minute); `tests/test_new_tab_setting.py` (URL-List-style payload keeps
the option; option-only payload keeps pause/captcha/limit); jsdom
`test_new_tab_setting.mjs` (no duplicate inputs, Settings Save payload = the option only,
restore reloaders).

## 4. Round 2 (same day, owner): "too many — 2 messages max: first minute and last minute"

Per-minute lines were still 6 per 5-minute pause and 16 per 15-minute penalty, and the
live run's "⏳ All tabs cooling" line repeated every 5 min on top. **D4 replaced:**
`core/cooldown.countdown_phase` = `cooling` / `last minute` (≤ 60 s). Both waiting
loggers write a line only when the phase changes — the wait's start and its last
minute, **2 at most** (1 when the wait starts inside the last minute):
`wait_for_tab_ready`, and the supervisor's all-cooling reason (keyed on the soonest
tab; its 5-minute reminder is off, the other reasons keep theirs; `_live_reason`
still holds the plain reason for the run badge, the phase is `_live_phase`).
The one-off pause-start line at the job's finish (`⏳ Page … cooling 05:00 (total …)`)
is not a wait line and is unchanged.
