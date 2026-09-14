# Working on the project

## Claim an issue, then branch from dev

Assign an issue to yourself and read its acceptance criteria and dependencies.
If the scope is too large for one review, split the issue before coding.

```sh
git fetch origin
git switch dev
git pull --ff-only origin dev
git switch -c feat/12-short-description
```

Use `feat/`, `fix/`, `docs/`, or `test/` followed by the issue number and a
short description. Always start new work from `dev`, never from `prod` or
`main`. Keep unrelated cleanup out of the branch.

Run `sh scripts/check.sh` before pushing. Add unit tests for changed logic and
integration tests for the boundary it crosses. A parser change needs malformed
input tests; a topology change needs a cleanup and failure-path test on the
isolated Linux testbed.

```sh
git push -u origin feat/12-short-description
gh pr create --base dev --title "feat: describe the change"
```

GitHub calls an MR a pull request. Use one MR per work item, link the issue,
and request review from a teammate. Include exact test commands, observed
outcomes, risks, and rollback steps. Performance changes need measurements,
not only a passing test suite.

Resolve conflicts on the work branch by merging the latest `origin/dev`,
then rerun checks. Do not rewrite a branch somebody else is using or force-push
a shared branch. Use squash merge for work-item MRs into `dev`.

After merging, verify the linked issue is actually closed with a completion
summary and evidence. GitHub's automatic closing keywords may not close an
issue until its change reaches the default branch, so check rather than assume.
Delete only the merged short-lived branch. Keep `dev`, `prod`, and `main`.

## Reviews

A teammate should approve the change after the latest substantive push.
Resolve review conversations and keep required CI green. Do not bypass a
failing check, remove a test to make the build pass, or approve your own MR.
Use your own Git identity and credit actual contributions.

The language is a component-level choice. Python is the initial configuration
and tooling language. A new Rust or C++ component must bring its locked build,
format/lint commands, tests, and CI job in the same MR. Bash must pass ShellCheck.
Discuss other languages in an issue or decision record first.

## Milestone promotions

A release manager coordinates the following only after the milestone's required
issues are complete and their evidence is reviewed:

1. Confirm the milestone checklist and record the candidate source SHA.
2. Open a promotion MR from `dev` to `prod`, with the milestone number and
   links to checks, evidence, limitations, and rollback instructions.
3. Use a merge commit, not squash or rebase, so branch ancestry stays intact.
4. Validate the `prod` candidate using the same source and configurations.
5. Open and merge `prod` to `main` with a merge commit after that validation.
6. Verify the release and issue states, record the release SHA, and close the milestone.
7. Bring promotion ancestry back into `dev` through a reviewed maintenance MR
   if needed before the next milestone. Do not develop features on release branches.

Never promote `dev` directly to `main`. Do not include new implementation in
promotion MRs. A documented deferment requires team agreement and must not hide
a failed acceptance criterion. There is no automatic deployment to lab equipment.

The branch-policy CI check verifies allowed MR source/target pairs. Milestone
completion and reproduction evidence still need human review. See
[repository administration](docs/repository-administration.md) for the
server-side protection requirements.

## Completion checklist

- The issue's acceptance criteria are met, including negative and boundary cases.
- Unit and integration tests pass; new runtime boundaries have their own tests.
- Relevant hardware checks ran on an isolated testbed and identify the environment.
- Documentation, units, schema versions, and run provenance match the code.
- No secrets, local notes, packet captures, caches, or unreviewed raw runs are staged.
- Results include uncertainty and unfavorable outcomes. No fabricated measurements.
- Any changed assumptions or limitations are documented.
- The MR explains how to undo the change without damaging unrelated host state.
