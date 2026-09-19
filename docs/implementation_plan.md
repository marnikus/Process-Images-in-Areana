# MVP Implementation Plan with Test Strategy

> **HISTORICAL (2026-09-19).** Step-by-step build plan from project start;
> the build is complete. Module names below reflect the tree at planning
> time — several were since renamed or deleted (e.g. `job_runner.py` →
> `single_job_runner.py`). Current architecture:
> `docs/current/SYSTEM_OF_RECORD.md` §7.


## Phases

### Phase 0 — Project Scaffolding (Done)
- Clean repo, create new structure
- Docs: research_summary, selector_map, workflow_diagram, data_model, risks, implementation_plan
- Keep essential rules for code creating and testing (see docs/rules.md)

### Phase 1 — Core Logic (No UI, No Browser)
- Implement `app/core/models.py` — dataclasses, enums
- `app/core/enums.py` — URLStatus, ImageStatus, JobStatus, RunState
- `app/utils/correlation.py` — generate_correlation_id
- `app/core/naming.py` — output path logic
- `app/core/scanner.py` — recursive scan, ignore _AI
- `app/core/persistence.py` — JSON load/save atomic, reconcile
- `app/utils/hashing.py` — file hash optional
- Tests for each: deterministic logic

**Deliverables:** Core modules + unit tests passing

### Phase 2 — Browser Abstraction & Site Adapter
- `app/browser/selector.py` — Selector object with primary+fallbacks
- `app/browser/site_adapter.py` — centralized selectors, readiness check, baseline capture, attachment verification, prompt verification, output detection
- `app/browser/controller.py` — Playwright wrapper:
  - launch persistent context with user_data_dir
  - open page, validate URL, check readiness
  - highlight element (draw rect overlay for N seconds)
  - set input files, fill textarea, click, wait, download
  - detect security dialog, recaptcha
  - screenshot utility
- `app/services/verification.py` — verification service using site_adapter
- `app/services/download.py` — download output image via Playwright request or page fetch
- Integration tests with mocks (no real browser) + manual test checklist for real browser

**Deliverables:** Browser controller + site adapter with selector map implemented

### Phase 3 — Job Runner & State Machine
- `app/core/state_machine.py` — defines valid transitions, guards
- `app/services/job_runner.py` — orchestrates single job workflow steps 09-20, with observe->execute->verify->persist->advance
- Handles errors, retries bounded, pause on CAPTCHA, prevent duplicate submission
- `app/utils/logging.py` — structured logging

**Deliverables:** Job runner that can process one image given mocked browser, with full logging

### Phase 4 — UI (Desktop)
- Choose PySide6 (Qt6) as UI framework (old app used it, cross-platform, supports qasync)
- `app/ui/main_window.py` — main window with areas:
  - URL list: add, edit, remove, enable/disable, test
  - URL status indicators
  - Folder picker
  - Image queue table with thumbnail, relative path, status, selected checkbox, assigned URL, attempts, output path, error
  - Bulk controls: select all, deselect all, select pending, retry failed, clear completed
  - Prompt editor multiline + preview with correlation token
  - Run controls: Start, Pause, Resume, Stop after current, Cancel current, Retry
  - Progress summary
  - Activity log
  - Settings panel: timeouts, retries, naming, file types, overwrite, highlight duration
- `app/ui/components/` — reusable widgets
- Persistence: UI changes auto-save to JSON, preset save/load
- Highlight config: duration user-settable

**Deliverables:** Working desktop UI that can manage URLs, folder, queue, prompt, settings, without browser automation yet

### Phase 5 — Integration (UI + Core + Browser)
- Wire UI to job_runner via QThread or asyncio
- Implement run controls:
  - Start -> iterate pending selected images, round-robin URL assignment
  - Pause -> finish current step, wait
  - Resume -> continue
  - Stop after current -> finish current job then idle
  - Cancel current -> abort current job, mark failed/interrupted
  - Retry -> re-queue failed
- Progress updates via signals
- Activity log streaming
- Handle CAPTCHA pause: show dialog, bring browser to front, wait
- Handle restart recovery: on startup load state, reconcile, mark interrupted

**Deliverables:** End-to-end working app: user can add URLs, pick folder, select images, enter prompt, start batch, see output saved as *_AI

### Phase 6 — Polish & Compliance
- Implement rect drawing overlay (highlight) with user-configurable duration
- Preset save/load JSON: all UI parameters storable
- Output naming: atomic write, unique suffix
- Security: never bypass CAPTCHA, keep credentials out of logs
- Observability: structured logs, current workflow step in UI, inspectable decisions
- Manual test checklist execution
- Known limitations doc

**Deliverables:** MVP complete per acceptance criteria

## Test Strategy

### Unit Tests (Automated, deterministic, no browser)
- `test_scanner.py`: recursive discovery, ignore _AI, supported types, preserve structure, detect added/removed
- `test_naming.py`: suffix _AI, preserve format, unique suffix when exists, never overwrite source, temp file atomic rename
- `test_persistence.py`: save/load roundtrip, atomic write, version migration, reconcile logic
- `test_correlation.py`: uniqueness, format, length
- `test_state_transitions.py`: valid/invalid transitions for URL, Image, Job, Run states
- `test_verification.py`: attachment verification logic (mock DOM), prompt verification, output baseline comparison
- `test_selector.py`: selector object fallback resolution

Run with `pytest` — must pass in CI.

### Integration Tests (Mocked browser)
- Use `unittest.mock` to mock Playwright page object
- Test `site_adapter.is_ready` with mocked selectors present/missing
- Test `job_runner` workflow with mocked controller that simulates success/failure/CAPTCHA
- Test download validation (valid image bytes vs HTML error)

### Manual Tests (Real browser, checklist)
- **Authentication:** Log in manually in persistent context, verify session persists after restart
- **URL Management:** Add valid URL, invalid URL, unreachable URL, test readiness, disable/enable, remove
- **Folder & Queue:** Pick folder with nested images, verify ignore _AI, select/deselect, bulk controls
- **Attachment:** Attach image, verify preview appears, verify correct filename, test remove and re-attach
- **Prompt:** Insert prompt with JOB-ID, read back, verify exact match
- **Submission:** Submit once, verify no duplicate submission on slow network, verify processing state
- **Generation Wait:** Wait for new output, verify baseline comparison, verify loading complete
- **Download & Save:** Download output, validate image, save beside source with _AI suffix, verify no overwrite, test unique suffix
- **CAPTCHA Pause/Resume:** Trigger security verification (if possible), verify pause, manual completion, resume
- **Restart Recovery:** Start batch, kill app during processing, restart, verify interrupted job marked, not auto-resubmitted, can resume
- **Error Handling:** Source file deleted mid-batch, output path permission denied, disk full simulation, network timeout, invalid URL
- **Highlight:** Verify rect drawn above clicking element for configured seconds
- **Preset:** Save preset JSON, load preset, verify all UI params restored
- **Logging:** Verify structured logs contain job_id, url_id, image_path, state, attempt, no secrets

### Quality Gates (from old AGENT_RULES)
- Keep essential rules:
  - Correctness, traceability, user control prioritized
  - Every completed job must have evidence: correct attachment -> exact prompt -> one confirmed submission -> new correlated output -> valid download -> safe _AI save -> persisted completed state
  - Never report success based only on click, timeout, or presence of any image
  - Structured logs
  - Tests for deterministic logic must pass before push
  - No DB, JSON persistence atomic
  - Site adapter replaceable, selectors centralized
  - Security: no CAPTCHA bypass

## Deliverables Checklist (from prompt)

Before coding (done in docs):
- [x] Research summary
- [x] Element/selector map
- [x] Workflow/state diagram
- [x] Data model and persistence plan
- [x] Risk list, compliance assumptions, unresolved questions
- [x] MVP implementation plan with test strategy

For implementation:
- [ ] Working application with clear setup instructions
- [ ] Documented configuration and site-adapter structure
- [ ] Automated tests for deterministic logic
- [ ] Safe integration tests or mocks for page interactions
- [ ] Manual test checklist
- [ ] Known limitations and maintenance guidance

## Timeline (MVP)
- Phase 1: 1 day
- Phase 2: 2 days
- Phase 3: 1 day
- Phase 4: 2 days
- Phase 5: 2 days
- Phase 6: 1 day

Total ~9 days for full MVP, but we will implement incrementally in this session, prioritizing core + browser + minimal UI.

## Tech Stack Decision
- Python 3.11+
- PySide6 for desktop UI (keeps old core familiarity, cross-platform)
- Playwright for browser automation (modern, handles file inputs, highlights, downloads, persistent context)
- qasync for Qt+asyncio bridge
- pytest for testing
- No DB, JSON only

Alternatives considered:
- Tkinter: simpler but less modern UI, no built-in async support
- Electron: JS stack, but old core Python, would require rewrite
- Selenium: older, less reliable for file inputs and highlights

Chosen: PySide6 + Playwright.

## Setup Instructions (to be documented in README)
- Install Python 3.11+
- `pip install -r requirements.txt`
- `playwright install chromium`
- Run `python -m app.main`
- On first run, browser launches with profile `./browser_profile`, user logs in to arena.ai manually
- Add URLs, pick folder, enter prompt, start

## Maintenance Guidance
- When arena.ai DOM changes, update `app/browser/site_adapter.py` selector map
- Use diagnostic logs to identify which selector failed
- Keep primary selectors semantic, avoid utility classes
- Test readiness via "Test URL" button before batch
- Version selector map with lastVerified date
