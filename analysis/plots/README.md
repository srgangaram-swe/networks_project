# Figures and preliminary results

This directory contains the plotting modules and a [preliminary gallery](preliminary).
The gallery uses the published 16-trial namespace pilot, not measurements of
the NucBox or physical Ethernet adapters. It preserves the original reference
data and analysis. New analysis writes these figures under its own plots directory.

| Figure | What to look for |
|---|---|
| [Policy comparisons](preliminary/policy_comparisons.png) | Added p99, goodput retention, and the proposed point targets. Small gray dots show matched latency runs; diamonds show paired-block means. |
| [Measured cluster view](preliminary/run_clusters_metrics.png) | The actual fitted labels in goodput and on-time p99 units. Shape is policy; color is cluster. |
| [Cluster profiles](preliminary/cluster_profiles.png) | Saved centroids in within-condition standard-deviation units and counts of each policy in each cluster. |
| [PCA](preliminary/run_clusters.png) | A linear projection of the six standardized metrics used by K-means. |
| [t-SNE](preliminary/run_clusters_tsne.png) | A seeded nonlinear projection of those same metrics. Global distances and apparent islands are not evidence of population structure. |
| [Request outcomes](preliminary/request_outcomes.png) | On-time replies, unsent slots, and timeout/late outcomes, with all scheduled slots retained. |
| [RTT quantiles](preliminary/tail_quantiles.png) | Means of per-run on-time p50, p95, p99, and p99.9, on a common color scale. These are not pooled-request quantiles. |

Each PNG has an SVG copy with the same basename. Open the full image for readable
labels or use the vector copy in a report. The gallery manifest binds the input
and figure hashes, analysis source, layout checks, and visual review.

There are only two paired blocks per policy and eight loaded runs. Confidence
intervals are unavailable. FQ-CoDel retained about 99.37% of FIFO goodput;
both CAKE variants were below the 90% target. All four CAKE runs occupy one
cluster while FIFO and FQ-CoDel occupy the other, even though their latency
differs. A cluster is a six-metric run profile, not a policy ranking.

Rebuild from the repository root after setting up the environment:

    mkdir -p runs
    .venv/bin/python -m analysis.policy_comparison \
      data/reference/namespace-pilot-2026-11-11/export \
      --output runs/reference-figures-01

Use a new output directory each time. Source data, failed output, and the
published reference remain intact. See [the analysis guide](../README.md)
for pairing, uncertainty, censoring, and model settings.
