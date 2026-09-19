# Batch B — third review pass: findings & steps (2026-09-19)

Scope: re-compare the as-built Batch B (two prior commits + gate fix) against the doc
specs one more level down — this pass reads the *workflow* docs (`CODE_VERIFICATION.md`,
SYSTEM_OF_RECORD §7, AGENT_RULES RULE 16 executable line) against the actual flow, and
audits the gate plumbing itself.

## Review results

Conforms (re-verified):
* `import_graph.py` full mode works (verdicts per module, exit 0) — only `--dead` had
  been exercised after the round-2 refactor.
* B-surface coverage is healthy: `json_store` 91%, `selector` 100%, `key_store` 100%,
  `solver` 89%, `site_adapter` 78% (generated data), config 82% — all at/above the
  80% target except the generated table.
* `verify_quality.py` flags confirmed (`--json/--changed/--allow-legacy/--baseline`).
* Working tree clean; branch green after two consecutive full pre-push runs.

Gaps found:

| # | Finding | Rule | Severity |
|---|---|---|---|
| G1 | `CODE_VERIFICATION.md` (the mandatory push-workflow doc) describes the PRE-Batch-B flow: syntax step = 7 hardcoded files; no selector-sync or dead-module gate; coverage step shown as push-blocking (the script is now report-only, with the documented pre-existing-gap rationale); no mention of the script's venv interpreter resolution ($PY) | 17 | must fix |
| G2 | SYSTEM_OF_RECORD §7 persistence row names `app_state.py` (does not exist) and `layout_service.py` (lives in `core/`); missing `json_store.py`, `preset_store.py`, `cooldown_store.py`. Browser row should note the map is generated (RULE 21 generator + sync gate) | 17 | must fix |
| G3 | `pre_push_check.sh` step 1 only `py_compile`s 7 hardcoded files — syntax gate does not cover the rest of the production tree (incl. all Batch B files) | 16 (gate plumbing) | should fix |
| G4 | AGENT_RULES.md RULE 16 executable line lists the gate flow without the two new gates (selector sync, dead modules) | 17 | should fix |

## Rejected (with reasons)

* **Shrink `quality_baseline.json`** for improved files: `verify_quality.py` has no
  update-baseline flag; manual curation of ceiling values risks breaking the gate on a
  miscalculated max. The ratchet's purpose is *not increasing* legacy — it is met. Revisit
  with a tool flag, not hand edits.
* **pytest smoke tests that run the two new tools as subprocesses**: no existing
  convention in `tests/` runs tools via subprocess (grep: zero hits); the gates are
  enforced at push time (hook) and documented as manual commands — duplicating them in
  the suite would start a second enforcement channel to keep in sync. RULE 8 covers
  production behaviour (455 tests); gates are tooling.

## Steps (implementation order)

1. **G1 — rewrite `CODE_VERIFICATION.md`** to match the real flow: syntax = whole tree,
   gate = `--changed --allow-legacy`, **plus the two new gates** (`generate_selectors.py`
   `--check` selector drift, `import_graph.py --dead` dead modules), tests, coverage =
   report-only (pre-existing gap tracked in `improvements-2026-09-19.md`), hook + `$PY`
   venv resolution. Keep the override-format section (still true). Stay ≤200 lines
   (RULE 18 context-file ideal).
2. **G2 — fix §7 rows**: persistence = `json_store.py` (canonical atomic writer /
   tolerant loader), `config_manager.py`, `preset_store.py`, `undo_store.py`,
   `cooldown_store.py`; add `layout_service.py` to the core row (it was already listed
   under core in code, the persistence row was the error); browser row notes the
   generated map + generator.
3. **G3 — `pre_push_check.sh` step 1**: `py_compile` every `app/**/*.py` +
   `tools/*.py` (find-based) instead of the 7-file list.
4. **G4 — AGENT_RULES.md RULE 16 line**: append the two new gates to the executable-flow
   sentence (no rule renumbering — RULE 17 append/amend discipline).
5. **Final gates**: full pre-push script (hook will run it on push), pytest, pyflakes/
   vulture, selector sync + dead audit.
