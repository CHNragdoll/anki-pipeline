# Evidence snapshots and executable entry points

Files in this directory record the inputs, guards and outcomes of a dated run.
They are not general-purpose commands. Absolute paths and local service URLs
identify the recorded owner's environment; they are not portable defaults.

In particular, the `source-confirmations-20261014-*-driver.py`,
`source-confirmations-20261014-post-adapter.py` and
`source-confirmations-20261014-rollback-guard.py` files preserve historical
bytes and SHA-256 pins. Do not execute these archives from this directory.
The approved driver is restored only to its original
`scripts/apply_source_confirmations.py` location under the explicitly approved,
backed-up and pinned recovery procedure in
[the source-confirmation record](../FIVE_SOURCE_CONFIRMATIONS_20261014.md#恢复应用代码).
The archived rollback helper originally lived under
`output/source-confirmations-20261014/cards-own/recovery-own/guarded_rollback.py`;
its parent-based paths describe that location. It was not executed against the
actual candidate. Current CLI entry points live in `scripts/`, and each write
still requires its original scope, input pins, owned paths and authorization.

Public source tests use portable synthetic fixtures. Tests requiring private
full-corpus snapshots skip only when the required input files are absent;
present but stale, altered or incorrectly sealed files continue to fail.
Missing private data is not an integration-test PASS. Release-specific package
imports and device observations are recorded separately from portable CI.
