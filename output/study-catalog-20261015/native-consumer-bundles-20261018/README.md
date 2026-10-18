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

## Subsequent owned full-context control

An independent three-card APKG and closed SDK collection were then built with
the actual common bundler. All 30 original fields (apart from the declared
Meta delivery footer), identity and schedule values were reconciled, and all
34 media files matched their SHA pins. Fresh-import deck remapping and an
earlier finalization assertion are retained as failed checks; the final closed
collection used direct SDK migration, with no normalization or data delta.

Only those three Meta transport maps were transplanted into a new APFS clone
of the already-tested 6,682-note native QA collection. All tables and typed
rows were compared to the closed baseline; models, original field text,
learning state and statistics stayed unchanged. Four additional media aliases
were copied after collision checks. The GUI preparation script binds the
fixed producer receipt, database and full media SHA set, and requires a real
transport change. An initial preparation read before its writer closed and
failed; its unchanged files/logs are retained, and a new stage explicitly
closed the writer before immutable reconciliation.

The unchanged official-Cocoa harness verified all independently derived
source row hashes and the abide year filter:

| Card | First complete back | Repeated complete back |
| --- | ---: | ---: |
| a | 5.384 s | 4.896 s |
| abide | 0.261 s | not measured |
| venture | 0.260 s | not measured |

These times include polling and semantic checks. The largest card and Browse
still miss the intended experience: the main event-loop gap reached 9.710 s.
Closure again recorded a monitor PermissionError / forced-termination flag;
the launcher exited 0, and no owned application process remained after the run.
The original QA database and media source remained unchanged. This is a
three-transport control in full card-count context, **not** full-book export,
default-import, phone, audio-click, or overall performance acceptance.

Separate native SQLite 3.49.2 checks confirmed the statistics-controlled
database chooses `ix_notes_csum` for the duplicate query. SDK searches took
0.377 s for the exact Word regex, 1.281 s for ordinary `abide`, and 0.00044 s
for the target ID. Those single calls were cache-warmed by qualification and
did not reproduce the GUI pause. ID search is a diagnostic comparison, not a
replacement for the user's normal workflow. The official Check Database
maintenance command refreshed statistics on a new tiny synthetic collection;
no maintenance was performed on the personal database.

See NATIVE-FULL-CONTROL.json, THREE-CARD-PRODUCER.json, NATIVE-QUERY-PLAN.json,
NATIVE-SEARCH.json and OFFICIAL-MAINTENANCE.json for the exact scope and pins.

## Isolated field-size diagnosis, not a delivery change

A one-second sample of the owned official application caught native Browser
search in SQLite: 417 of 515 main-thread samples followed overflow payload
reads into `unixRead` / `pread`. This identifies a large-field I/O path during
that sample; it does not measure physical bytes or the entire pause duration.
Clearing only the selected three notes' large editable fields in a recoverable
diagnostic clone did not solve the all-library search pause.

A second diagnostic clone retained all 6,682 notes but cleared qualified
compiled source fields above 16 KiB, excluding Word, Meta, Phonetic and Audio.
It changed 8,520 fields on 5,760 notes; active field UTF-8 payload fell from
847,171,949 to 115,606,182 bytes. The complete original database remains a
local media attachment and was actually cloned back with the original full
SHA. All other typed cells and all 67,703 original media files matched.
This is **not** a production field migration or a new APKG: native field
editing and full-text search would change if this representation were adopted.

The same official GUI harness and independent source-row hashes passed both
diagnostic controls. No profiler was used in the all-note run:

| Control | a first / repeated complete back | abide / venture complete back | Largest event-loop gap before closing |
| --- | ---: | ---: | ---: |
| Three selected notes only | 4.849 / 4.843 s | 0.255 / 0.253 s | 13.272 s |
| All qualified compiled notes | 4.857 / 4.931 s | 0.271 / 0.256 s | 3.772 s |

The all-note run's first exact Word search returned in 0.595 s; opening the
editor and complete Preview still added time. These are single runs including
polling and semantic SHA checks, not matched cold-cache performance guarantees.
The largest card still takes about 4.9 seconds. Both close monitors again
recorded a PermissionError and a forced-termination flag; launchers exited 0,
and the actual owned application PIDs were independently confirmed absent.
Original inputs remained unchanged. Overall responsiveness and clean-exit
acceptance remain open; the diagnostic representation has not been adopted.

See NATIVE-FIELD-SIZE-CONTROLS.json and the two FIELD-SIZE-*-PRODUCER.json
receipts. The user's preference on native field editing/search is pending.
