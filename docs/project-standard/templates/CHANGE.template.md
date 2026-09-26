# Change Record

## Identity

- Change ID: `<stable-change-id>`
- Owner: `<change-owner>`
- Task mode: `<review|change|data|release|adoption|audit>`
- Base reference: `<project-policy-defined-current-default-or-approved-equivalent>`
- Change branch or isolated workspace: `<reference-or-read-only-scope>`
- Intended project version: `<version>`
- Change type: `<omit for review; otherwise bug|feature|docs|refactor|maintenance|security>`
- Risk level: `<omit for review; otherwise R1|R2|R3|R4>`
- Risk rationale: `<omit for review; otherwise change-specific-risk-rationale>`
- Optional flags: `<zero-or-more-canonical-flags>`
- Native classifications: `<durable-review-metadata>`

## Authorization and evidence scope

- Authorized actions: `<read-only|local edits|data operation|formal release actions>`
- Exclusions: `<explicitly out-of-scope-actions-and-boundaries>`
- Baseline evidence: `<project-baseline-reference-or-not-applicable>`
- Current delta: `<changed-scope-and-new-evidence>`
- Reuse decision: `<same-scope-code-inputs-dependencies-environment-and-no-invalidation-or-rerun-reason>`

## Problem and scope

- Problem or opportunity: `<implementation-independent-statement>`
- Included behavior: `<bounded-scope>`
- Excluded behavior: `<explicit-non-goals>`
- Affected consumers and boundaries: `<list>`
- Constraints and assumptions: `<validated-list>`

## Design and approval

- Alternatives considered: `<options-and-tradeoffs>`
- Selected design: `<boundaries-data-flow-failures-security>`
- Acceptance criteria: `<observable-criteria>`
- Required evidence: `<criterion-to-evidence-map>`
- Approved by and at: `<authority-and-ISO-8601-date-time>`

## Implementation

- Plan: `<durable-plan-location>`
- Commits: `<focused-commit-references>`
- Data or state transition: `<procedure-or-evidenced-not-applicable>`
- Compatibility impact: `<impact>`
- Rollback or recovery: `<exact-procedure>`

## Verification

For every applicable check in scope, record command or method, subject,
environment, execution time, evidence state, result, coverage, limitations, and
evidence location. A routine task may reference the baseline and record only
the current delta. `DISCOVERED` and `PRIOR_PASS` are not current execution;
changed data schemas, permissions, migrations, dependencies, or other
risk-bearing inputs require fresh evidence.

## Review and release

- PR/MR or equivalent: `<durable-review-location>`
- Findings and disposition: `<list>`
- Version and change record: `<references>`
- Integration reference: `<project-policy-defined-integration-record>`
- Immutable source reference: `<project-policy-defined-annotated-or-equivalent-reference>`
- Release record: `<location>`
- Artifact correspondence: `<hash-or-provenance-evidence>`
- Final gate states: `<change-review-release-delivery-production-retirement>`
