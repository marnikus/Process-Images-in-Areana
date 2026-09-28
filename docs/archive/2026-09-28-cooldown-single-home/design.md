# Cooldown controls — one editing home (2026-09-28, owner spec "DUPLICATE COOLDOWN CONTROLS")

The owner's screenshot shows build `8410cb9`; the two numeric inputs were already
removed from Settings in `a12a262` (I-80). This round closes the spec's remaining
acceptance points and reverses one decision the spec did not approve.

## 1. Findings (read before designing)

| # | Finding | Evidence |
|---|---|---|
| F1 | Settings → Job Cycle no longer has Min cooldown / Captcha penalty (since `a12a262`); **but a12a262 also removed "Enable minimum pause between jobs"**, which the spec says to keep unless separately approved | `git show 8410cb9:…/index.html` has 3 ids, HEAD 0 |
| F2 | That checkbox **is** a duplicate: it writes `cooldown_enabled`, the same key as the URL List bar's `on` (`urlCooldownEnabled`) | `url-list/cooldown.js save` payload `enabled` |
| F3 | The URL List bar has **two** handler sets: `url-list/cooldown.js` (`UrlListCooldown`, live — `url-list.js` uses it first) and a copy of the same 5 functions in `url-list/actions.js` (fallback, never reached: cooldown.js always loads) — duplicated validation (0…1440 clamps) | `url-list.js loadCooldownConfig/saveCooldownConfig` |
| F4 | **Arena preset load restores the cooldown values into config but no view reloads** — the URL List bar shows the old numbers until restart | `restore_preset_cooldown` → reply; `arena-presets/render.js _onLoadArena` only logs |
| F5 | Two views of `cooldown_enabled` (F2): saving one leaves the other stale | no push signal for cooldown config |
| F6 | Canonical state = session keys `cooldown_*` via `get/set_cooldown_config` (partial saves since I-80); presets `cooldown` block; workspace restore reloads `UrlList.loadCooldownConfig` | one source of truth already |

## 2. Decisions

* **D1 — restore the checkbox** in Settings → Job Cycle (spec: keep unless approved).
  It stays a *view* of the one key `cooldown_enabled` — no second source of truth — and
  Settings Save sends only `{enabled, new_tab, new_tab_url}` (partial save keeps pause /
  captcha / rate limit). Removal of this proven duplicate (F2) is **offered to the owner**,
  not done.
* **D2 — one handler set** for the URL List bar: the dead copy in `url-list/actions.js`
  goes; `url-list.js` delegates to `UrlListCooldown` only. (Structure — own commit.)
* **D3 — the Settings module is renamed** `NewTabSetting` → `JobCycleSetting`
  (`job-cycle-setting.js`): it now owns the whole Settings → Job Cycle box (enable + new
  tab), and a name that says "new tab" would mislead. (Structure — same commit as D2.)
* **D4 — no stale views, one refresh point**: after every successful `set_cooldown_config`
  and every preset cooldown restore the bridge pushes the stored state —
  `cooldown_config_updated`, the same JSON as the `get_cooldown_config` reply — and
  `JobCycleSetting.apply()` (connected by the module itself, like `JobHistory`) re-renders
  BOTH views (`UrlListCooldown.applyConfig` + the Settings switch / new-tab option).
  *Rejected first draft:* reloading from each caller (Settings save, the URL List save
  callback, the preset render and import callbacks) — four places to remember, and the
  frozen `url-list/cooldown.js` (48 lines, `max_cc` at the hard limit 10) cannot take the
  hook; the push also covers any future writer. Accepted growth: `bridge.py` class LOC
  95 → 96 (one `Signal` line; Qt signals are class attributes).
* **D5 — behaviour unchanged**: no Python change to clamping, stacking or the cooldown
  cycle; `restore_preset_cooldown` keeps its full-restore semantics.

## 3. Tests first

`tests/test_cooldown_single_home.py` — real `ConfigManager` + real slots: values survive a
restart (new `ConfigManager` on the same dir), an older session file (no new-tab keys)
loads with its values, an arena preset restore shows the preset's values through
`get_cooldown_config`, an older preset without a `cooldown` block keeps the current values,
the Settings payload changes only `enabled`. jsdom: Settings shows the checkbox and no
numeric inputs; URL List bar keeps all; Settings save/load; both views refresh after
either save and after a preset load; one handler set.
