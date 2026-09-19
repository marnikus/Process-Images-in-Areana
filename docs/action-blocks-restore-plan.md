# Action Blocks Restore Plan — Arena (from Old App)

Date: 2026-09-15
Source: `Process Images in Areana/Old App` analysis (tree removed in R1 — readable at commit `11e6520`) + current Arena `app/core/action_blocks.py` + `app/ui/web/js/panels/action-blocks.js`
Goal: Restore full stacking jobs / Action Blocks system as in Old App, adjusted to Arena image-to-image workflow, with visual confirmations, rectangles, separate jobs visibility.

---

## 1. Old App Analysis (findings)

### 1.1 Registry & Base
- `actions/registry.py`: self-registration via `__init_subclass__` with `block_id`. `scan()` via `pkgutil.iter_modules` auto-imports every `actions/*.py` — no central list.
- `actions/base.py`: 
  - `BaseAction` with `block_id`, `name`, `icon`, `pre_delay_ms`, `enabled`, `config` dict, `to_dict()` serializes all public attrs round-trip safe, `display_name` uses `custom_name` if set.
  - `BlockField` dataclass: ONE setting = panel entry + cleaning + visual-click keyword (`request`). Fields: `name, type, label, default, options, help, clean, request`.
  - `DeclaredSettings(BaseAction)`: `FIELDS` tuple drives constructor, `to_dict()`, `config_schema()` — cannot drift. Defaults from `__init__` signature, cached via `_SIGNATURES`.
  - `FindClickBlock(DeclaredSettings)`: family that finds & clicks visibly. `label_template`, `find_defaults`, `click_runner()` looks up `find_and_click` in own module first (for patching), fallback shared runner. `find_kwargs()` builds runner kwargs from declared fields where `request` set. `fallback_attempts()` returns `(notice, label, kwargs)` extra tries.
  - `MarkerBlock`: engine-driven, no pre-delay, returns SKIP, logs marker message.

### 1.2 Visual Runner (RULE 1)
- `backend/visual_click.py`:
  - `ClickRequest` dataclass 10 kwargs: `selector, label_selector, match_text, match_mode, click_enabled, click_selector, highlight_enabled, confirm_pause_ms, highlight_ms, label`.
  - `find_phase(cdp, request, engine)`: logs FIND, `cdp.evaluate(find_probe)`, parses JSON, `interpret_find()`, draws RED outline via JS helper `highlight(el, color, ms, caption)`. Returns dict or None.
  - `click_phase`: ORANGE outline on click target, checks clickable, `CLICK_PAUSE_MS=250` beat, dispatch click.
  - `run_click`: both phases + hold `confirm_pause_ms` for visual confirmation. Entry `find_and_click()` adapter over `run_click()`.
  - `_report(engine, msg, level)` streams to `engine.report`.
- `backend/dom_highlight.py`:
  - Helpers: `probeVisible(el)` checks computed style display/visibility + offsetWidth/ClientRects, `describe(el)` tag+class, `clearHighlights()` removes `[data-cf-highlight]`, `highlight(el,color,ms,caption)` creates fixed div `outline:2px solid color`, `pointer-events:none`, `z-index:2147483647`, caption tag absolute -16px, auto-remove after ms.
  - Chassis `_PROBE_JS`: diagnostic object `out` with `phase, query, total, found, index, text, visible, disabled, clickable, clicked, target_desc, highlighted, rect, candidates, note, error`, try/catch → JSON.
  - `_FIND_BODY`: query vars `sel, childSel, matchText, exact`, label JS inner text trimmed 120, match filter exact/contains, `probeVisible(node)`, stash on `window.__cfStash`, highlight RED, candidates list up to max.
  - `_CLICK_BODY`: uses stashed element, optional `clickSel` descendant, fallback self-match `root.matches(clickSel)`, highlight ORANGE, `scrollIntoView({block:center})`, click.
  - `build_find_probe`, `build_click_probe`, `build_highlight_probe`, `build_clear_probe`.
  - Colors: `COLOR_FIND` RED `#ff2d2d`, `COLOR_CLICK` ORANGE `#ff9500`, `COLOR_COLLECT` GREEN `#00c853`.

### 1.3 Blocks Catalog (BUILTIN_BLOCKS from `stack-dnd.js`)
- 17 built-ins, each with `block_id, name, icon, defaults, labels, options/radios`:
  - `CUSTOM_FIND`: generic find & click — `custom_name, selector (① box), label_selector (② inner text), match_text ({{nick}} support), click_enabled, click_selector (optional inner), highlight_enabled, confirm_pause_ms, highlight_ms, pre_delay_ms, enabled`.
  - Others: `CLICK_MAIN_TAB`, `SCROLL_PARSE` (max_scrolls, scroll_pause_ms, viewport_selector, person_selector, highlight, filter_female etc), `CONDITIONAL_SKIP`, `CLICK_USER`, `WAIT_PAGE_LOAD`, `TYPE_MESSAGE` (message, use_composer, typing_speed_ms), `CLICK_SEND` (selector + fallback_selector fallback_text), `ATTACH_IMAGE` (folder_path, file_pattern, rotation_mode, simulate_dialog, verify_timeout_ms), `CLICK_BACK`, `PAUSE`, `SPEED_MULTIPLIER`, `TAKE_PERSON` (pick_mode random_new/random_done/order_first), `SEARCH_USERS`, `MARK_MESSAGED`, `COLLECT_HISTORY`, `REPEAT_LOOP`.
- Each block's settings are plain instance attrs, defaults mirrored in JS catalog for UI render.

### 1.4 UI Stack Editor (Old)
- `stack-dnd.js` facade + parts:
  - `stack-dnd-render.js`: stack list render, drag reorder, selection.
  - `stack-dnd-config.js`: Block Config pin / keep-open (localStorage + config.json).
  - `stack-dnd-form.js`: Tune panel row-builder table + Speed Multiplier.
  - `stack-dnd-menu.js`: + menu, run/save/export buttons, custom presets.
  - `stack-dnd-history.js`: block migration (strip RETIRED_KEYS, backfill defaults), undo/redo history 100 cap.
- Features: drag_indicator win-grip, enable toggle bar, custom_name shown in stack & logs, visual confirmation outlines config per block, pre-delay per block, save stack snapshot debounced 800ms via `bridge.snapshot_stack`.
- Custom Find presets: `presets-ui-blocks.js` — save block as preset chip, load adds to stack.

### 1.5 Execution Engine
- `services/run/coordinator.py` `RunCoordinator(QObject)` mixins: CycleLoop, CollectPhase, CyclePlan, ErrorRecovery, Hooks, Progress, RunLifecycle.
- `load_stack(blocks)`: `normalize_blocks` + `get_action_class` + `cls(**block)`; `get_stack()` returns `to_dict()` list.
- `execute(scroll_parser)`: begin_run → pre_run hook → for cycle in repeat_count → gate_before_cycle (stop) → execute_cycle → cycle_transition → mark_run_done → post_hook → finish_signals.
- `_execute_cycle`: prepare queue (collect→filter→order→take), inspect_stack, choose_cycle_mode (queued/standalone/empty), run_user_queue.
- Each block `execute(user_nick, cdp, engine)` → `ActionResult.OK/FAIL/SKIP`. Engine reports via `engine.report(msg, level)` → `debug_msg` signal → log console + trace.
- Stop honoured via `check_stopped(self)` at top each iteration + inside inner waits; `RunStopped` exception.
- Progress: `RunProgress` bus, `extend_total`, `note_status`.

### 1.6 Confirmation Idea Restored
- User sees RED outline on found element, pause `confirm_pause_ms` to eyeball, then ORANGE outline on click target, then click. For collect (Scroll & Parse detected person) GREEN outline.
- Overlay is `div` with `data-cf-highlight`, transparent, pointer-events:none, never intercepts.
- Duration configurable per block `highlight_ms`, saved in preset JSON, plus global `highlight_duration_seconds` in settings.
- Separate jobs: each job (user processing) shows its own stack execution with rect confirmations in log console.

---

## 2. Current Arena State (Gap)

### Current `app/core/action_blocks.py`
- 14 block types fixed for Arena flow, but missing generic CUSTOM_FIND capability.
- Each block: `id, block_id, name, description, icon, enabled, selector, color, timeout_ms, required, category, custom_name, pre_delay_ms, highlight_duration_ms, extra`.
- No `BlockField` pattern, no `label_selector`, `match_text`, `click_selector`, `click_enabled`, `confirm_pause_ms` per block distinct from highlight duration.
- `BLOCK_DEFINITIONS` has `default_selector` but not full selector priority table.
- `default_stack()` order fixed, validation ensures required present.

### Current `app/browser/dom_highlight.py`
- Exists but simplified vs old. Need check if it implements stash `__cfStash`, candidates, RED/ORANGE/GREEN, caption, clear.
- `cdp_arena.py` likely uses `highlight_selector` but not two-phase find/click with stash.

### Current UI `action-blocks.js`
- Has `blocks[]`, `jobStatuses{}`, `currentJobId`, drag reorder via HTML5 DnD, enable toggle, delete, edit via prompts, add via prompt, save/load via bridge.
- `render()` creates block element with drag handle, icon, info, controls.
- `renderJobStack(jobId)` shows per-block status pending/running/success/failed/skipped with color border, icon map, rect button to re-highlight.
- Missing: rich config panel per block (like Old's Tune panel with labels), `BlockField` driven form, custom_name edit, selector validation, fallback selectors, match_text, label_selector UI.
- Missing: separate jobs view — only current job shown, not all jobs with rectangles confirmations as it makes clicks.

### Current Execution `app/services/job_runner.py` or `bridge._do_run_batch`
- Likely runs fixed pipeline, not generic block stack interpreter. Need to adapt to run any stack including CUSTOM_FIND blocks.

### Storage
- `config/arena.json` stores `action_blocks` as list of dicts, but schema not versioned with `highlight_ms`, `confirm_pause_ms`, `label_selector`, `match_text`, `click_selector`.
- Preset system exists but not per-block presets like Old's custom blocks chips.

---

## 3. Desired Design for Arena — Restore & Adjust

### 3.1 Block Types for Arena (adjust to current needs)

Keep Old's pattern: BUILTIN_BLOCKS with defaults + labels, but Arena-specific:

| block_id | name | icon | purpose | defaults (Arena adjusted) | category |
|---|---|---|---|---|---|
| `CUSTOM_FIND` | Find & Click | 🔎 | Generic visual click — click on btn, click on text areas | custom_name, selector (① box), label_selector (② inner), match_text ({{job_id}} support), click_enabled, click_selector, highlight_enabled, confirm_pause_ms=700, highlight_ms=2000, pre_delay_ms=200, enabled | action |
| `OBSERVE_BASELINE` | Observe Baseline | 👁️ | Capture existing outputs count | selector=`div.no-scrollbar img`, highlight_enabled, highlight_ms=1200, pre_delay_ms=200 | observe |
| `CHECK_SECURITY` | Check Security | 🛡️ | Detect CAPTCHA dialog, pause USER_ACTION_REQUIRED | selector=`div[role="dialog"][data-state="open"]`, match_text=`Security Verification`, highlight_enabled, highlight_ms=2000 | observe |
| `ATTACH_IMAGE` | Attach Image | 🖼️ | Attach via CDP setFileInputFiles, verify preview | selector=`input[type="file"]`, file_pattern, simulate_dialog (click Add files btn), highlight_enabled, confirm_pause_ms, verify_timeout_ms=8000 | action |
| `HIGHLIGHT_ATTACH` | Highlight Attach | ✨ | Visual rect over file input before attach | selector=`input[type="file"]`, color=#00FF00, highlight_ms | visual |
| `TYPE_PROMPT` | Type Prompt | ⌨️ | Type prompt into textarea (Arena version of TYPE_MESSAGE) | selector=`textarea[name="message"]`, use_composer false, message (base prompt), typing_speed_ms=10, highlight_enabled, confirm_pause_ms | action |
| `INSERT_PROMPT` | Insert Prompt | 📝 | Insert final prompt with [JOB-ID] token | selector=`textarea[name="message"]`, color=#00AAFF | action |
| `VERIFY_PROMPT` | Verify Prompt | ✅ | Read back textarea value verify exact | selector=`textarea[name="message"]` | verify |
| `CLICK_SEND` | Click Send / Submit | 📨 | Click Send button once, fallback | selector=`button[aria-label="Send message"]`, fallback_selector=`button:has(svg)`, fallback_text=`Send`, highlight_enabled, confirm_pause_ms | action |
| `WAIT_OUTPUT` | Wait New Output | ⏳ | Wait new output baseline comparison | selector=`div.no-scrollbar img`, timeout_ms=180000, highlight_enabled, highlight_ms | wait |
| `DOWNLOAD` | Download HQ | ⬇️ | Download highest quality | selector=``, timeout_ms=30000 | action |
| `VALIDATE` | Validate Image | 🔍 | Validate bytes not HTML, PIL check | — | verify |
| `SAVE` | Save *_AI.ext | 💾 | Atomic save beside source | suffix=_AI, overwrite false | persist |
| `ADVANCE` | Advance & Persist | 🏁 | Mark completed, persist | — | persist |
| `PAUSE` | Custom Pause | ⏸️ | Pause N ms | duration_ms=1000 | control |
| `HIGHLIGHT` | Highlight Only | 🎯 | Pure visual confirmation, no click | selector, label_selector, match_text, highlight_ms, color | visual |

**Total ~16 types**, same pattern as Old's 17 but Arena-focused. `CUSTOM_FIND` is the powerful generic that lets user click any btn/text area with visual confirmations.

### 3.2 Visual Runner Restoration (RULE 1)

Restore Old's `ClickRequest` dataclass in `app/browser/dom_highlight.py` + `app/browser/cdp_arena.py`:

```python
@dataclass
class ClickRequest:
    selector: str
    label_selector: str = ""
    match_text: str = ""
    match_mode: str = "contains"  # exact vs contains
    click_enabled: bool = True
    click_selector: str = ""
    highlight_enabled: bool = True
    confirm_pause_ms: int = 700
    highlight_ms: int = 2000
    label: str = "element"
```

- `build_find_probe(selector, FindProbeSpec(...))` → JS with RED `#ff2d2d`, stash `__arenaStash`.
- `build_click_probe(click_selector, ClickProbeSpec(...))` → ORANGE `#ff9500`, uses stashed.
- `build_highlight_probe` → GREEN `#00c853` or custom color, no click, no scrollIntoView.
- `build_clear_probe` → remove all `[data-arena-highlight]`.
- Helpers: `probeVisible`, `describe`, `clearHighlights`, `highlight` exactly as Old but attr `data-arena-highlight`, stash `__arenaStash`.
- Phases:
  - FIND: log success/failure, selector tried, count, visibility, candidates near-misses, draw RED, pause `confirm_pause_ms` (scaled by speed multiplier if present).
  - CLICK: log clickability, draw ORANGE, `CLICK_PAUSE_MS=250`, click, log result.
- All blocks that click go through `find_and_click(cdp, request, engine)`.
- Overlay: `position:fixed, outline:2px solid color, outline-offset:-1px, background:transparent, pointer-events:none, z-index:2147483647`, caption tag with label.

Configurable durations saved in preset JSON:
- Per-block: `highlight_ms` (how long outline stays), `confirm_pause_ms` (pause after found to eyeball).
- Global settings: `settings.highlight.duration_seconds` (default outline lifetime), `settings.highlight.confirm_pause_ms`.
- Both stored in `config/arena.json` + `config/session.json` + per preset file.

### 3.3 Block Storage Process (restore storing)

Old pattern: `to_dict()` serializes all public attrs, round-trip via `cls(**data)`. Use same:

- Python `ActionBlock` dataclass with fields:
  ```
  id: str (uuid)
  block_id: str (type)
  name: str
  description: str
  icon: str
  enabled: bool
  selector: str
  label_selector: str
  match_text: str
  match_mode: str (contains/exact)
  click_enabled: bool
  click_selector: str
  highlight_enabled: bool
  color: str
  timeout_ms: int
  required: bool
  category: str
  custom_name: str
  pre_delay_ms: int
  highlight_ms: int
  confirm_pause_ms: int
  extra: dict (for future)
  ```
- `to_dict()` → dict with all fields, `from_dict()` → instance.
- `BLOCK_DEFINITIONS` dict with `name, description, icon, default_enabled, default_selector, color, required, category, default_label_selector, default_match_text, etc`.
- `DEFAULT_STACK_ORDER` list of block_ids for Arena default.
- `create_default_block(block_type)` uses definitions.
- Persistence: `config/arena.json` key `action_blocks` = list of dicts. Also `config/session.json` same for session resume. Preset files `config/presets/*.json` include full `action_blocks` + `settings` + `prompt` + `urls`? Per spec, all UI params storable, so preset = snapshot of `prompt, action_blocks, settings, urls, folder` minus queue jobs.
- Versioning: add `version` field in arena.json, migration strips RETIRED_KEYS (like old), backfills missing defaults.

### 3.4 UI Representation — Separate Jobs & Rectangles Confirmations

Restore Old's stack editor + job execution view:

- Left panel: Action Blocks stack (like Old's StackDnD)
  - Drag & drop reorder with win-grip `drag_indicator`.
  - Each block row: drag handle, icon (color), display_name (custom_name or name), meta (block_id • category • selector truncated), enable toggle (checkbox, disabled if required), edit button, delete button (if not required).
  - Click row selects it → Tune panel (or inline form) shows all fields for that block: custom_name text, selector text, label_selector text, match_text text, match_mode select (contains/exact), click_enabled checkbox, click_selector text, highlight_enabled checkbox, color picker, pre_delay_ms number, confirm_pause_ms number, highlight_ms number, timeout_ms number, enabled toggle.
  - Double-click block row triggers highlight of its selector via `bridge.highlight_selector(selector, color, highlight_ms, name)` — visual confirmation on page.
  - Add block button shows dialog with available types (like Old's + menu) — list of BUILTIN_BLOCKS not already in stack or allowed duplicates (e.g., CUSTOM_FIND, PAUSE, HIGHLIGHT can duplicate).
  - Save/Reset/Export/Import buttons (Old's preset-ui-blocks).

- Right / bottom panel: Job Execution Stack (separate jobs view)
  - When job starts: `job_started` signal → create job entry with id, imagePath, timestamp, status running.
  - Per block execution: `job_action_status` signal with `jobId, blockId, statusJson` where `statusJson = {status: pending|running|success|failed|skipped, message, rect: {x,y,width,height}, timestamp, block_name, color, highlight_duration_ms, selector, candidates}`.
  - Render as vertical list per job: each block row with status icon (hourglass_empty, play_circle, check_circle, error, skip_next), name, status text, message, rect button (highlight icon) that re-shows overlay on page for N seconds.
  - Show all jobs, not just current: list of jobs with collapsible per-job stack, or tabs. User sees separate jobs and rectangles confirmations as it makes clicks.
  - Visual: when block runs, overlay appears on page in its color for `highlight_ms`, and log console shows `🔍 FIND phase`, `🖱 CLICK phase`, `✅ FIND success`, `✅ CLICK success` etc (same as Old's logs).

- Log console: same as Old, shows step-by-step debugger detail via `engine.report`.

- Highlight overlay UI: `app/ui/web/js/panels/highlight.js` already exists — ensure it can show multiple rects, with label, color, duration, and that backend can trigger it via `highlight_selector` bridge method and via `job_action_status` rect.

### 3.5 Execution Engine Adjustment

Current `job_runner.py` runs fixed pipeline. Need to make it block-driven:

- `CDPArenaController` or `JobRunner` loads stack from `action_blocks` list.
- For each image job:
  - For each block in stack order:
    - If not enabled → report skipped success, continue.
    - `await pre_delay` (pre_delay_ms).
    - Switch on block_id:
      - `CUSTOM_FIND`: build ClickRequest from block fields, call `find_and_click(cdp, request, engine)`. Report status with rect.
      - `OBSERVE_BASELINE`: capture baseline via `evaluate` probe that lists existing output imgs srcs.
      - `CHECK_SECURITY`: probe for security dialog selector + match_text, if visible → emit USER_ACTION_REQUIRED, pause until dialog gone (poll).
      - `ATTACH_IMAGE`: if highlight_enabled → highlight attach input (GREEN), then `DOM.setFileInputFiles`, verify preview container has img.
      - `HIGHLIGHT_ATTACH`: pure highlight.
      - `TYPE_PROMPT`/`INSERT_PROMPT`: highlight textarea BLUE, type/insert final prompt with token, verify read-back.
      - `VERIFY_PROMPT`: read back textarea value, compare exact.
      - `CLICK_SEND`: find_and_click with fallback attempts (like Old's ClickSend fallback).
      - `WAIT_OUTPUT`: poll for new img not in baseline, wait complete && naturalWidth>0, GREEN rect.
      - `DOWNLOAD`: fetch src via httpx.
      - `VALIDATE`: PIL check.
      - `SAVE`: atomic save.
      - `ADVANCE`: mark completed, persist.
      - `PAUSE`: sleep duration_ms.
      - `HIGHLIGHT`: pure highlight probe.
    - On failure: if block required → job fails; else → continue? For Arena, required blocks failure = job failed. Non-required failure = log warn, continue (fail open per RULE 9).
    - Emit `job_action_status` after each block with rect if found.
- Stop honoured: `should_stop` predicate checked at top each block and inside inner waits (WAIT_OUTPUT polling, CAPTCHA wait, DOWNLOAD).
- Progress incremental: `job_started` → per block status → `job_finished`.

### 3.6 Selector Priority & Verification (RULE 21)

- All selectors in `app/browser/site_adapter.py` with primary + fallbacks, same as DOM_SELECTORS.md.
- Generic CUSTOM_FIND blocks allow user to override selector, but default selectors from definitions use semantic priority: `aria-label, name, type, placeholder, role` > structural > class fragment.
- Verification approach same as Old: `probeVisible`, `total matched`, `candidates` near-misses, `rect`.

### 3.7 Presets & Save Variables (restore full)

- Old had `config.json` storing block config pin, stack, presets. New: `config/arena.json` stores `action_blocks`, `settings.highlight` (duration_seconds, confirm_pause_ms, color), `settings.cdp` (host, port, user_data_dir), `prompt`, etc.
- Window presets: already exist via `layout_service.py` — `grid_layout`, `window_states`, `window_preset_store` in `session.json`.
- Action block presets: save/load/import/export with preview, like Old's custom blocks chips. Store in `config/presets/blocks/*.json` or inside `arena.json` as `custom_blocks`.
- All UI params storable: ensure `highlight_duration_ms`, `confirm_pause_ms`, `pre_delay_ms`, `color`, `selector`, `label_selector`, `match_text`, `click_selector` are in preset JSON.

### 3.8 Undo System (keep)

- Already exists `app/core/undo_service.py` with kinds `grid, urls, folder, queue, prompt, settings, window_states, arena, action_blocks`. Keep, ensure action_blocks edits go through undo.

---

## 4. Implementation Steps (full step by step)

### Phase 0 — Docs & Research (done)
- [x] Inspect Old App `actions/`, `backend/visual_click.py`, `backend/dom_highlight.py`, `ui/js/stack-dnd.js`, `ui/js/presets-ui-blocks.js`, `services/run/`.
- [x] Document findings in this plan.

### Phase 1 — Core Visual Runner Restore
1. Rewrite `app/browser/dom_highlight.py` to match Old's implementation:
   - Constants `HIGHLIGHT_ATTR = "data-arena-highlight"`, `STASH_KEY = "__arenaStash"`, colors RED `#ff2d2d`, ORANGE `#ff9500`, GREEN `#00c853`, BLUE `#00AAFF`, YELLOW `#FFAA00`.
   - Helpers `_HELPERS_JS`, `_base_out_js`, `_PROBE_JS`, `_splice`, `_QUERY_VARS`, `_LABEL_JS`, `_MATCH_JS`, `_FIND_BODY`, `_HIGHLIGHT_BODY`, `_CLICK_BODY`.
   - Functions `build_find_probe(selector, spec)`, `build_click_probe(click_selector, spec)`, `build_highlight_probe(selector, spec)`, `build_clear_probe()`, plus `interpret_find`, `interpret_click`, `interpret_click_target`.
   - Spec dataclasses `FindProbeSpec`, `ClickProbeSpec`, `HighlightSpec`.
2. Restore `ClickRequest` dataclass and `find_and_click`, `run_click`, `find_phase`, `click_phase` in `app/browser/cdp_arena.py` or new `app/browser/visual_click.py` (prefer separate file like Old's `visual_click.py` for single responsibility).
   - Ensure `engine.report` integration, `scale_ms` if speed multiplier present (optional).
   - Ensure overlay `pointer-events:none`, never intercepts.
3. Add `app/browser/probe_requests.py` if needed for spec dataclasses (or keep in dom_highlight).

### Phase 2 — Action Blocks Model Enhancement
4. Enhance `app/core/action_blocks.py`:
   - Add fields `label_selector, match_text, match_mode, click_enabled, click_selector, highlight_enabled, confirm_pause_ms, highlight_ms` to `ActionBlock`.
   - Update `BLOCK_DEFINITIONS` to include 16 types with full defaults (selector, label_selector, match_text, click_selector, highlight_enabled, confirm_pause_ms, highlight_ms, pre_delay_ms, timeout_ms, color, required, category, icon, description).
   - Add `BUILTIN_BLOCKS` list for JS catalog (mirror Python definitions) with labels for UI form.
   - Update `to_dict/from_dict`, `create_default_block`, `load_stack_from_dicts` with migration (strip RETIRED_KEYS, backfill defaults).
   - Add `RETIRED_KEYS` list.
   - Keep `validate_stack`.

### Phase 3 — Persistence & Presets
5. Update `app/persistence/config_manager.py` or `app/core/persistence.py` to ensure `action_blocks` saved in `arena.json` with new fields, versioned, atomic write.
6. Ensure `settings.highlight` includes `duration_seconds`, `confirm_pause_ms`, `color`, `border_width` and saved in preset JSON.
7. Add custom blocks preset store: `config/presets/custom_blocks.json` or inside `arena.json` `custom_blocks` list, with CRUD via bridge.

### Phase 4 — Execution Engine (Block Interpreter)
8. Update `app/services/job_runner.py` (or `app/browser/controller.py` + `bridge._do_run_batch`):
   - Load stack from config.
   - For each image job, iterate blocks, call appropriate handler.
   - For CUSTOM_FIND and CLICK_SEND: use visual runner `find_and_click`.
   - For HIGHLIGHT* and HIGHLIGHT: use `build_highlight_probe`.
   - For OBSERVE_BASELINE: JS probe to collect existing output srcs.
   - For CHECK_SECURITY: probe security dialog, if visible emit `USER_ACTION_REQUIRED`, pause.
   - For ATTACH_IMAGE: highlight then `DOM.setFileInputFiles` then verify preview.
   - For TYPE_PROMPT/INSERT_PROMPT: highlight textarea, insert via `Runtime.evaluate` or `type_text`, verify read-back.
   - For WAIT_OUTPUT: poll with baseline comparison, GREEN rect on new output.
   - For DOWNLOAD/VALIDATE/SAVE/ADVANCE: existing logic but wrapped as blocks.
   - Emit `job_action_status` with rect, status, message, color, duration after each block.
   - Honour stop via `should_stop` predicate checked each iteration + inner waits.

### Phase 5 — Bridge Signals
9. Update `app/ui/bridge.py`:
   - Ensure signals `action_blocks_updated`, `job_action_status`, `job_started`, `job_finished` exist.
   - Add methods `get_action_blocks`, `save_action_blocks`, `add_action_block(block_id)`, `reset_action_blocks`, `highlight_selector(selector, color, duration_ms, label)`, `get_builtin_blocks`, `save_custom_block`, `delete_custom_block`, `export_custom_block`.
   - Ensure `highlight_selector` calls `cdp_arena.highlight_selector` which uses `build_highlight_probe`.
   - Ensure `job_action_status` includes rect.

### Phase 6 — UI Restoration
10. Rewrite `app/ui/web/js/panels/action-blocks.js`:
    - Load BUILTIN_BLOCKS catalog from backend via `get_builtin_blocks` or embedded.
    - Render stack with drag_indicator, icon, display_name, meta, enable toggle, edit, delete.
    - Drag & drop reorder (HTML5 DnD) with visual feedback borderTop.
    - Selection → config form (Tune panel) that builds rows from block's schema (like Old's stack-dnd-form.js row-builder): text inputs for selector, label_selector, match_text, click_selector, custom_name, color picker, checkboxes for enabled, highlight_enabled, click_enabled, numbers for pre_delay_ms, confirm_pause_ms, highlight_ms, timeout_ms, select for match_mode.
    - Double-click to highlight selector.
    - Add block dialog: list available types, allow duplicates for CUSTOM_FIND, PAUSE, HIGHLIGHT.
    - Save/Reset/Export/Import.
    - Job execution view: `jobActionStack` container shows all jobs (not just current) with collapsible per-job stack, per-block status, rect button.
    - Integrate with HighlightOverlay panel.

11. Ensure `app/ui/web/js/panels/highlight.js` supports multiple rects, label, color, duration, and backend-triggered highlights.

12. Update `app/ui/web/index.html` if needed to include action_blocks window with proper structure (stack + job execution).

### Phase 7 — Integration & Testing
13. Manual test checklist (from `docs/manual_test_checklist.md` + Old's):
    - Add CUSTOM_FIND block with selector `button[aria-label="Add files"]`, verify RED outline, pause, ORANGE outline, click.
    - Add CUSTOM_FIND with textarea selector, verify typing.
    - Run full Arena flow with default stack, verify each block shows rect, log shows FIND/CLICK phases, separate jobs view updates.
    - Test highlight duration configurable, saved in preset JSON, persists after restart.
    - Test undo for action_blocks edits.
    - Test CDP connection with custom port and user-data-dir, tab matching.
    - Test CAPTCHA detection pauses with USER_ACTION_REQUIRED.
    - Test atomic save *_AI.ext.

14. Update docs:
    - `docs/current/SYSTEM_OF_RECORD.md` §2 #9 Action Blocks stack — update with 16 types, new fields.
    - `docs/current/DOM_SELECTORS.md` — add CUSTOM_FIND generic selectors, highlight colors.
    - `docs/current/AGENT_RULES.md` — ensure RULE 1 visual runner, RULE 3 block settings still accurate.

### Phase 8 — Push
15. Commit and push to `arena/01a0a5c5-process-images-in-areana`.

---

## 5. JSON Schemas

### ActionBlock (stored in arena.json)
```json
{
  "id": "custom_find_a1b2c3d4",
  "block_id": "CUSTOM_FIND",
  "name": "Find & Click",
  "description": "Generic visual click — click on btn, text areas",
  "icon": "search",
  "enabled": true,
  "selector": "button[aria-label=\"Add files\"]",
  "label_selector": "",
  "match_text": "",
  "match_mode": "contains",
  "click_enabled": true,
  "click_selector": "",
  "highlight_enabled": true,
  "color": "#ff2d2d",
  "timeout_ms": 10000,
  "required": false,
  "category": "action",
  "custom_name": "Click Add Files",
  "pre_delay_ms": 200,
  "highlight_ms": 2000,
  "confirm_pause_ms": 700,
  "extra": {}
}
```

### Arena Preset (config/arena.json)
```json
{
  "version": "2.0.0",
  "prompt": {"user_prompt": "...", "preview_with_token": "..."},
  "settings": {
    "highlight": {
      "enabled": true,
      "duration_seconds": 2,
      "confirm_pause_ms": 700,
      "color": "#FF0000",
      "border_width": 2
    },
    "cdp": {"host": "127.0.0.1", "port": 9222, "user_data_dir": "C:\\arena-images-chrome"},
    "timeouts": {"page_load": 30, "selector": 10, "attachment": 15, "generation": 180, "download": 30}
  },
  "action_blocks": [ {ActionBlock}, ... ],
  "custom_blocks": [ {name, block: ActionBlock, updated_at} ],
  "builtin_blocks_version": "2.0.0"
}
```

### Job Action Status (signal payload)
```json
{
  "job_id": "20260915-142530-A7F3",
  "block_id": "custom_find_a1b2c3d4",
  "block_name": "Click Add Files",
  "status": "running|success|failed|skipped|pending",
  "message": "✅ FIND success: Click Add Files — matched node #0 “Add files” (visible) — 🟥 red outline drawn at 100,200 80×30px",
  "rect": {"x": 100, "y": 200, "width": 80, "height": 30},
  "timestamp": "2026-09-15T14:30:00Z",
  "color": "#ff2d2d",
  "highlight_duration_ms": 2000,
  "selector": "button[aria-label=\"Add files\"]",
  "candidates": [{"index":0,"text":"Add files","visible":true,"clickable":true}]
}
```

---

## 6. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Selector drift on arena.ai (React/Next.js class changes) | Use semantic selectors (aria-label, name, type, placeholder) primary, structural fallbacks, avoid generated IDs/long utility chains. Keep DOM_SELECTORS.md living. CUSTOM_FIND lets user override without code change. |
| Visual runner breaks page layout | Overlay `pointer-events:none`, transparent bg, fixed position, z-index max, never calls scrollIntoView for highlight-only. Stash reuse ensures click lands on same node user saw. |
| Concurrent CDP connects cause instant disconnect | Already fixed: asyncio.Lock + loop mismatch detection + debounce + reuse check. Keep lock. |
| Grid layout mismatch (9 vs 11 windows) | Already fixed: migration in both JS and Python canonical_grid_payload. Ensure new blocks window count stays 11, add action_blocks window. |
| Action Blocks drag & drop breaks undo | All edits go through undo_service with kind `action_blocks`, 100 cap, truncate-on-branch. Automatic execution effects NOT recorded. |
| CAPTCHA bypass temptation | RULE 20: never bypass, pause USER_ACTION_REQUIRED, let user solve manually. CHECK_SECURITY block detects dialog, fails open to normal flow if probe error. |
| Partial file save on crash | RULE 23: atomic write temp+replace, never partial, validate before save. |
| Highlight duration not persisted | Store per-block highlight_ms + confirm_pause_ms + global settings.highlight in arena.json preset, validated on load. |

---

## 7. Acceptance Criteria (for implementation)

- [ ] CUSTOM_FIND block exists, can click any btn/text area with RED→pause→ORANGE flow, logs FIND/CLICK phases, shows rect overlay N seconds configurable, saved in preset JSON.
- [ ] All 14 original Arena blocks still work, plus CUSTOM_FIND, PAUSE, HIGHLIGHT = 16+ types, each with full config (selector, label_selector, match_text, click_selector, highlight_enabled, color, pre_delay_ms, confirm_pause_ms, highlight_ms, timeout_ms, enabled, custom_name).
- [ ] Visual runner restored from Old App: `build_find_probe`, `build_click_probe`, `build_highlight_probe`, `build_clear_probe`, stash `__arenaStash`, candidates, RED/ORANGE/GREEN/BLUE/YELLOW, pointer-events:none.
- [ ] Blocks storing process: `to_dict/from_dict` round-trip, `BLOCK_DEFINITIONS` + `BUILTIN_BLOCKS` catalog, migration strips RETIRED_KEYS, backfills defaults, persisted in `config/arena.json` + `session.json`, custom blocks presets chips.
- [ ] UI shows all separate jobs and rectangles confirmations as it makes clicks: stack panel with drag & drop, config form, double-click highlight, job execution panel with per-job collapsible stacks, per-block status icons, rect button to re-highlight, log console with step-by-step.
- [ ] Highlight duration configurable per block and global, saved in preset JSON, all UI params storable.
- [ ] Execution engine iterates stack, honours stop inside inner waits, reports incremental progress, emits job_action_status with rect.
- [ ] Undo system works for action_blocks edits.
- [ ] Docs updated: SYSTEM_OF_RECORD.md, DOM_SELECTORS.md, AGENT_RULES.md still accurate.
- [ ] Push to branch `arena/01a0a5c5-process-images-in-areana`.

---

*End of plan. Next: implement Phase 1-6 then Phase 7-8.*
