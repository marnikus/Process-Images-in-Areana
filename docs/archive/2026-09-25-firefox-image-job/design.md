# Design — Firefox image job (Ui.Vision), steps 14–19

**Status:** implemented 2026-09-25
**Entry:** SYSTEM_OF_RECORD.md → I-65
**Layer:** services → browser only. Chrome's CDP job path is not edited.

## What was true before

A claimed Firefox page ran the framework XClick demo and, on `Status=OK`,
was marked completed with no file (honest, but not an image job). New Chat
was skipped (`no CDP controller`). `register_job_done` ran for every
non-cancelled finish, including that empty success.

## What this change does

The same dispatcher claim now runs one image job through Ui.Vision macros
(XClick / XType / executeScript). Read-back, correlation, validation and the
atomic `*_AI` save are Python — the same rules Chrome already uses
(RULE 15 / 22 / 23). The preexisting tab is never closed and never opened
(`selectWindow` Value stays empty; launch keeps `continueInLastUsedTab=0`).

Chrome states, not new ones: manual security is `waiting_captcha` (the log
also says `waiting_user`, which is that state). Cooling is the existing
cooldown timer. Job count moves only when a file was saved, and only on the
Firefox finish branch — `_finish_normal` is unchanged, so Chrome still counts
every non-cancelled finish.

## Checkpoints

One record per image in `config/firefox_jobs.json`. Restoring it **rewrites**
the live book (a later partial edit does not survive). Submit intent is
persisted before the send macro; a lost ack does not click again. A
`.{name}.arena-saving` stamp plus the output file reconciles a save whose
queue write did not land, without resubmitting. A pending image with an old
`*_AI` sibling is not reconciled — that is a regenerate, not an interrupted save.

## Out of scope

Captcha solving on Firefox (detect + wait only, RULE 20). Parallel macros
(the existing machine lock stays).
