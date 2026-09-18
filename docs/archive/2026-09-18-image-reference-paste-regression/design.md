# Image-reference paste regression — research and design

> Superseded after two failed live validations by `docs/archive/2026-09-18-working-branch-composer-restoration/design.md`.

Date: 2026-09-18

## Reported failure

After the recording/dispatcher merge, a reference image and prompt text no longer arrive together in Arena's Direct image composer. The generation-wait badge starts even though the reference image was not attached. The supplied screenshot shows the current composer: plus control, Direct mode, Max model, prompt placeholder, and Send button.

## Investigation

### Confirmed execution regression

The merged multi-page dispatcher now executes `app/services/single_job_runner.py`. Its `ATTACH_IMAGE` handler calls `ctrl.attach_image()` directly. The older bridge-owned path first exercised the configured Add-files control and then attached. Thus the merged path lost part of the previously working composer interaction.

### Confirmed targeting and verification weaknesses

1. `CDPClient.attach_image_cdp` selects the first document-wide `input[type=file]`. It does not associate that input with the visible prompt textarea. Arena is an SPA and may retain inactive/hidden composer forms; the saved captcha page itself marks the composer form `aria-hidden=true` while preserving its file input.
2. `set_file_input_files` returns success for every non-throwing CDP reply, including replies with a protocol `error` object.
3. Attachment verification is document-wide and accepts any visible image with `alt` or `blob:`. It does not require the active composer, expected filename, or a preview that appeared after this attach. An unrelated image can therefore turn a failed upload into a false success.
4. The runner can consequently submit text alone and enter `WAIT_OUTPUT`, exactly matching the observed waiting badge symptom.

### Protocol research

Chrome DevTools Protocol defines `DOM.setFileInputFiles` for a specific file-input node and accepts filesystem paths. The command may identify the target by node ID, backend node ID, or object ID. The protocol response must be checked for an `error`; an empty `result` is the normal success shape. Source: Chrome DevTools Protocol `DOM.setFileInputFiles` documentation.

### Real-page evidence

The saved Arena page contains:

- `form` with `textarea[name=message]` and the screenshot's “Describe the image you want to generate…” placeholder;
- a hidden `input[type=file]` accepting PNG/JPEG/WebP;
- `button[aria-label="Add files"]` with the plus icon.

This supports active-composer scoping rather than generated class names (RULE 21).

## Design

### One attachment owner

Create `app/browser/attachment_probes.py` as the single owner of active-composer discovery and attachment evidence. Keep transport in `CDPClient` and orchestration in `CDPArenaController`.

### Active composer targeting

A probe finds a visible, enabled textarea using semantic selectors, takes its closest form, and finds that form's enabled image file input. It applies a random temporary `data-arena-upload-target` marker and returns a baseline fingerprint of preview images within that same form. `DOM.querySelector` then resolves only the marked node. The marker is removed in a finally path.

No generated Radix IDs or utility-class-only target is used.

### Honest CDP result

`set_file_input_files` returns failure when the CDP reply contains `error`. `attach_image_cdp` validates that the source path is an existing regular file, fails loudly when no active-composer input exists, and reports the selected active target.

### Evidence-gated completion

Verification is scoped to the currently visible textarea's form. It succeeds only when:

- a preview carries the expected filename, or
- a new preview fingerprint appears relative to the pre-attach baseline.

It must not accept an arbitrary pre-existing page image. `attach_image` captures the baseline before setting the file and polls for bounded upload completion. Prompt insertion follows only after attachment verification, and Submit follows only after both required blocks succeed.

### Paste-compatible fallback and controlled prompt

Initial user validation showed that active-input targeting alone did not restore the site interaction: neither image nor text appeared. Therefore protocol selection is necessary but not sufficient. Arena's composer explicitly supports paste, and its React-controlled textarea may re-render after a synthetic value assignment.

The final interaction uses two bounded attachment strategies against the same active form:

1. dispatch a paste-compatible `File`/`DataTransfer` payload to the active textarea and image input (the behavior the user performs manually);
2. fall back to `DOM.setFileInputFiles` on the marked node when paste is unavailable or produces no evidence.

Image bytes are bounded before base64 transport and never logged. Each strategy must independently pass active-form verification before proceeding.

Prompt insertion also becomes active-composer scoped. It supports textarea and contenteditable textbox surfaces, emits an `InputEvent` with React value-tracker compatibility, and is re-verified after the framework has had time to render. Immediate DOM assignment alone is not accepted as success.

### Dispatcher parity

The single-job runner will not open a native file dialog. Both legacy and merged dispatcher paths share the corrected controller/client implementation. Required attachment and prompt evidence gate Submit and `WAIT_OUTPUT`.

## Test plan

- JS probe tests: active form wins over hidden/stale form; baseline ignores unrelated images; filename/new-preview verification; no visible composer fails.
- Python tests: protocol errors are failures; missing/non-file path rejected; marker cleanup always runs; active marked node selected; controller retries bounded verification and never reports false success.
- Runner regression: failed attachment stops before prompt and wait; successful attachment precedes prompt then submit/wait.
- Full Python/JS suites, RULE 16, compileall, conflict-marker scan, and diff check.

## Quality design

New probe builders are small Python wrappers around isolated JavaScript literals (RULE 16 embedded-JS exception). Transport helpers target 4–20 lines. Existing oversized `CDPClient` is not expanded with multiple responsibilities: targeting/evidence logic lives in the new cohesive probe module. No boolean or exception branch is removed to game complexity.
