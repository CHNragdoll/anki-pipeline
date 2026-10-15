# Display example numbering correction

Scope: number the actual current example rows in display order after filtering,
ownership changes, merging, and lazy append. Historical audit numbering and
physical occurrence/frequency statistics are preserved. No user Anki profile is
opened or changed.

## Implementation

- The producer renumbers current Examples before packaging. Native ownership
  exclusion includes numeric edits in its existing exact inverse ledger.
- A small shared runtime maintains ordinals for current `ol.examples` rows as
  they are removed, hidden, reordered, decoded, or appended. It ignores history
  and chunk hover changes and releases detached nodes in a reused WebView.
- Existing sealed slim packages are read-only inputs. New packages preserve
  note/card/model identities, all non-Examples fields, source evidence, original
  media bytes, schedules, suspension, flags, and review logs.
- The website's two unsigned bookshelf shells use versioned companion assets.
  Sealed card HTML, catalogs, evidence, and the original composed asset remain
  unchanged. Refresh the normal bookshelf entry to load the companion.

## Observed verification

Output: `output/example-numbering-20261015/` (generated files are not in Git).

| Book | Vocabulary notes checked | Notes corrected | Badges corrected |
|---|---:|---:|---:|
| 2026 | 6,681 | 311 | 1,601 |
| 2027 | 6,531 | 307 | 1,585 |

All current inline lists were checked for continuous numbering. Every field
outside Examples is identical to the handed-off slim package, and reversing only
the recorded numeric edits restores the complete prior Examples field exactly.

Representative results are identical in both books:

- abide: 2 -> 1.
- venture: 2,3,4,5 -> 1,2,3,4.
- cater: 1,2,3,5,6 -> 1,2,3,4,5.
- beginning: 4,5,6,7,8,10,11,12,15,20 -> 1 through 10.
- train/training: existing continuous labels remain unchanged.

Native Anki SDK baseline import, update, and repeat import passed for both books:
6,682 / 6,532 total notes/cards; all fields/models, learning states, flags and
review logs preserved. All 66,423 / 65,511 native media files match package bytes;
missing media is zero. Both QA exports contain nine actual native question/answer
pairs including abide. Current package and original baseline end hashes match.
Full LAN downloads also match the new packages' SHA256 and lengths.

Chrome UI observations: native 2026 abide shows 1; native 2027 train shows 1-10;
native 2027 the shows 1-20 after scrolling loads the next batch. An isolated real
website cater iframe with the new module shows 1-5. The normal website shell
times out loading a card in Chrome; a copy of the untouched prior shell also
reproduces that failure. Therefore normal-shell browser acceptance is not claimed.
Temporary diagnostic runtime changes were reverted byte-for-byte to the reviewed
version; no loading-workflow change was retained. Physical AnkiMobile acceptance
remains for the user's device.

Focused Python suite: 87 passed. Numbering DOM suite: six passed. Independent
review found two issues (history self-markers and detached-node retention); both
were corrected and reviewed, with no remaining material finding. A broader
historical source-alias suite has three input manifest-hash failures before the
numbering path; those seals were not changed and a whole-project pass is not
claimed.

Machine-readable receipts: `all-book-numbering-verification.json`, each year's
`build-report.json`, `ordinal-field-proofs.json`, `native-verification.json`,
`lan-download-verification.json`, and `web/web-receipt.json`.

Rollback: use the preserved original slim packages; restore the two unsigned
shells from `web/before/`. No sealed source HTML or user learning data was edited.
