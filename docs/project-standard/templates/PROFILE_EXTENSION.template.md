# Conditional Profile Extension

Use a conditional profile only for a capability or risk that is not universal.
The profile may add controls but cannot weaken or reinterpret universal ones.

## Identity

- Profile ID: `<stable-profile-id>`
- Version: `<semantic-version>`
- Owner: `<profile-owner>`
- Purpose: `<capability-or-risk-covered>`
- Trigger conditions: `<objective-selection-conditions>`
- Explicit non-triggers: `<conditions-that-do-not-select-this-profile>`

## Added controls

For each added control, define:

- stable profile-scoped ID;
- `MUST` or `SHOULD` level;
- implementation-neutral requirement;
- applicable gate;
- required evidence kinds;
- risk-level effect;
- compatibility with earlier profile versions.

## Adoption

- Required project-profile fields: `<list>`
- Required verification additions: `<list>`
- Required security or data additions: `<list>`
- Required release and operational additions: `<list>`
- Project-native implementation mapping: `<document-location>`

## Lifecycle

- Upgrade policy: `<compatibility-and-migration>`
- Deprecation policy: `<notice-and-evidence>`
- Retirement policy: `<control-and-data-disposition>`
- Replacement profile: `<identifier-or-none-with-rationale>`
