# Narrow streamed-emitter copy-pin fix

This stage preserves the previous frozen emitter, maximum-card AST/profile stage, delivery, profile data, and source fields. Only the emitter tool is patched. No HTML/AST or semantic producer reran; no runtime/browser/service/product/PG/APKG was touched.

The baseline checked `fileSha(fieldsFile)` and later reopened that path to copy its inner JSON. A mutation in between could replace a same-length value while the success report still claimed the original fields SHA. `red.log` demonstrates this exact bug with a genuine abolish fields object: the fs.createReadStream call for start1 is intercepted to replace original-listener with tampered-listener after the initial hash. The old emitter improperly succeeds, so the rejection regression fails for the expected reason.

The candidate hashes `{`, each **actual copied Buffer**, and `}` during that existing second read. It compares this reconstructed exact field SHA to the authenticated pin before emitting external anchors or success report. The existing strict brace qualification makes this fixed-brace reconstruction exact. A mismatch throws, and it never writes anchors/report or claims success; any partial profile in the private failed output directory remains unverified. The input is not restored or modified by the emitter. Initial input pin qualification and all source/header checks remain unchanged.

`green.log`:3/3pass, covering that race plus the original real small-card parity/header failures. `candidate.diff` and `edit.json` show the exact small change and byte-exact inverse to the old tool.

`reemit.cjs` reuses the already-frozen22.46MB fields once with this patched emitter. `parity.json` and `reemit.log` verify both actual profile and anchors **byte for byte** against the previously frozen artifacts, using bounded binary reads. Profile remains22,462,511bytes/SHA6332cb46de5f23628923292572382128feda74c9e02719e9ebb7b1b23e1ca37a; anchors remainSHA4acc0976890210fafb1f1dfeef391e66d980f264e081ee7b03db79a388915fa3. The fix changes verification tooling, not either deliverable's bytes or gate policy.

All test/re-emitter processes are terminal and CPU is stopped. Largest-card real Safari acceptance is still separate and belongs to root.
