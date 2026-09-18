# Post-injection identity correction

The 15:04 live run exposed a false stale classification:

```text
15:04:58 token injected (dialog fields=2, callback called)
CAPTCHA_SOLVE status=token_stale reason=sitekey_changed
```

The sitekey comparison happened after injection, when the expected challenge had already been changed/removed by the callback. A post-injection challenge/sitekey change is normal and must not invalidate the injection. Identity comparison remains strict **before injection**; after injection, the acceptance gate checks page errors and final generation/output state instead.

This record also fixes missing provider task IDs on failure outcomes by storing the task id in `SolvePlan` before polling.
