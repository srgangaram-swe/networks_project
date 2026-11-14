# Project completion checklist

Repository review: November 14, 2026. The NucBox has not been set up yet.
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
| Generate traffic | src/foreground_io.py, src/foreground_tcp.py and src/bulk.py run paced UDP or framed TCP requests and reverse bulk TCP demand |
| Collect | scripts/campaign.py executes the recorded diagnostic schedule with retained attempts and manifests |
| Check and export | scripts/validate_bundle.py and scripts/export_pilot.py verify observations and export outcomes with hashes |
| Analyze | analysis/policy_comparison.py matches block baselines, bootstraps policy comparisons, and reports missing or censored quantities |
| Explore ML | Standardized K-means, Ward and DBSCAN retain PCA/t-SNE views and geometry scores; Ridge/Lasso use nested held-out blocks when at least six blocks exist |
| Observe TCP | src/tcp_observation.py and src/transport.py keep passive ACK candidates and Linux socket counters separate from application outcomes |
| Forecast | Optional shadow ridge models predict future application RTT/timeout cohorts using past events and delayed labels, without changing policy |
| Run together | scripts/run_pipeline.sh selects local simulation, namespaces or configured physical Linux roles, UDP/TCP and optional forecasts, then runs checked export and analysis |

Use the [NucBox guide](nucbox-setup.md) after first boot. Keep the Mac as the
development and control machine. No physical NIC is selected or reconfigured
by the namespace backend. This initial experiment is a virtual testbed on the
NucBox; it does not measure the adapters or cables.

The [topology guide](topology-pipeline.md) describes the physical profile,
dedicated-interface guards and rollback. Hosted SSH/veth checks exercise that
code on one disposable Linux kernel. They do not validate the actual equipment.
Local mode produces 48 toy trials and 240,000 slots; those results test software
and remain separate from measured evidence.

## Before primary collection

1. Complete #2 and #3: verify the actual NucBox model, Linux, kernel, qdiscs,
   drivers, access, booking, and inventory. Review the candidate protocol with
   the team and record accepted tool versions and numerical tolerances. For a
   physical three-machine layout, arrange the two Linux endpoint computers and
   verify physical-interface ownership and rollback on the chosen hardware. The two received
   cables cover the active links; the third requested cable was a spare.
2. Finish #9's measurement timing. The iperf reporting workaround preserves
   warmup and checked receiver totals, but the bulk and foreground windows are
   still separate. Measure and reconcile actual boundaries before using the
   values as synchronized primary comparisons. Do not split bytes proportionally
   across overlapping intervals or relabel these windows as aligned.
3. Finish #6 and #11 calibration on the actual testbed. Verify the effective
   bottleneck, delay placement, offloads, CUBIC/ECN, queue counters, sender
   overhead, and bounded-priority behavior. Hosted run
   [43108538117](https://github.com/srgangaram-swe/networks_project/actions/runs/43108538117)
   retained 2,900 of 80,000 slots as unsent and CAKE goodput below the 90%
   retention target. Investigate and retain these
   results; they cannot be turned into passing targets by selective exclusion.
4. Review readiness for #12 and #13 before primary collection. The explicit
   diagnostic-matrix mode can execute the 280 planned cells, retains up to three
   attempts per cell, and exports bounded batches with a full attempt ledger.
   The matrix is 40 unloaded and 240 loaded runs, with ten paired blocks and
   sixty measured seconds per run. Its 8.4 million measurement slots produce
   47 bounded export batches. This execution support does not resolve timing,
   calibration, or protocol acceptance. All manifests remain diagnostic.
5. Independently review the estimator and plots when the primary schema and
   dataset are frozen. The #14 statistical implementation and exploratory ML
   workflow are tested on diagnostic inputs, including a complete temporary
   280-cell analysis fixture. Clusters or t-SNE separation do not approve the
   dataset, establish causality, or replace the planned policy comparison.

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
