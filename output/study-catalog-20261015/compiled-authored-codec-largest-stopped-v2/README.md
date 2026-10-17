# Maximum authored-codec attempt stopped

The single root-owned Node attempt (PID 77809, root exec session 15480) aborted with
signal 6 after 23.544 s during construction of the 49,390,544-byte inert JSDOM.
The original stderr reports JavaScript heap out of memory with a 2,048 MB heap
limit. It did not reach the first original codec evaluation. No retry or heap
increase was performed.

No new profile, FRAME, asset descriptor, or success result was produced. The
small-candidate-frame files under preflight are unchanged sealed INPUTS, not a
maximum-card output. The copied preflight FROZEN not_executed flag describes its
historical pre-run seal; execution/RUN-ENDED.json is the terminal run receipt.
Do not execute the archived run.py or worker.cjs.

post-verification.json contains stream SHA/length and before/open/after stat and
alias checks for all 13 external inputs. These checks all matched their original
pins after termination. Large HTML/profile/packet content is referenced by path
and pins only, not copied here. All 13 local preflight files matched their seal.

Uncompleted: inert DOM completion, original FIRST zero-DOM-effect proof, actual
DOM 14-position ledger, tiny certificate insertion/inverse, original binder
validation, maximum candidate and maximum browser acceptance. This is failure
evidence, not a performance result or a weakened acceptance gate.

## Lossless Git archive v2

This archive derives only from the sealed stopped v1 evidence. No run, worker,
Node process, browser, service or original-input verification task was rerun.
All files other than this README, the outer FROZEN manifest and the stderr
container are byte-for-byte copies of v1. The original v1 directory is retained.

Original v1 FROZEN SHA256: `04a228399c1a2fa78c7cb2b106b7e39187c2ff93eef2ad6747d98f4c6a2c16e0`.

The original `execution/stderr.log` is stored as `execution/stderr.log.gz`,
gzip level 9, empty original filename and mtime 0. Decompression restores the
exact original 8381 bytes, SHA256 `1f29e618f1f69abbd8266a1d67a91f479356821a6ad15a22993b4ebed12e70a6`.
It was compressed only to retain the raw trailing whitespace without making
that original native-error text a whitespace-invalid Git text change.

`archive-evidence.py` is preserved historical evidence from v1; its hard-coded
v1 source/destination paths describe that prior archival operation. It is not
the v2 derivation procedure and must not be executed. The historical preflight
run/worker files likewise remain evidence only and must not be run.
