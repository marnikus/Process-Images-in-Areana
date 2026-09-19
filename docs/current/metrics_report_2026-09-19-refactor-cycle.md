# Metrics report — refactor cycle X (2026-09-19)

Snapshot of the finished branch (R0 + A + B + C integrated). Regenerate with
`.venv/bin/python tools/metrics_report.py`. Read the `over*` counters as the
verdict; the `max` fields show the largest *offending* value for the
cognitive/nesting lanes (0 = none over the limit).

Context: gate full run = **0 fails** (`tools/verify_quality.py --allow-legacy
--coverage-ratchet`), pytest 776 passed / 4 skipped, node --test 135 passed.
Coverage floor recorded in `tools/quality_baseline.json`: line 68.44 /
branch 61.02 (the absolute 80/75 target is Area D).

```
# Metrics Report — Files 125 Lines 19612 Funcs 1396 Mean 8.73 Median 8.0 Max 50
>30 1 4-20 1097 <4 264 Over300 15 Over500 6 Ideal 28
CC max 10 over10 0 Cog max 15 over15 0 Nest max 0 over4 0 Params>4 0
MI mean 59.66 min 0.00 <20 5 <40 31 Classes 126 >150 0 >300 0
Coverage line 68.4% stmts 70.2% branch 61.0%
Vulture @90 0 @60 208 Duplication 1.2549289603805471% 23 groups 401 lines
JS files 74 funcs 1609 >30 0 nest>4 0 CC>10 0
Coupling:
  app.browser Ca=34 Ce=1 I=0.03
  app.core Ca=26 Ce=1 I=0.04
  app.persistence Ca=5 Ce=0 I=0.00
  app.services Ca=14 Ce=26 I=0.65
  app.ui Ca=0 Ce=58 I=1.00
  app.utils Ca=7 Ce=0 I=0.00
LCOM4:
  app/ui/bridge.py::Bridge methods=10 LCOM4=9
  app/services/watcher.py::WatcherService methods=14 LCOM4=1
```

Largest files (>300 LOC, each with an `ideal-size:` reason where split would
scatter one cohesive mechanism): `services/single_job_runner.py` 875,
`services/cooldown_service.py` 787, `core/action_blocks.py` 753,
`browser/output_probes.py` 737, `services/captcha/solver.py` 557,
`ui/panels/browser_tabs.py` 544, `services/batch_orchestrator.py` 492,
`services/run_state.py` 417, `ui/services/undo_entries.py` 404,
`services/multi_page_dispatcher.py` 397.
