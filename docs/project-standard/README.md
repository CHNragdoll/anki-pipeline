# Universal Project Standard Package

Package version: 1.1.0

This directory is a portable engineering-governance package for any software
project. The normative requirements are independent of product domain,
programming language, framework, repository host, CI provider, architecture,
deployment model, and distribution model.

## Package contents

- [`PROJECT_STANDARD.md`](PROJECT_STANDARD.md): normative human-readable standard.
- [`control-catalog.json`](control-catalog.json): machine-readable universal controls and evidence
  vocabulary.
- [`schemas/`](schemas/): strict contracts for catalogs, project profiles, conformance,
  and exceptions.
- [`templates/`](templates/): human-readable project adoption, change, release, exception,
  and conditional-profile records.

A consumer may implement verification with any suitable technology. The
reference verifier in the source repository is a project-native adapter, not
a normative dependency.

The optional `scripts/verify_package.py` is a read-only package consistency
checker. When given a conformance record it checks the JSON Schema, full
catalog set, explicit `current` flags, evidence-to-record subject equality,
and declared gate/blocker invariants; it does not claim project conformance by
itself. It cannot establish external evidence freshness or authenticity,
source/commit/artifact correspondence, or project-specific invalidation
conditions; those require project audit evidence. Conformance-record
validation uses the package's JSON Schema and requires the `jsonschema` Python
package; without it the checker fails closed.

## Choose the smallest applicable task mode

Start with scope and authorization. A request to inspect, analyze, diagnose, or
report is `review` and is read-only unless the user separately authorizes a
change. The package recognizes these modes:

- `review`: bounded read-only inspection; do not fill a change type.
- `change`: code, configuration, documentation, or behavior work.
- `data`: imports, migrations, permissions, deletions, or other state work.
- `release`: an explicitly requested formal release.
- `adoption`: first adoption of the package by a project.
- `audit`: an explicitly requested full-standard audit.

Only mutating modes select one canonical change type and one change risk. Local
analysis or edits do not by themselves authorize push, PR/MR, merge, tag,
publication, or release.

Routine work uses the project's existing baseline plus the current delta. The
full 92-control catalog and one applicability decision per control are required
only for first adoption or a full-standard audit; an explicit full-conformance
claim is treated as a full-standard audit. They are not a per-task checklist.
A baseline result can be reused only when scope,
code, inputs, dependencies, environment, and decision match and no documented
invalidation condition occurred. Recheck changed data schemas, permissions,
migrations, dependencies, and other risk-bearing inputs. `PRIOR_PASS` is
historical evidence and never a current `PASS`.

Templates are record shapes for durable evidence, not a governance platform or
a requirement to fill JSON on every ordinary task.

## Risk and project policy

Project risk is the profile's overall impact and exposure; change risk is this
task's impact and exposure. Keep them separate. Small wording or CSS-only work
uses targeted checks. Ordinary behavior changes reproduce the issue or baseline
and run regression checks with the review required by project policy. Database,
permission, migration, and sensitive-state work needs stronger planning,
backup or recovery evidence where applicable, validation, and rollback
evidence. Formal release work follows the complete project release reference.

## Adopt the standard

### 1. Copy the package

Copy the complete `project-standard/` directory at one immutable released
version. Record its version and source reference. Do not copy only selected
controls, because omitted controls would disappear from applicability review.

This complete package copy is for first adoption or an explicitly requested
standard upgrade. It is not required for a routine review or change.

### 2. Create the project profile

Create a versioned project profile from
`templates/PROJECT_PROFILE.template.md`, plus a machine-readable record that
conforms to `schemas/project-profile.schema.json`.

Record:

- accountable owner and approval authorities;
- project purpose, supported use, consumers, and exclusions;
- repository, protected default branch, and PR/MR or equivalent review;
- environments, platforms, architecture, state, data classes, and trust
  boundaries;
- distribution, release, recovery, support, and retirement models;
- risk level and exact rationale;
- selected conditional profiles;
- one applicability decision per universal control;
- the verification matrix and any expiring exception identifiers.

### 3. Decide applicability

Every catalog control receives exactly one `applicable`, `not_applicable`, or
`exception` decision.

- `applicable` means the project must produce current control evidence.
- `not_applicable` requires specific rationale and evidence that the
  underlying capability or risk is absent.
- `exception` requires an approved, scoped, expiring exception record and
  never changes the control to `PASS`.

Do not use project size, schedule pressure, missing automation, or unfamiliar
tools as non-applicability evidence.

### 4. Select risk level and conditional profiles

Choose `R1`, `R2`, `R3`, or `R4` from actual impact, exposure, sensitivity,
privilege, continuity, safety, and regulatory obligations.

Conditional profiles add requirements for non-universal capabilities. They
may strengthen the standard but cannot weaken it. Store project-specific
implementation details in the local project profile or selected profile, not
in the universal control text.

### 5. Map the standard to local tools

Map neutral concepts to the project's actual systems:

| Universal concept | Project mapping to record |
| --- | --- |
| version control | authoritative system and repository |
| protected default branch | branch and enforcement mechanism |
| PR/MR or equivalent | durable review object |
| CI pipeline | commands, environment, and evidence location |
| immutable source reference | annotated tag or equivalent |
| release record | durable release system |
| artifact | distributed source, package, image, binary, data, or model |

The mapping changes tools, not outcomes. A project-native adapter may automate
schema and gate validation in its chosen language or CI system.

### Project-native release reference

Before a formal release, inspect the actual repository forge, protected default
branch, integration history, immutable source reference, release record, and
artifact publication rules. Record these in the project's `releasePolicy` and
follow them for that project. A project may explicitly require `main`, an
explicit merge commit, an annotated tag, and a GitHub Release; preserve those
requirements when declared. The universal package does not assume `main`,
GitHub, an English `CHANGELOG`, or an immediate push after every commit.

#### Classify every change review

Every PR, MR, or equivalent review object has exactly one primary change type
and exactly one risk level with rationale. The types are `bug`, `feature`,
`docs`, `refactor`, `maintenance`, and `security`; optional controlled flags
are `breaking-change`, `dependencies`, `migration`, `needs-manual-test`, and
`blocked`.

GitHub projects normally map these to one `type:*` label and one `risk:R1`-
`risk:R4` label. GitLab and other systems use equivalent durable metadata.
Missing, duplicate, unknown, or contradictory classifications block the review gate.
Optional controlled flags add context, and `blocked` cannot turn a blocked gate into a pass.

### 6. Build the verification matrix

For each behavior, boundary, and risk, record:

- exact scope and subject version;
- repeatable method or command;
- representative environment;
- expected evidence and state;
- coverage limitations;
- owner and durable result location.

The matrix is risk based. It does not require irrelevant test technologies,
but every omission needs an applicability decision that addresses the
underlying risk.

### 7. Assess conformance

Create a record from `templates/PROJECT_CONFORMANCE.template.md`. Use only the
exact evidence states:

`PASS`, `FAIL`, `NOT_RUN`, `BLOCKED`, `NOT_APPLICABLE`, `PRIOR_PASS`, and
`DISCOVERED`.

Only current `PASS` evidence and an approved, evidenced
`NOT_APPLICABLE` decision satisfy a release gate. A structurally valid record
can still report every gate as blocked.

### 8. Execute changes and releases

Use `templates/CHANGE.template.md` for each change and
`templates/RELEASE_CHECKLIST.template.md` for each release. Preserve
requirements, design approval, plan, isolated work, focused commits,
verification, review, explicit integration history, version, change record,
immutable reference, release record, and artifact correspondence.

For a continuing task, a safe existing branch or worktree may be reused when
its owner, base, and dirty state are known and preserved. Do not restart every
turn from `main` or overwrite unrelated work.

Delivery and production are separate decisions. Never describe a release as
production-ready when an applicable production control is unresolved.

### 9. Manage deviations

Use `templates/EXCEPTION.template.md` for every deviation. An expiring
exception contains the affected control, scope, risk, owner, approver,
approval time, start, expiry, and remediation. Expired, revoked, incomplete,
or unapproved exceptions block the affected gate.

### 10. Update the standard

Adopt a newer released package through the same reviewed change process:

1. compare control, schema, and semantic changes;
2. update the project profile and applicability map;
3. migrate machine records;
4. rerun project-native verification;
5. record compatibility, exceptions, and open findings;
6. release the project adoption change.

Do not edit universal controls inside a consumer project to make a failing
gate pass. Propose a versioned change to the master standard or record a local
conditional profile or exception.

## Non-normative applicability examples

These examples demonstrate risk selection; they do not add controls.

### Local utility

A local utility may have no network, persistent state, human interface, or
ongoing operation. It still records ownership, requirements, source history,
review, verification, dependency/license evidence, version, release, and
supported use. Missing capabilities receive evidenced non-applicability
decisions.

### Library

A library emphasizes API compatibility, supported runtimes, dependency
provenance, consumer integration evidence, upgrade policy, immutable
packages, and source-to-artifact correspondence. It does not invent
operational monitoring if it runs only inside consumer processes.

### Service

A service normally selects network, persistent-state, security, privacy,
observability, continuity, deployment, incident, and retirement profiles
according to actual exposure. Production admission is separate from the
ability to build a release.

### User-facing application

A user-facing application normally assesses accessibility, input and error
behavior, supported platforms, update delivery, local or remote state,
privacy, recovery, and support. A non-networked application does not inherit
network-service controls merely because it has a user interface.

## Artifact correspondence

For every formal release, verify that the immutable source reference, version,
change record, release record, source archive, generated artifacts, build
inputs, and recorded hashes all identify the same source state. Test
discovery, an old pass, or a successful upload is not correspondence proof.
