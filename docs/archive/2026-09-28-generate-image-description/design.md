# Design: Generate Image Description + Prompt Preset Loader

Date: 2026-09-28
Topic: new action blocks for text description generation + INSERT_PROMPT preset support

## 1. Problem

User requests two features:

1. **New action-block setup "Generate image description"**
   - Same flow as image generation: attach image + insert prompt
   - Output is different: text output (not image) that app should save
   - Save as JSON file with same base name as source image in same dir
   - Example: `icon-color-dropper.png` -> `icon-color-dropper.json`

2. **INSERT_PROMPT block preset support**
   - Currently Prompt editor uses only active prompt from current session
   - Add option to load prompt from presets (stack presets + prompt presets)
   - UI: dropdown list with prompt presets + checkbox "load from preset"

## 2. Current System Analysis

### Action Blocks
- `app/core/action_blocks.py` defines BLOCK_DEFINITIONS catalog (19 types)
- `app/services/single_job_runner.py` has handler map: 20 handlers including CUSTOM_FIND, HIGHLIGHT, PAUSE, TYPE_PROMPT
- Each block has selector, highlight, timeout, etc. Stored as plain attrs (RULE 3)
- Flow: OBSERVE_BASELINE -> ATTACH_IMAGE -> INSERT_PROMPT -> SUBMIT -> WAIT_OUTPUT -> DOWNLOAD -> VALIDATE -> SAVE -> ADVANCE

### Output Detection
- `app/browser/output_probes.py`: JS_BASELINE_V3 and JS_CHECK_NEW_OUTPUT_V3 detect new images via selectors + JOB-ID correlation
- `app/browser/cdp_arena/output.py`: PollContext, WaitSpec, wait_for_new_output loop
- `app/browser/cdp_arena/mixins.py`: OutputMixin._poll_output_diag + wait_for_new_output
- `app/browser/site_adapter.py`: SELECTORS dict with output_image, prompt_textarea, etc.

### Prompt Handling
- `app/persistence/preset_store.py`: PromptPresetMixin stores prompt_presets dict {name: {template}}
- `app/ui/panels/blocks_library.py`: slots list_prompt_presets, save/load/delete
- `app/ui/web/js/panels/arena-presets/`: store/render/actions for prompt presets
- `app/services/batch_orchestrator.py`: build_job_ids creates final_prompt from bridge.state.prompt.user_prompt + correlation token
- `app/services/single_job_runner.py`: insert_prompt uses ctx.final_prompt directly

### Frontend Action Blocks
- `block-store.js`: loads builtin catalog, custom blocks, stack presets via bridge callbacks
- `block-fields.js`: orderedDefs + row builders for config form (text, select, checkbox, color)
- `block-config.js`: head + form rendering, debounced save
- `block-render.js`: stack list rendering

### Quality Gates (RULE 16)
- Function LOC ≤30, Class ≤150, Params ≤4, Methods ≤15
- CC ≤10, Cognitive ≤15, Nesting ≤4
- Must run radon, coverage
- Ideal sizes RULE 18: func 4-20, file 150-300

## 3. Design: Feature 1 - Generate Image Description

### 3.1 New Block Types

Add 3 new block definitions to BLOCK_DEFINITIONS:

1. **OBSERVE_TEXT_BASELINE** (optional, for completeness)
   - Captures existing text outputs before generation
   - Similar to OBSERVE_BASELINE but for text
   - Selector: assistant message container

2. **WAIT_TEXT_OUTPUT** (required for description flow)
   - Waits for new text output (assistant message) after submit
   - Uses correlation ID verification same as image output
   - Timeout configurable (default 120s)
   - Highlights new text with GREEN
   - Stores text in JobCtx.text_output

3. **SAVE_DESCRIPTION_JSON** (required for description flow)
   - Saves text_output as JSON file beside source
   - Same base name as source image, .json extension
   - Example: /path/icon-color-dropper.png -> /path/icon-color-dropper.json
   - JSON format: {"description": "<text>", "source": "icon-color-dropper.png", "prompt": "...", "job_id": "..."}
   - Atomic write, unique suffix if exists (unless overwrite)
   - Validates text not empty

Alternative single block **GENERATE_IMAGE_DESCRIPTION** could combine wait+save, but modular approach keeps single responsibility (RULE 10) and allows custom stacks.

We will add:
- WAIT_TEXT_OUTPUT
- SAVE_DESCRIPTION_JSON
- OBSERVE_TEXT_BASELINE (optional marker)
- Also create stack preset builder for "Generate image description"

### 3.2 New Probe: Text Output

Create new file `app/browser/text_output_probes.py`:

- SELECTORS_TEXT: assistant message selectors
  - Primary: `div[data-message-author-role="assistant"]`, `div.group:has(div.markdown)`, etc.
  - Fallbacks: main content area text blocks
- JS_BASELINE_TEXT: capture existing assistant messages (count, texts, tops)
- JS_CHECK_NEW_TEXT: find new assistant message after correlation ID
  - Similar logic to image probe but for text:
    - Scan for [JOB-ID] markers
    - Find associated assistant container below/above
    - Extract text content (innerText, trimmed)
    - Verify associatedJobId matches correlationId
    - Return {ready: true, text: "...", rect: {...}} or {ready: false, reason: ...}

Add selector to site_adapter.py:
- "assistant_message" SelectorObject with text output selectors

Add probe selectors to probe_selectors.py:
- assistant_message_selectors() function
- text_output_selectors() alias

### 3.3 Controller & Output

Create `app/browser/cdp_arena/text_output.py` similar to output.py:
- PollContextText (old_texts, correlation_id, old_outputs)
- WaitSpecText
- wait_for_new_text_output loop (reuses same polling infra but with text check JS)

Add to mixins.py:
- TextOutputMixin or extend OutputMixin with:
  - _poll_text_diag
  - wait_for_new_text_output
  - capture_text_baseline

Simpler: add new mixin class TextOutputMixin with 2 methods to keep methods ≤15 per class (RULE 16).

Update controller.py facade to inherit TextOutputMixin.

### 3.4 Job Context & Runner

Extend JobCtx in single_job_runner.py:
- text_output: Optional[str] = None
- text_baseline: Dict[str, Any] = field(default_factory=dict)

Add handlers:
- _handle_text_baseline: captures text baseline via ctrl.capture_text_baseline()
- _handle_wait_text: waits for new text output, stores in ctx.text_output, handles timeout
- _handle_save_json: saves ctx.text_output as JSON file

Helper functions (keep small):
- _get_description_output_path(source_path, overwrite, unique_template) -> Path
  - Uses same logic as get_output_path but .json extension and same base name
- _save_description_json_file(path, text, source_name, prompt, job_id) -> bool
  - Builds JSON doc and atomic writes

Add to handler_map:
- OBSERVE_TEXT_BASELINE -> _handle_text_baseline
- WAIT_TEXT_OUTPUT -> _handle_wait_text
- SAVE_DESCRIPTION_JSON -> _handle_save_json
- Also alias GENERATE_IMAGE_DESCRIPTION if we want single block? Better keep separate.

### 3.5 Naming

In naming.py:
- Add OutputSpec for JSON? Or new function get_description_json_path
- Simplest: function get_json_description_path(source_path, overwrite=False) -> Path
  - Returns source.parent / (source.stem + ".json")
  - If exists and not overwrite, add _1, _2 suffix

But to reuse existing logic, we can add helper that reuses OutputSpec with downloaded_ext=".json" and suffix=""

Better: create new dataclass JsonSpec and function get_description_path

Keep function small, params ≤4.

### 3.6 Stack Preset

Add new stack order for description in action_blocks_defaults.py or new function build_description_stack():
- HIGHLIGHT_ATTACH, OBSERVE_TEXT_BASELINE, CHECK_SECURITY, ATTACH_IMAGE, VERIFY_ATTACHMENT, HIGHLIGHT_PROMPT, INSERT_PROMPT, VERIFY_PROMPT, HIGHLIGHT_SUBMIT, SUBMIT, WAIT_TEXT_OUTPUT, SAVE_DESCRIPTION_JSON, ADVANCE

But we should not modify DEFAULT_STACK_ORDER (that's for image generation). Instead, add new constant DESCRIPTION_STACK_ORDER and helper build_description_stack().

Also expose via builtin blocks? The preset system already allows saving stack presets, but we should provide default preset named "Generate image description" that users can load.

In blocks_stack.py, add method to get description stack JSON? Or simply document.

Simpler: add new block types to BUILTIN_BLOCKS automatically via BLOCK_DEFINITIONS, and users can create stack manually. Additionally, we can add a helper in JS to create description stack via button? But requirement says "create new action blocks setup" - implies we should add a preset or default.

We will add DESCRIPTION_STACK_ORDER constant and ensure UI can load it.

### 3.7 Second Feature: INSERT_PROMPT Preset Loader

#### Backend
- INSERT_PROMPT block needs extra fields:
  - use_preset: bool (default False)
  - preset_name: str (default "")
  - load_from_preset: bool (alias for use_preset, for UI checkbox)

In BLOCK_DEFINITIONS["INSERT_PROMPT"], add extra_defaults:
  - use_preset: False
  - preset_name: ""
  - load_from_preset: False

- In single_job_runner.py _handle_prompt:
  - If block has use_preset or load_from_preset true and preset_name set, load preset template from bridge.config.presets.load_prompt_preset(preset_name)
  - If found, use that template instead of ctx.final_prompt? But need correlation token still.
  - Build final prompt from preset template + correlation ID
  - Fallback to ctx.final_prompt if preset not found

We need access to preset store in JobCtx. bridge has config.presets.

Add helper _resolve_prompt_text(ctx, block) -> str:
  - Checks block.extra or block attributes for use_preset
  - If true, loads preset
  - Returns preset template with token or ctx.final_prompt

#### Frontend
- block-fields.js: add defs for use_preset and preset_name
  - But only for INSERT_PROMPT block type
  - Need conditional rendering: show preset dropdown only when INSERT_PROMPT

- block-store.js: add promptPresets array and loader
  - Load prompt presets via bridge.list_prompt_presets (already exists in arena-presets store)
  - Expose to config form

- block-config.js: renderHead already generic, but buildForm needs to handle preset dropdown
  - Add method to populate dropdown with prompt presets
  - Checkbox "Load from preset" toggles dropdown visibility

- New file? Keep small: add logic to block-fields.js to handle select with options from store

Implementation:
- In block-store.js, add promptPresets: [] and loadPromptPresets() method
- In action-blocks.js facade, call loadPromptPresets during init and expose to config

- In block-fields.js, add new field type "prompt_preset_select" that renders dropdown of presets

- In block-config.js, after building form, if block is INSERT_PROMPT, inject preset controls:
  - Checkbox "load from preset"
  - Dropdown with prompt preset names
  - When checkbox checked, dropdown enabled, and on change, update block.preset_name

Simplify: add two fields to BLOCK_DEFINITIONS labels for INSERT_PROMPT:
  - use_preset: "Load from preset (checkbox)"
  - preset_name: "Prompt preset name"

But requirement says "add control as drop list with prompt presets + check box 'load from preset'"

So we need UI that shows checkbox + dropdown.

We can add to block-fields.js a custom row builder for INSERT_PROMPT that checks if key is preset_name, renders select with options from ActionBlocksStore.promptPresets.

- Store needs to have promptPresets loaded.

Let's design block-store.js additions:
```
promptPresets: [],
loadPromptPresets(cb) { call bridge.list_prompt_presets }
```

In action-blocks.js init, call this._store.loadPromptPresets()

In block-fields.js, add method _promptPresetOptions() that returns store.promptPresets or []

In row() method, if def.key === 'preset_name' and block.block_id === 'INSERT_PROMPT', render select with options from store.

Also need checkbox for use_preset: already checkbox type.

We also need to handle extra fields: use_preset and preset_name live in block.extra or as direct attributes? Existing blocks use extra for suffix, overwrite, duration_ms. For INSERT_PROMPT, we should add as direct attributes to keep to_dict round-trip (RULE 3). So add to ActionBlock dataclass: use_preset, preset_name? But better to use extra to avoid changing dataclass too much? However RULE 3 says block settings are plain instance attributes. So we should add as attributes.

Check ActionBlock dataclass: it has many fields but not use_preset. We can add via extra dict, but to_dict includes extra. Simpler to add new fields to dataclass with defaults, and handle in _CTOR_RAW.

Add to ActionBlock:
  use_preset: bool = False
  preset_name: str = ""

And in BLOCK_DEFINITIONS extra_defaults for INSERT_PROMPT.

Also need to update BUILTIN_BLOCKS defaults to include these.

### 3.8 File Sizes & Quality Gates

- New file text_output_probes.py: ~200-250 lines (ideal 150-300)
- New file text_output.py in cdp_arena: ~150-200 lines
- Modifications to existing files should keep functions ≤30 LOC, CC ≤10
- Need to run tools/verify_quality.py --changed
- Need tests: update test_action_blocks.mjs to include new blocks, maybe new test for text probe

### 3.9 Testing Strategy

- Python tests: test new naming function get_description_json_path
- JS tests: test_action_blocks.mjs should cover new block types in getDefaultBlocks? Actually default blocks don't include new ones, but we test store
- Manual test: run app, create stack with new blocks, check JS console
- Quality: radon cc, coverage

### 3.10 Documentation Updates

- Update SYSTEM_OF_RECORD.md with new block types
- Update DOM_SELECTORS.md with new assistant_message selector
- This design doc archived

## 4. Implementation Order (RULE 16.6)

1. Understand problem (done)
2. Design doc (this file)
3. Backend probes & selectors (site_adapter, probe_selectors, text_output_probes)
4. Controller mixins (text_output.py, mixins.py, controller.py)
5. Naming helper (naming.py)
6. Action blocks definitions (action_blocks.py)
7. Job runner handlers (single_job_runner.py)
8. Frontend store & fields (block-store.js, block-fields.js, block-config.js, action-blocks.js)
9. Bridge slots for prompt presets in blocks_stack? Already exists
10. Tests & quality gates
11. Update docs

## 5. Risks

- Text output detection may be fragile if arena.ai chat structure changes - need robust selectors and fallback to any assistant text
- JSON save path logic must handle overwrite and unique suffix like image save
- Preset dropdown must not break existing block config - conditional only for INSERT_PROMPT
- Must keep file sizes ideal, not exceed 30 LOC per function

## 6. Acceptance Criteria

- [ ] New block types WAIT_TEXT_OUTPUT and SAVE_DESCRIPTION_JSON appear in Add Action dialog
- [ ] Stack "Generate image description" can be built: attach + prompt + submit + wait text + save json
- [ ] When job runs with that stack, text output is captured and saved as {base}.json beside source
- [ ] JSON contains description, source, prompt, job_id
- [ ] INSERT_PROMPT block config shows checkbox "Load from preset" + dropdown of prompt presets
- [ ] When checkbox checked and preset selected, runner uses preset template instead of active prompt
- [ ] Quality gates pass: no function >30 LOC, CC ≤10, etc.
- [ ] Existing tests still pass
