# Repository administration

The three long-lived branches are `dev`, `prod`, and `main`.
The initial repository snapshot seeds all three. Subsequent work follows the
review and promotion flow in CONTRIBUTING.md.

## Required branch settings

Apply these settings to all three branches:

- Require a pull request and one approving teammate review.
- Dismiss stale approvals and require resolution of review conversations.
- Require the `checks` and `branch-policy` status checks.
- Require the branch to be current with its target before merging.
- Apply protection to administrators.
- Disallow force pushes and branch deletion.
- Allow merge commits so milestone promotions preserve ancestry.

Work-item MRs use squash merge into `dev`; milestone promotions use merge
commits. Keep automatic branch deletion off so promotion MRs cannot remove a
long-lived source branch. Delete merged feature branches explicitly.

The `branch-policy` check permits feature branches into `dev`, `dev` into
`prod`, and `prod` into `main`. A reviewed `main` to `dev` synchronization
is allowed solely to carry promotion ancestry forward. It is not a route for
feature development.

## Availability

This is a public repository, as chosen by the owner. GitHub supports branch
protection for it on the current plan. Verify the settings above through the
repository settings or API after any account, workflow, or visibility change.
Changing it to private may require an upgraded plan to retain these protections.

## Team access

The repository owner adds teammates with write access after confirming their GitHub usernames.
No collaborator invitations or permission changes are implied by creating
issues. Members need suitable repository access to claim issues and open MRs.
