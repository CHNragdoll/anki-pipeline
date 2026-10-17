# Isolated compiled gzip transport candidate

Only new files in this stage; no product source, formal page, service, learning
data or package changes. No server/browser, DOM parser, semantic producer or
large JSON parse was run. This is a transport A/B, not a new codec candidate.

## Actual change

A is the existing frozen-profile FRAME052ccc54/HTML4e950. B has six exact
reversible edits: insert the transport helper and private descriptor validation;
add a resource task branch; pass the original compiled descriptor at the one
load call; append gzipSrc to the three private asset descriptors; construct the
private transport. `edits.json` reverses B exactly to A.

The three HOST functions in `canonical-artifact-functions.js` are copied as exact
current source bytes into `transport.js`: deliveryAborted/deliveryText/
verifiedArtifactText. The factory only supplies a local fetch adapter and a
post-read complete206 guard. It does not change global fetch or digest. The
normal success uses explicit gzip, validates decoded text against the ORIGINAL
HTML/profile/runtime SHA, then fills the same resource promise/cache/private
proof. The cache remains URL|pin, 24 entries, failed-task cleanup unchanged.

Qualification is private descriptor object identity plus exact captured own-data
fields, URL and pin, not a caller boolean or similar object. It is checked before
cache lookup and after await; drift rejects. Original support.load source/module/
packet binding remains before the call and valid/owner checks remain afterwards.
No success proof certifies a new packet or profile. Existing profile parse/freeze,
bind, source proof, original author order and ALL prepareView/following function
bytes remain identical.

Gzip HTTP/decompression unavailability falls back to the original raw URL WITH
Range bytes=0-. This is essential: an ordinary HTML GET through the LAN proxy can
rewrite origins and inject scripts. The fallback retains complete Content-Range,
UTF8 byte-length and SHA validation. Wrong decoded SHA never retries raw. Abort
or decoded-stream budget failure never retries. Content-Encoding:gzip is treated
as browser-decoded and is not decompressed twice. Gzip non200 is unavailable;
rawfallback supplies the old guarded representation rather than accepting a
partial gzip response. Source media and native resources keep their original path.

## Evidence

`RED.log` is the actual old resource function: expected explicit gzip, got raw
Range. `GREEN.log` has12 passing focused groups, covering real gzip streams,
LAN injection/fallback, bad decodedSHA/no retry, complete/partial206, missingDS,
Content-Encoding, abort windows, streaming decoded budget, descriptor identity/
getters/drift, failed cache retry, source Range, cache24/proof expiry and exact
inverse/source-gate identity. Initial test extraction was corrected before these
recorded logs; no SyntaxError is represented as the meaningful RED.

`pack-assets.py --pack` ran exactly once on the three already pinned files using
1MiB chunks, gzip6/mtime0, exclusive output and no-follow input. It checked input
stat before/after, original raw SHA during compression, and decompressed every
result to the same byte count/SHA. Source total71,877,501B, gzip total8,184,676B.
These are file representation sizes, not measured network or latency savings.
`packed-assets.json` contains every file pin and the real terminal evidence.

## Parent/server handoff

Use `preflight.json` and `routes.json`. Reuse the complete dP6sM3 HOST parent/
collector, not the small standalone parent that calls api.mount(packet). The same
55,603,149B original artifact, original wrapper chain and HOST must be retained
in A/B/A; only sharedFrame html differs. The raw body/profile/runtime are mapped
read-only from their original paths; new gzip files live only here. For .gz
routes serve Content-Type:application/gzip, NO Content-Encoding and NO injection.
Keep same origin/port/cache policy, fresh parent documents, and record all pins.
Root owns the only server/Safari operation. Nothing has been installed.

Existing helper tests for reference (not rerun):
`tests/test_study_catalog_web_artifact_text.py` has15 source transport contracts.
This new test runs no JSDOM:

```sh
node /tmp/study-compiled-gzip-transport-v2-20261017-oqwh482o/contracts.cjs --red
node /tmp/study-compiled-gzip-transport-v2-20261017-oqwh482o/contracts.cjs
```

Do not rerun --pack into existing outputs. Do not run the historical max codec
producer. CPU tasks have ended; performance and complete Safari acceptance remain
unknown until the root's actual A/B/A.

## Cache-hit P2 closure (v2)

Old a29e seal remains immutable. The warmed-hit and pending second-descriptor
REDs both show Missing expected rejection using actual old resource. The only
new FRAME edit awaits existing promise for compiled callers, revalidates that
call's exact descriptor, and checks its captured optional signal before return.
Ordinary resource cache hits retain the original return path. Caller-local
rejection does not remove or contaminate A's already authenticated shared task.

Actual frozen FRAME has no frameAbort global; injected signal contracts do not
claim otherwise. The original support.load valid() check after Promise.all and
before profile JSON parse/bind is byte-identical and tested against a current
owner changing while a warmed request is pending. No synthetic global owner or
new public callback protocol was introduced.

`CACHE_HIT_GREEN.log` has4 additional groups, including the two exact P2
negative cases, optional signal abort and actual support.load cancellation.
`GREEN.log` retains12 transport groups. `cache-hit-only.diff`/last ledger edit
reverse exactly to4b910 parent; all6 edits reverse to052ccc baseline.
Three gzip files are referenced read-only from the parent stage; there was no
recompression, hardlink or large file copy. `routes.json` intentionally points
to those existing paths. Do not execute copied historical --pack.

Run new scope: `node /tmp/study-compiled-gzip-transport-v2-20261017-oqwh482o/cache-hit-contract.cjs`.
