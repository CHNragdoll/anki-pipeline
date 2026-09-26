# Architecture and trust boundaries

This describes the `3.0.0-rc.1` candidate in this repository. The program is a local Python CLI, not a hosted service. Its owner runs each command explicitly. There is no scheduler, listening socket, user account system, or Anki collection writer.

```text
Legacy V2.0 SQLite / workbook / audio (read-only inputs)
                  │
                  ▼
       CLI + config.toml (local owner)
         ├─ migration / wordbook / PDF / dictionary input
         ├─ exact text matching and translation ID validation
         ├─ versioned SQLite store ── backups / restore to new path
         ├─ quality report ── genanki package + browser preview
         └─ enrich (CLI) ── HTTPS Oxford or Youdao; optional MP3 download
                  │
                  ▼
       data/, backups/, output/ (local, ignored by Git)
```

## Components and interfaces

| Component | Responsibility and contract |
| --- | --- |
| `cli.py`, `config.py` | Explicit commands and TOML paths. Relative paths resolve from the config file, not the shell directory. Commands return nonzero on reported errors. |
| `inputs.py` | Read an Excel wordbook. Only `enrich` requests Oxford/Youdao. Oxford audio downloads accept an HTTPS host/path allowlist, bounded response, and MP3 validation. |
| `pdf.py`, `text.py`, `forms.py` | Read a PDF once, carry year/section/part/text/page provenance, match complete inflections and explicitly supplied forms, parse numbered originals/translations, and create stable sentence identities. PDF extraction itself is read-only. |
| `migration.py`, `pipeline.py` | Read the old database and audio; create a separate versioned database and audio copy. Keep original row JSON, every parsed sentence, and rejected match decisions. `extract` adds new sentences without replacing existing translations. `reclassify` reapplies lexical acceptance after a rule change without changing original text or translation. |
| `store.py`, `translations.py` | Own SQLite schema, transactions, online backup, restore to a new path, content digest, and CSV import/export. CSV rows bind sentence ID to word, sentence, source, and content hash. |
| `quality.py`, `packaging.py`, `templates/` | Report integrity, missing content/audio, and quarantined sentences. Build an `.apkg` with stable note/deck IDs and an HTML preview. Only accepted, translated, review-free examples appear on cards. |

The package targets Python `>=3.11`; the local trial uses a locked environment. Runtime dependencies are pinned in `pyproject.toml` and `uv.lock`. The source and build output are distinct: repository history is authoritative for code, the local SQLite file for edited learning content, legacy inputs for their original values, and the release record for the published version.

## State and identity

SQLite schema version 1 has `cards`, `sentences`, `legacy_rows`, `metadata`, and `events`. Card IDs derive from sheet, lesson, and word. Sentence IDs derive from card ID plus normalized word, original sentence, and source; they do not depend on display order or the old numbering. `legacy_rows` retains source payloads for audit. `accepted=0` isolates word mismatches without deleting their original text or translation. Missing and visibly incomplete translations remain explicit review items. A card can exist without an example; package inclusion requires a completed accepted translation for each displayed example.

All state-changing CLI operations target the configured new database or output paths. `migrate` reads V2.0 inputs but writes the new database, a legacy snapshot backup, and a separate audio copy. Database mutations validate their intended input and use an immediate transaction; writes to an existing database take a prior SQLite backup. Restoration refuses to replace an existing destination. PDF extraction and dictionary enrichment enter through explicit commands; `doctor`, `check`, and translation export do not mutate the database. `build` writes package, preview, and reports to the output directory; callers should choose a new `--file` path when preserving an earlier package.

## Trust boundaries

1. **Owner to local CLI:** Shell access is the authority boundary. There is no second identity or role, network listener, token, or session. A user with filesystem access can read and modify the local database; OS account permissions and private repository permissions are the access controls. This is the evidence for `SEC-002` non-applicability to application-managed identity, not a claim that filesystem access is harmless.
2. **Legacy data to new state:** Old SQLite, workbook, and audio are untrusted inputs. Migration opens the source read-only, checks integrity and its SHA-256 before/after reading, writes a separate snapshot, and promotes a new database without replacing another file. Numbering conflicts or orphan translations fail before promotion. PDF and HTML content are treated as data; generated Anki fields are escaped by the packager.
3. **Translation CSV to SQLite:** CSV may contain private study material. Import validates header, row IDs, hashes, original text/source, duplicates, accepted state, size, and completeness before writing. The transaction rechecks edited rows under the write lock. Blank CSV translation cells do not erase completed work.
4. **Opt-in network:** The CLI `enrich` command sends queried words to Oxford or Youdao over HTTPS. Separately, clicking a generated card’s sentence speaker sends that English sentence to Youdao over HTTPS, with system speech as a fallback. Oxford audio comes from the allowed US pronunciation path and is size/type checked before atomic local storage. Raw legacy SQLite, full wordbook, translation CSV, existing audio directory, and generated `.apkg` are not sent by the program to those services. CLI requests are bounded by the command limit and HTTP timeout; card speech has a loading/stall timeout. Provider content can change and failures are reported per word.
5. **Local repository to private GitHub:** Source, tests, governance records, and dependency lockfile belong in Git. `data/`, `backups/`, `output/`, `.venv/`, generated packages, local translations, and credentials remain outside source history. A separately attached release `.apkg` can contain copied audio and example text; inspect its contents and distribution rights before attaching it. A private repository still requires secret and artifact inspection before push or release.

## Failure and recovery behavior

Unknown database schema versions, a destination that already exists, changed legacy input, duplicate translated IDs, altered source text, unsafe audio paths, and failed integrity checks stop the affected operation. The migration creates a temporary database and only promotes it after validation; the subsequent audio-copy phase can leave a partial *new* audio directory if interrupted. Check and retry that copy after correcting the cause, preserving the old audio. SQLite writes roll back on exception; a backup is taken before mutation of an existing database. `restore` writes a separate destination for comparison before any manual replacement decision. A failed `enrich` word is listed and does not stop other requested words; no failed lookup is silently treated as valid dictionary data. The CLI has no automatic retry or background work.

The `.apkg` and browser preview are generated artifacts, not authoritative state. The browser preview checks rendering but is not evidence of desktop or mobile Anki import compatibility. This release candidate is a local trial until those client workflows are actually tested.


### Card sentence playback (local template trial)

The restored example speaker is separate from CLI enrichment. Like the original template, an explicit click sends that English sentence to Youdao over HTTPS for speech; it does not send its translation, wordbook, or audio library. No sentence request runs on card display. Playback falls back to system speech on failure or an 8-second loading/stall timeout; an unavailable system voice reports an error. Clicking again, switching sentences, or flipping the preview stops prior playback. This restores the original speaker behavior requested with the visual reference; the removed word-level “本机朗读” button stays absent.
