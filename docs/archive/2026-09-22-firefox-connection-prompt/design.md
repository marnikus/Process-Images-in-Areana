# Firefox connection prompt — design (2026-09-22)

Owner report: Firefox shows an "Incoming Connection" popup for 127.0.0.1:9224
that regenerates about every second. Scanning must not re-trigger the dialog
per cycle; silence it permanently without launch flags or profile switching
(manual launch + real profile are preserved).

## 1. Root cause (measured, not guessed)

Three facts multiply:

* Firefox's debugger server prompts **once per accepted TCP connection**
  (`devtools/server/devtools-server.js:_onConnection` says hello per conn;
  even a bare GET triggers it — support q135989, SO 70998890).
* I-64's RDP client opened **one connection per op** (connect → op → close).
* `list_targets` **re-detected every call** (CDP-GET + RDP probe + list ≈
  3 connections per pass per endpoint), and the reconciler re-lists every
  5 s (`live/debug_view.DEFAULT_MS`).

So every scan cycle re-prompted. Worse, short per-cycle timeouts made
approval a lottery: an approved-but-slow connection was abandoned before
the click, and the next cycle prompted again.

## 2. Discovery: the prompt can be switched off remotely

Mozilla sources (hg `devtools/`, read raw — searchfox symbol pages and
direct curl both proved unusable):

* `shared/security/auth.js`: `prompt-connection=false` → `ALLOW`, no
  dialog. There is deliberately **no "always allow" button**
  (debugger#3070) — the preference flip is the only silence path, and it
  **persists** (setters call `savePrefFile`).
* `server/actors/root.js` + `actor-registry.js`: every global actor —
  including `preference` — is attached to the **`listTabs` reply** as
  `preferenceActor: <id>`. The flip needs no new discovery: one `listTabs`
  the client sends anyway reveals the actor.
* `actors/preference.js` + `shared/specs/preference.js` (confirmed
  verbatim by geckordp 1.0.3): `{to:pref,type:"getBoolPref",value:<name>}`
  → `{value}`; `{to:pref,type:"setBoolPref",name,value}` → `{}`.

So any approved connection can dots its own i's: read the actor id from
`listTabs`, flip the pref once, and every later connection is silent —
including connections from future app runs and Firefox restarts.

## 3. Design v2 (what this round ships)

* **D-1 — one pooled socket per endpoint.** `rdp._run` keeps a
  `(connection, Lock)` per endpoint under `_pool_guard`. The mutex
  serializes ops (RDP has no request ids); any error closes the socket so
  the next op redials; `_revive` re-applies the caller timeout and heals a
  raced-close (a concurrent `reset_pool` between handoff and op) by
  redialing instead of failing. Failures return, never raise.
* **D-2 — the first contact waits.** A fresh connection gets
  `APPROVAL_WAIT = 10.0` s for the greeting and its op (reuse keeps the
  caller timeout). One OK click inside the window converges the endpoint;
  the window is a pinned UX contract (`test_first_contact_waits…` asserts
  the constant and the hold).
* **D-3 — best-effort remote flip, before the op.** `_silence_prompt`
  (listTabs → get → conditional set, one `arena` log line when it flips)
  runs on every fresh connection and swallows everything: a flip failure
  must never break a listing. Running it *before* the op is load-bearing:
  on a server that sends its greeting but gates requests pre-approval,
  only the flip's long-wait read survives to do the silencing. `probe` /
  `detect_protocol` / `connect()` stay pure (detection never flips).
  The notes document what happened and the revert (`about:config`).
* **D-4 — directed-first listing with a self-correcting TTL cache.**
  `endpoints._list_known` tries the recalled protocol, else the registry's
  — no probe on the happy path. A working answer is trusted 300 s; a dead
  endpoint is remembered 5 s and short-circuits to the composed
  not-reachable line (no poke per pass); only a failure re-measures via
  `detect_protocol`. The cache means *what the endpoint answers*: a
  successful detect is trusted even when the fallback listing fails, so an
  empty-but-answering endpoint reports its stable error instead of
  alternating with "not reachable".
* **D-5 — a confirmed failure reports the attempt.** When the fallback
  re-probe confirms the directed protocol, the directed error stands — no
  second listing attempt, no extra connection.
* **D-6 — guided failure.** The Firefox connect-failure tip now names
  Disable (it stops the debugger server until relaunch); the registry
  notes carry the once-per-install guidance (click OK once → the app
  switches the prompt off → flip it back in about:config to be asked
  again). First sentences — and the not-reachable text built from them —
  are unchanged.
* **D-7 — tests isolate endpoint memory.** An autouse `conftest` fixture
  resets the RDP pool and the protocol cache around every test, so a
  recycled fake port never inherits a stale socket or a stale protocol.
* **D-8 — cohesion over splitting (RULE 18.2).** `rdp.py` carries
  `# ideal-size: 400` with its reason: framing + connection + pooled
  lifecycle + prompt flip share the packet helpers, and everything under
  the pool lock must stay in one scope; splitting would scatter
  request/reply pairs that always change together.

## 4. Non-goals (stated, not forgotten)

* Launch flags / profile switching to dodge the prompt — refused by the
  owner; the manual launch line is untouched.
* Image attach on RDP — still the named gap from I-64 (no
  `DOM.setFileInputFiles` equivalent).
* The global `screenshot` actor exists and could be a future RDP
  screenshot path — a lead, not this round.

## 5. Verification map

* Pool: reuse / serialize / dropped-heals / reset-races (T1, T2, T7, T16,
  T16b) + `firefox.connections == 1` across listings (T11).
* Flip: flips-once / skips-redundant-set / no-actor / pref-errors /
  probe-pure (T3–T6, T9) + the wire-sequence pins in the list/evaluate
  tests + the 10 s approval hold (T8).
* Directed-first + cache: cold-skips-CDP / second-reuses / ESR-fallback /
  dead-quiet / neg-expiry / same-proto-stands / empty-stays-trusted
  (T10–T15) + the Disable pin.
* Mutants killed: pool bypass (3 fail), flip skip (3 fail), cache bypass
  (2 fail), same-arm re-attempt (1 fail), cross-arm back to bury-on-fail
  (1 fail), revive-arm removal (OSError escapes — 1 fail). Production
  restored byte-identical after each (`grep -c MUTANT` = 0).
