# Standard Exception

An exception is a visible, time-bounded risk decision. It never changes a
control result to `PASS`.

```json
{
  "id": "EXC-<stable-identifier>",
  "controlId": "<ABC-001>",
  "scope": "<exact-version-component-environment-and-gate>",
  "risk": "<impact-likelihood-and-affected-consumers>",
  "owner": "<remediation-owner>",
  "approvedBy": "<authorized-risk-owner>",
  "approvedAt": "<ISO-8601-date-time>",
  "startsAt": "<ISO-8601-date-time>",
  "expiresAt": "<ISO-8601-date-time>",
  "remediation": "<specific-actions-owner-and-completion-evidence>",
  "status": "ACTIVE",
  "evidence": [
    "<finding-risk-review-and-approval-locations>"
  ]
}
```

Allowed status values are `ACTIVE`, `EXPIRED`, `REVOKED`, and `CLOSED`.
Expiration is evaluated from `expiresAt`, not from the label alone. Extending
an exception requires a new owner decision and preserved history.
