# Analysis

The independent bundle validator checks integrity before the diagnostic exporter
computes per-run RTT percentiles, adjacent-request jitter, sender delay, timeout
counts, and receiver goodput. The plotting command consumes the resulting CSV
and checks its recorded hash. It plots every selected run separately.

Run-level bootstrap intervals, matched-baseline effects, and the primary policy
comparison are not implemented. The collector has not passed the Linux pilot.
Keep synthetic fixtures under tests and never use them as measurement evidence.

See the export and plot commands in the
[operating guide](../docs/running-experiments.md).
