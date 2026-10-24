# Bounded Cigen and gate cost diagnostic

Frozen baseline: `/tmp/study-compiled-numbering-first-claim-v2-20261017-grx8pxci/phase-frame.js`, SHA `bf909260b76e478608e6c313b8bdd49d14fb624e162750830a3295e6deb1e816`.

This is instrumentation only. No product, original QA, source author, numbering claim, e56 runtime, profile, body, HOST or source asset changes. No install, browser or large DOM run. Existing author/claim execution order, source/token/width/signature readiness, three equal snapshots, RAF and 10-second timeout remain. The seven edits reverse byte exactly to the baseline JS and HTML. `transform.cjs` supports only those exact pinned baseline/candidate bytes; `build.py` regenerates only this owned /tmp directory from pinned sources.

`installCigen` keeps its helper and counters inside the function serialized to the target realm. It has no free reference to the outer FRAME helper. Timed wrappers execute the existing operations exactly once and record in finally. The original style block is moved intact into a synchronous measurement callback; it still performs the same local selectors, computed-style reads/properties and two inline font writes in order. No extra source selectors, geometry/style/text reads, awaits, RAFs, timers, microtasks, JSON, messages or observers are added to the hot path.

Recording begins immediately before the original body adoption boundary, only for the original first-back phase claim. It ends immediately after the original successful waitPrepared/full-gate return, before its existing complete point. Cigen counters are sealed and gate counters become inactive. Later promotion/verification/flip work is not counted. Clearing/replacing the body drops the record and disables Cigen recording. The WeakMap value contains only numbers, fixed strings and a frozen scalar snapshot; no packet, node, callback or owner reference.

The only parent-facing addition is the own frozen data API `StudyCompiledLayoutCostStatus.read(currentSourceDocument)`. It returns null until the sealed document is the current committed side with exact current packet/id/token/viewToken/document identity, and null after ownership changes. The return is one frozen object with exactly the 42 fields in `protocol.json`; no arrays, rows or source data. The existing <=64 phase message stream is untouched and no new hot-path messages are sent. Native_report owns the parent reader and one isolated QA integration.

Times are wall/inclusive intervals, not CPU. Cigen selector/layout/style numbers are nested within refresh; the batch numbers select only the original batch-finally synchronous refresh. Layout style-block includes existing local lookups, computed-style property accesses and original font writes. Selector time covers evaluation of querySelectorAll, not the following existing membership iteration. Unaccounted batch time includes original iteration/contains/registration/postMessage plus clock overhead. Snapshot time covers the existing snapshot() call, not JSON.stringify of its return. Snapshot is nested within gate check time. Do not add nested intervals.

`gateFirstCheckAt`, `gateFirstAllReadyAt`, `gateFinishedAt` use FRAME performance.timeOrigin. Blocker counters record only predicates the original short-circuit evaluates: no later child/fonts value is sampled when an earlier predicate fails. `gateLastBlocker` means the last failed evaluated predicate, and is retained after ready. It is not a newly read current-blocker snapshot. Null timestamp means the original path never reached that boundary. All other numeric values are finite nonnegative, counts/token/viewToken are safe integers; there are no -1/Infinity sentinels.

`contracts.cjs` reconstructs actual old/new installCigen and waitPrepared in tiny fake realms and compares ordered DOM/query/style/write/message/RAF traces, returns and injected exception identity. It covers isolated serialization, nested batches, load/MO/resize, readiness short-circuit, changed snapshots, cancellation, child/native failures, snapshot/RAF throws, timeout, cache release and committed/stale status ownership. This is behavior/shape evidence, not a Safari timing or memory acceptance.

Commands:

`python3 -B build.py`

`/opt/homebrew/bin/node contracts.cjs`

No task-owned CPU process remains running.
