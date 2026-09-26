# Project Profile

Use this profile to map the universal standard to one project. Replace every
angle-bracket value with current project evidence. Do not remove a control
because it appears irrelevant; record a supported applicability decision.

Routine work uses this profile's baseline and records a bounded current delta.
The complete applicability map is required only for first adoption or a full
audit; an explicit full-conformance claim is treated as a full audit. It is not
rebuilt for every task.

## Identity

- `standardVersion`: `<universal-standard-version>`
- `projectVersion`: `<current-project-version>`
- `project`: `<stable-project-name>`
- `owner`: `<accountable-owner>`
- `purpose`: `<supported-purpose-and-explicitly-excluded-use>`
- `distributionModel`: `<how-consumers-receive-or-use-the-project>`

## Repository and change review

- `system`: `<version-control-or-forge-system>`
- `location`: `<authoritative-repository-location>`
- `defaultBranch`: `<protected-default-branch>`
- `reviewMechanism`: `<PR/MR-or-equivalent-durable-review>`
- `reviewClassification.changeTypes`: `<canonical-type-to-native-mapping>`
- `reviewClassification.riskLevels`: `<R1-R4-to-native-mapping>`
- `reviewClassification.flags`: `<canonical-flag-to-native-mapping>`

The mapping must preserve exactly one primary type and exactly one risk level
on every durable review object.

## Runtime and architecture

- `environments`: `<supported-environment-list>`
- `platforms`: `<supported-platform-list>`
- `architecture`: `<component-boundaries-and-interfaces>`
- `stateModel`: `<stateful-or-stateless-with-authoritative-state-details>`
- `dataClassification`: `<data-classes-or-evidenced-none>`
- `trustBoundaries`: `<external-and-internal-trust-boundaries>`

## Risk and conditional profiles

- `riskLevel`: `<R1|R2|R3|R4>`
- `riskRationale`: `<specific-impact-and-exposure-rationale>`
- `selectedProfiles`: `<capability-profile-identifiers-or-empty-list>`

## Applicability

Create exactly one record for every control:

```json
{
  "controlId": "GOV-001",
  "status": "applicable",
  "rationale": "The project has an accountable owner.",
  "evidence": [
    {
      "kind": "approval record",
      "location": "<durable-location>",
      "subject": "<version-or-scope>",
      "current": true
    }
  ]
}
```

Allowed `status` values are `applicable`, `not_applicable`, and `exception`.
Every record requires non-empty `rationale` and `evidence`. A
`not_applicable` record must prove the underlying capability or risk is
absent. An `exception` record must also contain `exceptionId`.

## Verification matrix

For every material behavior or risk, record:

- `id`: stable check identity;
- `scope`: behavior, boundary, version, and environment covered;
- `method`: repeatable test or review method;
- `command`: exact project-native execution command or manual procedure;
- `expectedEvidence`: durable result and required evidence state.

## Release and recovery

- `releasePolicy`: `<actual-forge-default-branch-integration-immutable-reference-release-and-artifact-policy>`
- `recoveryPolicy`: `<recovery-or-evidenced-non-applicability-policy>`
- `evidenceReusePolicy`: `<same-scope-code-inputs-dependencies-environment-decision-and-invalidation-conditions>`
- `exceptions`: `<active-exception-identifiers-or-empty-list>`
