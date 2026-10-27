# Storage retirement and canonical publication — 2026-10-27

Branch: feat/unified-study-database-20261015. User authorizes minimizing project/service storage and removing dependencies on retired versions. No remote publication is authorized.

## Plan and acceptance

1. Inventory the live service configuration, registry, nine explicit mounts, original inputs and latest APKGs. Record current free space. Determine retained lower bound from actual required files, not directory sums.
2. Build one canonical current publication per book under AnkiStudyCatalog/published/current, preserving every byte with same-filesystem hardlinks. Replace v1/v2 storage with lightweight aliases backed exclusively by current cards/media/catalog. Keep old URLs usable. Store private service configuration outside dated exports.
3. Validate the original StaticMounts and StudyPreviewRoutes guards unchanged; start an isolated loopback instance against PostgreSQL in read-only initialization mode. Compare catalogs, selected complete cards and audio, including train, abide, a/an and a large card. Reconcile canonical files to originals; preserve learning tables and APKG hashes.
4. Switch the existing service only after candidate checks pass. Keep rollback configuration and old roots until production HTTP verification succeeds. Then retire superseded export files; preserve source data, originals, unique audits and necessary backups. Do not touch unrelated personal files or Trash.
5. Inventory/prune further reproducible historical build outputs only when current services and exporters have no dependencies. Report remaining protected and unresolved storage separately. Reduce duplicate artifacts by content identity; never infer physical recovery from logical sizes.
6. Check README and architecture against the resulting code/deployment; record Git checkpoints for the implementation. No push, PR, merge or Release is included.

Recovery: prior private configuration/registry/mounts and exact before/after file ledgers are retained outside HTTP roots. During cutover rollback uses the previous service configuration. After retirement, current canonical publication remains complete; retired URL aliases use its bytes. Raw input and database backups remain untouched.

Status: completed locally. Retained directory footprint is approximately 175.36 GB for Anki plus 39.90 GB for AnkiStudyCatalog, 215.26 GB combined. This is the practical retained baseline for the agreed protected inputs and backups, not a mathematical minimum.

Acceptance: 93 focused tests passed; 37 complete card digests and all nine entrypoints verified; ten learning-progress table digests unchanged; current APKG hashes unchanged. A fresh service started with all three historical catalog files absent and idempotent catalog retention read PostgreSQL only. Full exporter regeneration was not run because of an existing genanki file-materialization stall; no new package was generated.

See ../STORAGE_RETENTION.md and ../evidence/storage-retirement-20261027.json for retained scope, recovery and measurement limits. No push, PR, merge or release performed.
