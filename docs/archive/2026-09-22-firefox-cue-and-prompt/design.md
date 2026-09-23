# The robot cue, the "Allow connection?" prompt, and the profile Firefox really uses

Round 10, 2026-09-22. Owner report with screenshots: Firefox shows the robot icon in the URL bar
after start, the launch command in his console uses `-profile` / `-no-remote`, and Firefox asks
*"An incoming request to permit remote debugging connection was detected … Allow connection?"*
over and over. His conclusion: the flags cause remote-control mode, the app must send messages
without prompting, and Firefox must look like a normal browser.

This document separates what is **true**, what is **our bug**, and what is **impossible**, because
two of the four report points are misdiagnosed and acting on them would break the channel.

## 1. Measured facts (sources, not guesses)

| Claim in the report | Verdict | Evidence |
|---|---|---|
| The robot icon = remote-control mode | **True — but not caused by the flags** | The icon is Firefox's own URL-bar element `#remote-control-box` / `#remote-control-icon` (`browser/base/content/navigator-toolbox.inc.xhtml:172-176`), styled in `browser/themes/shared/urlbar.css:992-1010`, with the tooltip string `Browser is under remote control (reason: {component})` (`browser/locales/en-US/browser/browser.ftl:623`). A Mozilla developer (whimboo) states the cue is shown when WebDriver **or the DevTools server** is running, and lists `--start-debugger-server` as one of the three triggers, with "remove them to get the cue removed". It follows the *server*, not `-profile`/`-no-remote`. |
| `-profile` / `-no-remote` trigger the cue | **False** | Same sources. `-no-remote` only makes a *new* instance start (without it, the flag is handed to the already-running Firefox and no socket ever opens — the owner's console shows exactly those repeated hand-offs). `-profile` only picks the profile directory. |
| The icon can be removed while keeping the channel | **False** | It is browser *chrome*: no preference drives it (the pre-Quantum `devtools.debugger.prompt`/`remote-enabled` toggles are gone), and it cannot be hidden without patching Firefox UI files (`userChrome.css`), which is a fingerprint of its own and is not something this app ships. The only way to have no cue is to have no debug server — i.e. no Firefox channel at all. |
| The icon flags the browser to websites | **False — and this is the part that matters** | The icon lives in the parent-process UI; page JavaScript cannot read it. What pages *can* read is `navigator.webdriver`, and that flag belongs to Marionette / the Remote Agent (`--remote-debugging-port`, Firefox bug 1719505), not to the DevTools server this app talks to. Round 10 stops asserting that and **measures it**: `app/browser/stealth.py` evaluates `navigator.webdriver`, the UA and the plugin count in the attached tab and the Diagnose button prints the answer. |
| The prompt reappears forever | **Partly our bug** | `devtools.debugger.prompt-connection=false` is what suppresses the prompt (Mozilla bug 1013379 comment 1). Our `Prepare Profile` writes it — into the *configured* dir, which was `C:\arena-images-firefox` by default while the owner runs his **real** profile. So the running Firefox never saw the pref and asked on every connection. Worse: one pass opened **two** connections per browser (a `probe`, then the real `listTabs`), i.e. up to two prompts per pass. |

## 2. Decisions

* **D-1 — Firefox's default is the browser's own profile.** The Firefox row's `data_dir_default`
  becomes `""`; with no directory configured the generated command is
  `firefox.exe -no-remote --start-debugger-server 9224` and Firefox starts with *its* profile —
  real history, cookies, extensions, the same session the owner browses in. That is what the
  stealth requirement asks for, and it removes the wrong-profile write. A configured directory
  still produces `-profile="…"` (isolation stays available).
* **D-2 — Prepare Profile writes into the profile Firefox itself uses.** New leaf module
  `app/browser/firefox_profiles.py` resolves it the way Firefox does: `profiles.ini`'s
  `[Install*] Default=` entry first, else the `[Profile*]` row with `Default=1`, else the only
  profile present; per-OS roots (`%APPDATA%\Mozilla\Firefox`, `~/Library/Application Support/Firefox`,
  `~/.mozilla/firefox`) with `ARENA_FIREFOX_PROFILES_INI` / `ARENA_FIREFOX_PROFILE_DIR` overrides for
  tests and portable copies. The write itself is unchanged: opt-in, additive, idempotent.
* **D-3 — One connection per listing.** `endpoints.list_targets` asks the row's *declared* protocol
  on one connection and only falls back to probing when that fails; for Firefox that single attach
  both lists the tabs and proves the channel. Two sockets per pass became one, so at most one
  Allow per pass even on a profile where the pref is missing.
* **D-4 — The cue is named, never hidden.** `browsers.py`'s note and `stealth` sentence, the
  Settings panel, README and the system of record all say what the icon is, that it is local-only,
  that web pages cannot see it, and that it is the price of *any* Firefox debugging channel.
  No UI patching, no claims about it being gone.
* **D-5 — Stealth is measured, not asserted.** `app/browser/stealth.py` holds the one expression
  and the one verdict: `navigator.webdriver`, UA, plugins, languages, and a headless marker. The
  Diagnose path prints one line, and a `True` webdriver is named as the problem instead of being
  papered over.
* **D-6 — The flags stay, with their real meaning.** `-no-remote` is what makes the socket open at
  all while Firefox is running; `-profile` is optional isolation. Neither is a cue and neither is
  removed. The panel says so in one sentence, next to the command.

## 3. Files

| Action | Path | What |
|---|---|---|
| new | `app/browser/firefox_profiles.py` | `profiles_ini_path`, `parse_default_profile`, `default_profile_dir`, `profile_source` |
| new | `app/browser/stealth.py` | `STEALTH_JS`, `parse`, `verdict`, `line` |
| edit | `app/browser/browsers.py` | Firefox `data_dir_default=""`; `build_command` omits the dir flag for an empty dir; notes/stealth text |
| edit | `app/browser/endpoints.py` | `list_targets` — declared protocol first on one connection, detection only as fallback |
| edit | `app/browser/rdp/profile.py` | `prepare_profile` resolves the default profile when no dir is configured |
| edit | `app/ui/panels/cdp_tools.py` | row payload `profile_dir` / `profile_is_default` / resolved `prefs_file`; `prepare_active_profile` passes the resolved dir; Diagnose logs the stealth line |
| edit | `app/ui/panels/browser_tabs.py` | `report_stealth(bridge)` — the one measured stealth line (any channel) |
| edit | `app/ui/web/js/panels/browser-connection.js` | `compose()` omits an empty dir flag; the dir label names the default profile |
| edit | `tests/fakes/rdp_stub_server.py` | answers the stealth expression (a fake session with `webdriver=false`) |
| new | `tests/test_firefox_cue.py` | the round's contract |
| edit | `docs/current/SYSTEM_OF_RECORD.md`, `docs/current/QUALITY_RECHECK.md`, `README.md` | the living truth |

## 4. Rejected alternatives

* **Patch Firefox's UI to hide the icon** (`userChrome.css`): another fingerprint, breaks on
  updates, and it is the user's browser, not ours. The honest answer is the one above.
* **Drop `-no-remote` as the report asks**: the debug flag would then be handed to the running
  instance and ignored — the channel would simply stop opening. This is the one point of the
  report we must not implement, and the panel explains why.
* **Auto-accept the prompt by writing prefs into the running profile without asking**: the write is
  the same one the owner can already trigger with Prepare Profile, but doing it silently changes a
  browser the app does not own. It stays opt-in.
* **`getPreferences` / `setPreferences` over RDP to fix the pref live**: those root-actor requests
  are gone from current Firefox (searchfox: no such request type in `devtools/`), so relying on
  them would be a guess. The profile file is the mechanism Firefox actually documents.
* **Keep two connections per pass and call it harmless**: it doubles the prompt when the pref is
  missing, and one pass should ask a browser one question.

## 5. Tests first (RED at `9abda34`)

`tests/test_firefox_cue.py`: the default Firefox command carries no `-profile` but keeps
`-no-remote` and the DevTools flag; a configured dir still wins; `profiles.ini` resolution
(`[Install*] Default`, `Default=1`, single profile, nothing → `""`); `prepare_profile` with no dir
writes `<real profile>/user.js` additively and reports "already" on the second run; the Settings row
carries `profile_dir` + `profile_is_default` and a `prefs_file` inside the real profile; one listing
pass opens exactly one connection (the fake Firefox counts them); a Firefox row on a CDP endpoint is
still found (the ESR path survives D-3); the stealth probe returns the page's own answer and the
verdict names `navigator.webdriver=true`; the row's text names the URL-bar cue, the Allow prompt and
the pref that removes it.

## 6. Outcome (2026-09-22)

Delivered as designed; measurements and gates in `docs/current/QUALITY_RECHECK.md` addendum **2026-09-22**,
living truth in SoR **I-62** clause (k).

* **Own profile by default** — `firefox.exe -no-remote --start-debugger-server <port>`; a configured dir still
  gives `-profile="…"`, and an empty dir means no dir flag for Chrome/Edge too.
* **`profiles.ini` resolution** — `Prepare Profile` writes `<real profile>/user.js` (additive, idempotent,
  opt-in) and an unresolvable profile is a named refusal, never the current directory.
* **One connection per pass** — the fake Firefox counts one socket per listing where round 9 made two.
* **The cue and the flags, told straight** — the row, the README and the SoR name the URL-bar cue, say pages
  cannot see it, and keep `-no-remote` with the reason it exists.
* **Measured stealth** — `app/browser/stealth.py` + Diagnose's `🔎 Stealth check … navigator.webdriver=false …`,
  with a flagged session named loudly.

Numbers: pytest **2,171 passed / 4 skipped**, JS **377 (375 pass, 0 fail)**, coverage **89.17 % line /
84.58 % branch** (baseline 86.36 / 82.33), `verify_quality --changed-files` **0 fails**, new modules at
92 % / 97 % line coverage. RULE 16 during the round: `_list_over` 5 params → an `_Endpoint` value object.
