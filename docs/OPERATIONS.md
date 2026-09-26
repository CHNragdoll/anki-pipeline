# Local operation and recovery

This runbook covers the `3.0.0-rc.1` candidate. Commands run from the repository root on the owner-controlled machine. The `config.toml` file supplies paths relative to itself; inspect it before any write. The default inputs point to the old V2.0 SQLite database, workbook, and audio directory. The default new state lives under `data/`, backups under `backups/`, and packages/reports under `output/`. These directories are ignored by Git and must be backed up separately when their contents matter.

## Install and inspect

```sh
uv sync --extra dev --frozen
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/anki-pipeline --version
.venv/bin/anki-pipeline doctor
```

`doctor` reports configured path existence and Python version. It does not prove source integrity, backup recoverability, or Anki client compatibility. Before a migration, confirm the configured new database and audio paths are outside the old paths; keep the V2.0 application stopped while its SQLite input is hashed and read.

## Local trial workflow

```sh
.venv/bin/anki-pipeline migrate
.venv/bin/anki-pipeline check --report output/quality-check.json
.venv/bin/anki-pipeline export-translations --file output/pending-translations.csv
.venv/bin/anki-pipeline import-translations --file output/completed-translations.csv
.venv/bin/anki-pipeline check --report output/quality-after-translations.json --strict-translations
.venv/bin/anki-pipeline build --file output/anki-rebuilt-3.0.0rc1.apkg
```

`migrate` only reads old inputs, creates a legacy SQLite snapshot under `backups/`, writes a new database, and copies audio into `data/audio`. It records the source SHA-256 and preserves rejected example rows for review. If a different target database already exists, migration stops; it does not overwrite it. The first `check` can exit 0 while reporting warnings for quarantined examples or missing translations. `--strict-translations` exits 2 while accepted examples still need translations. `build` requires base quality (`ok=true`), packages all cards, and includes only accepted examples with complete translations. It also writes `preview.html`, `quality-report.json`, and `build-report.json`. Open the preview in a browser and inspect front/back, audio references, and visible examples. Desktop/mobile Anki import remains `NOT_RUN` unless separately performed and recorded; this task does not import into the owner's collection.

Audio copying follows database promotion. If that phase fails, the new database and a partial *new* audio directory may remain. Preserve them for diagnosis, correct the missing/unsafe old-media input, rerun `migrate` to copy absent files without replacing existing new audio, then run `check`. Do not delete or modify the V2.0 media to recover.

The translation CSV is a working document containing source sentences and translations. Keep it outside Git. Do not change the `sentence_id`, `word`, `text`, `source`, or `content_hash`, or `translation_revision` columns. Every import validates the full file and binds each nonblank translation to the same sentence content; blank cells leave prior translations alone. An edited source row, duplicate ID, stale hash, or rejected example stops import before any update.

New wordbook/PDF input is optional and changes only the new database:

```sh
.venv/bin/anki-pipeline import-wordbook --file /private/path/wordbook.xlsx
.venv/bin/anki-pipeline extract --pdf /private/path/exam.pdf
```

`extract` requires either `--pdf` or `paths.pdf` in the config. New PDF examples enter with empty translations and require review. Wordbook import preserves existing enrichment where the incoming field is blank. Run `check` again after either command.

After changing lexical rules or explicit word forms, reassess existing sentences and inspect the revised accepted/quarantined counts:

```sh
.venv/bin/anki-pipeline reclassify
.venv/bin/anki-pipeline check --report output/after-reclassify.json
```

`reclassify` backs up the database before any changed acceptance decision. It preserves source text and translations; a newly accepted sentence can still require translation review.

Dictionary enrichment is the sole network command; it sends queried headwords to the selected provider and may download Oxford MP3 files. Run it only when network transfer is approved for those words:

```sh
.venv/bin/anki-pipeline enrich --provider oxford --limit 10
.venv/bin/anki-pipeline enrich --provider youdao --limit 10
```

The limit must be 1–100. Results are best effort per word, and failures are reported. No batch job or schedule runs automatically. Provider pages may change; inspect the result and rerun `check` before a build.

## Backup, restore, and rollback

```sh
.venv/bin/anki-pipeline backup
.venv/bin/anki-pipeline restore --file backups/NAME.sqlite3 --to data/restored-for-review.sqlite3
.venv/bin/anki-pipeline --config config.toml check --report output/after-restore-check.json
```

`backup` uses SQLite's online backup API and checks integrity. `restore` refuses an existing target and checks the restored file. The final `check` command above still checks the *configured active* database, not the new restore path; to validate restored content, copy `config.toml` to a private temporary config, set `paths.database` to the restored file, then run `doctor` and `check --report` with `--config` pointing to that file. Compare `logical_digest` or table counts and sample IDs with the active database before manually switching paths. Never overwrite the active database in place. A package can be rebuilt from the validated new database; it is not a replacement for a SQLite backup or the translation CSV.

The operator owns backup retention and storage separation. Before a delivery or operational use decision, record backup path, SHA-256, restore test, count/digest reconciliation, retention duration, and where the copy is stored separately from the working directory. Stop writes if integrity, source hash, audio containment, or translation alignment fails; preserve the failing input and backup for diagnosis.

## Release, support, and retirement

The planned private GitHub release uses a reviewed PR into `main`, an annotated `v3.0.0-rc.1` tag on the integrated commit, and a GitHub prerelease record. `pyproject.toml`/`anki_pipeline.__version__` use the equivalent Python form `3.0.0rc1`. Before publication, compare the source reference, version, changelog, build report, generated package hash, and release assets. A prerelease is a delivery milestone; production admission is a separate decision. Open findings and `NOT_RUN` client compatibility checks remain visible in the release record.

The repository owner receives issues through the private GitHub issue/PR flow, decides severity and response priority, and maintains only explicitly declared versions. For this initial candidate, `3.0.0-rc.1` is the trial version; no long-term support or automatic updates are promised. Updates require a reviewed change and a new version. Before retirement, export the local database and required CSV/audio, verify a restore, tell current consumers, revoke repository access as appropriate, remove optional network credentials if ever introduced, apply the owner's retention/deletion decision to local copies, and preserve release evidence and source history.


`project.root` defaults to the config directory. For a nested config folder, set `[project] root = ".."`. Writable database/audio/output/backups and explicit output files must stay inside that project root; old input directories are protected. `paths.legacy_package` optionally recovers MP3 files from a legacy `.apkg` after numeric-index, CRC, type and size checks (5 MiB/member, 256 MiB total); it does not extract arbitrary paths. Existing valid new media are preserved; invalid targets fail for repair.
