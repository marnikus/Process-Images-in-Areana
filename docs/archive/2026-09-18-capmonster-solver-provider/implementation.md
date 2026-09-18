# CapMonster Cloud provider — implementation record

Date: 2026-09-18 · Companion to `design.md` (same folder). Final measured state
of the change on branch `arena/01a0b61b-process-images-in-areana`.

## What was built

| File | Change |
|---|---|
| `app/services/captcha/providers.py` | NEW (103 lines) — `ProviderSpec` + two specs (`2captcha`, `capmonster`), `provider_for()` with default fallback, per-provider error classifiers mapping to the solver's stable reason tokens; `CAPTCHA_NOT_READY` → `pending` |
| `app/services/captcha/api_client.py` | `Captcha2Client` → `SolverApiClient(key, spec)`; base URL + error classifier from spec; `taskId` echoed raw (CapMonster ints); `get_result` converts `pending` → processing; `delete_task` no-ops when `spec.can_delete` is false |
| `app/services/captcha/key_store.py` | `CaptchaSettings` = active provider + shared timeout + per-provider `ProviderCreds`; `CaptchaSettings.for_provider` seed helper; store `config/captcha_solvers.json`; legacy `config/2captcha.json` migrated read-only on load; `api_key`/`enabled` are properties of the active provider (solver/service code unchanged) |
| `app/services/captcha/solver.py` | spec-driven: task types, poll cadence (`plan.spec.poll_interval_sec`), log titles, `isInvisible` gated on `spec.enterprise_invisible`; `_TASK_TYPES`/`task_type_for` deleted (dead code avoided) |
| `app/services/captcha/service.py` | `apply_settings(provider, api_key, enabled, timeout)` — empty key keeps the stored one; `status_payload` + per-provider masks; balance/logs provider-aware; report `task_type`/`poll_interval_s` from the spec |
| `app/ui/bridge.py` | `set_captcha_settings` passes `provider` through (net +1 line) |
| `app/ui/web/index.html` + `js/panels/captcha.js` | Captcha window: provider drop-down above the unchanged enable/key/timeout fields; switching reloads that provider's masked status; title `Captcha — Solver` |
| `.gitignore` | + `config/captcha_solvers.json` |
| Docs | RULE 20 amended (this date); SYSTEM_OF_RECORD rows 12/20, I-29, storage map, windows map; `docs/README.md` archive entry |

## Gates (RULE 16 §16.7 — measured after)

* **pytest** `455 passed` (baseline 427; +28 new/updated), only the pre-existing
  `PIL` env failure in `test_thumbnail_service` remains (unrelated).
* **`tools/verify_quality.py --changed --allow-legacy`** — ✅ PASS, no new fails; legacy
  offenders untouched (`_poll_task` CC 10→10, `_resolve_captcha` CC 10→10, `_finish_auto` CC 7→7).
* **New/edited functions** — all ≤30 LOC / ≤4 params / CC ≤7 / nesting ≤3
  (worst: `SolverApiClient._post` CC 7, `apply_settings` 15 LOC CC 5 params 4 — at the
  prefer line, under the fail line).
* **Coverage of changed modules** (branch): `api_client` 100%, `providers` 100%,
  `key_store` 93%, `service` 87%, `solver` 91% — ≥75% gate met everywhere.
* **RULE 18** — new file `providers.py` 103 lines (leaf); edited files: `api_client` 108,
  `key_store` 176 (band), `solver` 543 (−1 line), `service` 407 (+26, pre-existing large file,
  no function worsened).

## Tests added/updated (RULE 8)

`tests/test_captcha_providers.py` (NEW, 9 tests), CapMonster flows in
`test_captcha_api_client.py` (6 new), per-provider store + migration in
`test_captcha_key_store.py` (rewritten, 14), provider-true payloads/cadence/logs in
`test_captcha_solver.py` (5 new + spec-aware fakes), provider routing + provider-true
`CAPTCHA_SOLVE` facts in `test_captcha_service.py` (4 new). The spec-aware `FakeClient`
mirrors the real client: no `deleteTask` when `spec.can_delete` is false.

## Deliberate behaviour changes (documented in design §3.3)

1. Saving a provider's fields also commits it as the ACTIVE provider (the drop-down +
   Save is one decision).
2. Empty API-key field on Save = keep the stored key for that provider (the UI clears
   the field after every save; with two providers the old wipe semantics would be a
   footgun). Enabled still requires a key.
