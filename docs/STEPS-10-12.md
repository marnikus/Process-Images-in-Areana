# Steps 10–12 — offline completion and release handoff

2026-09-15. Owner authorized the remaining steps and pushing this session branch.
The previously agreed offline-only boundary remains: **live adapter acceptance,
authorized site pilot and supported-OS release acceptance are not complete**.
Missing page evidence is not replaced with guessed selectors or mock success.

## Step 10: correlated original bytes and safe local publication

`automation/output.py` adds `FixtureOutput` and `OutputSaver`. This is an explicit
Python fixture contract, not a network downloader or desktop action. The caller must
supply permitted original bytes belonging to the exact persisted submitted message
and observed response. No thumbnail URL, signed URL, blob, cookie or token is stored
as a durable download contract. A reviewed original-download adapter remains blocked.

Validation uses the existing actual Pillow decoding/verification pipeline: maximum
64 MiB, 40 million pixels, one non-animated frame, supported PNG/JPEG/WebP/BMP/TIFF.
The extension comes from decoded bytes, never a server filename. Original bytes
and their SHA-256 are preserved, including any original embedded metadata.

Publication sequence:

1. Check ownership, original permission and bytes before writing any output.
2. Choose an existing trusted output directory and `<source-stem>_AI.<actual-ext>`;
   collisions use `_AI_2`, `_AI_3`, etc. Existing files and dangling links count.
3. Persist `save_intent` with the absolute candidate path, response ID and SHA-256.
4. Write/fsync a private same-directory `.partial`, then atomically create the final
   name using a hard link. Never replace an existing destination. A collision race
   or unsupported filesystem fails closed; no unsafe fallback copy/replace.
5. Flush the directory where supported, read/decode/hash-check the final file,
   then persist matching `saved` evidence. Only then release queue ownership.

No output overwrite mode is enabled. Source files are never replaced. Output folders
must be trusted, stable local directories; this is not a hostile-parent-replacement
or network-filesystem durability guarantee. Links/reparse directories are rejected.
Windows has file flushes but no portable directory-fsync guarantee; NTFS/hard-link
behavior and graphics still require the manual checklist below.

A crash/write failure after publication retains unresolved intent/review, not a
false completion. Explicit recovery never republishes or downloads. `verify_saved(id)`
checks the already-recorded local path, original hash, decoded format/extension and
directory flush, then records completion only if proven. Missing/changed/link files
remain unresolved. A submission-only `needs_review` cannot manufacture saved evidence.
Orphan `.partial` files after process death are not automatically deleted; inspect
only after closing the app and backing up state. No remote side effect is undone.

Saved source fingerprints cannot be prepared again. A selected changed source needs
fresh scan/selection. A two-source fixture lifecycle demonstrates round-robin prepare
through save, restart and global undo without rewriting external evidence. This is
not an autonomous live batch scheduler.

## Step 11: truthful read-only UI integration and regression

The retained dark queue, Job history and Saved outputs panels now render recorded
attempt phases, actual confirmed-submission counts, paused/stop-after flags and saved
path/hash evidence. Text is inserted as text, not executable HTML. A saved record
means verified at publication/recovery time; files may subsequently change.

All existing settings, preset/variable libraries, drag/layout behavior and global
undo remain. Execution evidence stays outside undo. Unresolved attempts lock edits.
There are still **no enabled desktop upload/Send/download controls** and no live
adapter. The fixture coordinator and explicit recovery are Python APIs, not operator
UI controls. An authorized tiny-batch site pilot and live end-to-end UI wiring are
release gates, not completed by the fixture tests.

## Step 12: packaging, audit and cleanup decision

`tools/release_check.py <wheel>` rejects missing, changed, duplicate or unexpected
wheel members. Every packaged runtime module/asset must match current source bytes;
only a narrow distribution-metadata allowlist is additional. It is a membership/
identity check, not a secret scanner or native installer test. The old app, test
media, Chrome profiles, dependencies and diagnostics are not shipped in this wheel.

**Cleanup decision: retain legacy source and relevant documentation.** The wheel
already isolates the new runtime; destructive removal would lose provenance and
regression evidence while native/live extraction gates are open. No legacy family
or user data was deleted. The inactive CI template remains unchanged in status.

Measured checks:

- Full `python tools/check.py`: 348 Python tests; 16 extracted workspace DOM tests;
  selected retained JS suites and 20 legacy visual-probe tests; Ruff, strict mypy
  (54 production files), JS lint/format, size/complexity and coverage gates pass.
- 15 targeted safety mutations killed, including removed Send intent, restart gate,
  unique target, no-clobber publication and output hash checks. Not a full score.
- Headless combined coverage 98.66%; automation statements/branches 99.53%/98.25%.
- Built wheel: 98 members pass membership/source audit. Fresh wheel installation
  outside the checkout passes CLI, packaged visual/UI assets, real JSON storage and
  real image validation/no-clobber publication. No native GUI launch is claimed.
- `pip-audit --skip-editable`: no known vulnerabilities in audited distributions;
  the local editable package is skipped. `npm audit --omit=optional`: zero known
  vulnerabilities. These do not audit our own code or Qt's embedded Chromium.

## Windows / live release checklist — still pending

1. On a supported Windows machine, install Python 3.11+, create an isolated venv,
   install the reviewed wheel with `[desktop]`, and launch `image-queue desktop`.
   Validate WebEngine rendering, dialogs, close/reopen, layout drag/resize, all preset
   families, keyboard/global undo and durable state recovery with real graphics.
2. Back up the external JSON state directory first. Do not downgrade an execution
   ledger containing new save phases to code that does not support them.
3. Start user-owned Chrome with the documented debug-profile command; independently
   check exact user-opened tabs, duplicates, redirects, disconnect and authentication.
4. Review privacy-consented same-conversation idle/attachment/enabled-Send/submitted/
   processing/completed/security/auth evidence and original-download permissions
   under `rebuild/01-RESEARCH.md`. Implement/review the production adapter separately.
5. On NTFS, test collision races, disk full, permissions, abrupt termination before/
   after publication, explicit recovery and source preservation. Do not silently
   fall back if hard links are unsupported.
6. Only after adapter/OS gates, wire operator execution/recovery controls, obtain
   explicit per-submit approval and perform an authorized tiny-batch pilot. Check
   original image ownership, format/hash, stopping and manual CAPTCHA/auth handling.
7. Activate CI using an integration with workflow-write permission. No remote CI
   success or installable Windows executable/installer is claimed by this handoff.

Reproduce release checks from an activated development environment:

```sh
python tools/check.py
python -m pip wheel --no-deps . -w dist
python tools/release_check.py dist/arena_image_queue-0.1.0-py3-none-any.whl
```

Version 0.1.0 remains an offline development build, not a declared live production
release. Build artifacts, profiles, outputs, logs and dependency environments stay
out of Git. Future maintenance must preserve the reviewed exact-site contracts,
source safety, immutable evidence and all native/live acceptance gates.
