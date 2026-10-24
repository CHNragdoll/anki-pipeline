# Compiled binder v2c boundary archive

This inert experiment archives runtime `b3ea07cc22c772c1ac0289c7068658159ad9b00b0daf19fed7f8919a83369546` separately from the measured v2b binder in the parent directory. It is not connected to any generator, host or APKG path.

The four runtime edits close the reviewed P2 for semantic region membership: new unkeyed native examples, removed or reordered original unkeyed examples, region/outer-ancestor replacement, and unknown lazy membership. Baselines include original unkeyed rows; validation and mutation observation reject changed membership without rebuilding it. This is not a claim of support for arbitrary external modifications or previously unsupported Slim slots.

Run only the five targeted portable contracts from the repository root:

```
node --test --test-reporter=tap tests/fixtures/experimental-compiled-card-v1/boundary-v2c/boundary.test.cjs
```

`runtime.js`, `edits.json`, `inverse.json`, `runtime.diff`, `boundary.test.cjs`, and the original `red.log` / `green.log` are byte-exact frozen sources. `source-FROZEN.json` and `source-README.md` retain the original scope. `source-pins.json` records exact source and repository pins, an independently checked four-edit forward/inverse proof, reused original replay payload hashes, and parent-file pins before archival. Only the test fixture receives relative paths, the existing independent SHA helper, and lossless gzip reads; `fixture-portability.diff` contains those changes. No runtime logic is changed during archival.

`portable-tests.log` records the independent five-contract run for this archive. The parent separately reported that the small full-author normal-path regression passed for v2c; this five-test portable run does not rerun that harness. Safari evidence currently applies only to the prior v2b inputs.
