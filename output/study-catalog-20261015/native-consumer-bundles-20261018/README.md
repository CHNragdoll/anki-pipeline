# Native carrier grouping correction

The v5 alias-sorted layout loads carriers belonging to unrelated profiles.
Static ZIP/header inspection found that the complete transport reference set
for `abide` grew from 385,315 to 116,761,820 raw JS bytes; for `a`, from
34,856,669 to 134,853,266 bytes. These are referenced file sizes, not measured
disk I/O, decoded content size, or client latency.

The common exporter now gathers every opaque `(descriptor.id, profile.sha256)`
consumer before physical-media deduplication. The common planner combines
small carriers only when their nonempty consumer sets are identical. Missing
usage passes through unchanged. Existing source pins, exact bytes, streaming,
8 MiB / 256-member caps and Meta-only transport rebinding remain in force.
The runtime, original ten fields, semantic resources and counts are unchanged.

Two baseline regression assertions failed as intended. Python 3.13 passed 33
related tests; Python 3.11 passed all 18 carrier tests, while its exporter test
imports lack `psycopg`. Eight Node owner/cache tests passed. Independent review
passed another 16 focused tests and found no P1/P2 issue in the four-file diff.

The real three-profile proof extracted only 20 original carriers (35,196,240
bytes) from the pinned v4 archive. Actual planner and streaming helpers produced
three bundles, all byte-for-byte equal to their member concatenation:

| Profile | Original / corrected referenced raw JS | Groups before / after |
| --- | ---: | ---: |
| a | 34,856,669 / 34,856,669 B | 14 / 4 |
| abide | 385,315 / 385,315 B | 14 / 2 |
| venture | 438,622 / 438,622 B | 14 / 2 |

Every referenced bundle member already belongs to that profile. The original
archive SHA and source bindings remained unchanged. These consumer sets cover
three profiles, not the complete books. The whole-profile guarantee does not
promise the smallest front/back-phase load: a shared file can preload another
part already bound to the same profile.

This checkpoint does **not** contain a regenerated full package, a PostgreSQL
delivery registration, native GUI performance acceptance, or publication.
All copied inputs are listed with their SHA and original path in MANIFEST.json.
