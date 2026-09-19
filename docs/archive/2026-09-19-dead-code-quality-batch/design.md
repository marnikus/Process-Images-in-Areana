# Batch B — dead code removal, RULE 21 selector generation, import hygiene, JSON-store dedup

Date: 2026-09-19. Scope: production Python under `app/` + `tools/` + `tests/`.
Governing rules: `docs/current/AGENT_RULES.md` (RULE 8, 16, 17, 18, 19, 21, 23).

> **Status: implemented.** See `implementation-2026-09-19.md` in this folder for the
> as-built results, deviations, and gate evidence.

## B1 — Prove deadness

Method: AST import graph over every `.py` in the repo (`tools/import_graph.py`, added by this
batch) — a module is **dead** when no production module (`app/`) imports it and it is not an
entry point (`app.main`). Evidence, per module (importers at time of audit):

| Module | LOC | Production importers | Verdict |
|---|---:|---|---|
| `app/services/job_runner.py` | 332 | **none** (zero importers anywhere) | DEAD — old Playwright-era monolithic runner; live path is `bridge → multi_page_dispatcher → single_job_runner → cdp_arena` |
| `app/browser/controller.py` | 643 | only `job_runner` (dead) | DEAD — Playwright `BrowserController`; sole `playwright` import in the repo; absent from SYSTEM_OF_RECORD §7 browser layer (`cdp_client`, `cdp_arena`, `dom_highlight`, `site_adapter`) |
| `app/services/job_state_machine.py` | 109 | none in production | DEAD — docstring: "pure logic extracted from job_runner.py (Phase 2)"; extraction never wired, source module is dead |
| `app/browser/output_detector.py` | 155 | none in production | DEAD — "extracted from output_wait/state (Phase 2)"; `output_wait.py`/`cdp_arena.py` keep their own inline decision logic, the extraction was never consumed |

**Kept despite zero production importers (documented, not deleted):**

| Module | Why kept |
|---|---|
| `app/services/verification.py` (114) | Its test `tests/test_verification.py` is listed in SYSTEM_OF_RECORD §8 as the required RULE 15 test (baseline capture, output validation). Deleting it would break the doc's test table. Flagged for a future batch when its logic is wired into the live download path. |
| `app/core/state_machine.py` (59) | Its test `tests/test_state_transitions.py` is listed in SYSTEM_OF_RECORD §8 as the required RULE 7 test (state machine 00-22). Its only production importer was the dead `job_state_machine` — flagged for a future batch. |

`app/services/captcha/**` and `app/services/captcha_recording/**` were audited and are **alive**
(`app/services/captcha/__init__.py` re-exports `CaptchaService`, imported lazily by `bridge.py` and
`single_job_runner.py`).

## B2 — Delete the 4 dead modules

Delete: `job_runner.py`, `controller.py`, `job_state_machine.py`, `output_detector.py`.
Ripples:

* `tests/unit/test_job_state_machine.py`, `tests/unit/test_output_detector.py` — test dead code
  only (not in the SYSTEM_OF_RECORD §8 table) → delete with their modules.
* `requirements.txt`: drop `playwright>=1.40.0` (only `controller.py` imported it).
* Suite equivalence gate (RULE 16.6): baseline **459 passed**; after deletion the suite must pass
  with exactly the deleted tests removed and nothing else changed.

## B3 — RULE 21: generate the selector map, then wire it

Problem: invariant I-18 ("all selectors in `site_adapter.py`") is false in the live code — the
map exists but only the dead controller imported it; every live probe (`cdp_arena`, `output_probes`,
`new_chat`, `captcha_js/*.js`) carries inline selector chains.

Design (new `tools/generate_selectors.py`):

1. **Extract** CSS selector literals from the live probe builders: JS array chains
   (`['a','b',...]` fed to `querySelectorAll`), single `querySelector(All)('sel')` args,
   `closest('sel')` lists, and the `SELECTORS_V3` list. Excludes: internal overlay attributes
   (`[data-arena-highlight]`), scan patterns (`img`, `div, span, p, pre`), template-interpolated
   selectors (`` `img[src="${url}"]` ``), and DOM-API method names.
2. **Group** chains into named map entries. A live chain becomes one entry:
   `primary = chain[0]`, `fallbacks = chain[1:]` — **exact live order**, so regenerating and
   wiring change no probe behaviour (the test suite is the equivalence gate).
   Unifying the two send-button chains is behaviour-preserving: the click probe already checks
   `el.disabled` in JS, making the `:not([disabled])` selector filter redundant.
3. **Classify** each primary per RULE 21 tier: semantic (`aria-label`, `name`, `role`, `type`,
   `placeholder`, `title`, `href`, `alt`) > structural (`:has`, descendant chains, scoping) >
   class fragment. Emits a tier report; class-fragment primaries that are a check's only
   selector are flagged as warnings (fix later, not in this batch — that is a behaviour change).
4. **Regenerate** `app/browser/site_adapter.py` between marker comments
   `# >>> generated:SELECTORS begin` / `end` (idempotent — second run produces no diff).
   The map gains `tier` per entry; `SelectorObject` gains an optional `tier` field.
5. **Wire** live probes to the map: `cdp_arena` JS builders and `new_chat`/`output_probes`
   chains take their selector lists from `site_adapter.get_selector(name).all_selectors()`.
   The map becomes the single file where selector updates land (RULE 1 "one file").
6. **Coverage check** (generator exit 1 on miss): every live selector literal must appear in
   exactly one generated entry.

`DOM_SELECTORS.md` keeps the richer hand-verified fallback catalogue as reference; the generated
map is the executable subset that live code actually tries, with `evidence` = file + probe name.

## B4 — Unused imports (vulture ≥90 + pyflakes, zero new findings)

Remove the pre-existing findings in live files (dead-file findings vanish with B2):
`cdp_arena.py` (`build_order_check_text`, `build_clear_js`), `dom_highlight.py` (3× `COLOR_*`),
`output_wait.py` (`Awaitable`), `page_status.py` (`_is_cooling`), `core/layout_service.py` (`Any`),
`core/persistence.py` (`Optional`), `core/scanner.py` (`os`), `core/state_machine.py` (`UrlStatus`),
`core/undo_service.py` (`copy`, `json`). Unused-locals findings (`models.py:193 pending`) are
audited individually — a dataclass field is never an unused local.

## B5 — JSON-store dedup

Five copies of the same atomic-JSON-write pattern + three copies of the tolerant loader:
`config_manager.py` (defines `_atomic_write`/`_load_json`), `preset_store.py` (verbatim copy),
`undo_store.py` (verbatim copy), `core/persistence.py` (two inline copies),
`services/captcha/key_store.py` (inline copy + `_cleanup_tmp`).

Design: new `app/persistence/json_store.py` with the canonical pair

* `atomic_write_json(path, data, *, mode=None)` — `mkstemp` in target dir + `json.dump`
  + `Path.replace`; optional file mode (key store keeps 0600, RULE 20).
* `load_json(path, default)` — missing/corrupt/non-dict → `copy.deepcopy(default)` (RULE 13:
  bad payload costs one failed load, never a crash).

All five sites import it. Layer direction stays legal: `core.undo_service` already imports
`persistence.undo_store`, so core→persistence edges exist; `services` sits above `core`.
`core/naming.py::atomic_write_bytes` is a bytes contract (RULE 23 image files), not JSON — unchanged.

## B6 — Full gate + docs sync

* `pytest`: green, only deleted tests missing.
* `tools/verify_quality.py --allow-legacy`: no NEW breach vs today; deleting `controller.py`
  removes ~15 legacy breaches. Baseline entries for deleted files are pruned.
* `tools/generate_selectors.py`: coverage 100% + idempotent.
* Docs (RULE 17): `SYSTEM_OF_RECORD.md` (module/test rows, §7 browser layer note, I-18 now true),
  `DOM_SELECTORS.md` (generated map + generator workflow), `docs/README.md` (map this archive).

## Rejected alternatives

* Delete all 6 zero-production-importer modules (incl. `verification.py`, `state_machine.py`):
  rejected — both carry SYSTEM_OF_RECORD §8-mandated tests; deleting them would force doc surgery
  and drop RULE 15/RULE 7 test coverage from the suite.
* Make probes use the old 17-entry map's full fallback lists: rejected — live chains are shorter;
  adding never-live-tried fallbacks changes probe behaviour and is not a refactor.
* Put `json_store.py` in `app/core/`: rejected — `app/persistence/` is the established home for
  JSON persistence and already imported from `core` (`undo_service`).
