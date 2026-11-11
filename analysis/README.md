# Statistical analysis and exploratory ML

This builds on Jonathan Lloyd's policy-comparison workflow. It consumes the
checked campaign export, preserves the recorded baseline pairing, and produces
descriptive statistics, paired-block policy comparisons, and exploratory run
clusters. Collection and analysis use separate source identities in the report.

## Run

The NucBox installer includes requirements-analysis.txt. For analysis on the
Mac, install those dependencies into the existing virtual environment:

    .venv/bin/python -m pip install -r requirements-analysis.txt
    .venv/bin/python -m analysis.policy_comparison runs/experiment/export \
      --output runs/policy-analysis

The output directory must be new and its parent must exist. The command writes
every input run to runs.csv, recorded pairings to matched_baselines.csv,
run_statistics.csv, policy_comparisons.csv, run_clusters.csv, three PNG figures,
and report.json with input and output hashes, source identity, package versions,
seeds, model settings, counts, and limitations. A failure retains partial output
with a failed status. Success never upgrades diagnostic data to primary evidence.
The output also contains diagnostic_summary.txt and writeup_table.tex, which
provide the observed point estimates and context for drafting the report.
They preserve unavailable values and do not generate final research conclusions.

The complete NucBox command runs collection and this analysis together. See
[the setup guide](../docs/nucbox-setup.md#run-the-complete-initial-experiment).

## Input checks and pairing

Each input contains summary.csv, requests.csv, provenance.json, and the campaign
attempts.json. Hashes, row counts, identities, outcomes, numeric finiteness,
per-run counters, nearest-rank percentiles, adjacent on-time jitter, and sender
lag are checked before analysis. New exports bind the attempt ledger's hash to
provenance. Older exports can be analyzed with an explicit legacy-unbound design
flag in the report; a recorded hash does not authenticate who produced a file.

A completed attempt's manifest digest connects the summary row to its schedule
cell. Each loaded run uses its own policy's unloaded baseline from the same
recorded block. Missing baselines, duplicate cells, unmatched requests, and
changed source identities fail instead of triggering an average-baseline fallback.
Run IDs, policies, blocks, and measured outcomes are never silently dropped.

Up to 128 exports can be supplied as positional inputs. They must be disjoint
chunks of the same recorded campaign and source, with at most 20 runs and
200,000 requests per export. Requests are checked one export at a time; the
combined analysis keeps at most 400 run rows. These are current diagnostic
bounds. A batched export root can also be supplied directly; its completed index
binds every batch's provenance and the full campaign attempt ledger. An incomplete
index, changed hash, or duplicate run fails before analysis output is created.
The explicit 280-cell diagnostic matrix exports 47 batches of at most six runs.
Legacy CPU fields may be absent; new exports retain shared-host CPU scope and
percentages. Neither execution nor analysis grants primary eligibility.

## Statistical estimates

Summaries include p50, p95, p99, p99.9, jitter, goodput, timeout rate, missed-slot
rate, and sender delay. New exports also summarize shared-host CPU use. Every
metric has count and size columns so missing measurements remain visible.

The policy comparison subtracts the matching unloaded p99, then compares policy
and FIFO within the same blocks. It reports absolute added latency, FIFO minus
policy added latency, relative reduction, goodput, and goodput retention. The
default is 10,000 block-bootstrap resamples, seed 562, with 2.5/97.5 percentile
endpoints. The same draws are reused across policies and conditions with the
same block set, preserving shared-baseline correlation. Requests are never the
replication units. Intervals are pointwise, not a simultaneous multiple-comparison
guarantee. Fewer than three blocks yields point estimates without intervals.

Zero or negative FIFO added latency makes the relative reduction unavailable.
If any bootstrap reference denominator is nonpositive, its entire ratio interval
is unavailable; unfavorable draws are not discarded. Censored or missing p99
values remain in the run table and make the corresponding latency comparison
unavailable. Goodput and outcome counts remain visible. The 50% latency and 90%
goodput thresholds are descriptive point targets, not automatic acceptance.

## K-means, PCA, and t-SNE

K-means describes two run profiles separately within each offered-load and
flow-count condition. Features are on-time p99, goodput, adjacent on-time jitter,
sender p99 lag, timeout rate, and missed-slot rate. StandardScaler puts the six
measurements on comparable scales. Policy labels, run IDs, block IDs, and the
target flags are not model inputs. Unloaded rows remain in the analysis but
are not fitted as a separate cluster population.

The fit requires at least eight complete runs and two distinct feature vectors.
An insufficient or missing-feature condition is recorded as unavailable without
deleting its runs. K is fixed at two, with ten initializations, a 100-iteration
limit, one numerical thread, and seed 561. Canonical centroid ordering makes
cluster labels stable for a fixed dataset. The report records centroids in
original units, normalization, silhouette, and the fitted iteration count.

PCA and t-SNE visualize the same standardized vectors. K-means fits in the full
six-dimensional space, not either projection. t-SNE uses PCA initialization,
automatic learning rate, 1,000 iterations, seed 561, and perplexity
min(30, (n-1)/3), which stays below the condition's sample count. Perplexity and
versions are saved. The eight loaded pilot runs support a mechanics check,
not a stable account of population structure. Apparent islands and distances
in t-SNE do not establish global separation, treatment effects, or prediction.

This is unsupervised exploratory analysis. No held-out predictive accuracy is
claimed and no cluster or distance automatically excludes a measurement.
Supervised modeling would require an explicit prediction target, more independent
blocks, and splits that keep a block and its baselines together. The current
pilot does not support that claim.

Methods: [K-means](https://scikit-learn.org/stable/modules/clustering.html#k-means),
[standardization](https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.StandardScaler.html),
[PCA](https://scikit-learn.org/stable/modules/generated/sklearn.decomposition.PCA.html),
and [t-SNE](https://scikit-learn.org/stable/modules/generated/sklearn.manifold.TSNE.html).

## Verification and costs

Run sh scripts/check_analysis.sh. Tests include hand-computed policy effects,
an exhaustive small block-bootstrap reference, malformed exports, pairing errors,
zero denominators, failure persistence, row-order invariance, and real CLI/plot
execution. Ruff enforces the existing McCabe limit and analysis branch coverage
has its own unchanged 90% floor. Synthetic fixtures stay in tests.

CSV reading uses at most 32 MiB per file and 200,000 request rows per input.
Request validation is O(N log N), with O(N) memory per export. Bootstrap work is
O(B R C), with at most 10,000 resamples, 400 run rows, and bounded conditions.
Clustering fits at most 400 rows and six features; K-means has ten starts and
100 iterations, and t-SNE has a 1,000-iteration limit. Silhouette uses O(R^2)
distance work. The fixed bounds are for offline analysis, not real-time operation.
