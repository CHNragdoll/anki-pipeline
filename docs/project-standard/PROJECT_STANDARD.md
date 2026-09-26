# Universal Project Standard

Standard version: 1.1.0

Status: Normative

## 1. Scope and non-goals

This standard defines the minimum engineering-governance outcomes and evidence required for every software project. It applies independently of industry, product domain, programming language, framework, repository host, CI provider, architecture, deployment model, and distribution model.

It does not prescribe one tool, directory structure, architecture style, test framework, hosting service, delivery channel, or product capability. Capability-specific obligations belong in conditional profiles. A template, tool, or successful syntax check alone does not prove conformance.

## 2. Normative language

- **MUST / MUST NOT**: mandatory for every applicable control.
- **SHOULD / SHOULD NOT**: expected unless an owner-approved, time-bounded exception records the reason and remediation.
- **MAY**: optional.

When this document and the machine-readable catalog disagree, the release gate fails until both are corrected and versioned together.

## 3. Ownership and authority

The project profile identifies the accountable owner, decision authorities, supported purpose, ownership boundaries, and sources of truth. Approval authority cannot be inferred from tool access alone. The owner retains enough source, data, history, configuration, credentials, build knowledge, artifacts, and recovery material to continue, migrate, or retire the project.

## 4. Task modes, applicability, risk, and exceptions

Every project selects exactly one current risk level:

- `R1`: limited impact and failure radius.
- `R2`: standard recoverable user or business impact.
- `R3`: sensitive data, privileged effects, material transactions, or important availability.
- `R4`: safety, regulatory, infrastructure-control, or severe organizational impact.

The project profile's risk level describes the project's overall impact and
exposure. A change risk describes this task's impact and exposure; they are
related inputs but are not interchangeable. A read-only review has no change
type and does not need a change record.

Use one task mode for each piece of work:

- `review`: bounded, read-only inspection, diagnosis, or reporting. It records
  scope, baseline, current delta, evidence limits, and applicable gates; it
  does not modify project state or fill a change type.
- `change`: code, configuration, documentation, or behavior work.
- `data`: import, migration, deletion, permission, or other state work.
- `release`: an explicitly requested formal release under the project's release
  policy.
- `adoption`: first adoption of this package, including a complete profile and
  applicability map.
- `audit`: an explicitly requested full-standard audit of the catalog and
  claimed gates.

Routine reviews and changes use the project's baseline plus the current delta.
The complete catalog is required only for first adoption or a full-standard
audit; an explicit full-conformance claim is itself a full-standard audit. It
is not rebuilt for every routine task.

Each control is recorded as applicable, `NOT_APPLICABLE`, or covered by a declared exception. `NOT_APPLICABLE` requires specific rationale and evidence that the underlying risk or capability does not exist. An exception requires owner approval, scope, risk, start date, expiry date, and remediation; it never becomes a pass.

Every change selects exactly one canonical primary type: `bug`, `feature`, `docs`, `refactor`, `maintenance`, or `security`. It also selects exactly one `R1`-`R4` change risk with specific rationale. Zero or more controlled flags may record `breaking-change`, `dependencies`, `migration`, `needs-manual-test`, or `blocked`. Flags add context but do not replace the required type, risk, rationale, evidence, or gate state.

## 5. Universal lifecycle

The task mode determines which lifecycle stages are in scope. A `review` uses
intake, authorization, bounded inspection, evidence assessment, and reporting.
A `change` or `data` task uses requirements, design, approval, safe isolation,
implementation or state operation, verification, and review. A `release` adds
versioning, integration, immutable reference, release record, artifact
correspondence, and delivery verification required by the project's release
policy. `Adoption` and `audit` assess the complete catalog and applicability
map. Emergency work may accelerate review but cannot remove traceability,
verification, versioning, or post-change evidence.

## 6. Universal controls

For each control, implementation is project-native and risk-proportional.
Evidence must identify the subject version, method, environment, time, result,
coverage, limitations, and durable location. Apply the control's stated gate
only when that gate is in scope for the selected task mode and project policy;
applicability does not mean every control runs on every task.

### Implementation guidance for all controls

Use project-native tools and keep the procedure proportionate to the selected
mode and risk. Small wording or CSS-only changes need targeted checks. Ordinary
behavior changes need a reproducible check or regression evidence and the
necessary review. Database, permission, migration, and sensitive-state work
needs a stronger plan, backup or recovery evidence where applicable,
validation, and rollback evidence. Formal releases use the complete project
release workflow. Do not turn a project-level risk label into a claim about
the current change.

### GOV — Governance

Ownership, authority, risk, applicability, and exceptions.

#### GOV-001 — Accountable owner

**Level:** MUST

**Gate:** change

The project MUST identify an accountable owner with authority over scope, risk acceptance, release, and retirement.

**Required evidence kinds:** project profile; approval record.

#### GOV-002 — Purpose and consumers

**Level:** MUST

**Gate:** change

The project MUST record its purpose, intended consumers, supported use, and explicitly excluded use.

**Required evidence kinds:** project profile; requirements.

#### GOV-003 — Owner control and portability

**Level:** MUST

**Gate:** delivery

The owner MUST retain effective access to source, history, configuration, credentials, data, build instructions, release artifacts, and recovery material required to continue or migrate the project.

**Required evidence kinds:** ownership inventory; export procedure; recovery evidence.

#### GOV-004 — Risk classification

**Level:** MUST

**Gate:** review

The project MUST select and justify one current risk level from R1 through R4 and MUST reassess it after material scope or exposure changes.

**Required evidence kinds:** risk assessment; project profile.

#### GOV-005 — Control applicability

**Level:** MUST

**Gate:** review

Every control MUST have a recorded applicability decision with specific rationale and evidence; blanket exclusions are prohibited.

**Required evidence kinds:** applicability matrix; supporting evidence.

#### GOV-006 — Explicit approval

**Level:** MUST

**Gate:** release

Implementation, release, production admission, risk acceptance, and retirement decisions MUST be approved by the authority declared in the project profile.

**Required evidence kinds:** approval record; review record.

#### GOV-007 — Time-bounded exceptions

**Level:** MUST

**Gate:** release

Any exception MUST identify the affected control, scope, owner approval, risk, start date, expiry date, and remediation plan and MUST NOT be treated as a pass.

**Required evidence kinds:** exception record; approval record; remediation plan.

### REQ — Requirements

Problem definition, scope, constraints, acceptance, and traceability.

#### REQ-001 — Problem statement

**Level:** MUST

**Gate:** change

Each change MUST state the problem or opportunity in terms that can be evaluated independently of the proposed implementation.

**Required evidence kinds:** change record; requirements.

#### REQ-002 — Defined scope

**Level:** MUST

**Gate:** change

Each change MUST define included behavior, excluded behavior, affected consumers, and affected project boundaries.

**Required evidence kinds:** change record; scope decision.

#### REQ-003 — Measurable acceptance

**Level:** MUST

**Gate:** review

Requirements MUST include observable acceptance criteria that identify the evidence needed to prove completion.

**Required evidence kinds:** acceptance criteria; evidence map.

#### REQ-004 — Constraints and assumptions

**Level:** MUST

**Gate:** review

Material technical, legal, operational, schedule, compatibility, and ownership constraints and assumptions MUST be recorded and validated.

**Required evidence kinds:** requirements; constraint validation.

#### REQ-005 — Requirement traceability

**Level:** MUST

**Gate:** release

Every accepted requirement MUST be traceable to design, implementation, verification, review, and release evidence or to an approved non-applicability decision.

**Required evidence kinds:** traceability matrix; verification evidence.

#### REQ-006 — Scope-change control

**Level:** MUST

**Gate:** change

A material change to scope, assumptions, risk, or acceptance criteria MUST be explicitly reviewed and approved before dependent work continues.

**Required evidence kinds:** decision record; updated requirements; approval record.

### ARC — Architecture

Boundaries, interfaces, state, dependencies, failure behavior, and decisions.

#### ARC-001 — System context and boundaries

**Level:** MUST

**Gate:** review

The project MUST document its boundary, consumers, external systems, trust boundaries, and ownership boundaries at a level proportionate to risk.

**Required evidence kinds:** architecture description; boundary diagram.

#### ARC-002 — Component responsibilities

**Level:** MUST

**Gate:** review

Components MUST have understandable responsibilities, dependencies, and change boundaries so behavior can be reasoned about and reviewed.

**Required evidence kinds:** component map; interface documentation.

#### ARC-003 — Explicit interfaces

**Level:** MUST

**Gate:** review

Interfaces between components and with consumers MUST define inputs, outputs, errors, compatibility expectations, and ownership.

**Required evidence kinds:** interface contract; compatibility policy.

#### ARC-004 — State ownership

**Level:** MUST

**Gate:** review

State ownership, consistency, lifecycle, and authority MUST be explicit wherever the project creates, reads, changes, or deletes state.

**Required evidence kinds:** state model; data-flow evidence.

#### ARC-005 — Failure behavior

**Level:** MUST

**Gate:** review

Material failure modes, partial-failure behavior, limits, retries, timeouts, recovery, and fail-open or fail-closed decisions MUST be designed explicitly.

**Required evidence kinds:** failure analysis; resilience design; test evidence.

#### ARC-006 — Dependency replacement

**Level:** MUST

**Gate:** delivery

Material external dependencies MUST have documented boundaries, configuration ownership, and a feasible upgrade, replacement, disablement, or exit path.

**Required evidence kinds:** dependency map; replacement procedure.

#### ARC-007 — Architecture decisions

**Level:** SHOULD

**Gate:** review

Long-lived or difficult-to-reverse architecture decisions SHOULD record considered alternatives, consequences, and the approval decision.

**Required evidence kinds:** architecture decision record.

### VCS — Version control

Isolation, commits, review, integration, and immutable history.

#### VCS-001 — Version-controlled source

**Level:** MUST

**Gate:** change

Source, configuration, schemas, migrations, build instructions, tests, and governance artifacts required to reproduce a release MUST be version controlled unless an approved exclusion explains the alternative authority.

**Required evidence kinds:** repository history; project profile.

#### VCS-002 — Isolated change branch

**Level:** MUST

**Gate:** change

Each change MUST use an isolated branch or equivalent workspace based on the
project's current protected default branch or an explicitly approved
equivalent. A safe existing branch or workspace MAY be reused for a continuing
task when ownership, base reference, and dirty state are recorded and
preserved; it MUST NOT overwrite unrelated work.

**Required evidence kinds:** branch reference; base reference.

#### VCS-003 — Focused commits

**Level:** MUST

**Gate:** review

Commits MUST be reviewable, accurately described, limited to intentional scope, and free of unrelated owner work or secrets.

**Required evidence kinds:** commit history; diff review.

#### VCS-004 — Recorded change review

**Level:** MUST

**Gate:** review

Every integrated change MUST have a PR, MR, or equivalent durable review object that records scope, exactly one canonical change type, exactly one R1-R4 risk classification with rationale, optional controlled flags, evidence, findings, and disposition.

**Required evidence kinds:** review object; review findings.

#### VCS-005 — Truthful checks

**Level:** MUST

**Gate:** review

Automated and manual check results MUST distinguish executed passes, failures, omissions, blockers, historical evidence, and discovery-only results.

**Required evidence kinds:** check results; manual verification record.

#### VCS-006 — Explicit integration history

**Level:** MUST

**Gate:** release

Integration into the protected default branch MUST preserve an explicit integration record and the detailed commits required for traceability.

**Required evidence kinds:** integration commit; branch history.

#### VCS-007 — Immutable published history

**Level:** MUST

**Gate:** release

Published commits, release references, review records, and audit evidence MUST NOT be silently rewritten, moved, or deleted.

**Required evidence kinds:** remote references; release record; audit log.

### QLT — Quality

Risk-based verification, regression, compatibility, performance, and recovery.

#### QLT-001 — Risk-based verification matrix

**Level:** MUST

**Gate:** review

The project MUST define a verification matrix that maps relevant behaviors and risks to test or review evidence and states why omitted categories are not applicable.

**Required evidence kinds:** verification matrix; applicability rationale.

#### QLT-002 — Acceptance verification

**Level:** MUST

**Gate:** release

Every acceptance criterion MUST have current evidence at the same scope and environment required by the criterion.

**Required evidence kinds:** acceptance evidence; traceability matrix.

#### QLT-003 — Regression protection

**Level:** MUST

**Gate:** review

A defect fix or behavior change MUST include repeatable evidence capable of detecting recurrence unless the project profile approves a stronger alternative.

**Required evidence kinds:** regression test; alternative evidence.

#### QLT-004 — Static validation

**Level:** MUST

**Gate:** review

Applicable source, configuration, schema, and artifact formats MUST be validated with deterministic static checks.

**Required evidence kinds:** static check results; schema validation.

#### QLT-005 — Component behavior

**Level:** MUST

**Gate:** review

Material component behavior and error handling MUST be verified at the smallest useful boundary.

**Required evidence kinds:** component test results.

#### QLT-006 — Integration boundaries

**Level:** MUST

**Gate:** release

Material interactions across owned or external boundaries MUST be verified using representative interfaces, state, and failure behavior.

**Required evidence kinds:** integration test results; boundary evidence.

#### QLT-007 — Consumer workflows

**Level:** MUST

**Gate:** delivery

Critical consumer workflows MUST be verified end to end at a representative level or have an approved reason and alternative evidence.

**Required evidence kinds:** workflow test results; alternative evidence.

#### QLT-008 — Compatibility

**Level:** MUST

**Gate:** delivery

Supported platforms, environments, versions, interfaces, and upgrade paths MUST have a declared compatibility policy and representative evidence.

**Required evidence kinds:** compatibility matrix; compatibility results.

#### QLT-009 — Installation and migration

**Level:** MUST

**Gate:** delivery

Applicable clean installation, repeat installation, upgrade, migration, and rollback paths MUST be verified without assuming an existing healthy state.

**Required evidence kinds:** installation results; migration results; rollback results.

#### QLT-010 — Resource and performance limits

**Level:** MUST

**Gate:** production

Material latency, throughput, capacity, resource, size, and concurrency limits MUST be defined and verified where exceeding them can affect consumers or safety.

**Required evidence kinds:** performance criteria; load evidence; limit tests.

#### QLT-011 — Human interaction quality

**Level:** MUST

**Gate:** delivery

Projects with human interaction MUST verify applicable accessibility, usability, input, error, and recovery behavior; projects without human interaction MUST record non-applicability.

**Required evidence kinds:** accessibility evidence; usability evidence; non-applicability rationale.

#### QLT-012 — Recovery verification

**Level:** MUST

**Gate:** production

Where failure can lose state or interrupt required service, recovery procedures MUST be exercised and verified rather than documented only.

**Required evidence kinds:** recovery exercise; integrity checks.

### SEC — Security and privacy

Threat boundaries, identity, access, inputs, secrets, privacy, and response.

#### SEC-001 — Threat and trust model

**Level:** MUST

**Gate:** review

The project MUST identify protected assets, actors, entry points, trust boundaries, abuse cases, and security assumptions proportionate to risk.

**Required evidence kinds:** threat model; trust-boundary evidence.

#### SEC-002 — Identity and authorization

**Level:** MUST

**Gate:** release

Identity, authentication, authorization, session, and privileged-action controls MUST be explicit, least-privileged, and verified wherever access distinctions exist.

**Required evidence kinds:** access model; authorization tests.

#### SEC-003 — Input and output safety

**Level:** MUST

**Gate:** release

Untrusted input MUST be bounded and validated, and output MUST be encoded or constrained for its destination context.

**Required evidence kinds:** validation rules; security tests; code review.

#### SEC-004 — Secure state changes

**Level:** MUST

**Gate:** release

State-changing actions MUST verify authority, target, integrity, replay protection where relevant, and safe failure behavior.

**Required evidence kinds:** state-change design; security tests.

#### SEC-005 — Secret management

**Level:** MUST

**Gate:** delivery

Secrets MUST be excluded from source and artifacts, stored through an approved mechanism, minimally scoped, rotated when required, and prevented from unsafe logs or error output.

**Required evidence kinds:** secret scan; secret inventory; rotation policy.

#### SEC-006 — External communication

**Level:** MUST

**Gate:** delivery

External communication MUST define approved destinations, transport protection, authentication, timeouts, size limits, data handling, and failure policy.

**Required evidence kinds:** network policy; communication tests; data-flow record.

#### SEC-007 — Sensitive-data classification

**Level:** MUST

**Gate:** review

The project MUST classify data it receives, creates, infers, stores, transmits, logs, or exposes and apply controls appropriate to sensitivity and obligations.

**Required evidence kinds:** data classification; data-flow record.

#### SEC-008 — Privacy obligations

**Level:** MUST

**Gate:** production

Where personal or sensitive data exists, collection, purpose, minimization, access, retention, transfer, deletion, and disclosure obligations MUST be documented and verified.

**Required evidence kinds:** privacy assessment; retention evidence; rights procedure.

#### SEC-009 — Safe files and execution

**Level:** MUST

**Gate:** release

File access, parsing, upload, extraction, execution, and generated paths MUST enforce containment, type, size, integrity, permission, and unsafe-link boundaries where applicable.

**Required evidence kinds:** file-boundary tests; parser tests; code review.

#### SEC-010 — Secure defaults and failure

**Level:** MUST

**Gate:** release

Security-relevant defaults MUST minimize exposure, and missing or unverifiable security state MUST fail closed unless an approved design proves fail-open behavior is safer.

**Required evidence kinds:** configuration review; failure tests; risk decision.

#### SEC-011 — Security findings

**Level:** MUST

**Gate:** production

Security findings MUST record severity, affected version, evidence, disposition, owner, and remediation or approved exception; tool coverage limits MUST remain explicit.

**Required evidence kinds:** security audit; finding register; coverage statement.

#### SEC-012 — Incident readiness

**Level:** MUST

**Gate:** production

Projects with material security or availability impact MUST define detection, containment, evidence preservation, communication, recovery, and post-incident review responsibilities.

**Required evidence kinds:** incident plan; exercise evidence; contact ownership.

### SUP — Supply chain

Dependency identity, integrity, provenance, licensing, vulnerability, and build evidence.

#### SUP-001 — Third-party inventory

**Level:** MUST

**Gate:** release

Every third-party code, service, model, asset, tool, and runtime required to build, test, deliver, or operate the project MUST have an owned inventory or a justified exclusion.

**Required evidence kinds:** dependency inventory; SBOM; service inventory.

#### SUP-002 — Exact identity and integrity

**Level:** MUST

**Gate:** release

Third-party components and release-critical tools MUST be identified by exact version or immutable reference and verified by integrity or provenance evidence.

**Required evidence kinds:** lockfile; hash record; provenance record.

#### SUP-003 — Authoritative provenance

**Level:** MUST

**Gate:** release

Third-party material MUST come from a recorded authoritative source or an approved mirrored source whose correspondence is verified.

**Required evidence kinds:** source record; mirror verification.

#### SUP-004 — License decision

**Level:** MUST

**Gate:** release

Each third-party component MUST have a verified license and a documented decision covering intended use, modification, distribution, disclosure, attribution, and commercial constraints.

**Required evidence kinds:** license text; license decision; attribution record.

#### SUP-005 — Vulnerability evidence

**Level:** MUST

**Gate:** production

Applicable dependencies, runtimes, images, and artifacts MUST have current vulnerability evidence that identifies coverage limits and affected exact versions.

**Required evidence kinds:** vulnerability report; coverage statement; finding disposition.

#### SUP-006 — Controlled updates

**Level:** MUST

**Gate:** delivery

Dependency and tool updates MUST be reviewed, verified, and intentionally adopted; production execution MUST NOT silently acquire unreviewed versions.

**Required evidence kinds:** update policy; locked resolution; update review.

#### SUP-007 — Build provenance

**Level:** MUST

**Gate:** release

Release artifacts MUST be traceable to source, build instructions, inputs, tool identities, and the environment or service that produced them.

**Required evidence kinds:** build record; artifact manifest; provenance attestation.

#### SUP-008 — Dependency minimization

**Level:** SHOULD

**Gate:** review

The project SHOULD avoid unnecessary third-party components and SHOULD record the value and replacement strategy for material dependencies.

**Required evidence kinds:** dependency review; replacement strategy.

### DAT — Data and state

Ownership, identity, validation, migration, retention, backup, export, and deletion.

#### DAT-001 — Authoritative state

**Level:** MUST

**Gate:** review

For every material state domain, the project MUST identify the authoritative source, writer ownership, identity model, and consistency expectations.

**Required evidence kinds:** state inventory; ownership model.

#### DAT-002 — Schema and format

**Level:** MUST

**Gate:** release

Persistent or exchanged data MUST have versioned, validated formats or schemas and defined compatibility behavior.

**Required evidence kinds:** schema; format specification; validation results.

#### DAT-003 — Stable identity

**Level:** MUST

**Gate:** review

Material entities and records MUST use stable identities appropriate to their lifecycle rather than mutable display values.

**Required evidence kinds:** identity design; data tests.

#### DAT-004 — Validated writes

**Level:** MUST

**Gate:** release

Data changes MUST validate complete intended input before irreversible writes and MUST define atomicity, idempotency, retry, and partial-failure behavior.

**Required evidence kinds:** write-path tests; transaction design; failure tests.

#### DAT-005 — Migration and rollback

**Level:** MUST

**Gate:** delivery

Data-format or state transitions MUST have versioned migration, compatibility, validation, and rollback or recovery procedures.

**Required evidence kinds:** migration procedure; migration tests; rollback evidence.

#### DAT-006 — Retention and deletion

**Level:** MUST

**Gate:** production

Retained state MUST have explicit retention, archival, legal-hold where applicable, deletion, and verification rules.

**Required evidence kinds:** retention schedule; deletion procedure; verification evidence.

#### DAT-007 — Export and portability

**Level:** MUST

**Gate:** delivery

Owner-controlled data and material configuration MUST have a documented, usable export path in a sufficiently described format.

**Required evidence kinds:** export procedure; export sample; restore or import evidence.

#### DAT-008 — Backup and restoration

**Level:** MUST

**Gate:** production

Where state loss is material, backups MUST define scope, protection, integrity, retention, separation, recovery objectives, and successful restoration evidence.

**Required evidence kinds:** backup policy; backup integrity record; restoration exercise.

### REL — Release

Versioning, change records, immutable references, artifacts, and gates.

#### REL-001 — Unique version

**Level:** MUST

**Gate:** release

Every release MUST have a unique, monotonically progressing version under a documented versioning policy; published versions MUST NOT be reused.

**Required evidence kinds:** version file; version policy; release history.

#### REL-002 — Change record

**Level:** MUST

**Gate:** release

Every release MUST have a human-readable change record describing material additions, changes, fixes, removals, security impact, compatibility, and actual verification state.

**Required evidence kinds:** changelog; release notes.

#### REL-003 — Immutable source reference

**Level:** MUST

**Gate:** release

Every release MUST have an immutable source reference that resolves to the
intended integrated source state. The project's release reference MUST define
whether that reference is an annotated tag or another integrity-protected
native release reference.

**Required evidence kinds:** immutable reference; release policy.

#### REL-004 — Release record

**Level:** MUST

**Gate:** release

Every immutable release reference MUST have a durable release record containing version, scope, verification, security state, compatibility, upgrade, and rollback information.

**Required evidence kinds:** release record; release notes.

#### REL-005 — Artifact correspondence

**Level:** MUST

**Gate:** delivery

Distributed artifacts and source archives MUST be verified to correspond to the immutable source reference, declared version, and recorded build inputs.

**Required evidence kinds:** artifact hash; artifact manifest; source correspondence.

#### REL-006 — Release gate

**Level:** MUST

**Gate:** release

A release MUST NOT proceed while an applicable mandatory control is FAIL, NOT_RUN, BLOCKED, PRIOR_PASS, or DISCOVERED, or while required evidence is missing, stale, or contradictory.

**Required evidence kinds:** conformance report; gate decision.

#### REL-007 — Upgrade and rollback

**Level:** MUST

**Gate:** delivery

A release MUST describe required upgrade, migration, compatibility, and rollback or recovery actions at a level appropriate to its impact.

**Required evidence kinds:** upgrade guide; rollback procedure; compatibility note.

#### REL-008 — Milestone traceability

**Level:** MUST

**Gate:** release

The version, change record, review object, integrated commits, immutable reference, release record, and artifacts MUST be mutually traceable.

**Required evidence kinds:** traceability record; remote references; artifact manifest.

#### REL-009 — Truthful readiness state

**Level:** MUST

**Gate:** production

Development-ready, releasable, deliverable, production-ready, and retired states MUST be reported separately and MUST reflect the strictest unresolved applicable gate.

**Required evidence kinds:** readiness decision; conformance report; open findings.

### OPS — Operations

Delivery, observability, continuity, support, incidents, and retirement.

#### OPS-001 — Delivery model

**Level:** MUST

**Gate:** delivery

The project MUST define how supported consumers obtain, configure, update, verify, and remove or retire the software.

**Required evidence kinds:** delivery procedure; consumer guide.

#### OPS-002 — Environment ownership

**Level:** MUST

**Gate:** production

Supported environments, configuration authority, credentials, external services, and differences between development, verification, and operational use MUST be documented.

**Required evidence kinds:** environment inventory; configuration record.

#### OPS-003 — Observability

**Level:** MUST

**Gate:** production

Where ongoing operation matters, the project MUST define health, logging, metrics, tracing, alerting, evidence retention, and sensitive-data boundaries proportionate to risk.

**Required evidence kinds:** observability plan; alert evidence; log review.

#### OPS-004 — Operational limits

**Level:** MUST

**Gate:** production

Operational capacity, quotas, dependencies, maintenance, degraded behavior, and stop conditions MUST be known where they can affect supported use.

**Required evidence kinds:** operational limits; capacity evidence; runbook.

#### OPS-005 — Continuity and recovery

**Level:** MUST

**Gate:** production

Projects with continuity obligations MUST define recovery objectives, responsibilities, dependencies, procedures, communication, and exercised restoration evidence.

**Required evidence kinds:** continuity plan; recovery exercise; recovery objectives.

#### OPS-006 — Support and maintenance

**Level:** MUST

**Gate:** delivery

The project MUST define supported versions, issue intake, severity, response ownership, update policy, and end-of-support behavior appropriate to its distribution model.

**Required evidence kinds:** support policy; maintenance policy; issue process.

#### OPS-007 — Operational change safety

**Level:** MUST

**Gate:** production

Operationally material changes MUST have controlled rollout, validation, stop, rollback or recovery, and communication procedures proportionate to risk.

**Required evidence kinds:** rollout plan; rollback evidence; change record.

#### OPS-008 — Retirement

**Level:** MUST

**Gate:** retirement

Retirement MUST address consumer notice, migration or export, access revocation, dependency shutdown, retention, secure deletion, evidence preservation, and ownership transfer or archive.

**Required evidence kinds:** retirement plan; migration evidence; revocation evidence; archive record.

### DOC — Documentation

Required knowledge, evidence quality, freshness, consistency, and handoff.

#### DOC-001 — Project entry point

**Level:** MUST

**Gate:** delivery

The project MUST provide an authoritative entry point describing purpose, ownership, setup, supported use, verification, delivery, and where deeper records are maintained.

**Required evidence kinds:** project readme; documentation index.

#### DOC-002 — Reproducible instructions

**Level:** MUST

**Gate:** delivery

Build, verification, delivery, upgrade, backup, restoration, and retirement instructions MUST be exact, current, and executable for each applicable project lifecycle stage.

**Required evidence kinds:** operating instructions; execution evidence.

#### DOC-003 — Evidence provenance

**Level:** MUST

**Gate:** release

Evidence MUST identify the subject version, command or method, environment, time, result, coverage, limitations, and immutable or integrity-protected location.

**Required evidence kinds:** evidence manifest; hash record; execution record.

#### DOC-004 — Evidence freshness

**Level:** MUST

**Gate:** release

Evidence MUST be current for the version and gate it supports; historical or discovery-only results MUST remain visibly distinct from current execution.

**Required evidence kinds:** evidence timestamps; version linkage; result state.

#### DOC-005 — Consistency

**Level:** MUST

**Gate:** release

Versions, scope, controls, readiness, findings, commands, paths, links, and artifact identities MUST be internally consistent across human and machine records.

**Required evidence kinds:** consistency check; review record.

#### DOC-006 — No unsupported claims

**Level:** MUST

**Gate:** release

Documentation and reports MUST NOT claim execution, coverage, safety, compliance, readiness, or completion beyond the exact evidence available.

**Required evidence kinds:** claim review; evidence map.

#### DOC-007 — Knowledge transfer

**Level:** MUST

**Gate:** delivery

Material project knowledge required to continue, verify, recover, migrate, support, or retire the project MUST be recorded outside a single person's memory.

**Required evidence kinds:** handoff record; runbook; ownership inventory.

#### DOC-008 — Decision history

**Level:** SHOULD

**Gate:** review

Material requirement, design, risk, exception, and release decisions SHOULD retain rationale, alternatives, approver, and consequences.

**Required evidence kinds:** decision record; approval history.

## 7. Conditional profiles

A conditional profile adds controls for a capability or risk that is not universal. Profiles may cover interaction surfaces, network exposure, persistent state, deployment models, privileged automation, model use, sensitive or regulated data, safety impact, third-party extension ecosystems, distribution obligations, regional behavior, or continuity needs.

A profile MUST declare its identifier, version, trigger conditions, added controls, evidence requirements, risk effect, compatibility, and retirement path. Profiles may strengthen but MUST NOT weaken or reinterpret universal controls. Project-specific rules remain in the consumer repository or profile, not in this universal core.

## 8. Evidence semantics and freshness

Evidence states are exact:

- `PASS`: executed against the relevant version and passed.
- `FAIL`: executed and failed.
- `NOT_RUN`: applicable but not executed.
- `BLOCKED`: applicable but prevented by a recorded external condition.
- `NOT_APPLICABLE`: excluded through an approved, evidenced applicability decision.
- `PRIOR_PASS`: historical evidence that was not rerun for the current subject.
- `DISCOVERED`: a check exists or was enumerated but did not execute.

Only `PASS` and approved `NOT_APPLICABLE` satisfy a release gate. Evidence
must be fresh enough for the version, environment, and decision it supports.
Evidence may be reused from a project baseline only when the assessed scope,
code, inputs, dependencies, environment, and decision are unchanged and no
documented invalidation condition has occurred. Changes to data schemas,
permissions, migrations, dependencies, or other risk-bearing inputs require
reverification. Missing, stale, contradictory, unverifiable, discovery-only,
or historical evidence fails closed; `PRIOR_PASS` is never current `PASS`.

## 9. Change, review, integration, and release

Tracked changes are isolated from the protected default branch or an approved
equivalent workspace. Focused commits preserve intentional scope. A durable
PR/MR or equivalent review object for a mutating change records purpose,
exactly one canonical change type, exactly one R1-R4 change risk with
rationale, optional controlled flags, verification, findings, and disposition.
Read-only reviews do not fill a change type. Projects map the canonical
classifications to durable native metadata such as labels or fields without
changing their meaning.

The review gate fails closed when a required type or risk is missing, when more than one primary type or risk is selected, when a classification is unknown, when review metadata contradicts the change record, or when the native classification cannot be inspected. The `blocked` flag reports a blocker and cannot turn a blocked gate into a pass.

Every formal release has a unique version, human change record, immutable
source reference, release record, and artifact correspondence evidence as
defined by the project's release reference. Before release, inspect the
project's actual forge and default branch. A project policy may require an
explicit merge into `main`, an annotated tag, and a GitHub Release; those remain
project requirements when declared, but they are not universal assumptions.
Published commits, references, reviews, and audit evidence are not silently
rewritten.

## 10. Delivery, production, and retirement gates

Release, delivery, production, and retirement are separate decisions. Passing a development or release check does not imply production readiness. A gate remains blocked while any applicable mandatory control has `FAIL`, `NOT_RUN`, `BLOCKED`, `PRIOR_PASS`, or `DISCOVERED`, while an exception is expired or unapproved, or while evidence is missing, stale, or contradictory.

Retirement preserves required evidence, supports consumer migration or export, revokes access, shuts down dependencies, applies retention and deletion rules, and records final ownership or archival status.

## 11. Conformance and audit

A conforming project maintains a versioned project profile, applicability map,
conformance record, evidence references, open findings, exceptions, and
current gate decisions. A daily review or ordinary change may report a bounded
delta against the project baseline. First adoption or a full-standard audit
evaluates every catalog control at the scope of the claimed decision; an
explicit full-conformance claim is treated as a full-standard audit. No report
may imply complete conformance from partial control coverage.

Conformance levels are:

- **Change conformant**: requirements, design, isolation, and implementation evidence satisfy the change gate.
- **Review conformant**: review-gate controls and findings are resolved or truthfully blocked.
- **Release conformant**: every applicable mandatory release control is `PASS` or approved `NOT_APPLICABLE`.
- **Delivery conformant**: distributed artifacts and consumer procedures are verified.
- **Production conformant**: all applicable production controls and operational evidence pass.
- **Retirement conformant**: retirement controls and evidence pass.

An audit must map each claimed requirement to direct evidence, verify that the evidence covers the same version and scope, identify tool or method limitations, and reject unsupported conclusions. Failure to find a problem is not proof that the control passed.
