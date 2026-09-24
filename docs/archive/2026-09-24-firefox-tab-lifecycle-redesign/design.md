# Firefox tab lifecycle redesign — one run per profile, URL-driven tab index, remoting-free delivery

Date: 2026-09-24. Bug report: tab detection & lifecycle failures (E212 tab-not-found,
user tabs harmed on error, first run fails / N autostart tabs storm the first profile).

## 1. What the research proved (and what it killed)

R1. **`firefox -P <name> <url>` does NOT reach a running non-default profile.**
Firefox's remote command line "ignores the profile parameter" (`nsAppRunner.cpp`;
SuperUser q/119014) and reuses the already-running instance; users report the `-P`
flag "seems to be ignored" when profiles run side by side (support.mozilla q/1267056).
Simultaneous profiles additionally require `-no-remote` on the extra instances —
banned vocabulary here (I-62) — and `-no-remote` instances accept NO remote URLs at
all. Consequence: every per-tab launch of the old planner landed in the FIRST
instance — the reported N-autostart storm, the over-clicking, the unreached profiles.
The old premise ("Firefox's own per-profile remoting hands the URL to THAT running
instance") was wrong and is retired.

R2. **`selectWindow` has no `url=` selector** (ui.vision/rpa/docs/selenium-ide/
selectwindow: only `title=` with `*` wildcards, `tab=N` relative to the start tab,
`tab=open/close/closeallother`). The report's literal `url=*pattern*` is therefore
unimplementable; the URL-driven equivalent is `tab=N`: the session store names WHICH
tab matched the URL filter, and the run addresses it by relative index
(`target_pos - window_tab_count`, autostart appends last so offsets are negative).
Title text is never constructed for these runs — dynamic/stale titles were the E212
("failed to find the tab with locator 'title=*…*'") source.

R3. **`selectWindow` itself is flaky** (forum: ~95%, "tab is there with the expected
title but not found"; once it errors the macro is dead). Mitigation: ONE bounded,
side-effect-free retry on the stable message shape "failed to find the tab with
locator" — that message can only come from the macro's FIRST command (selectWindow),
i.e. before any click fired, so the retry cannot double-click.

R4. **No current code path closes user tabs** (macro holds no `tab=close`; the
autorun page's `window.close()`/`about:blank` is own-tab-only by web semantics;
Python never touches tabs). The reported tab loss rides the storm from R1
(concurrent macro instances sharing one active tab + repeated native clicks).
The fix removes the storm AND makes the protected-tab rule structural: the builder
refuses every tab-mutating `selectWindow` target, and the run verifies post-run
that every pre-existing tab is still in the session store.

## 2. The new shape

- **One run per profile** (`plan.runs_by_profile`): matching tabs group by profile
  dir; each run addresses its profile's FIRST match. Multi-match profiles get a loud
  detect warning naming the count ("narrow the pattern for the others") — R4 honesty,
  no silent under-processing.
- **Selector priority** (`plan.selector_for` + `plan.resolve_selector`): title
  pattern set → the user's literal `title=*{pattern}*` (the extension matches LIVE
  titles — fresh by construction); otherwise → `tab=N` resolved FRESH at launch from
  a re-read session store (positions outlive titles). Nothing is ever built from
  OS-window titles. Titleless tabs now run (index needs no title).
- **Delivery without remoting** (`desktop.choose_delivery` + `deliver_url`):
  profile window found → address-bar delivery (raise → verify foreground → Ctrl+T →
  paste URL → Enter; clipboard saved/restored; Windows only); nothing running +
  single profile → CLI cold start with `-P`/`-profile` (the ONE case where `-P`
  works); anything else → MANUAL fallback: the run prints the exact URL + steps and
  still polls the savelog, so a complying user completes the run. A CLI launch into
  a running instance for a non-default profile (the old misfire) is never attempted.
- **Stale-store races**: blank-selection + patterns + zero matches → bounded 20 s
  rescan (the store flushes every ~15 s; first runs race it). Unresolvable at
  launch (tab closed since detect) → `skipped`, which never aborts other profiles.
- **Protected tabs** (`guard.py` + `macro.refuse_tab_mutation`): snapshot at detect,
  post-run diff warns per vanished pre-existing tab; builder bans `tab=open/close/
  closeallother` and any non-integer `tab=` literal.

Unknown, safe either way: whether `title=` matches across windows (delivery still
targets the tab's own window, so both semantics work).

## 3. Files

`plan.py` (Search, runs_by_profile, resolve_selector, multi_matches; `runs`,
`split_unaddressable`, `clashes`, title truncation deleted), `sequence.py`
(resolve → deliver → poll + one retry + verify), `runner.py` (rescan, snapshot,
multi-match warnings), `desktop.py` (choose_delivery, deliver_url, Win32Ops),
`guard.py` (new: snapshot/verify), `macro.py` (refuse_tab_mutation). No panel, JS,
or config changes — the spec fields are unchanged.
