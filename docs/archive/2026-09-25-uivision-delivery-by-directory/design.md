# Design — deliver the macro by profile directory, never by ambiguous name (2026-09-25)

**Status:** implemented 2026-09-25 · amends `2026-09-24-uivision-protected-tabs-open-profiles`
(its `-P <name>` preference is superseded here) and `2026-09-23-uivision-multi-profile`
(its `firefox -P "<name>"` remoting claim)
**Entry:** SYSTEM_OF_RECORD.md → `Firefox auto with Extension` (I-63)
**Owner report (entry):** *“Bug appear only on first run! on first run it always runs
macro twice on one profile but should … once per each profile per one tab. 2d run was
finished correct.”*

## 1. What the delivered log proved (facts, not guesses)

Both framework runs planned correctly — `plan.one_per_profile` held: `2 macro run(s)`,
two distinct session directories each time (`9THrgpBc.Profile 1`, `osSged5f.Profile 2`,
`rvxjuu2q.user-2`; 3 s apart; every `savelogs` read `ok`). Yet the run was reported as
executing twice on ONE profile. Three hard facts from that log:

1. **The profile labels flipped between the two runs.** The session with 6 tabs sitting
   on directory `osSged5f.Profile 2` was labelled `user-2` in run 1, while in run 2 the
   same label rode directory `9THrgpBc.Profile 1`. The directories are identical across
   runs; the `profiles.ini` `Name=` ↔ directory mapping we consumed is not. Whatever the
   cause (ini rewrite, reader race), **a name read at runtime is not a stable profile
   identifier** — and `-P <name>` keys on exactly that.
2. **`foreground` raised 2 of 2 Firefox windows for every single-target run**
   (`2/2 — mai; mor`, order flipping between runs). `pick_tab_window` matches OS windows
   by title only; two profiles open on the same page present the same title, so the
   pre-raise cannot know which window belongs to the run.
3. **The plan, selectors, savelogs and polls were all correct** — so the double
   execution happens in *delivery* (which instance receives the autostart URL) and/or
   *foreground* (which window is on top when the native click lands), not in planning.

## 2. Research (sources consulted this round)

* **Firefox command-line docs** (firefox-source-docs `CommandLineParameters`):
  `-P <profile>` — *start with the named profile*; `--profile <path>` — *start with the
  profile located at <path>*. Two different keys: name (ini lookup) vs directory
  (filesystem identity).
* **man firefox**: `-P` *“will start the profile manager if a valid profile name is not
  specified”* and *“you will need to also use -no-remote if there is already a running
  firefox instance”* — i.e. name-keyed invocation against a running multi-instance setup
  is documented as unreliable.
* **Mozilla SUMO (Managing profiles)**: launching `-P` while Firefox is already running
  *“will just open a new browser window using the current profile”* — the URL can be
  handed to **another** running instance than the one named. This is the delivery
  failure class our first-run log exhibits.
* **`2026-09-23-uivision-multi-profile` design**: `-profile <dir>` remoting keys the
  running instance by its profile **directory** — already trusted there for unnamed
  profiles; this round extends that trust to **all** profiles, because sessions always
  carry their directory while names may be absent, duplicated or unstable (fact 1).

## 3. Decisions

**D1 — delivery is directory-first.** `launch.profile_args(name, dir)` now returns
`("-profile", dir)` whenever the directory is known (it always is for a session-derived
target — the same directory the session store was read from). `("-P", name)` survives
only as the **name-only fallback** (no directory available), and `()` when neither is
known (single/fallback run — unchanged). Effect: the autostart URL is remoted to the
instance that owns **the exact directory our matched tab was found in** — self-consistent
even while `profiles.ini` names drift. The `BANNED_ARG_MARKERS` scan still covers the
whole argv.

**D5 — the mapped foreground never raises an ambiguous set.** `desktop.
foreground_tab_window` raises OS windows only when the title mapping yields **exactly
one** window. On 2+ hits (same page open in several profiles) it raises **nothing**
and reports `(hits, 0)`; `Sequence._foreground` then logs a named `warn` line
(`0/N … ambiguous title … none raised, the macro's own bringBrowserToForeground
decides`). The click-time authority is the macro's own foreground command — our
pre-raise must never put the *wrong* profile's window on top. The unmapped fallback
`desktop.foreground(pattern)` keeps its pinned raise-every-match contract (no profile
attribution exists there to be wrong about).

**D6 — the launch line carries the delivery evidence.** `sequence._launch` logs
`, profile=<dir basename>` (or `, profile=<name>` for the fallback) inside the existing
`starting Firefox with the autorun URL (…)` line, so any future first-run report shows
exactly which instance was addressed.

**Non-goals:** `profiles.ini` names remain used for *display labels* only (renaming
machinery is untouched); plan/selection/protected-tabs logic is unchanged; the plain
fallback foreground path stays as pinned.

## 4. Structure — current → target (recorded before editing)

| symbol | file | now | target | note |
|---|---|---|---|---|
| `profile_args` | launch.py | 14 | ≤19 | branch flip dir-first; file `max_func_loc` 19 unchanged |
| `foreground_tab_window` | desktop.py | 7 | ≤14 | ambiguity branch; file max 19 (`pick_tab_window`) unchanged |
| `Sequence._foreground` | sequence.py | **28** (= file floor, R0.3 zero-tolerance) | ≤26 | extract `_mapped_note` (new, ≤20) |
| `Sequence._launch` | sequence.py | 24 (above PREFER 20) | **=24** | inline new helper `_profile_note` (new, ≤10) — no growth |
| `_mapped_note`, `_profile_note` | sequence.py | — | ≤20 each | new symbols must not breach in a legacy file (RULE 16 §16.5) |

Ratchet rules honoured: file-level `max_func_loc`/`max_cc` must not grow anywhere
(`ratchet_growth`, zero tolerance); per-symbol LOC growth fails above the symbol's own
baseline once it breaches PREFER 20; new symbols in legacy files must meet ≤20.

## 5. Tests first (RULE 8)

1. `test_uivision_plan.py` — `profile_args` dir-first: `("Work", "/ff/p1")` →
   `("-profile", "/ff/p1")`; name-only keeps `("-P", "Work")`; both-empty keeps `()`;
   render test pins the plan's `profile_args` to the directory.
2. `test_uivision_desktop.py` — **new**: two OS windows sharing one session title →
   `foreground_tab_window` returns `(hits, 0)` and raises nothing; the unique-match
   raise stays pinned.
3. `test_uivision_runner.py` — all four `["-P", "Work"]` launch pins become
   `["-profile", "/ff/p1.work"]` (dir known); **new**: ambiguous mapped result logs the
   named `warn`; **new**: launch line shows `profile=…` evidence.
4. Existing suite must stay green unchanged everywhere else (protected tabs, URL
   pattern, one-per-profile, open-only discovery).

## 6. Supersession

* `2026-09-24-uivision-protected-tabs-open-profiles/design.md` §launch argv preference
  and `2026-09-23-uivision-multi-profile/design.md` `firefox -P "<name>"` framing are
  superseded by D1 (status lines added in place, RULE 17).
