# Metrics report — cycle R2 (Area D integrated, 2026-09-19)

Snapshot of the branch after Area D landed on top of the integrated cycle
(R0 + A + B + C + D). Regenerate with `.venv/bin/python tools/metrics_report.py`.
Read the `over*` counters as the verdict; the `max` fields show the largest
*offending* value for the cognitive/nesting lanes (0 = none over the limit).

Context: gate = **0 fails** (`tools/verify_quality.py --allow-legacy
--coverage-ratchet`; full mode 0 fails / 0 warns), pytest **1344 passed /
4 skipped**, node --test **137 passed**, vulture @90 clean, jscpd 1.240 % /
23 groups (lane vs `tools/jscpd_baseline.json`). Coverage floor re-recorded in
`tools/quality_baseline.json`: **line 84.46 / branch 80.27** — the absolute
80/75 target that was still outstanding after cycle X is met.

Delta vs cycle X (`metrics_report_2026-09-19-refactor-cycle.md`): files 125→127,
lines 19,612→19,963, coverage line 68.4→84.5 % / branch 61.0→80.3 %, funcs
1396→1422, vulture @60 208→213 (same @90 = 0), duplication 1.255→1.240 %.

Mutation (separate, non-blocking lane — see `d5-mutation.md` for the full table;
scoped mutmut on the integrated tree): `recording` 82.0 % killed (1,573/1,919),
`services-watch` 63.3 % (233/368) vs 74.9 % / 55.0 % on Area D's own branch.

```
# Metrics Report — Files 127 Lines 19963 Funcs 1422 Mean 8.73 Median 8.0 Max 50
>30 1 4-20 1116 <4 271 Over300 15 Over500 6 Ideal 28
CC max 10 over10 0 Cog max 15 over15 0 Nest max 0 over4 0 Params>4 0
MI mean 59.71 min 0.00 <20 5 <40 31 Classes 126 >150 0 >300 0
Coverage line 84.5% stmts 85.4% branch 80.3%
Vulture @90 0 @60 213 Duplication 1.2402956914416503% 23 groups 401 lines
JS files 74 funcs 1614 >30 0 nest>4 0 CC>10 0
Coupling:
  app.browser Ca=34 Ce=1 I=0.03
  app.core Ca=26 Ce=1 I=0.04
  app.persistence Ca=5 Ce=0 I=0.00
  app.services Ca=15 Ce=26 I=0.63
  app.ui Ca=0 Ce=59 I=1.00
  app.utils Ca=7 Ce=0 I=0.00
LCOM4:
  app/ui/bridge.py::Bridge methods=10 LCOM4=9
  app/services/watcher.py::WatcherService methods=14 LCOM4=1
```
