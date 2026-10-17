# Experimental authored-codec v1 archive

This is the **reviewed v2 small prototype**, archived under a stable fixture name.
It is not imported by product code and is not a production codec, FRAME,
installer, release, browser acceptance or maximum-card performance result.

The external source seal is
`8a57cba99652f9ed841c99c0bd1b44ee8611dc15638b1c4a0b141c8d3d2651d9`.
`source-FROZEN.json` is the unchanged original 50-file manifest. `source-files.json`
maps every original file either to byte-identical `sealed/` bytes or to an
already present, pinned repository fixture. Three identical 44,765-byte HTML
copies, the 17,711-byte base profile and the 33,549-byte 9014 source are referenced
without duplication. No 49 MB HTML or 22 MB profile is included or exercised.

All helper/build/adapter and historical evidence bytes are preserved exactly.
`sealed/README.md`, logs and reports describe the historical `/tmp` experiment;
their absolute paths are provenance, not instructions to write live assets.
Never execute `sealed/prepare-inputs.py` or `sealed/emit-evidence.cjs` in place.

## Reproduce with existing dependencies

From the repository root:

```sh
NODE_PATH="$PWD/node_modules" python -B -m unittest tests.test_experimental_authored_codec -v
```

Alternatively run `python -B tests/fixtures/experimental-authored-codec-v1/run.py`
for the structured report. Node.js and the existing `node_modules/jsdom` are
required; the runner installs nothing and performs no network requests.

The runner verifies this archive and all 50 source pins, reconstructs only a
temporary directory, changes three exact absolute jsdom imports to `require('jsdom')`,
and makes the original inverse verifier inspect the untouched build bytes.
`portability-edits.json` binds all four before/after edits and hashes. Every edit
is reversed and compared byte-for-byte before execution. No codec or capability
algorithm changes. The temporary directory is removed on success or failure.

It runs the original inverse/syntax verifier, the original **14 contract groups**,
and the two reviewed P2 regressions. Original RED/MUTATION/INTRINSICS/GENERATION
logs remain sealed historical evidence; the archive does not rerun unsafe old
helpers merely to reproduce failures.

## NONINSTALLABLE historical files

`sealed/previous-drift-helper.cjs`, `sealed/pre-fix-capability.cjs` and
`sealed/pre-fix-build.cjs` are **NONINSTALLABLE**. They are retained only so the
reviewed fixes can be reversed against their exact historical bytes. The runner
never executes or imports them. There is no installer or product import here.

## Exact acceptance boundary

The tiny synthetic fixture declares the approved 14-pin source order but executes
only the two complete 9014 authors (including the other four IIFEs each time).
The first pure codec discovery scans change from 3 to 0; the later author follows
the original path. This is not full authored-cohort/native/FRAME acceptance.

The real small abolish fixture has a different 2027 cohort. Its generation output
is therefore **ineligible**, unchanged, with zero patches. It is an identity and
fallback oracle, not evidence that its full cohort was compiled or executed.
Unknown cohorts and missing/unknown certificates retain original behavior.

The two reviewed regressions cover NodeList.forEach descriptor drift retaining
the original exception/fallback, and actual/declared cohort preflight before any
generation-time first-IIFE evaluation. Source author, v5 composition, tiny HTML,
ineligible real HTML and both reviewed code fixes have exact inverse proofs.
No Safari, mobile, largest-card, native-ready, source publication, paint or net
performance claim is made by these tests.
