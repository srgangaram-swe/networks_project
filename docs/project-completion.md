# Project completion checklist

Repository review: November 11, 2026. The NucBox has not been set up yet.
This checklist distinguishes a working initial software path from the evidence
still needed to finish the experiment, report, and demonstration.

## Executable initial path

The integration branch for this work preserves the pilot implementation and
Jonathan Lloyd's original analysis commit. Neither teammate's branch is rewritten.
Chris Ong's C++ TCP prototype is also retained with its original history. Its
build, exact-frame validation, loopback binding, bounded harness, sanitizer
checks, and real-socket regressions are documented in
[the prototype guide](../experiments/cpp_network_testing/README.md).

| Stage | Code and current scope |
|---|---|
| Install | scripts/setup_nucbox.sh installs Ubuntu tools, the local environment, analysis dependencies, and runs checks |
| Inspect | scripts/inspect_hardware.py reads versions, drivers, link state, and module evidence |
| Isolate | src/topology_runtime.py journals owned client/router/server namespaces and cleans them up |
| Generate traffic | src/foreground_io.py and src/bulk.py run paced UDP requests and reverse TCP demand |
| Collect | scripts/campaign.py executes the recorded diagnostic schedule with retained attempts and manifests |
| Check and export | scripts/validate_bundle.py and scripts/export_pilot.py verify observations and export outcomes with hashes |
| Analyze | analysis/policy_comparison.py matches block baselines, bootstraps policy comparisons, and reports missing or censored quantities |
| Explore ML | analysis/run_clustering.py fits standardized K-means and records PCA and t-SNE projections |
| Run together | scripts/nucbox_experiment.py runs the initial 16-trial namespace pilot through analysis |

Use the [NucBox guide](nucbox-setup.md) after first boot. Keep the Mac as the
development and control machine. No physical NIC is selected or reconfigured
by the namespace backend. This initial experiment is a virtual testbed on the
NucBox; it does not measure the adapters or cables.

## Before primary collection

1. Complete #2 and #3: verify the actual NucBox model, Linux, kernel, qdiscs,
   drivers, access, booking, and inventory. Review the candidate protocol with
   the team and record accepted tool versions and numerical tolerances. For a
   physical three-machine layout, arrange the two Linux endpoint computers and
   implement/review physical-interface ownership and rollback. The two received
   cables cover the active links; the third requested cable was a spare.
2. Finish #9's measurement timing. The iperf reporting workaround preserves
   warmup and checked receiver totals, but the bulk and foreground windows are
   still separate. Measure and reconcile actual boundaries before using the
   values as synchronized primary comparisons. Do not split bytes proportionally
   across overlapping intervals or relabel these windows as aligned.
3. Finish #6 and #11 calibration on the actual testbed. Verify the effective
   bottleneck, delay placement, offloads, CUBIC/ECN, queue counters, sender
   overhead, and bounded-priority behavior. The last hosted pilot retained
   3.78% unsent slots and lower CAKE TCP goodput. Investigate and retain these
   results; they cannot be turned into passing targets by selective exclusion.
4. Review and enable the full collector for #12 and #13. The current executor
   deliberately caps campaigns at 40 cells; configs/primary.json plans 280.
   Full collection needs reviewed readiness criteria, a larger retained attempt
   ledger, and bounded export batches rather than simply removing the guard.
   The planned matrix is 40 unloaded and 240 loaded runs, with ten paired blocks
   and sixty measured seconds per run. At 500 requests/s, it produces 8.4 million
   measurement slots, so the current 200,000-row export limit needs batching.
5. Complete #14 against the frozen primary schema and independently review the
   estimator and plots. The statistical and ML workflow now exists and is tested
   on diagnostic inputs. Exploratory clusters or t-SNE separation do not approve
   the dataset, establish causality, or replace the planned policy comparison.

## Finish the course deliverables

Confirm the official rubric and report, presentation, and demonstration dates
for #4. Milestone dates in GitHub are planning targets. Complete the sensitivity
checks, priority-abuse validation, and independent replication in #15 through
#17. Freeze the dataset and audit claims for #18, including unfavorable outcomes,
timeouts, omitted send slots, and every failed attempt.

Write and review methods, results, and limitations for #19; prepare and rehearse
the presentation and safe demo for #20. Reproduce from a clean checkout and
finish the release/submission checklist for #21 through #23. Integration into
dev, then validated promotions to prod and main, should preserve the source and
evidence ancestry. A failed feasibility target is still a reportable result.

All diagnostic manifests and analysis reports remain ineligible for primary
collection. No issue is complete merely because its code has been pushed.
