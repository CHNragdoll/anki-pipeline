# Private largest-card compiled transport A → B → A

Prepared only. No server/Safari/PG or production modification was performed here. Root owns any server process/session and browser acceptance. The gzip candidate admission remains subject to its independent review.

- Manifest external SHA: `84bcc115205fed132c41d0a29e4884e801c2ece6d4cd7956ddc2a53de3c680d1`.
- 84 exact A/B routes. Both variants share one startup-authenticated immutable187,346,220-byte snapshot (178.7MiB); hard memory-byte limit300MiB. It is a private source snapshot, not dynamic current-source serving. At shutdown, only used source files are rechecked by streaming SHA plus original stat/dev/ino after all request threads drain.
- Same full inline HOST6a96b752… (53,441B), same navigation/prepared/source-wrapper/native/module/CSS/media chain. Historical external HOSTaed67c9c… (52,722B) is separately labeled. No constructed packet shortcut. A is052ccc54; B is cdb69f8c from candidate freeze6dd1b9ae. Only compiled transport and collector identity metadata differ. Original flip, source-token check, fullgate/10s, optional bounded after-gate checks and manual JSON download are retained.
- Three compiled raw inputs71,877,501B are unchanged; three explicit gzip carriers8,184,676B are shared read-only from worker stage. `.gz` always uses application/gzip with no Content-Encoding, so browser DecompressionStream recovers original pinned bytes. No HTML injection, response rewrite, dynamic gzip or directory fallback exists. GET/HEAD/Range remain available and no-store across A/B.
- The original55,603,149-byte artifact was JSON-parsed exactly once under root authorization to enumerate actual side/child resources, policy/CSS URLs and source-wrapper head. No22MB profile parse, DOM or semantic producer ran. The closure has35 entries and no external resource URL requiring remap. Unknown paths404;403/404/416 requests are logged as bounded path-only metadata without query/body/pin. Unrelated neighboring prefetch URLs remain unknown and must not be treated as an admitted source-chain resource.

Default only checks small manifest bytes and source metadata; it does not authenticate all payload bytes or bind:

```sh
cd /Users/apple/Documents/PyCharm/Anki/anki_rebuild
.venv/bin/python -B '/private/tmp/study-compiled-transport-snapshot-20261017-j7w999xq/snapshot_server.py' --manifest '/private/tmp/study-compiled-transport-snapshot-20261017-j7w999xq/manifest.json' --manifest-sha256 84bcc115205fed132c41d0a29e4884e801c2ece6d4cd7956ddc2a53de3c680d1
```

Root-only launch after independent admission: add `--serve`. Startup hashes each unique admitted file once, then binds127.0.0.1 on a random ephemeral port and prints ready PID plus exact A/B URLs with the real card hash. Root retains that session. Stop only that exact process with SIGTERM/SIGINT; handlers only set a flag, the main loop stops accepting, server_close drains requests, then writes private requests/closed receipts. There is a30-second socket idle timeout. Do not interpret process exit alone as drain; inspect closed.drained and used_sources_unchanged.

Run A, B, A as separate fresh parent documents. Use the original complete-back timing signal and download each JSON with the unchanged button. Matching full-gate/compiled-handle acceptance is still required; HTTP readiness, static equivalence or this server's tests are not measured Safari speed, paint or a cold-cache guarantee.

Verification:8 small pure/temp tests passed0.030s, including fake-only HTTP with no socket and real failure-ledger assertions; both collector JS syntax checks passed; actual metadata-only manifest check passed. No large payload was parsed or hashed again during final assembly, and source assets were never copied or modified.
