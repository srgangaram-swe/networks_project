# Semester roadmap

Dates below are planning targets based on the proposal's semester sequence, not
confirmed course deadlines. Issue #4 records the rubric and official dates.
Do not compress verification to meet a target; revise the plan with the team.

| Milestone | Planning target | Completion outcome |
|---|---|---|
| [M0: Repository foundation](https://github.com/srgangaram-swe/networks_project/milestone/1) | 2026-09-14 | Establish the shared repository, tested configuration contract, CI, protected branches, and semester work plan. |
| [M1: Protocol and controlled testbed](https://github.com/srgangaram-swe/networks_project/milestone/2) | 2026-09-27 | Freeze measurement choices and show an isolated Linux bottleneck with verified queue policies and safe cleanup. |
| [M2: Workloads and validated pilot](https://github.com/srgangaram-swe/networks_project/milestone/3) | 2026-10-11 | Complete bounded foreground/background workloads, the randomized runner, and evidence validation. |
| [M3: Primary experiment](https://github.com/srgangaram-swe/networks_project/milestone/4) | 2026-10-25 | Collect ten runs per loaded condition and matching unloaded baselines, with recorded validity, interleaved policies, and first run-level uncertainty estimates. |
| [M4: Sensitivity and independent replication](https://github.com/srgangaram-swe/networks_project/milestone/5) | 2026-11-08 | Complete one-factor sensitivity checks, bounded-priority validation, and independent replication. |
| [M5: Frozen evidence and report draft](https://github.com/srgangaram-swe/networks_project/milestone/6) | 2026-11-22 | Freeze the primary dataset, reproduce figures, review claims, and finish report and presentation drafts. |
| [M6: Clean reproduction and final delivery](https://github.com/srgangaram-swe/networks_project/milestone/7) | 2026-11-29 | Reproduce the documented path from a clean checkout, rehearse the demo, resolve review findings, and release the final report and evidence package. |

## Work items

The four core implementation and integration items are assigned to Saif. All
other work is open for teammates to claim. The repository setup item closes once
its evidence is verified. Dependencies and detailed acceptance criteria live in
the issues.

### M0: Repository foundation

- [#1: Set up the repository, checks, and protected workflow](https://github.com/srgangaram-swe/networks_project/issues/1)

### M1: Protocol and controlled testbed

- [#2: Freeze the experiment protocol and component contracts](https://github.com/srgangaram-swe/networks_project/issues/2) (Saif)
- [#3: Confirm equipment, Linux support, and testbed access](https://github.com/srgangaram-swe/networks_project/issues/3)
- [#4: Confirm the grading rubric and related-work comparison](https://github.com/srgangaram-swe/networks_project/issues/4)
- [#5: Build isolated topology setup, inspection, and cleanup](https://github.com/srgangaram-swe/networks_project/issues/5)
- [#6: Implement and verify the four queue-policy profiles](https://github.com/srgangaram-swe/networks_project/issues/6)

### M2: Workloads and validated pilot

- [#7: Implement the paced foreground client and responder](https://github.com/srgangaram-swe/networks_project/issues/7) (Saif)
- [#8: Implement bulk-load control and workload validation](https://github.com/srgangaram-swe/networks_project/issues/8)
- [#9: Implement the randomized trial runner and run lifecycle](https://github.com/srgangaram-swe/networks_project/issues/9) (Saif)
- [#10: Implement run-bundle validation and data-quality checks](https://github.com/srgangaram-swe/networks_project/issues/10)
- [#11: Run the pilot and approve readiness for full collection](https://github.com/srgangaram-swe/networks_project/issues/11)

### M3: Primary experiment

- [#12: Collect and validate unloaded per-policy baselines](https://github.com/srgangaram-swe/networks_project/issues/12)
- [#13: Collect the full randomized primary load matrix](https://github.com/srgangaram-swe/networks_project/issues/13)
- [#14: Implement run-level summaries, bootstrap intervals, and comparison plots](https://github.com/srgangaram-swe/networks_project/issues/14)

### M4: Sensitivity and independent replication

- [#15: Run one-factor checks of rate, RTT, and message size](https://github.com/srgangaram-swe/networks_project/issues/15)
- [#16: Verify bounded classification and resistance to priority abuse](https://github.com/srgangaram-swe/networks_project/issues/16)
- [#17: Perform an independent replication and investigate anomalies](https://github.com/srgangaram-swe/networks_project/issues/17)

### M5: Frozen evidence and report draft

- [#18: Freeze the dataset and audit every reported claim](https://github.com/srgangaram-swe/networks_project/issues/18)
- [#19: Write and review the methods, results, and limitations report](https://github.com/srgangaram-swe/networks_project/issues/19)
- [#20: Build the presentation and a safe one-command demonstration](https://github.com/srgangaram-swe/networks_project/issues/20)

### M6: Clean reproduction and final delivery

- [#21: Integrate the final reproducibility package and release candidate](https://github.com/srgangaram-swe/networks_project/issues/21) (Saif)
- [#22: Reproduce the release candidate from a clean checkout](https://github.com/srgangaram-swe/networks_project/issues/22)
- [#23: Complete the team rehearsal and submission checklist](https://github.com/srgangaram-swe/networks_project/issues/23)

## Release rule

One work item becomes one MR into dev. Only a completed milestone advances from
dev to prod, then from prod to main after release-candidate validation. Every
milestone ends with a completion summary and reviewable evidence. A failed
feasibility target is a reportable result, not a failed course project by itself.
