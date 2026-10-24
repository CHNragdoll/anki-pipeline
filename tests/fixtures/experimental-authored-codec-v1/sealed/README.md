# Authenticated compiled author-codec prototype (one-shot)

This is a small, noninstalled `/tmp` prototype. It does not change product HOST,
FRAME, client, formal exports, media, databases, APKG, services or Git. It has no
browser timing result and is not a complete FRAME/installer candidate.

## Exact work moved to generation

`build.cjs` first verifies the exact executable source cohort and declared cohort.
Unknown cohorts retain the input HTML byte-for-byte without executing the codec.
For the approved cohort it executes the unmodified first IIFE of the real SHA-pinned 9014 author
script with existing JSDOM. It does not implement another codec. Source-position
patches retain the original scaffold, all raw script lexemes and untouched bytes.
The generated HTML/profile acquire new, external SHA anchors. `*-edits.json` and
`*-inverse.json` reproduce the exact source HTML; original source proof remains
separate from this derived artifact.

This is an explicit compiled-artifact trust boundary: generation performs the
original static semantic conversion; runtime authenticates that output and its
producer/cohort certificate. A certificate cannot authenticate its own hash. The
caller supplies externally held HTML/profile/source/IIFE pins to a real verifier.
The prototype does not claim runtime independently repeats the original codec.

The real source is `source-9014.js` (33,549 B), SHA
`9014f667e36b6b3094b212c110cb2af8b0bb910a89ba15ea7a052df50d5a96ba`.
The first IIFE is 3,918 B, SHA
`f34d24bbcd05fb2b29c7b9c18f987132e4fd8b83e92a2fab915f4c6e50d2589a`.
The following four IIFEs remain byte-identical, SHA
`59185820030764bb5dd171f3796dda4ecc02f092de14da87bdae60d2a6a39335`.
The copied existing compact-v5 adapter is SHA
`64f9178c2d57a12eb35dc1f2fa5e20f8c939db93eea2cf79d7954b6984fa605a`.

## Conservative runtime capability

`capability.cjs` has a private document WeakMap. It authenticates primitive input
strings against external pins, snapshots the approved cohort/config before
awaits, parses the authenticated HTML, captures original top-level node identities,
and observes before the caller's synchronous static-snapshot adoption. Any
unsupported cohort, residual compact marker, custom element, environment change,
foreign bridge, owner change or relevant DOM drift uses the original codec.

The capability is consumed on the first successful check, immediately disconnects
its observer and releases its owner callback and DOM references. It cannot revive
on A→B→A, and the second author invocation always follows the original path.
Mutations are not excused as arbitrary moves: new→remove→append was a real failing
counterexample to an earlier helper, so the final version rejects structural drift.
Only insertion/removal of the exact synchronously executing authored SCRIPT in
HEAD is recognized, using the actual `document.currentScript` plus exact code.

`withCapture` provides a short-lived private capture only if the property is
entirely absent; foreign getters are not invoked. Cleanup only removes its own
value and preserves the original exception. No global decoded boolean or public
seed can qualify a document. No native readiness, font/child/geometry gate,
cancellation check or time budget is changed.

## Precise future integration seams (not performed here)

1. After the existing source-scaffold/semantic overlay and before sealing the
   derived HTML/profile, run this exact first IIFE and range patch. Rebase any
   path-sensitive profile from the final output. The current tiny profile does
   not assert that unrelated native bindings were recomputed.
2. After the existing authored resource SHA and `valid()` checks, adapt only the
   exact 9014 source with `adapter.cjs`, BEFORE the current compact-v5 adapter.
   Unknown pins remain unchanged; changed/repeated exact shapes are rejected.
3. Reuse the current successfully authenticated compiled-load identity proof.
   The standalone `load` function is a tiny authentication test harness, not an
   instruction to SHA/JSON-parse/deep-freeze a second 22 MB profile in FRAME.
   A future FRAME connection must share the existing successful object and pins.
4. Capture the owned parsed nodes before original static-snapshot adoption and
   attach immediately after it, before first author execution. Wrap the exact
   synchronous execute call with `withCapture`; retain original array order,
   resource proof, valid checks and all remaining four IIFEs.

There is no product FRAME patch or QA installer in this stage. These seams still
need an actual FRAME integration review and controlled maximum-card test before
any deployment decision.

## Observed evidence and limitations

`RED.log`: current old code performs three static discovery scans and fails the
new zero-repeat contract. `MUTATION_RED.log` preserves the rejected move-tolerant
helper's counterexample; `previous-drift-helper.cjs` is historical and NONINSTALLABLE.

`GREEN.log`: 14 focused groups passed. First pure-codec scans are 3→0. Across two
complete 9014 executions they are 6→3; the second call uses the original path.
Reader/chunk/countdown interactions and both executions of all four remaining
IIFEs match. Exact source and compact-v5-composed inverses pass. Authentication,
unknown/missing certificate, residual markers, drift, already-delivered MO,
quoted `>` tags, nested packed content, UTF16, pending cancel, ABA, foreign doc,
throw cleanup and real synchronous SCRIPT insertion are covered.

The synthetic tiny fixture declares the approved 14-pin source order but only
executes both full 9014 authors; it is not a full-cohort/native/FRAME test. The
44,765 B actual compiled abolish fixture is a generation/identity oracle; its
different 2027 author cohort is explicitly ineligible and keeps original runtime.
No giant DOM, native producer, Safari, network, paint or full FRAME gate was run.
The earlier 433/377 ms author measurements include other work and cannot be
reported as this prototype's savings.

The supported environment is the existing pre-author trusted runtime with stock
DOM/reflection intrinsics. Captured method/NodeList.forEach/Object.prototype changes and observed
DOM changes invalidate the capability. This does not claim equivalence under
arbitrary malicious per-node own getters or undetectably replaced host behavior.
The build pass uses a small JSDOM DOM and small profile; scale/cost and authentic
large-profile identity sharing remain unmeasured. No decoder portability beyond
the exact audited source is claimed.

## Run

Existing dependencies only; no install or network:

```sh
node /tmp/study-compiled-authored-codec-v2-20261017-ycixfxdu/contracts.cjs --red
# Expected exit 1, real old source assertion 3 !== 0.
node /tmp/study-compiled-authored-codec-v2-20261017-ycixfxdu/contracts.cjs
# Expected exit 0, 14 groups.
node /tmp/study-compiled-authored-codec-v2-20261017-ycixfxdu/emit-evidence.cjs
```

`report.json` has exact artifact pins and counts. `FROZEN.json` covers all stage
files except itself; it also marks the earlier unsafe helper as historical.
Tests and evidence emit completed naturally; no background CPU task remains.

## Revision v2: reviewed P2 closure

The original `44862d82...90cdf3` stage remains unchanged. `PARENT-FREEZE.json`
records that historical seal. This revision is a separate directory.

1. After authentication/adoption, replacing `NodeList.prototype.forEach` with a
   throwing function made the original first IIFE + compact-v5 throw, whereas the
   earlier capability incorrectly accepted and skipped the throw.
   `INTRINSICS_RED.log` reproduces this; `INTRINSICS_GREEN.log` proves the final
   descriptor check falls back with the exact same Error, scans=1, accepted=0.
2. An unknown earlier inline script can inspect compact aliases before 9014.
   The old build pre-expanded those aliases even while emitting eligible=false.
   `GENERATION_RED.log` proves the observation changed true→false. Preflight now
   checks the actual executable cohort and passed cohort BEFORE eval(FIRST).
   Both unsupported cases return unchanged HTML with no patches and an unqualified
   certificate; `GENERATION_GREEN.log` preserves the earlier observation and
   approved-cohort compilation.

`intrinsics-audit.md` bounds the intrinsic review to the exact no-marker first
IIFE + v5 path. No blanket new guard for callback-only Array.from/classList was
added without a difference. The four following IIFEs and all source script bytes
are unchanged. `v2-proof.json` reverses only the two code changes back to the old
sealed helper/build; original author and HTML inverses remain exact.

Run the two new focused programs in addition to the existing 14 groups:

```sh
node /tmp/study-compiled-authored-codec-v2-20261017-ycixfxdu/intrinsics-contract.cjs
node /tmp/study-compiled-authored-codec-v2-20261017-ycixfxdu/generation-preflight-contract.cjs
```

The standalone `capability.load` is ONLY the small input-authentication harness.
It is not a proposed second compiled loader. Actual FRAME integration must
register the current existing successful support.load HTML/frozen-profile/pins
identity and original parsed nodes using private ownership, without re-verifying,
parsing or freezing the 22 MB profile. That integration is not implemented or
claimed by this small prototype. If `withCapture` supplies enabled=false, callers
execute the original non-injected v5 source; they must not access a foreign
capture/getter via an injected guard. Future final profile paths/slots must be
rebased on the generated output rather than assumed unchanged.
