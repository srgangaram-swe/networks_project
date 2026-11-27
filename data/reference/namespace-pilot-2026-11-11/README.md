# Reproducible namespace diagnostic preview

These are generated request-response and TCP measurements from
[workflow 43111991762](https://github.com/srgangaram-swe/networks_project/actions/runs/43111991762),
collected on a disposable Ubuntu runner at source e3ddaff. They are not
measurements from the physical NucBox and are not a primary dataset.

The experiment contains four policies, two paired blocks, unloaded baselines,
and 110 Mb/s single-flow background demand. Sixteen completed trials scheduled
80,000 measured requests. There were 3,192 unsent slots (3.99%), zero timeout
or late outcomes, and shared-host CPU measurements. No trial was replaced.
Two blocks are insufficient for the configured confidence intervals.

CAKE best-effort retained 89.37% of FIFO bulk goodput and CAKE bounded retained
89.18%, below the 90% target. Keep these outcomes and generator omissions in
any interpretation. Calibration, workload-window alignment, protocol review,
and actual device checks remain open.

## Rebuild from a fresh checkout

    sh scripts/setup_environment.sh
    mkdir -p runs
    .venv/bin/python -m analysis.policy_comparison \
      data/reference/namespace-pilot-2026-11-11/export \
      --output runs/reference-analysis-01

The [root README](../../../README.md) also has the Docker Compose command.
Choose a new output directory for each rebuild. Current analysis provenance
will identify the rebuilding checkout; collection provenance remains e3ddaff.

## Files and integrity

The export directory preserves the original summary, provenance, full attempt
ledger, and tool versions. requests.csv.gz contains the exact original CSV
bytes, compressed with a zero timestamp. The loader bounds both compressed
and expanded data, verifies the original CSV hash, and rechecks every request
against its run's counters and quantiles. It rejects ambiguous plain-plus-gzip
inputs, corrupt archives, changed hashes, and expanded files above 32 MiB.

The analysis directory preserves all ten generated tables, figures, and summary
artifacts, plus the original report. Their hashes match that report. The root
manifest records the published machine-generated file hashes and source
workflow. These hashes establish file integrity, not scientific approval.

Raw packet captures and host identifiers are not included. Traffic records
contain synthetic run/request IDs, outcomes, timing values, and sender lag.
No personal or employer traffic was collected. Rebuilding the analysis does
not generate network traffic or create namespaces.
