# Repository working agreements

## Main branch and owner consent

- All changes to `main` must go through a pull request. Required checks must pass against an up-to-date base, and review conversations must be resolved.
- Before merging **each PR**, obtain the human repository owner's explicit consent for that PR in the current conversation. State the PR number, actual changes, check results and relevant risks before asking.
- A passing CI run, agent review, the owner's authorship of the PR, or a general authorization to publish a release is **not** approval to merge a later PR. Never enable auto-merge in advance of the owner's consent.
- Consent covers the reviewed diff. Material changes after consent require renewed owner approval before merging.
- Do not force-push or delete `main`, bypass its protection, skip required checks, or weaken protection to make a PR mergeable. Changing protection requires separate, explicit owner authorization.
- This owner-consent requirement is an agent workflow rule. GitHub separately enforces PRs, checks and branch safety; it does not verify approval in this conversation.

## Scope and verification

- Questions, diagnosis and status checks are read-only unless the user requests changes. Preserve user changes, raw learning data and credentials.
- Keep changes scoped and verify the exact claim. Do not infer client acceptance from CI or package generation alone.
- Follow [the branch protection record](docs/BRANCH_PROTECTION.md) and the current [project profile](docs/PROJECT_PROFILE.md). A local edit does not authorize a push, PR, merge, tag or release by itself.
