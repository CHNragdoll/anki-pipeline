# Project Conformance Record

Create one versioned record for the exact subject being assessed. This
conformance record is for first adoption, an explicitly requested full-standard
audit, or an explicit full-conformance claim (which is treated as a full audit).
A routine review or change should use the change/review record to capture its
relevant controls and current delta against the project baseline; it does not
need to recreate all 92 controls.

## Subject

- `standardVersion`: `<universal-standard-version>`
- `projectVersion`: `<subject-project-version>`
- `subject`: `<release-change-delivery-production-or-retirement-scope>`
- `generatedAt`: `<ISO-8601-date-time>`
- `sourceReference`: `<immutable-or-current-source-reference>`
- `assessmentMode`: `<adoption|audit>`
- `baselineReference`: `<project-baseline-or-not-applicable>`
- `deltaScope`: `<current-change-and-controls-assessed>`

## Evidence states

- `PASS`: executed against this subject and passed.
- `FAIL`: executed and failed.
- `NOT_RUN`: applicable but not executed.
- `BLOCKED`: applicable but prevented by a recorded condition.
- `NOT_APPLICABLE`: excluded by an approved, evidenced decision.
- `PRIOR_PASS`: historical evidence only.
- `DISCOVERED`: a check exists or was enumerated but did not run.

Only `PASS` and approved `NOT_APPLICABLE` satisfy a release gate.

## Control result

Create exactly one result for every catalog control. A package/project-native
verifier MUST reject missing or duplicate control IDs in a conformance record.

```json
{
  "controlId": "GOV-001",
  "state": "PASS",
  "assessedAt": "<ISO-8601-date-time>",
  "summary": "<bounded-factual-result>",
  "evidence": [
    {
      "kind": "<evidence-kind>",
      "location": "<durable-location>",
      "subject": "<same-version-and-scope>",
      "executedAt": "<ISO-8601-date-time>",
      "current": true,
      "summary": "<coverage-and-limitations>"
    }
  ]
}
```

A `PASS` requires current evidence with the same scope, code, inputs,
dependencies, environment, and decision; baseline evidence is reusable only
when the project's reuse policy says no invalidation condition occurred.
`NOT_APPLICABLE` requires
`applicabilityDecision` and evidence. Never convert an exception, old result,
or discovered check to `PASS`.

## Gate decisions

Record `change`, `review`, `release`, `delivery`, `production`, and
`retirement` separately. Each decision identifies `state`, `decidedAt`,
`decidedBy`, and a factual `summary`. A gate cannot be `PASS` when an
applicable control for that gate is `FAIL`, `NOT_RUN`, `BLOCKED`, `PRIOR_PASS`,
or `DISCOVERED`, or when required evidence is stale, missing, or contradictory.

## Open findings

Record stable finding ID, `LOW|MEDIUM|HIGH|CRITICAL` severity,
`OPEN|MITIGATED|ACCEPTED|CLOSED` state, summary, and owner.
