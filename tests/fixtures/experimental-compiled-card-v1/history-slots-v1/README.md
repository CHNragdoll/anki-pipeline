# Exact history slots and outer-owner prototype archive

This is inert experimental source, not connected to the generator, web host, APKG exporter or entry points. It archives the reviewed two-stage prototype: explicit train history slots, then the narrow outer-owner cancellation repair. It grants no arbitrary lazy-content capability and has no full-host, Safari, large-card or speed acceptance.

The exact runtime, augmented profile, anchors and loader-input JSON remain unchanged. Both original part strings are embedded verbatim in `loader-input.json`; their SHA and UTF-8 lengths are in `fixture-seals.json`. The exact final train replay HTML is reused from `../replay/train/body.html.gz` with lossless decoding. Existing authored chunks/filter/reader/residual, SHA verification and v2c baseline fixtures are reused by relative path.

`adapter.js` exports **adaptCompiledHistorySlotsOwner(code, originalPin)** and includes the frozen prior history adapter. Call only this outer function once. `compiled-slim.js` is its exact small shared IIFE; `protocol/compiled-slim.js` is the prior history version. Unknown pins preserve bytes and known boundary drift rejects. `inverse-proof.json` independently records the seven runtime, ten history-loader and thirteen owner-loader exact inverse boundaries. Both original inverse records and edit tables are retained.

Run the 12 existing history contracts plus six owner contracts from the repository root:

```
node --test --test-concurrency=1 --test-reporter=tap tests/fixtures/experimental-compiled-card-v1/history-slots-v1/history.test.cjs tests/fixtures/experimental-compiled-card-v1/history-slots-v1/owner.test.cjs
```

The 12 history contracts now share the final owner-aware fixture, providing integration regression coverage without duplicating source data. Their prior-history adapter assertion explicitly retains the prior adapter output; the six owner contracts verify the outer adapter output. Assertions otherwise remain intact. `portability-edits.json` shows relative dependency/data paths, reuse of the shared final fixture and exact source selection changes. Runtime/adapter logic is never rewritten for archival.

Original RED and GREEN logs remain byte-exact under `protocol/` and `owner/`, alongside both source READMEs and FROZEN manifests. Those source READMEs document historical temporary-stage reproduction, not executable archive dependencies. The current portable run is recorded separately in `portable-tests.log`. The original 44-contract log and all v2b/v2c source bytes are untouched.

Scope remains exactly two original closed excluded-history disclosures: original loading/hash/retry/reader/history/chunk services execute; exact graphs authorize only the two parts and AF text. The owner repair prevents stale loader-owned work before toggles, queued requests, part loads and AF-script append, while actual absent-profile behavior retains native-generation ownership. Four archived pairs have no Projection/Fine/Bank/Group/Residual semantic consumers. All 70 history spans retain 280 original hover/tap/re-tap/Escape comparisons. This is not a new canonical producer, source reconciliation or independent profile authentication algorithm.

The first portable run was 16/18 and remains in `portable-tests-attempt-1.log`: extracting the common fixture omitted the test-local `D=__dirname`, and the historical 100-`setImmediate`-turn wait ended before an authentic asynchronous digest completed. Only test packaging was repaired: restore the directory constant and retain the same readiness predicate with a one-second wall-clock bound. The second related-only run is 18/18; both original source RED/GREEN logs are unchanged. No runtime/source/profile/part modification was required.

## Historical full-host harness limitation

A separate review found a defect in the old full-host/full-authored capture harness: mapping a live `childNodes` NodeList with `Array.from(..., node => document.adoptNode(node))` mutates that list during iteration and can skip adjacent top-level nodes. The product FRAME uses a pre-captured snapshot and a for-loop, so this is a harness scope defect, not evidence of that defect in the product path. The old frozen inputs/logs are preserved as historical bytes and must not be treated as proof that a complete full-host DOM was captured. A corrected complete combined harness is being verified separately; this archive does not claim its result.

These 18 contracts are loader/binder tests. Their fixture parses the sealed final HTML directly into JSDOM and runs the actual small original loader plus authored chunk/filter/reader/residual closures; it does not run the old adoption mapper. The test files, both loader slices, binder and reused small authored closures contain no `adoptNode` call. Thus this concrete live-list adoption defect does not affect the related 12+6 result, and that result remains limited to the tested loader/binder capability rather than full-host acceptance.
