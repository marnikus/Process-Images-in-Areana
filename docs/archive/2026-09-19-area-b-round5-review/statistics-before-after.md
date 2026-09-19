# Area B Statistics — Before vs After (2026-09-19)

**Compared:** `8529d6b` (branch point — before any Area B work) vs
`1487945` (HEAD after B20). **Method:** the BEFORE state was measured
*fresh* this session in a git worktree of `8529d6b` using the same
venv / node / jscpd toolchain (with that era's own gate tool, since the
tool itself is part of what changed); the AFTER state was measured fresh
at HEAD. Absolute counts are reported next to every percentage
(D-area anti-gaming rule).

## Master table

| Metric | Before (8529d6b) | After (1487945) | Δ |
|---|---|---|---|
| Gate fails — structural (no coverage.json) | **149** (78 files) | **128** (76 files) | **−21** |
| Gate fails — incl. absolute coverage lanes | 151 | 130 | −21 |
| Pre-push lane (`--coverage-ratchet`) | did not exist; `pre_push_check.sh` could not pass | 128 fails, script **exit 0** | new capability |
| Coverage — line | 41.21% (5,112 / 11,721) | **44.31%** (5,143 / 11,003) | +3.10 pts |
| Coverage — branch | 32.28% (1,020 / 3,160) | **35.10%** (1,018 / 2,900) | +2.82 pts |
| pytest | 459 passed | **541 passed** | +82 |
| node tests | 101 pass, **1 fail** (`test_captcha_recording.mjs`) | **115 pass, 0 fail** | +14, red→green |
| vulture @90 (app) | 13 findings | **0** findings | −13 |
| jscpd clones / dupLines (app+tests) | 55 / 599 | **42 / 454** | −13 / −145 |
| app .py files | 78 | 76 | −2 (−4 dead modules, +2 new: `json_store`, `probe_selectors`) |
| app LOC | 19,037 | 17,715 | **−1,322** |
| app functions / classes | 1,052 / 77 | 996 / 73 | −56 / −4 |
| `CDPArenaController` | 371 LOC / 30 methods | 359 / 28 | −12 / −2 |
| `CDPClient` | 469 LOC / 22 methods | 456 / 21 | −13 / −1 |
| `Bridge` class / `bridge.py` / max func | 5,000 LOC / 200 methods / 5,127 / 1,209 (`_do_run_batch`) | unchanged (5,128) | 0 — Area A scope |
| pytest files / test functions | 46 / 304 | **53 / 374** | +7 / +70 |
| js test files (`test_*.mjs`) | 11 | 12 | +1 |
| Gate-tool self-tests | 0 | **14** (subprocess) | +14 |
| Quality baseline | flat per-file maxima only | + per-symbol `funcs` maps (220 bridge symbols) + tamper-proof coverage floor 44.31/35.10 | hardened |
| B-owned module coverage | e.g. `preset_store` 29.3/20.0, `output_state` 3.7/0.0 | **all 12 owned modules ≥80/75** (8 at 100/100) | F-1 closed |
| Commits / review rounds | — | 24 commits, 5 review rounds (B1–B6, B7–B12, B13–B15, B16–B18, B19–B20) | — |
| Docs / test deliverables | — | 13 new docs (reviews, plans, records) + 10 new test files | — |

## Coverage denominator honesty (anti-gaming)

- **Line:** covered lines went 5,112 → 5,143 (**+31** genuinely covered)
  while total statements went 11,721 → 11,003 (**−718**, dead-code
  deletion). Both effects contributed to +3.10 pts — neither alone.
- **Branch:** covered branches 1,020 → 1,018 (**−2**) while branch points
  3,160 → 2,900 (**−260**). The ratio gain (+2.82 pts) comes from
  removing uncovered dead branches, not from new branch tests. Recorded
  honestly.

## Milestones per round (each measured fresh at the time)

| Round | Key deltas |
|---|---|
| Base → B1–B6 | gate 149→128; −1,239 LOC dead code; cov 41.21/32.28 → 43.09/33.76; jscpd 55→44 clones; vulture 13→0; node 101/1-fail → 111/0 |
| B7–B12 | cov → 44.31/35.10; owned modules all ≥80/75; pytest 459→533; node →115; jscpd →42/454; pre-push script exit 0 for the first time |
| B13–B15 | gate tool itself fits RULE 18 (all funcs ≤30 LOC, self-check clean); node lane in pre-push; docs aligned |
| B16–B18 | coverage floor tamper-proof; changed-file lane gates exactly the unpushed commits; 539 pytest |
| B19–B20 | per-symbol legacy ratchet — D6 negative test proven (36-LOC function in `bridge.py`: exit 0 → **exit 1**); 541 pytest |

## Verified unchanged (other areas' scope — honest boundaries)

- `Bridge` 5,000 LOC / 200 methods, `bridge.py` ~5,127, max function
  1,209 LOC `_do_run_batch` → Area A (A4/A5).
- Coverage of `cdp_client` (9.2%), `output_wait`, `single_job_runner`,
  `bridge` → Areas C/D (D4 ramp).
- Absolute 80/75 coverage target → D4 (ratchet enforces the
  never-decrease half meanwhile).
- cc/cognitive/params/methods/nesting on legacy files still downgrade
  (no baseline maxima for them) → R0.3/D6 full form.

## Reproducibility

```bash
# AFTER (current tree)
bash tools/pre_push_check.sh                      # full battery, exit 0
python tools/verify_quality.py --json --coverage-ratchet
QT_QPA_PLATFORM=offscreen python -m coverage run --branch --source=app -m pytest tests -q
npx jscpd app tests --min-tokens 60 --reporters json --output /tmp/j
python -m vulture app tools/vulture_whitelist.py --min-confidence 90

# BEFORE (git worktree of the base, same venv/node)
git worktree add /tmp/base_wt 8529d6b && cd /tmp/base_wt   # then same commands
```

Worktree measurement note: the base node failure
(`test_captcha_recording.mjs`, generic "test failed") reproduces at
`8529d6b` and passes at HEAD in the identical environment.
