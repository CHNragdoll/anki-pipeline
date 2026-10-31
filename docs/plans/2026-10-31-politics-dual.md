# Political exam papers: shared Web / Anki delivery

Repository: anki_rebuild; branch feat/unified-study-database-20261015. Existing tree clean at start. Read exam-library as a source only; do not alter its SQLite, papers, answers or Git checkout. No remote publication authorized.

Scope: adapt existing political whole-paper content into the same PostgreSQL content projection and existing APKG / Web exporters used by the other books. Preserve question order, full material/subquestions, options, formulas, images, answer-source paragraphs and provenance. Keep whole-paper access. Anki granularity requested asynchronously (per-question recommended vs per-paper); source audit and adapter are independent of that answer.

1. Snapshot source read-only and audit all 21 question papers / 794 parent questions (2003–2023). Preserve 225 records without mapped answers (2003–2008) as explicitly missing; never infer answers. Use full answer source blocks, not only normalized explanation fields, to avoid dropping answer points.
2. Implement subject-neutral question-bank adapter and stable native identities with source reconciliation and focused tests. Use existing package importer and common project_book/project_note exporters; no politics-specific export fork.
3. Before append-only PG import: save original scope/config/progress fingerprints and recoverable existing state. New book writes must be isolated in a transaction with explicit rollback scope; previous books/native identities and study state unchanged. Keep only one current output and one source adapter package, no repeated whole-library copies.
4. Generate complete APKG and Web from the shared catalog. Verify source coverage, figures, offline math, stable identities/reimport, card fronts/backs and original answer content. Add generic question-oriented navigation labels without changing vocabulary labels. Publish local candidate only after checks, then add local bookshelf entry without replacing existing books.
5. Run independent review of the actual diff, fix findings, update homepage documentation/architecture and record Git checkpoints. Report native import, actual browser checks and phone acceptance separately. No push/PR/merge/Release.

Recovery: keep source database and resources read-only; journal exact source fingerprints, output hashes and append-only book IDs. Back up changed service manifests before local activation; preserve old-book resources and progress. Remove or re-point only this task's new registration/output if acceptance fails.
