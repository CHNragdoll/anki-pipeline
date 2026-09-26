# Release Checklist

Release version: `<unique-version>`

Subject source reference: `<integrated-source-reference>`

Decision owner: `<authorized-owner>`

Project release reference: `<actual-forge-default-branch-and-release-policy>`

## Traceability

- [ ] Requirements, design, approval, plan, commits, verification, review, and
      release are mutually traceable.
- [ ] The actual forge and protected default branch were inspected; integration
      and publication follow the project's release reference.
- [ ] The version is unique and matches every authoritative project record.
- [ ] The human change record describes actual scope, compatibility, security,
      migration, rollback, and verification states.
- [ ] The change was integrated through the recorded PR/MR or equivalent and
      explicit integration history.

## Conformance

- [ ] Every universal control has one applicability record.
- [ ] Every applicable mandatory release control is `PASS`.
- [ ] Every `NOT_APPLICABLE` decision has current rationale and evidence.
- [ ] Every exception is owner-approved, in scope, unexpired, and linked to
      remediation; no exception is represented as a pass.
- [ ] No required evidence is `FAIL`, `NOT_RUN`, `BLOCKED`, `PRIOR_PASS`, or
      `DISCOVERED`.
- [ ] Evidence matches this version, scope, and required environment.
- [ ] Reused baseline evidence has matching scope, code, inputs, dependencies,
      environment, and decision; changed data, permissions, migrations, or
      dependencies were reverified.
- [ ] Security and supply-chain findings have truthful dispositions.

## Immutable release

- [ ] The project-policy-defined immutable source reference points to the
      intended integrated source state.
- [ ] The release record matches the immutable reference.
- [ ] Distributed artifacts and source archives correspond to the reference.
- [ ] Build inputs, tools, provenance, and artifact integrity are recorded.
- [ ] Upgrade, migration, compatibility, rollback, and recovery instructions
      are complete where applicable.

## Readiness

- [ ] Release, delivery, production, and retirement states are reported
      separately.
- [ ] The release is not described as production-ready unless every applicable
      production control passes.
- [ ] Open blockers, exceptions, coverage limitations, and unsupported claims
      are visible.
