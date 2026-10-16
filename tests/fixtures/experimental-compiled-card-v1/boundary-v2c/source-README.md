# Compiled binder v2c: semantic membership boundary closure

This is a runtime-only patch over frozen v2b. It does not change profiles, anchors, new-runtime API, source algorithms, event ownership or ignored attribute rules inside a bound root. V2/v2b and producer freezes are untouched. No repository/product/service/PG/APKG/UI writes occurred.

Use `runtime.js` with the unchanged externally authenticated v2 `replay/{abolish,train}/profile.json` + `anchors.json` in `/tmp/study-compiled-card-binder-v2-20261017-gjmnnl5m`. Local `abolish`/`train` fixture copies contain the exact replay HTML pinned by those anchors.

## Actual defect and correction

V2b watched only logical roots that happened to have bindings. Appending an unkeyed `li.example-card` to the examples list changed no such root and passed both MutationObserver and refresh.

V2c records the ordered **node identities**, parents and original keys of semantic rows/roots in the caller-authenticated final DOM at install. This includes original native rows without keys; it does not treat them as newly added or merge by text. Semantic roots comprise reports/example sections/lists/native example-card roots/SF sentence pairs/panels/members. Original lazy-node identities are recorded only as an invariant; existing train slots do not gain compiled runtime support.

- Full validation compares this structural membership baseline.
- Mutation delivery requests the same membership check only when added/removed element subtrees or relevant class/key changes could affect a semantic root/row/lazy boundary. Ordinary status text or transient chunk-active changes do not trigger a whole semantic collection scan.
- The observer watches outermost declared semantic regions. Their ancestor chain is watched for direct child-list changes only, catching deletion or replacement of a whole outer wrapper/region without rejecting arbitrary ancestor attributes.
- Original detailed mutation qualification still uses the v2b Set ancestor walk. No per-record full-root `contains` loop returns. No extra overlapping nested-root subtree registrations are introduced.
- Reader control attributes outside logical roots, source-owned non-lazy script text/add/remove, and ordinary footer changes are allowed when semantic membership remains exactly unchanged.
- Unknown new lazy markup and moved/removed/replaced source rows invalidate; no new lazy protocol, guessing, reconstruction or automatic canonical rerun is introduced.

This baseline assumes the caller's existing external whole-HTML/profile authentication and original source lifecycle before install. It is not an independent DOM-origin authentication scheme.

## Targeted evidence

`red.log`: real abolish source-preserving replay + appended unkeyed native row produces `asyncInvalid:false, refreshRejected:false` under v2b; the meaningful boundary assertion fails.

`green.log`: **5/5 PASS**, 1.81-second process:

1. The exact reviewer reproduction now invalidates after MO delivery and refresh rejects; the foreign row is not deleted.
2. A real train unkeyed native row is accepted initially as baseline; removing it invalidates without rebuilding it.
3. Replacing either the complete examples region or its outer ancestor invalidates asynchronously, preserving the replacement.
4. Reordering original unkeyed rows or introducing an unsupported manifest invalidates without reconstruction.
5. Both cards' real original SF filters and source-reader changes, outer reader label style/class/hidden updates, source-owned non-lazy script add/text/remove and source footer changes remain valid after MO delivery and refresh.

`edits.json`, `runtime.diff`, `inverse.json` show four exact source boundaries and a byte-exact inverse to v2b `e559bd68401cb16fb0a2ffaba60aeca11bf76dffc25d0880a9873e1223042dc9`.

The prior unchanged interaction evidence is retained in the previous freezes: 13 v2 contracts, live old/new 26/50 event snapshots, 3 v2b observer contracts and the parent's actual v2b Safari results. These are historical evidence for unchanged paths, not a claim that v2c has been browser-tested. Parent owns the final targeted review and integration check. All task-owned CPU work is stopped.
