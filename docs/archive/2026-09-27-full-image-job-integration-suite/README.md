# Full Image-Job Integration Suite — PLAN ONLY (no production code yet)

> **⚠ READ [`merge-note.md`](merge-note.md) FIRST (added 2026-09-28).** This plan was researched
> against commit `02e0240`, which is a stale lineage unrelated to `origin/main`. Main already ships a
> Firefox/Ui.Vision job pipeline (`app/services/firefox_job*.py`, `app/browser/uivision/` — 19 files),
> documents invariants up to **I-68** and coverage floors **89.34/86.37**, so **D-12 must be redesigned**,
> I-55…I-59 renumber to I-69…I-73, and every `file:line` re-verified before any stage lands. The
> design's *shape* survives; its facts about the current tree do not.

Dated 2026-09-27, written against `02e0240` (S7 receiver flag, I-51). Owner brief: *"design a
big behavior test where the app runs and simulates the full process — detect the web page →
create URL → add page to pool → select image and send as job → simulate page states (prompt in
textarea, Send enabled, generation starts, generated image appears, saved within 300 s, page
error/refusal, endless generation past 300 s → page restarted into a clean preparing state) —
with real saved web-page states, in one global test, over a Chrome connection **and** a Firefox
connection."* RULE 16.6 step 2: research + design in a doc first; RULE 17: dated archive folder.

## How to read this folder

| File | Read it for | Size (measured) |
|---|---|---|
| [`merge-note.md`](merge-note.md) | **READ FIRST** — the drift between this plan's base (`02e0240`) and `origin/main` (`aec7b86`), measured: unrelated histories, 355 files / 41 199 insertions apart, a real Firefox + Ui.Vision pipeline on main, I-68 already documented, floors 89.34/86.37; what is still true (`tests/e2e/` absent, `pytest.ini` unchanged ⇒ L-9/L-13 hold); the 6-step re-verification round required before S0 | 49 lines |
| [`evidence.md`](evidence.md) | What the app **actually does today**, every claim with `file:line`: the real 16-step path, the three frozen contracts the fake pages must satisfy (CDP surface, selector registry, in-page payloads), the knobs that already exist (⇒ **zero production change**), the reusable test assets, the environment facts, and the latent defects **L-9…L-15** found while researching | 204 lines |
| [`design.md`](design.md) | The plan: contract, decisions **D-1…D-22** with rejected alternatives, architecture (`tests/e2e/` package), the three lanes (Chromium native CDP · Firefox through a CDP-shaped adapter · jsdom fallback), the one global test flow, the three owner scenarios with exact assertions, the two-part 300 s contract, evidence format, isolation, invariants **I-55…I-59**, staged delivery **S0…S7**, risks, out of scope, the end-of-plan RULE 16/17/18/19/20 recheck and §14.1 — this round's own citation audit | 639 lines |
| [`fixtures.md`](fixtures.md) | The **fake pages**: fixture inventory rebuilt from the committed saved page + `DOM_SELECTORS.md`, the element-by-element DOM contract (which app probe each element serves), the 14-state page state machine, the scenario schema and its 20 scenarios, the deterministic fake result image, sanitization rules, server routes, layout/geometry contract, and defects **L-16/L-17** (the committed dump's absolute New Chat `href`; no result-image markers in an empty chat) | 272 lines |
| [`quality-budget.md`](quality-budget.md) | RULE 16 / RULE 18 numbers: what is and is not gated, per-new-file size budget, the coverage-floor and test-time argument, marker policy so the default push budget is untouched, gate commands, RULE 16.7 checklist, anti-gaming refusals | 201 lines |
| [`tdd-interfaces.md`](tdd-interfaces.md) | TDD-first: per stage the interface split (every new symbol with signature, size budget, caller, *must-not*), the RED-first test branch with the failure expected at base, GREEN/REFACTOR/equivalence/gate/docs steps | 302 lines |
| [`record-replay.md`](record-replay.md) | **Research round (same day):** which record/replay technology to combine with this plan — candidate-by-candidate status checks with sources (HAR 1.2, Chrome DevTools sanitized export, Playwright HAR record/replay + its `connect_over_cdp` limits, the repo's own sanitized DOM recorder, Polly.js, WireMock, Mountebank, Nock, Cypress, BrowserMob, mitmproxy, Percy/Chromatic, Mocky), the scored pick (**D-23 HAR-first fixture provenance**), and the owner-facing instructions: what to prepare (P1…P8), what to record per state (A1…A7), four capture routes incl. the console probe-read-back snippet, the planned `tools/har_ingest.py` pipeline, where recorded bytes get replayed, the capture schedule that closes **L-17** and settles **L-16**, rules + ethics | 310 lines |
| [`coverage-matrix.md`](coverage-matrix.md) | The deliverable matrix: every page state × job state × scenario × lane → test id + evidence, plus the brief's §6/§7/§8/§9 checklists mapped line by line to tests | 116 lines |

## The four owner decisions this plan is built on

1. **Firefox lane = a test-side BiDi/Playwright → CDP adapter** (real Firefox, the app is not
   touched). The app has **zero** Firefox/Ui.Vision code today — verified, `evidence.md` §9 L-9.
2. **Default lane = real Chromium** (`playwright install chromium`, already in `README.md:29`),
   talking **native CDP** to the app; jsdom is a fallback lane, never the only lane for a scenario.
3. **Test-only seams** — no `app/` change anywhere in this plan (`design.md` D-20 lists every
   existing knob used instead).
4. **Fixtures rebuilt from the committed saved page** `docs/research/Directly Chat with Frontier
   Image Generation AI Models.html` + `docs/current/DOM_SELECTORS.md`, sanitized; the owner's
   local git-ignored `arena webpages/state*` dumps are design-time evidence only (I-43).

## Citation convention (and how it was checked)

Full repo-relative path at first mention; later the short form `file.py:123` or `file.py:12-30`,
resolved under `app/…`, `app/browser/cdp_arena/…`, `app/services/…`, `app/ui/panels/…`,
`app/core/…`, `app/utils/…`, `tests/…` or `tools/…` — the house style of the other archive folders.
Every `file:line` in this folder was re-resolved against the working tree at `02e0240` on
2026-09-27 (script-checked: no citation points outside its file, and the quoted symbol is on the
quoted line). Paths that do **not** exist yet are the plan's own new files under `tests/e2e/`,
`tests/js/e2e/` and `tools/e2e_check.sh`.

## Added by the research round (2026-09-27, same day)

**D-23 HAR-first fixture provenance** — `record-replay.md`. Fixture *evidence* is captured as HAR
(the browser's own sanitized DevTools export, or Playwright's built-in HAR recorder), reduced by a
small owner-run ingest to sanitized artifacts, and **replayed by the fake-site server this plan
already designs** — never by a service virtualizer, because a HAR is passive and D-17 keeps behaviour
in the page. It amends D-15 (rebuilt *from recorded evidence*), downgrades risk R6, adds the
owner-run stage **S1a**, closes **L-17** (real result bytes + the real `.r2…` URL shape) and settles
**L-16** (the recorded New Chat `href`). Rejected with sources: WireMock/Mountebank (JVM/Node service
virtualizers), Polly.js (in-page JS interception), Nock (Node-only), Cypress (framework replacement),
BrowserMob (unmaintained proxy), Percy/Chromatic (visual SaaS), Mocky/FakeJSON (hosted fixtures),
mitmproxy as primary (machine-wide CA) — it stays the fallback recorder.

## Status

Plan only, **and stale-base — see `merge-note.md`** — the research round included: no capture has been taken, no tool installed, no code written. `docs/current/SYSTEM_OF_RECORD.md` and `docs/current/AGENT_RULES.md` stay untouched
until a stage lands (RULE 17); `docs/README.md` gained one archive row + one `*Last updated*`
entry on 2026-09-27. Invariant numbers **I-55…** are used because I-52…I-54 are reserved by
`docs/archive/2026-09-20-dynamic-urls-and-worker-debug/merge-note.md`. No `app/`, `tests/`,
`config/` or tooling file was created or edited by this planning round.
