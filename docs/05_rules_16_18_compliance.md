# 05 — RULE 16 & RULE 18 Compliance

Re-checked after implementation, as required.

---

## RULE 16 — Code-quality gates on every production change

| Gate | Rule | This change set |
|---|---|---|
| G1 Build/boot | app must start | optional SDK import guarded; `QFileDialog is None` handled; no new hard dependency |
| G2 Lint | no unused imports, no bare `except:` | every `except` is typed or `# noqa: BLE001` with a reason |
| G3 Types | annotated public functions | all new Python is `from __future__ import annotations` + typed signatures |
| G4 Unit tests | new logic is testable headless | `merge_missing_defaults`, `load_blocks`, `dispatch`, `audit_slots`, `resolve_start_dir`, `CaptchaGate` are pure/injected — no Qt, no network |
| G5 No silent failure | every catch reports | `BridgeCall`, `PanelBoot`, `dispatch()` return/emit a reason |
| G6 No dead code | replaced code is deleted | removal map in `docs/03` §5 |
| G7 Layering | ui → services → core, never upward | new services import no Qt; new panels import no browser internals |
| G8 Contracts checked | drift fails loudly | `audit_slots()` banner + `tools/check_dom_ids.py` |
| G9 Secrets | keys never in logs/state | API key stays in `config/2captcha.json`; `SdkConfig` is never serialised into logs |
| G10 Docs | change explains itself | five docs, each mapped to a phase |

### CI gate (`tools/check_dom_ids.py`)

The gate fails the build when JS references a DOM id that neither
`index.html` ships nor JavaScript creates on demand (guarded
`createElement` + `id` assignment — the element is guaranteed to exist at
the point it is read, so it is not contract drift):

```python
GET_BY_ID  = getElementById('literal')        # must exist
JS_ID_ASSIGN = .id = 'x'                      # JS-created: OK
JS_ID_IN_MARKUP = id="x" in JS strings        # JS-created: OK
```

Baseline before this work: **14 missing ids**. Target: **0**.

---

## RULE 18 — Ideal sizes: write for the reader's context budget

Limits used: file 150–300 lines ideal (hard cap 400 with a justification
header), function ≤ 30 lines, cyclomatic complexity ≤ 10, parameters ≤ 4,
class ≤ 10 public methods.

| Deliverable | Lines | Longest fn | CC max | Params max | Verdict |
|---|---|---|---|---|---|
| `app/services/captcha/sdk_client.py` | 171 | 19 | 5 | 2 | ✅ |
| `app/services/captcha/watcher_gate.py` | 167 | 17 | 4 | 4 | ✅ |
| `app/services/watcher_pkg/captcha_step.py` | 185 | 17 | 6 | 4 | ✅ |
| `app/ui/bridge_slots.py` | 157 | 16 | 6 | 3 | ✅ |
| `app/ui/panels/blocks_defaults.py` | 144 | 18 | 6 | 2 | ✅ |
| `app/ui/panels/folder_browse.py` | 140 | 16 | 5 | 2 | ✅ |
| `js/core/bridge-call.js` | 112 | 14 | 6 | 3 | ✅ |
| `js/core/panel-boot.js` | 101 | 22 | 7 | 2 | ✅ |
| `js/panels/url-list/add-url.js` | 103 | 12 | 5 | 2 | ✅ |
| `js/panels/folder-picker-browse.js` | 106 | 16 | 6 | 2 | ✅ |
| `js/panels/action-blocks/block-defaults.js` | 129 | 18 | 5 | 2 | ✅ |
| `js/panels/arena-presets/prompt-presets.js` | 127 | 14 | 5 | 2 | ✅ |
| `js/panels/watcher/captcha-watch.js` | 112 | 18 | 6 | 2 | ✅ |

All 13 code files land inside the 100–300 line window; the five docs are
93–169 lines. No file needs the 400-line escape hatch.

Where a file carries an `# ideal-size:` header it states *why* it stays one
unit (RULE 18.2 — do not scatter pairs that always change together).

### Sizes removed vs added

| | Before | After |
|---|---|---|
| captcha transport | `api_client.py` 3.9 KB + `solver.py` 28.6 KB | `sdk_client.py` ~5 KB |
| captcha decision | spread over 5 modules | `watcher_gate.py` ~5 KB |
| captcha per-page state | `recovery.py` 8.4 KB | inside `captcha_step.py` |
| **net** | ~41 KB | ~17 KB |

### Files still over budget (tracked, not touched here)

| File | Bytes | Planned split |
|---|---|---|
| `app/ui/web/index.html` | 55 835 | one partial per window + a loader |
| `app/services/single_job_runner.py` | 32 586 | already block-shaped → one module per block family |
| `app/core/action_blocks.py` | 31 513 | catalog / defaults / validation |
| `app/services/cooldown_service.py` | 26 729 | policy vs store |

These are listed so the debt is visible; none of them is enlarged by this
change set — `single_job_runner.py` and `cooldown_service.py` both shrink
when the captcha branches are cut.
