# CAPTCHA watcher isolation — implementation record

Date: 2026-09-19

Implemented in this branch:

* Watcher-owned `2captcha-python` adapter with lazy SDK import, bounded
  `asyncio.to_thread` calls, per-tab in-flight deduplication, masked status,
  and fail-open manual fallback.
* Image processing no longer calls the CAPTCHA service at security, submit,
  download, or generation-wait boundaries. `CHECK_SECURITY` remains in the
  default Action Blocks catalog as an informational/restorable block.
* Watcher configuration is an explicit runtime gate; disabled Watcher does
  not probe or solve.
* Action Blocks renderer IDs now match the HTML and empty/corrupt stored
  stacks restore from the canonical Python default stack.
* URL, folder, and preset UI wiring is bridge-ready and the Prompt Presets
  surface has Save, Load, and Remove actions.

The existing legacy CAPTCHA package is retained only for compatibility with
old persisted recordings and callers. It is not part of the production image
pipeline or Watcher call path. A later cleanup can archive its old direct API
client after downstream consumers migrate.
