# Local publication and generated-storage retention

The 2026-10-27 maintenance removes dependencies on complete historical web exports without changing the current card bodies, Anki packages, source databases or learning records. It does not publish a release.

## Canonical resources

The local service now uses `AnkiStudyCatalog/published/current/settings/service.json`. Its registry and mount manifest are private siblings. Each book has one complete publication under `published/current/books/`. Six historical v1/v2 mount names use thin shells and the current book's exact cards, catalog and media delegates. The existing mount-confinement, current-catalog digest and native-identity guards remain in force. v2 learning membership is read from the exact migration-pinned PostgreSQL catalog object; obsolete entry HTML and wrapper files are no longer startup dependencies. Explicit v1 compatibility keeps its filesystem checks.

The bookshelf opens current v3 pages directly. Original legacy landing bookmarks forward to those same pages, preserving their query and fragment. The old auxiliary-link URL resolves to the tracked current runtime through an exact asset whitelist. Its old physical output file has been removed; no retired export tree is needed. The exam stylesheet is an unchanged pinned file under `anki_pipeline/web_runtime/study/`.

## Next publication

1. Before retiring a migrated installation’s legacy catalogs, run `scripts/retain_service_catalogs.py --config /private/service.json --backup-directory /private/catalog-backup` as a dry run, then add `--apply` within the authorized migration scope. It verifies the approved migration pins/native aliases, backs up exact bytes, and transactionally adds immutable objects and ownership keys. It does not overwrite existing records or change learning membership. Repeating it after retention reads PG only and makes no writes.
2. Generate the new book projection from the shared catalog using the normal exporter, in a disposable work directory. Keep original inputs outside it.
3. Prepare a private candidate service configuration whose registry/catalog pins describe the **newly generated** projections. Do not stage the old active configuration and mistake its unchanged bytes for a new export.
4. Run `scripts/stage_current_publication.py --config /private/candidate/service.json --destination /private/AnkiStudyCatalog/published/candidate-YYYYMMDD`. The destination must not exist or overlap a mounted HTTP root. The command only stages files and configurations; it does not activate or delete anything.
5. Validate the existing security guards, isolated service, complete card bodies, audio and ranges, old URL aliases, learning-state digests, and latest package hashes. Activate the verified candidate with a recoverable prior configuration.
6. Verify production before retiring old generated workspaces. Preserve original inputs, the current packages and one selected rollback set. Retain summaries and losslessly compressed necessary audits rather than whole experimental publications.

Hardlinks are only used after same-file identity or complete SHA256/length equality establishes identical bytes. Published files are immutable: future updates must be staged separately, never written in place through a shared hardlink.

## This maintenance's receipts and recovery

Machine-local, ignored receipts live in `output/storage-retirement-20261027/`; the public summary is [`evidence/storage-retirement-20261027.json`](evidence/storage-retirement-20261027.json).

- `candidate-verification.json` and `production-verification.json`: 37 complete card body digests, all nine version entrypoints, current packages and service checks.
- `browser-check.json`: fresh headless Chromium sessions opened all three books and flipped to their backs. Content resources loaded successfully; the pre-existing optional favicon 404 is recorded separately. This is not a new Safari/mobile performance acceptance claim.
- `catalog-retention-applied.json` and private `settings/learning-catalog-backups-20261027/`: three exact legacy learning catalogs retained as immutable PG objects, three new ownership keys and one storage audit event. No existing data was overwritten. `cold-restart-verification.json` proves startup and idempotent retention with all three old catalog files temporarily absent; originals were restored afterward.
- `progress-before.json` and `progress-final.json`: matching digests of all ten independent learning-progress tables.
- `retained-source-manifests.json`: five original imports; source packages and both original SQLite inputs remain at their original paths.
- `cold-report-archives.json`, `cold-database-archives.json`: full SHA256, original path and compressed recovery file for every cold archive. Restore an individual file with `zstd -dc <archive.zst> > <original-path>`, after creating its parent directory. Recheck its SHA256 against the receipt before use.
- `backups/cold-output-20261027/`: content-addressed archives and restoration notes. Four older historical semantic stages remain in `backups/lossless-stage-archive-20261025/`.
- `legacy-landings/`: original landing pages as gzip files. `settings/previous-service.json` and `previous-mounts.json` preserve the pre-maintenance configuration. Before retirement those could be used for direct rollback; after retirement, use the complete canonical publication or restore the required inputs rather than pointing a service at removed old directories.
- Gzipped retirement ledgers distinguish obsolete generated exports/workspaces from retained original data. Trial-package retirement explicitly retains exact import inputs, current packages, named original Liu packages, formal release copies and the previous complete two-year rollback packages.

No new APKG was generated or substituted. Full exporter regeneration was not repeated: an optional readiness import encountered an existing project-venv `genanki` file-materialization stall and was stopped. Original input existence/length, current package hashes, the running service and rendered content were checked independently. No Python environment or dependency versions were changed.

## Size interpretation

`du` deduplicates hardlinks within its traversal, and APFS can additionally share extents across different files. Directory totals are useful retention measurements, not a promise of equally large physical recovery. Record `df`/filesystem available bytes before and after, and disclose concurrent/background effects. Do not add every unlink size and label that sum “disk freed”.
