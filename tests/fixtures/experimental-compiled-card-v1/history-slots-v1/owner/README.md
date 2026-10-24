# Narrow outer-owner closure for the frozen history-slot prototype

This new isolated stage fixes the review's concrete cancellation defect. The prior stage `/tmp/study-compiled-history-slots-20261017-othb1ipq` remains unchanged. Runtime, profile, external anchors, original source parts, exact history graphs, original AF media and all schemas/versions are byte-identical. No repository/product/service/UI/database/APKG changes were made.

## Defect and precise fix

The original native-generation `alive()` can stay true after the external compiled owner is canceled. The frozen history-slot adapter already stopped insertion and AF text writes after awaited work, but `request` could first write `loading`/`aria-busy`, a queued second request could start its media hash, and `history` could append its AF script after that cancellation.

The only new predicate is:

```js
function ownsWork() {
  return alive() && (!compiled || !compiledInvalid && compiledCurrent());
}
```

It guards schedule-task entry, request entry, one entry and post-load checks, and history/toggle entry. The same private loader's refresh/click/scroll entry and post-await continuation use the identical predicate, preventing the same stale loader-owned filter work. Ordinary legacy absent-profile execution reduces exactly to the previous `alive()` predicate. The existing failure/current callback and post-await evidence authorization remain unchanged; cleanup of in-flight internal queue/batching bookkeeping remains allowed. No whitelist, new capability, graph qualification or source-data change was introduced.

`owner-edits.json` contains 13 exact one-line/function-entry substitutions. `inverse.json` verifies their exact inverse to prior compiled Slim SHA `1e47b42051f6350d3e7a43274a1f7e61f34815cf2ccd069a0d8394c7af2029d9`. `owner.diff` shows only this guard change.

`adapter.js` includes the prior frozen history adapter, then exports **`adaptCompiledHistorySlotsOwner(code, originalPin)`**. Use that outer function instead of the previous adapter entry; it invokes the previous adapter once internally. Unknown pins remain unchanged, known exact-boundary drift is rejected. `compiled-slim.js` is the real resulting shared IIFE, not a whole authored module.

## Recorded behavior

`red-final.log` runs the same focused tests against `prior-compiled-slim.js`: the three new cancellation checks fail for the actual review causes. The first records `loading` and `aria-busy`; the second observes two hashes instead of only the already-running first hash; the third detects an appended original AF script. The original current-owner positive and candidate legacy absent-profile positive pass.

`green-final.log`: **6/6 pass, 2,251.89 ms** in a sequential small-DOM Node run:

1. Cancel before toggle: no loader DOM mutations or media request.
2. Queue a second real original request while the first hash is blocked; cancel, release the first hash: the second task never starts hashing or writing.
3. Cancel before opening the real loaded AF disclosure with a missing registry entry: no evidence script append.
4. The **candidate's actual absent-profile branch**, after external-owner cancellation, still follows native-generation ownership and loads the original part plus AF evidence.
5. A current compiled owner still loads both original history parts and exact AF text, with unchanged frequency and three group-audit contents.
6. Combined adapter matches the actual shared IIFE exactly, preserves unknown bytes and rejects known owner-boundary drift.

The prior unchanged 12-test history protocol evidence was not rerun or relabeled. This stage has no browser/large-card acceptance. Root owns consolidated review and subsequent integration. No test process remains running.

## Reproduction

In a new copy of this stage, run `node patch.cjs`, then `node --test owner.test.cjs`. To reproduce RED use `LOADER_SOURCE=prior-compiled-slim.js node --test owner.test.cjs`. `fixture.cjs` is the existing authentic small original loader fixture, with only source selection and explicit candidate-legacy selection added. The frozen stage itself is an immutable input.
