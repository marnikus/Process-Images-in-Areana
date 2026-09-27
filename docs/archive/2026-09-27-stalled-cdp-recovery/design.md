# Stalled CDP connection and wrong-tab selection — 2026-09-27

## Evidence and limits

Owner's 18:05–18:08 log: an image exists visually, but output polling and the
Watcher time out on Runtime.evaluate; even Page.getNavigationHistory times out.
No download is attempted. This is upstream of saving bytes, not evidence of an
image-format or filename failure. The prior I-71 change diagnoses the timeout
but pings the same socket indefinitely. A connected websocket is not proof that
its CDP session is responding. We cannot access the owner's localhost Chrome
from this sandbox; the log cannot distinguish a stalled connection from a truly
blocked renderer. Do not claim a renderer root cause has been established.

A separate reproducible defect: `_parse` includes `?model_a=max` in the requested
path, while `_parsed_target` excludes queries. Thus `/image/direct` scores 60,
tied with `/agent/...` and `/c/...`; stable sorting chooses the first tab.

## Design before implementation

1. Parse URL host/path using urllib; retain exact-URL priority, ignore query and
fragment for route matching, use segment boundaries, refuse unrelated paths for
an explicit route. Bare hosts and free-text queries retain their existing use.
2. A failed three-second health ping may replace the transport **once per outage**,
under the connection lock, connecting only to the remembered websocket URL.
Do not use the general connect candidate search (different ports may mean a
different browser). Do not reload, navigate, resubmit, or replay arbitrary JS.
3. Bound the entire repair at eight seconds, clean up partial sockets, propagate
cancellation. Concurrent Watcher/job checks share the lock and attempt marker.
A successful fresh `1` ping clears the failure and re-arms future recovery;
protocol errors or missing values do not count as a healthy page.
4. Continue the existing output probe, baseline/JOB-ID checks and atomic save.
A genuinely frozen page still fails honestly; never save a guessed network image.
Log repair attempt and result through the existing connection reporter.

## Structure / quality budget

New `app/browser/cdp/recovery.py` owns session repair, not the transport facade.
Existing page_recovery delegates ping/recovery to it. Target each helper ≤20 LOC,
CC ≤10, ≤4 parameters, no new class. Existing measured radon maxima:
page_recovery CC8; tab_matcher CC9. No baseline relaxation, no added settings,
no splitting into numbered helpers or hiding decisions in lambdas.

## Tests and acceptance

RED first: query route selects the image tab; explicit wrong routes rejected;
protocol error ping stays unhealthy; a socket that drops replies is replaced
and the same client's evaluate returns the generated-image result; genuinely
frozen replacement is not repeatedly reconnected; simultaneous callers share
one repair; cancelled/failed repair leaves no receive task or pending commands.
Use real CDPClient transport/connect/receive routing with a fake websocket at
the I/O boundary. Run full Python/JS suites, coverage, Rule 16 gate, radon,
vulture and duplication checks. Real Windows/Arena acceptance remains required:
no extra submit, same tab, generated image saved through normal verification.
