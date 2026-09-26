# Project profile — anki-pipeline

The machine-readable source for this adoption is [`project-profile.json`](project-profile.json). It records an individual rationale and applicability basis for every control in Universal Project Standard `1.1.0`. This document explains the local decisions; it is not a conformance pass or a release approval.

## Identity and authority

| Field | Decision |
| --- | --- |
| Project/version | `anki-pipeline` `3.0.0-rc.2` (Python metadata spelling `3.0.0rc2`) |
| Accountable owner | CHNragdoll, the private repository and local data owner. User approval is the authority for scope, risk acceptance, merge, prerelease, production admission, and retirement. |
| Purpose | Rebuild the V2.0 English vocabulary to Anki pipeline as a reproducible, recoverable local trial. Preserve original data and rejected examples; align translations by stable sentence ID. |
| Consumers | The owner running the CLI and reviewing generated cards. Downstream Anki desktop/mobile clients require separate compatibility evidence. |
| Excluded use | Hosted service, unattended ingestion, upload of raw legacy databases/input directories, automatic import into the owner's Anki collection, and a production-ready claim from a local preview alone. |
| Distribution | Private GitHub source and an authorized `v3.0.0-rc.2` prerelease with owner-only source and APKG assets. |
| Overall risk | `R2`: a bad migration or translation mismatch can damage recoverable study content and learning accuracy. No material transaction, privileged infrastructure action, or safety workflow is in scope. The rc.2 change is classified `bug`, `R2`; the project and change risk are separate decisions. |

The authoritative Git repository is `https://github.com/CHNragdoll/anki-pipeline`, default branch `main`. PRs are the durable review object. The branch-protection setting and labels must be checked on the actual forge before merge; their declaration here is policy, not proof they are configured. Each PR needs exactly one `type:*` label among `bug`, `feature`, `docs`, `refactor`, `maintenance`, `security`, one `risk:R1`–`risk:R4` label with rationale, and any applicable `breaking-change`, `dependencies`, `migration`, `needs-manual-test`, or `blocked` flags. The current candidate is `bug`/`R2`; unrun client checks remain visible.

## Runtime, ownership, and boundaries

The package declares Python `>=3.11`, with pinned runtime dependencies and a locked local environment. The local trial is owner-controlled macOS. The program is a CLI with no server, scheduler, application-managed account, or session. `config.toml` owns paths; the invoker's OS account and private GitHub permissions define access. [`ARCHITECTURE.md`](ARCHITECTURE.md) records modules, formats, trust boundaries, state identities, and failures. [`OPERATIONS.md`](OPERATIONS.md) records commands, backup/restore, support, and retirement.

Old V2.0 SQLite/workbook/audio remain read-only inputs. The separate new SQLite database owns edited cards, translations, raw legacy snapshots, and event records. Local audio copies, backup files, CSV exports, preview, reports, and `.apkg` are distinct artifacts. The CLI `enrich` command sends queried headwords to Oxford or Youdao over HTTPS; it does not upload raw database/audio. Raw input directories, databases, audio libraries and credentials stay out of Git history; user-requested template screenshots contain study examples. An attached release `.apkg` would contain example text and copied audio; inspect those assets and distribution rights before publication.

No conditional profile is selected because the copied package contains no declared project-specific profile with added controls. The local persistent-state, CLI, and opt-in network obligations are mapped to the applicable universal controls and verification matrix. A later formal profile can add requirements but cannot weaken this baseline.

## Applicability and evidence

The JSON profile maps all **92 applicable controls** with individual rationales and no exceptions. SEC-002 is assessed through local OS ownership, private repository visibility and write-target restrictions; the application has no separate accounts or sessions. This is an applicability decision, not a full conformance claim.

An `applicable` entry says the risk/control exists; it does not claim execution or `PASS`. The profile's `evidence` entries are current pointers used to decide applicability, not verification results. The verification matrix lists the repeatable methods and expected artifacts. Actual execution state belongs in the conformance record and release evidence: `PASS`, `FAIL`, `NOT_RUN`, `BLOCKED`, `NOT_APPLICABLE`, `PRIOR_PASS`, or `DISCOVERED`. Only a current `PASS` or an approved, evidenced `NOT_APPLICABLE` can satisfy an in-scope mandatory gate. Client import remains `NOT_RUN` until tested; a preview and a valid zip do not change that state.

Current source, relevant inputs and SHA-256, dependency lockfile, runtime environment, scope, and decision must match before reusing a prior result. A changed schema, migration, parser, permission, dependency, package renderer, or release artifact invalidates affected evidence. `PRIOR_PASS` stays historical. The repository's original-input hash manifest is an input baseline, not proof that future input reads or generated artifacts are unchanged.

## Release and readiness policy

The rc.2 path is a reviewed private PR from `fix/template-parity`, latest green checks, explicit merge commit into `main`, annotated `v3.0.0-rc.2` tag and private prerelease. See [rc.2 release record](RELEASE_RC2.md) for scoped evidence, current branch-control decision and limitations. The rc.1 equivalent-control approval in RELEASE.md is historical and cannot authorize rc.2. Published tags and assets must not be moved or overwritten.

Readiness has distinct states:

1. **Candidate/local trial:** code and local data/artifacts can be evaluated; no release or client claim follows automatically.
2. **Private prerelease delivered:** PR, merge, tag, release record, and artifact correspondence have current evidence. Any unrun client workflow remains a disclosed limitation.
3. **Production/client admission:** separate decision after applicable operational, recovery, security, compatibility, and Anki client evidence passes. The `3.0.0-rc.1` milestone does not assert this state.
4. **Retired:** consumer notice/export, access revocation, local deletion/retention, and evidence archive are completed and recorded.

There are no approved exceptions in this first profile. Any future exception needs an explicit identifier, affected control, owner approval, scope, start/expiry, risk, and remediation record. A new code or release decision must not infer an exception from the presence of this document.

本次发布的用户批准、等效控制及最终证据入口见 [当前 rc.2 发布记录](RELEASE_RC2.md)；发布前检查点中的阻塞状态按其中的实际后续证据更新，不等于生产或 Anki 客户端验收。


### Card sentence playback (local template trial)

The restored example speaker is separate from CLI enrichment. Like the original template, an explicit click sends that English sentence to Youdao over HTTPS for speech; it does not send its translation, wordbook, or audio library. No sentence request runs on card display. Playback falls back to system speech on failure or an 8-second loading/stall timeout; an unavailable system voice reports an error. Clicking again, switching sentences, or flipping the preview stops prior playback. This restores the original speaker behavior requested with the visual reference; the removed word-level “本机朗读” button stays absent.
