# MERGE NOTE — read this before acting on any other file in this folder

Written 2026-09-28, after the plan was pushed. **The whole plan in this folder was researched and
written against commit `02e0240` ("S7 receiver flag + the ⊘ icon (I-51)"), which turns out to be a
stale, unrelated lineage.** `origin/main` has moved far ahead of it. Nothing here is landable as-is;
the design is still usable, but the facts underneath it must be re-verified and two decisions must be
redone. This note records the drift exactly, in the house pattern of
`docs/archive/2026-09-20-dynamic-urls-and-worker-debug/merge-note.md`.

## 1. The drift, measured (reproduce with these commands)

```bash
git merge-base 02e0240 origin/main          # -> EMPTY: the two histories are unrelated
git log --oneline origin/main | wc -l       # -> 1  (main is a single squashed commit aec7b86)
git diff --stat 02e0240 origin/main         # -> 355 files changed, 41199 insertions(+), 5494 deletions(-)
git diff --stat 02e0240 origin/main -- app   # -> 166 files changed, 14908 insertions(+)
```

| Fact the plan assumed (at `02e0240`) | Truth on `origin/main` (`aec7b86`) | Consequence |
|---|---|---|
| "The app has **zero** Firefox / Ui.Vision code" (`evidence.md` §8 **L-9**, and the owner decision behind **D-1/D-12**) | **False.** `app/browser/uivision/` = **19 files** (`launch.py`, `macro.py`, `job_macros.py`, `job_scripts.py`, `file_dialog.py`, `desktop.py`, `identify.py`, `config.py`, …), `app/browser/browsers.py`, and a whole Firefox job pipeline: `app/services/firefox_job.py`, `firefox_job_ctx.py`, `firefox_job_host.py`, `firefox_job_journal.py`, `firefox_job_output.py`, `firefox_job_phases.py`, `firefox_job_recovery.py`; Firefox also reaches `app/core/{run_scope,state_machine,window_catalog}.py`, `app/services/{batch_orchestrator,cooldown_service}.py` | **D-12 must be redesigned.** The real Firefox lane is Ui.Vision-macro driven (desktop automation, native file dialogs), **not** CDP — so a test-side BiDi/Playwright→CDP adapter would test a path Firefox jobs do not take. The "everything is headless-safe" claim (D-1, `evidence.md` §2 note on in-page clicks) no longer covers that lane |
| Archive folders end at `2026-09-21-staged-chain-implementation` | main carries **10 more plan/record folders**, incl. `2026-09-24-uivision-protected-tabs-open-profiles`, `2026-09-24-uivision-url-pattern`, `2026-09-25-firefox-account-name`, `2026-09-25-firefox-image-job`, `2026-09-25-firefox-pool-integration`, `2026-09-25-uivision-delivery-by-directory`, `2026-09-25-cdp-fail-pending-on-disconnect`, `2026-09-25-global-workspace-save`, `2026-09-25-webchannel-signal-slot-clash`, `2026-09-26-firefox-job-refactor/audit.md` | The Firefox/Ui.Vision behaviour contract is **already specified elsewhere** — `2026-09-25-firefox-image-job/design.md` says a Firefox worker must run ONE image job "reusing the existing Firefox worker, Ui.Vision, macro, queue, pool, logging, persistence and cooldown systems, **same behaviour and the same states as Chrome**". This suite must test *that* contract, not invent a parallel one |
| Invariants **I-55…I-59** are free (I-52…I-54 reserved) | main documents up to **I-68** | renumber the plan's five invariants to **I-69…I-73** (next free) before any stage lands |
| Coverage floors line **86.36** / branch **82.33** | `tools/quality_baseline.json` on main: line **89.34** / branch **86.37** (the file grew by ~2 400 lines of per-file ratchet entries) | `quality-budget.md` §1/§4 numbers are stale; the ratchet table must be re-measured with the gate's own `current_maxima()` |
| Slot surface **135**, `app/` tree as cited | 166 `app/` files differ | **every `file:line` citation in this folder must be re-verified against main** before it is trusted (the 2026-09-27 audit in `design.md` §14.1 was against `02e0240` and is correct *for that tree only*) |

## 2. What is still true on main (checked, not assumed)

* **`tests/e2e/` does not exist on main** — `git ls-tree -r --name-only origin/main | grep -E "^tests/(e2e|js/e2e)|e2e_check|har_ingest"` returns nothing. The suite this plan designs is still missing, so the plan's *purpose* stands.
* **`pytest.ini` is unchanged** on main: markers are still only `unit / integration / e2e / slow / serial` with `--strict-markers`, and no test uses `e2e`/`slow`/`serial` except through the conftest path rule ⇒ **L-9 and L-13 still hold**.
* `docs/current/SYSTEM_OF_RECORD.md`, `AGENT_RULES.md` and `DOM_SELECTORS.md` all exist on main and are newer — the rule set (RULE 1…23) the plan rechecked itself against is the same shape, but rows/invariants moved.
* The record/replay research (`record-replay.md`) is **base-independent**: HAR 1.2, DevTools' sanitized export, Playwright's `record_har`/`route_from_har`, the `connect_over_cdp` limits and the rejected candidates are facts about external tools, not about this tree. Only its §6 reuse claims (the in-house recorder's `file:line`s, `config/captcha_recordings/`) need re-verification, and its D-23 numbering must follow the renumbered decisions.

## 3. What must happen before S0 (the re-verification round)

1. **Re-base the work on `origin/main`.** Either re-create this branch from `aec7b86` or merge main in; the histories are unrelated, so `pre_push_check.sh`'s changed-file gate would otherwise print its LOUD "no common ancestry ⇒ gate ALL files" warning.
2. **Read the Firefox/Ui.Vision record set** (`2026-09-25-firefox-image-job`, `-firefox-pool-integration`, `-firefox-account-name`, `2026-09-26-firefox-job-refactor/audit.md`, `2026-09-24-uivision-*`) and rewrite **D-1/D-12/D-22** around `app/services/firefox_job*.py` + `app/browser/uivision/`: the Firefox lane becomes a **Ui.Vision macro lane** (needs a desktop, an installed XPI, real Firefox profiles, native file dialogs ⇒ `e2e_desktop` marker, serial, opt-in), and the CDP adapter idea is either dropped or kept only for a Chromium-shaped smoke lane.
3. **Re-verify contracts A/B/C** (`evidence.md` §2/§3/§4) against main: the CDP method inventory, `site_adapter.py` + `probe_selectors.py` (both changed), the in-page payloads in `cdp_arena/js_snippets.py` and `output_probes.py`, and — new — the **Ui.Vision macro contract** (`job_macros.py`, `job_scripts.py`), which is a second page contract the fixtures must satisfy.
4. **Re-verify the 16-step flow** (`evidence.md` §1) and the defect list: L-10 (`test_url` stub), L-11 (`reload_page` dead), L-12 (`poll_interval = 2.0`), L-14 (revival resubmit), L-16 (absolute New Chat `href`), L-17 (no result-image evidence in the committed dump) must each be re-checked; some may already be fixed on main.
5. **Renumber**: invariants → I-69…I-73; re-measure the coverage floors and the per-file ratchet; re-count the slot surface; re-run the citation audit script over all seven files.
6. **Then** start S0 as written (markers, `.gitignore reports/e2e/`, `tools/e2e_check.sh`) — that stage is small and mostly base-independent.

## 4. Status of this folder

Plan only, pushed at `a5a7e5f` on branch `arena/01a0e1fe-process-images-in-areana`. **Do not land
any stage from it until §3 is done.** The design's shape (one global test per scenario × lane, real
app above fake pages, per-scenario submit counts, two-part 300 s contract, evidence bundles,
skip-gated lanes, HAR-based fixture provenance) survives; its *facts about the current tree* and its
*Firefox lane* do not.
