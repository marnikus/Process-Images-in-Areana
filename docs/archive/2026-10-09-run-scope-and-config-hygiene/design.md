# Design — runtime config out of Git (API keys) + "completed is never sent again"

Status: **IMPLEMENTED** — A in `54cb501` (B13a), B + C in the B13b commit; see *Outcome* at the end and [`bugfix-verification.md` §B13](../2026-10-02-captcha-watcher-isolation/bugfix-verification.md) for the evidence. Written as a plan first (owner asked for the plan before the go).
Rules applied: RULE 16 (gates), RULE 18 (ideal sizes), RULE 19 (order),
RULE 8 (tests execute real code), RULE 10 (one control per decision),
RULE 9 (a skip must not stall the stack), RULE 17 (this doc is the record).

---

## Area A — API keys are in Git and on GitHub

### A.1 Findings (read-only audit, 2026-10-09)

| Fact | Evidence |
|---|---|
| Two 2Captcha keys are **tracked and public** | `config/2captcha.json` (`api_key` `1d51…27d4`), `config/captcha_solvers.json` (`api_key` `6891…4983`, twice). `gh repo view` → `isPrivate: false`. |
| They entered in the **root squash commit `0eeec39`** (2026-09-19 "upd") | `git log -- config/2captcha.json` → only `0eeec39`. That commit is `main`'s tip **and the base of every `arena/*` branch** (10+ on the remote). |
| `.gitignore` already lists the files — but they were committed **before** the rule, so the ignore never applied | `git ls-files config/` → 894 files (6.4 MB): `app_state.json` (local paths `F:/Stocks 2026/…`, tab ids), `session.json`, `undo.json` (278 KB history), `cooldowns.json`, `captcha_stats.json`, 36 `captcha_recordings/*` (DOM snapshots + network URLs of the user's arena.ai session), `arena_presets.json` (private `arena.ai/c/<chat-id>` URL, prompt templates), `window_presets.json`. |
| Other ignored-but-tracked junk | 50 `app/**/__pycache__/*.pyc`, `logs/2026-09-16.log`. |
| Not a code path problem | `CaptchaKeyStore` writes `config/captcha_solvers.json` (legacy `2captcha.json`) — that is correct local-only storage; nothing in `app/` reads keys from the repo. |

### A.2 What I can and cannot do from this session

* **Can:** untrack everything under `config/` (keep `config/.gitkeep`), `logs/`, `*.pyc`; harden `.gitignore`; add a guard test + pre-push check; commit + push **this branch**. The branch tip (and `main` after the PR merges) then carries **no config data**.
* **Cannot:** rewrite `main` or the other `arena/*` branches (session is pinned to one branch; force-push to `main` is out of scope). The keys therefore **stay in GitHub history until the owner purges it** — and GitHub keeps dangling commits fetchable by SHA even after a purge.
* **Therefore the only real remediation is rotation.** Both keys must be regenerated at 2captcha.com **before** anything else; treat the current ones as burned.

### A.3 Plan (branch work, ~1 h)

1. `git rm -r --cached config logs app/**/__pycache__` (files stay on disk); keep `config/.gitkeep`.
2. `.gitignore`: replace the per-file list with `config/*` + `!config/.gitkeep` (`__pycache__/`, `logs/`, `*.log` already present).
3. **Guard that executes** (RULE 8): `tests/test_repo_hygiene.py` — runs `git ls-files` and asserts: nothing under `config/` except `.gitkeep`, no `*.pyc`, no `logs/`, and no tracked text file contains an `api_key`-shaped 32-hex value. Same check as a shell step in `tools/pre_push_check.sh` so the pre-push hook blocks a re-leak.
4. Docs: `SYSTEM_OF_RECORD.md` gets one invariant row (I-43 *config/ is runtime data; never tracked; keys live only in `config/captcha_solvers.json` on the user's disk*) + `README.md` "Configuration & secrets" paragraph (where the key is entered — Captcha Settings panel — and that the file is git-ignored).
5. Hand-over for the owner (documented in the PR text, not executed here):
   * rotate both keys at 2captcha, paste the new one into the Captcha Settings panel (writes the ignored file);
   * optional history purge: `git filter-repo --invert-paths --path config --path logs --path-glob '*.pyc'` on a fresh clone → force-push `main` and every `arena/*` branch → GitHub Support ticket to drop cached views. Rotation makes this hygiene, not urgency.

### A.4 Decisions taken with the owner (2026-10-09)

* **Keys:** owner rotates both keys at 2captcha and re-enters the new one in the Captcha Settings panel; I untrack + ignore + guard on this branch (no purge script requested).
* **`arena webpages/` (182 files, 22 MB) is untracked too** — the two saved pages contain personal e-mail addresses in the page state (`marnikus@…`, `artemisgoddess26@…`), i.e. PII in a public repo. Consequence: `tests/js/test_captcha_saved_page.mjs` already runs with `skip: !hasFixtures`, so it keeps running on the owner's machine (files stay on disk) and skips in CI. Follow-up (not now): PII-stripped minimal fixtures under `tests/fixtures/` so the lane runs everywhere.
* `.gitignore` additions: `config/*` + `!config/.gitkeep`, `arena webpages/`, plus the guard test in A.3 step 3 extended to `arena webpages/`.

---

## Area B — images with status `completed` are processed again

### B.1 What the code does today

* The run scope predicate exists and **does exclude `completed`** — but it is **duplicated** (`ui/panels/queue_scan.selected_images` and `services/batch_orchestrator._selected_images`, same 5-status tuple) and it is evaluated **once, at batch start**. From then on the batch iterates a **snapshot list**; `should_continue(ctx, img)` receives the image but never looks at `img.status`; the parallel worker (`multi_page_dispatcher.run_one_image_on_page`) does not either.
* Consequence: whatever is in a stale list gets claimed, incl. images completed in the meantime. Concrete doors:
  1. **Second batch while one is alive.** `check_start_ready` only refuses when `_run_state == "running"`. After **Pause** (`paused`) or **Stop after current** (`stopping`) the Start button is enabled (JS never disables it) and `start_run` **resets `_pause_requested` / `_stop_after`** — which wakes the old loop. Two loops now walk overlapping lists on the same tab: images done by one are re-sent by the other.
  2. **Parallel → sequential fallback.** `_try_parallel` catches `Exception` from `dispatch_parallel` and returns `False`; `_run_sequential` then re-runs **all** of `ctx.images`, including the ones the parallel phase already completed.
  3. **Cancel race.** `cancel_current` flips `_run_state = "idle"` synchronously; the batch future is still unwinding; an immediate Start passes the gate.
* The committed `config/app_state.json` shows exactly this footprint: completed items with `attempt_count` 4–6 and outputs `…_AI_3.png` / `…_AI_4.png` (the unique-suffix path is taken only when `_AI` already exists).
* Owner's description: *"marked as completed but sent a second time again"* — symptom only, no sequence; all three doors are closed by the design below, and the claim-time re-check catches any door not listed.

### B.2 Design (single source of truth + claim-time re-check + one batch)

**New file `app/core/run_scope.py` (~40 lines, no Qt, no services import)**

```python
RUNNABLE = frozenset({"pending", "selected", "failed", "needs_review", "processing"})
def is_runnable(status: str) -> bool          # completed / skipped / deselected → False
def run_scope(images) -> list                 # selected AND is_runnable — the ONE predicate
```

* `queue_scan.selected_images` → thin alias of `run_scope` (import surface for `run_control` and `Bridge._get_selected_images` stays frozen); `batch_orchestrator._selected_images` deleted (duplication, RULE 16.4).
* **Claim-time re-check (the actual fix):**
  * sequential: `batch_orchestrator.should_continue(ctx, img)` gains the third gate — `not is_runnable(img.status)` → log `⏭ Skipping <rel> — already <status>` and return **"skip"** so the loop moves to the next image (RULE 9: never stall the stack; today it returns only stop/continue, so `_run_one_image` maps skip → `"next"`);
  * parallel: `multi_page_dispatcher._run_with_sem` performs the same check **after** acquiring the semaphore, right before `run_one_image_on_page` (the closest point to the claim), and returns without touching a page.
* **One batch at a time (RULE 10 — one control):** `run_state.batch_active(bridge)` = `_batch_future is not None and not done()` (the future is already cleared in `_on_coro_done`). `run_control.check_start_ready` refuses with `⚠ A batch is still active (paused/stopping/unwinding) — Resume or Cancel it first` while it is alive, **whatever `_run_state` says**, and — key detail — `start_run` never gets to reset `_pause_requested` / `_stop_after`, so the old loop keeps honouring them.
* Optional UI touch (tiny): `run-controls.js` disables Start while `run_state ∈ {running, paused, stopping}`; the Python gate remains the decision.

### B.3 Numbers now → target (RULE 16.6 step 2, ratchet is "no growth of any file maximum")

| File | Baseline maxima (func LOC / CC / methods) | Touch | Result |
|---|---|---|---|
| `services/batch_orchestrator.py` | 17 / 7 / – | `should_continue` 10→13 LOC, CC 3→4; `_selected_images` removed | no maximum grows |
| `services/multi_page_dispatcher.py` | 29 / 8 / – | `_run_with_sem` 3→7 LOC, CC 1→2 (**not** `run_one_image_on_page`, already 29 LOC) | no maximum grows |
| `ui/panels/run_control.py` | 19 / 6 / 10 methods | module func `check_start_ready` 10→14 LOC, CC 3→4 (no new method — class is at 10) | no maximum grows |
| `services/run_state.py` | 18 / 7 | + `batch_active` (4 LOC, CC 2) | no maximum grows |
| `ui/panels/queue_scan.py` | 19 / 7 | `selected_images` body → `return run_scope(images)` | shrinks |
| `core/run_scope.py` (new) | – | 3 symbols, max CC 2 | 100 % covered |
| `core/enums.py` | func LOC 0 | **not touched** — first function there would trip the ratchet (0→n) | — |

Per-file coverage floors to hold: orchestrator 92.5 %, dispatcher 88.5 %, run_control 82.8 %, run_state 82.1 %, queue_scan 52.2 %.

### B.4 Tests first (RULE 8 — each fails if the feature is deleted)

| Test | Executes | Asserts |
|---|---|---|
| `tests/test_run_scope.py` | `is_runnable`, `run_scope`, `queue_scan.selected_images is run_scope`-equivalence | table of the 8 statuses; selected×status matrix; the two old call sites return identical lists |
| `tests/test_batch_orchestrator.py::test_completed_image_is_skipped_at_claim_time` | real `_run_one_image` with `img.status="completed"` | `mark_processing` / `_execute_image` never called, `⏭` log line, returns `"next"` and the following pending image **is** processed |
| `…::test_parallel_fallback_does_not_redo_completed` | `_try_parallel` raising after the first image completed, then `_run_sequential` | the completed image is not re-executed; second image is |
| `tests/test_multi_page_dispatcher_run.py::test_settled_image_never_acquires_page` | real `_run_with_sem` | no page acquired, no `job_started`, pool untouched |
| `tests/test_run_control_gate.py` | real `check_start_ready` / `start_run` on the stub bridge with a live `Future` and `_run_state="paused"` / `"stopping"` / `"idle"` | refused with the new error; `_pause_requested` / `_stop_after` untouched; allowed once the future is done; `schedule_coro` not called |
| `tests/test_run_state.py::test_batch_active_*` | `batch_active` | live → True, done/cancelled/None → False |
| characterization goldens | full suite | **unchanged** (no block behaviour changes; 135 slots frozen) |

### B.5 Docs in the same change (RULE 17)

* `SYSTEM_OF_RECORD.md`: I-44 *run scope has one predicate and is re-checked at claim time — `completed`/`skipped` items are never claimed by any loop*; I-45 *one batch at a time — Start is refused while the batch future is alive, whatever the label*; queue row wording.
* `bugfix-verification.md` §B13 (root cause + evidence table); `QUALITY_RECHECK.md` 2026-10-09 entry with the per-file numbers above.

### B.6 Still deliberate

* `Reset all` / `Reset` / `Retry` return items to `pending` on purpose — that is the user saying "do it again". Nothing in this change touches them.

---

## Area C — resume on scan (owner said **yes**)

**Behaviour:** when a scan **adds** a source image to the queue and a generated sibling already exists next to it (`<base>_AI.<ext>`, or a counter variant `<base>_AI_<n>.<ext>`, any supported extension — the same family `folder_ai.strip_ai_name` / `naming.is_ai_generated_filename` already define), the new item enters as **`completed`** with `output_path` = that sibling (exact `_AI` preferred, else the highest counter), `selected=False`. It is therefore outside the run scope (Area B) until the user presses Reset/Retry.

**Boundary (kept simple and predictable):** adoption happens **only for items new to the queue** (Clear list → Scan, New batch, first scan on another machine). Items already in the queue keep their in-app status on a rescan — so *Reset → Scan* does not flip an image back to completed, and RULE 14 stays intact (outputs on disk inform the queue, the queue never touches outputs).

**Where (one walk, no second directory traversal):**

| File | Change | Maxima (baseline → after) |
|---|---|---|
| `core/scanner.py` (134 lines) | `scan_folder` keeps one `rglob`; the loop becomes `_collect(root, supported, recursive) → (sources, ai_files)` + `_outputs_by_source(ai_files) → {(parent, base): Path}`; every source dict gains `"existing_output": str \| None` | func LOC 28 / CC 7 / nest 3 — unchanged (new helpers ≤ 15 LOC, CC ≤ 4); file ≈ 165 lines (RULE 18.2 band) |
| `core/models.py` `ImageItem.from_scan_dict` | `output = d.get("existing_output")` → `status=COMPLETED if output else …`, `output_path=output` | CC 2 → 3 (file max already 3), LOC 20 → 23 |
| `ui/services/scan_service.py` | `merge_scanned` unchanged (new items arrive completed); new `scan_summary(scanned, added) -> str` = *"Scanned N images, A new, R already have _AI output (Reset to redo)"* | func LOC 18 / CC 5 unchanged |
| `ui/panels/queue_scan.py` | both scan workers log `scan_summary(...)` instead of their f-string (same line count — `run_scan_new_batch` sits at the file's 19-LOC maximum, so no added line there) | unchanged |
| `core/persistence._handle_changed` | dead path (no caller) — left alone, noted in SYSTEM_OF_RECORD as such | — |

**Tests (real files in `tmp_path`, RULE 8):** `tests/test_scanner.py` — `a.png`+`a_AI.png` → `existing_output` ends with `a_AI.png`; `b.png` alone → `None`; `c.png`+`c_AI_2.png`+`c_AI_3.png` (no plain `_AI`) → `_AI_3`; `ignore_ai_suffix=False` still reports outputs for the plain sources. `tests/test_models.py` — `from_scan_dict` with/without output. `tests/test_scan_service.py` — merge of a new item with output → `completed`, not in `run_scope`; rescan of an existing `pending` (reset) item with an `_AI` sibling → stays `pending` (documents the boundary); `scan_summary` wording. Goldens unaffected (they never scan).

**Docs:** SYSTEM_OF_RECORD queue row (`completed` also = "output already on disk when discovered"), invariant I-46 *a scan adopts existing `_AI` output only for newly discovered items*; `bugfix-verification.md` §B13 covers B + C.

---

## Order of work (after your go)

1. **Area A** — untrack `config/` (keep `.gitkeep`), `logs/`, `*.pyc`, `arena webpages/`; `.gitignore`; `tests/test_repo_hygiene.py` + `pre_push_check.sh` step; README/SOR paragraph. Separate commit, pushed first. (Owner: rotate keys in parallel.)
2. **Area B** — tests red → `core/run_scope.py` → `should_continue` / `_run_with_sem` / `check_start_ready` / `batch_active` → tests green.
3. **Area C** — tests red → scanner one-walk outputs → `from_scan_dict` → `scan_summary` → tests green.
4. Gates: `pytest -n 4`, `npm run test:js`, coverage run, `verify_quality --allow-legacy --coverage-ratchet --js` and the `--changed --base origin/<branch>` lane on the committed diff; RULE 16.7 checklist walked line by line; docs (SOR I-43…I-46, §B13, QUALITY_RECHECK) in the same commits; push.

Estimated size: A ≈ 60 lines of test/shell + ignore rules; B ≈ 40 new + ~25 changed production lines, ~120 test lines; C ≈ 45 new + ~10 changed production lines, ~90 test lines. No file leaves its RULE 18 band; no ratchet maximum grows.

---

## Outcome (2026-10-09, after the go)

Delivered as planned, with three deviations worth recording:

| Planned | Done | Why |
|---|---|---|
| Claim-time check inside `should_continue` | Loop-level `claim_denied` in `_run_sequential` (before `_run_one_image`) and in `_run_with_sem` (after the semaphore, before the page) | `should_continue` stays a pure bool verdict; `_run_one_image` sits at the file's max func LOC (17) and the parallel worker needed the identical call anyway — one helper, two call sites, no wrapper |
| `scan_folder` "one walk + output map" | Same, but split into `_checked_root` / `_image_files` / `_output_rank` / `_outputs_by_source` | first cut hit CC 9 in `scan_folder` (fail-lane is >10, prefer ≤7); the split leaves `scan_folder` at CC 5 and every helper ≤ 12 LOC |
| Resume-on-scan for *every* scanned source | Newcomers only (`merge_scanned` never overrides an in-app status) | otherwise *Reset → Scan* would flip the image straight back to `completed`; boundary pinned by `test_rescan_keeps_in_app_status_of_known_items` |

### Final recheck — RULE 18 (ideal sizes) and RULE 16 (gates)

Every new or edited production function (measured with the gate's own AST counters; radon is not installed in the sandbox, `verify_quality.py` falls back to the same counting rules):

| File | Function | LOC | CC | Nesting | Params | RULE 18 verdict |
|---|---|---:|---:|---:|---:|---|
| `core/run_scope.py` | `is_runnable` | 3 | 1 | 0 | 1 | < 4 by design — predicate used in several places (18.1) |
| | `run_scope` | 3 | 3 | 0 | 1 | < 4 by design — predicate used in several places (18.1) |
| | `claim_denied` | 6 | 2 | 1 | 2 | in band |
| `core/scanner.py` | `_build_item` | 22 | 3 | 0 | 3 | 21 → 22 (one dict key); `# ideal-size: 22 lines reason=one scan-item dict literal …` |
| | `_checked_root` | 6 | 3 | 1 | 1 | in band |
| | `_output_rank` | 4 | 2 | 0 | 1 | in band |
| | `_outputs_by_source` | 11 | 5 | 2 | 1 | in band |
| | `scan_folder` | 14 | 6 | 1 | 2 | in band (first cut CC 9 rejected; the one-expression `_image_files` helper was inlined — a 3-line helper that only re-hosts a comprehension is the 18.1 anti-pattern) |
| `core/models.py` | `_discovered_status` | 5 | 3 | 1 | 2 | in band |
| | `from_scan_dict` | 20 | 3 | 0 | 2 | at the top of the band |
| `ui/services/scan_service.py` | `scan_summary` | 5 | 3 | 0 | 2 | in band |
| `ui/panels/queue_scan.py` | `run_scan_merge` / `run_scan_new_batch` | 14 / 16 | 2 / 2 | 0 | 2 / 3 | in band; `selected_images` alias **deleted** (one call re-hosted under another name, 18.1) |
| `ui/panels/run_control.py` | `check_start_ready` | 12 | 5 | 1 | 1 | in band; `check_start_inputs` / `fail_processing_images` / `start_run` only changed the callee name |
| `services/run_state.py` | `batch_active` | 4 | 2 | 0 | 1 | in band |
| `services/batch_orchestrator.py` | `_run_sequential` | 12 | 5 | 2 | 1 | in band |
| | `_load_run_settings` | 4 | 1 | 0 | 1 | in band |
| `services/multi_page_dispatcher.py` | `_run_with_sem` | 6 | 2 | 1 | 2 | in band |

Files: `run_scope.py` 44 (leaf, fine under 150), `scanner.py` 134 → 169, `models.py` 292 → **300** (top of the band; the next `ImageItem` addition splits the file), `scan_service.py` 87 → 94, `queue_scan.py` 315 → 309, `run_control.py` 275 → 279; `run_state.py` 417 → 423, `batch_orchestrator.py` 492 → 489, `multi_page_dispatcher.py` 398 → 402 — the last three were outside the band before B13 and carry their module `# ideal-size:` reason (numbers refreshed to ~420 / ~490 / ~400). Module `core/` stays at 13 files (18.3 band 5–15). Context files: `QUALITY_RECHECK.md` 176 lines (band 60–200); `SYSTEM_OF_RECORD.md` was already over 200 before this round (pre-existing debt, not grown by a new section — three invariant rows and the dated paragraph).

RULE 16.7 checklist, walked:

```text
[x] No new function >30 physical LOC                  max new/edited 22 (_build_item, legacy 21 → 22, ideal-size note)
[x] No new class >150 LOC or >15 methods              no new class; RunControlMixin stays at 10 methods (gate is a module func)
[x] No new function with >4 params                    max 3
[x] CC ≤10, cognitive ≤15, nesting ≤4                 max CC 6 (scan_folder), max nesting 2
[x] coverage ≥80 % and not below baseline; branch ≥75 %  see gate evidence (§B13) — ratchet floor 86.36 / 82.33
[x] every new function has a test that fails if deleted  verified by removing the orchestrator skip (2 fail), the Start gate (4 fail), the scanner map / model adoption (test_scan_resume fails)
[x] no new vulture/pyflakes findings; no duplication  pyflakes clean on all touched files; the duplicated predicate was removed, none added
[x] quality-override comments                         none added
[x] no dummy helpers                                  `_image_files` and `selected_images` removed for exactly that reason
[x] RULE 18 ideals                                    table above; deviations carry ideal-size reasons
[x] RULE 19 order                                     scan_folder: nesting first (validation out), then CC (AI filter as comprehension), size last
[x] SYSTEM_OF_RECORD.md + docs updated                §2 rows 2/3/6, I-44…I-46, §7 core list, §8 test rows, dated paragraph; README run-scope section; QUALITY_RECHECK follow-up; §B13 record
```

Tests added: `test_run_scope.py` 14, `test_run_control_gate.py` 6, `test_scan_resume.py` 11, `test_queue_thumbnails.py` 8 (per-file coverage floor of `queue_scan.py` after the alias deletion — covered by the real thumbnail contract, not by keeping the alias), 5 across `test_batch_orchestrator.py` / `test_multi_page_dispatcher_run.py` / `test_run_state.py`; each was checked to fail with its fix removed.
