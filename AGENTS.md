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

## Keep feedback and downloads at the top

- The first three README sections after the title and quick links must be `项目概述`, `下载 Anki 卡包`, and `反馈问题`, in that order. Keep these sections inside the `pinned-entrypoints` markers; do not insert feature updates, screenshots, architecture diagrams or historical logs above them.
- Keep mathematics first in the exam downloads and previews, followed by politics.
- Keep all current books in the shared download table, including politics. Each row links both its current complete package and its stable per-book Release. A book update changes its existing row and Release, rather than adding a dated release entry.
- Keep the feedback instructions and both Issue forms aligned with all supported subjects and entry points. Preserve separate required device, OS, software name, full software version and software-icon screenshot fields.

## Keep the homepage architecture current

- For every project update or delivery, check the complete architecture diagram against the code being delivered and update it together with the homepage README when the structure changes.
- Keep `assets/architecture/anki-pipeline-full-20261024.mmd`, its PNG and SVG exports, the README embed/download links, and the cited source revision consistent. Do not update only the prose while leaving an obsolete image.
- Preserve the full diagram, including all current groups, nodes and connections. Verify that the exported image is not clipped and that README asset links resolve before delivery.

## Generated storage retention

- Use disposable build workspaces. Do not retain a full dated web, media, database or package copy for every experiment by default.
- Publish one current resource set per book. Historical URLs may use lightweight aliases to it; they must not require retaining complete old web directories. Keep shared file bytes unchanged and verify full digests before deduplication.
- Preserve original inputs, learning state, current complete packages and an explicitly selected rollback set. Cold audit/history archives require complete decompression verification and a recorded restore map.
- Retirement must remain within the owner's authorized scope. Inventory active mounts and dependencies, stage and verify replacements before switching, then verify production before deleting superseded generated data. Report directory-size reduction separately from measured APFS free space.

- Cold archives and their restore manifests are one recovery unit. Keep durable manifests beside retained backups; a copy under disposable output is not sufficient. Restore archived legacy inputs before running a historical source-rebuild command.
