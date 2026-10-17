# Compiled authored-codec: reviewed small prototype archive

The reusable bytes and test live in
`tests/fixtures/experimental-authored-codec-v1/` and
`tests/test_experimental_authored_codec.py`. This directory records the actual
portable acceptance and its exact file inventory. It contains no large card,
browser report, deployment, product implementation or installer.

Source freeze: `8a57cba99652f9ed841c99c0bd1b44ee8611dc15638b1c4a0b141c8d3d2651d9`.
All 50 originals are authenticated: 45 copied unchanged, five referenced against
existing repository fixture hashes. This avoids 185,555 duplicate bytes. Helper,
build and adapter algorithms are unchanged; four temporary path-only edits have
explicit before/after SHA and exact inverse checks. Unsafe previous helpers are
retained with the explicit **NONINSTALLABLE** label and are never imported.

`actual-portable-report.json` and `portable-tests.log` record one actual run:
original 14 groups plus two P2-focused programs passed, as did the original
code/HTML/authors inverse/syntax verifier. The unittest completed in 3.346 s.
Historical RED evidence is the unchanged sealed original logs; no unsafe helper
was rerun during this archive acceptance.

The tiny fixture declares 14 pins but only exercises the two complete 9014
authors. The real 44,765-byte abolish fixture is an explicitly **ineligible**
different-cohort fallback oracle; it remains unchanged. This is not full-cohort,
FRAME/native-ready, maximum-card, Safari/mobile or performance acceptance.

Reproduce using only already installed dependencies, from the repository root:

```sh
NODE_PATH="$PWD/node_modules" /tmp/anki-study-runtime-20261015/bin/python -B -m unittest tests.test_experimental_authored_codec -v
```

`run.py` builds only a temporary directory, runs the four bounded programs and
removes the directory afterwards. It does not use product imports, services,
network, PG, real Anki, APKG, large DOMs or a producer.

For read-only seals without repeating the contracts, run `verify-archive.py`
with the external SHA of `manifest.json` as `--expected-manifest-sha256`.
`owned-files.json` is the exact new-file scope. No Git operation was performed
by this task; output is ignored until the root agent explicitly archives it.
