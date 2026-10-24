# Converter actual-read snapshot pin fix

This new stage preserves all prior frozen artifacts and the existing34410fprofile/357effanchors. It corrects only the finite Bank converter's read boundary: the prior code verified fileSha(source), then reopened the path via readFileSync and parsed the reopened bytes without hashing that actual snapshot. A same-inode replacement between those calls could therefore enter the seven before-digests under a stale authenticated source pin.

`pinned-fields.cjs` now reads the actual Buffer once, checks its SHA against the existing expectede4328fields pin, and only then decodes fatal UTF8 and JSON parses. `converter.diff` and `edit.json` preserve the exact inverse. The existing initial stream preflight is retained; no canonical Bank algorithm, e56 runtime, source draft, DOM, AST or semantic replay changed.

`snapshot.test.cjs` uses the precise same-inode read-before-injection: original projectionWrappers value becomes tampered after the preflight hash and before the actual read. `red.log` shows the old acceptance missing its required rejection. `green.log`:2/2pass, including correct snapshot and bad pin checks. Input mutation is detected rather than restored.

The existing finite201-record converter reran once on the pinned original fields, with the same reviewed copy-SHA emitter and unchanged normalizer. `parity.json` records actual bounded binary comparison of both regenerated deliverables against their prior frozen versions: profile22,459,697bytes/SHA34410f5681e22620350b35b8c6d18d753745d89ce5a929e77b7675607252cdcf, anchorsSHA357eff37eea7bd07786051dc34f5ed7004288aff1db0a75802ae50b3ead7beb0. The corrected audit helper from the report-only addendum is reused, so201actual complete attribute comparisons explicitly report true. All original7field digests and source counts remain unchanged.

This does not imply the already independently authenticated old34410artifact was damaged: root has independently verified its bytes. QA can use the same pins. No browser/product/service/PG/APKG work occurred; CPU processes are terminal.
